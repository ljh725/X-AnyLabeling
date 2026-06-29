#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unify group_id across person/head/face by edge-alignment matching.

This script rewrites the ``group_id`` of ``head`` / ``face`` rectangles so
that every box of the same real-world target shares one id. It is a data
cleaning tool, not a QA report: it reads dirty annotations and writes a
corrected copy.

The matching rule is a physical constraint distilled from manual
inspection of this data, NOT a generic spatial score:

    head 顶边 (top)  ≈ person 顶边 (top)     # 人从头顶往下拉框
    face 底边 (bottom) ≈ head 底边 (bottom)  # face 到下巴，head 到脖子

Because annotators pull the person box from the crown of the head down and
the head box from the crown down to the neck, the tops of person and head
sit on (almost) the same line. Likewise face (brows-to-chin) and head
(crown-to-neck) share their bottom edge. These edge alignments are far
stronger and more parameter-free than an IoU / containment score.

Special handling: when a head has no person box above it, the head still
forms a valid instance. A head+face pair (or an orphan head alone) is
assigned a fresh group_id rather than being discarded. This data
legitimately contains targets with only head/face.

Pipeline (per file)::

    normalize labels (regex) and reset head/face group_id
      -> match head  -> person  by |head.top - person.top|
      -> match face  -> head    by |face.bottom - head.bottom|
      -> orphan head/face self-pair; assign fresh group_ids
      -> write corrected copy; collect warnings

Usage::

    python pose_qa/grouping/group_merger.py \\
        --input-dir D:/data/labels \\
        --output-dir D:/data/labels_fixed

    # Or edit the CONFIG block at the top and run directly in an IDE.
"""

from __future__ import annotations

import argparse
import json
import os
import os.path as osp
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Optional

import numpy as np
from scipy.optimize import linear_sum_assignment

try:
    from tqdm import tqdm
except ImportError:

    def tqdm(iterable=None, *args, **kwargs):
        """Minimal fallback for tqdm when not installed."""
        return iterable


# ========== IDE direct-run CONFIG ==========
INPUT_DIR: str = r"D:\data\labels"
OUTPUT_DIR: str = r"D:\data\labels_fixed"
WORKERS: Optional[int] = None  # None -> min(16, cpu_count)
# ==========================================


def get_rect_coords(shape: dict) -> Optional[dict]:
    """Extract {left, right, top, bottom} from a rectangle shape.

    Tolerates both the 2-diagonal-point and 4-corner point formats by
    taking min/max over all points.

    Args:
        shape: A shape dict with a ``points`` list.

    Returns:
        Coord dict, or None if fewer than 2 points.
    """
    pts = shape.get("points", [])
    if len(pts) < 2:
        return None
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return {
        "left": min(xs),
        "right": max(xs),
        "top": min(ys),
        "bottom": max(ys),
    }


def x_overlap(a: Optional[dict], b: Optional[dict]) -> float:
    """X-axis overlap length of two rects (0 if disjoint)."""
    if a is None or b is None:
        return 0.0
    return max(
        0.0, min(a["right"], b["right"]) - max(a["left"], b["left"])
    )


def rect_center(c: Optional[dict]) -> Optional[tuple[float, float]]:
    """Center point (cx, cy) of a rect, or None."""
    if c is None:
        return None
    return (
        (c["left"] + c["right"]) / 2.0,
        (c["top"] + c["bottom"]) / 2.0,
    )


def rect_height(c: Optional[dict]) -> float:
    """Height of a rect (0 if None)."""
    if c is None:
        return 0.0
    return c["bottom"] - c["top"]


def rect_area(c: Optional[dict]) -> float:
    """Area of a rect (0 if None)."""
    if c is None:
        return 0.0
    return max(0.0, c["right"] - c["left"]) * max(
        0.0, c["bottom"] - c["top"]
    )


def rect_contains(
    inner: Optional[dict], outer: Optional[dict], tol: float = 0.0
) -> bool:
    """Whether inner is inside outer, with optional tolerance."""
    if inner is None or outer is None:
        return False
    return (
        inner["left"] >= outer["left"] - tol
        and inner["right"] <= outer["right"] + tol
        and inner["top"] >= outer["top"] - tol
        and inner["bottom"] <= outer["bottom"] + tol
    )


# --- candidate filters (hard geometric constraints) ---


def head_person_candidate_ok(head: dict, person: dict) -> bool:
    """Whether a head may belong to a person (hard constraints).

    Constraints (from the physical labeling action):
      - some x-overlap exists,
      - head top is near/under the person top (head starts at the crown),
      - head width does not overflow the person width,
      - if not fully contained, x-overlap must cover >= 60% of head width,
      - head area must be < 50% of person area (head is not the body).

    Args:
        head: Head shape.
        person: Person shape.

    Returns:
        True if the pair passes the hard constraints.
    """
    hc = get_rect_coords(head)
    pc = get_rect_coords(person)
    if hc is None or pc is None:
        return False

    person_h = rect_height(pc)
    head_h = rect_height(hc)
    if person_h <= 0 or head_h <= 0:
        return False

    tol_y = max(8.0, 0.03 * person_h)
    tol_x = max(5.0, 0.02 * (pc["right"] - pc["left"]))
    overlap = x_overlap(hc, pc)

    if overlap <= 0:
        return False
    if hc["top"] < pc["top"] - tol_y:
        return False
    if hc["top"] > pc["bottom"] + tol_y:
        return False
    if hc["left"] < pc["left"] - tol_x or hc["right"] > pc["right"] + tol_x:
        return False

    contained = rect_contains(hc, pc, tol=max(tol_x, tol_y))
    overlap_ratio = overlap / max(1.0, hc["right"] - hc["left"])
    area_ratio = rect_area(hc) / max(1.0, rect_area(pc))

    if not contained and overlap_ratio < 0.6:
        return False
    if area_ratio > 0.5:
        return False
    return True


def face_head_candidate_ok(face: dict, head: dict) -> bool:
    """Whether a face may belong to a head (hard constraints).

    Constraints:
      - some x-overlap exists,
      - face center falls inside the head box (with tolerance),
      - face bottom is at/above the head bottom (shared bottom edge),
      - face top is at/below the head top.

    Args:
        face: Face shape.
        head: Head shape.

    Returns:
        True if the pair passes the hard constraints.
    """
    fc = get_rect_coords(face)
    hc = get_rect_coords(head)
    if fc is None or hc is None:
        return False

    fcx, fcy = rect_center(fc)  # type: ignore[misc]
    if fcx is None:
        return False
    tol = max(5.0, 0.05 * rect_height(hc))

    if x_overlap(fc, hc) <= 0:
        return False
    if not (hc["left"] - tol <= fcx <= hc["right"] + tol):
        return False
    if not (hc["top"] - tol <= fcy <= hc["bottom"] + tol):
        return False
    if fc["bottom"] > hc["bottom"] + tol:
        return False
    if fc["top"] < hc["top"] - tol:
        return False
    return True


# --- one-to-one matching (Hungarian, globally optimal) ---


def hungarian_one_to_one_match(
    items_a: list[dict],
    items_b: list[dict],
    dist_fn: Any,
    candidate_fn: Optional[Any] = None,
    secondary_dist_fn: Optional[Any] = None,
) -> tuple[list[tuple[dict, dict]], list[dict]]:
    """Globally-optimal one-to-one matching via the Hungarian algorithm.

    Unlike greedy matching, this minimizes the TOTAL assignment cost, so
    a locally-suboptimal pair can still be chosen when it yields a better
    global result. This matters when candidates cross (head A slightly
    closer to person X, head B slightly closer to person X too, but A is
    MUCH closer to Y) -- greedy locks the smallest first and can strand
    the other; Hungarian balances both.

    Cost design:
      - Only pairs passing ``candidate_fn`` are admissible; the rest get
        INF cost and are never chosen.
      - ``cost = dist + small * secondary`` so primary distance dominates
        while secondary breaks ties (e.g. center-x for face/head).
      - After solving, only assignments with cost < INF are kept.

    Args:
        items_a: Left-side items (e.g. heads). length N.
        items_b: Right-side items (e.g. persons). length M.
        dist_fn: Primary distance fn(a, b) -> float (smaller = closer).
        candidate_fn: Hard filter fn(a, b) -> bool. Pairs that fail are
            excluded (INF cost).
        secondary_dist_fn: Tiebreak distance; contributes with a small
            weight so it never overrides the primary.

    Returns:
        (matched_pairs, unmatched_a).
    """
    n, m = len(items_a), len(items_b)
    if n == 0 or m == 0:
        return [], list(items_a)

    INF = 1e9
    cost = np.full((n, m), INF, dtype=np.float64)
    for i, a in enumerate(items_a):
        for j, b in enumerate(items_b):
            if candidate_fn is not None and not candidate_fn(a, b):
                continue
            primary = dist_fn(a, b)
            if primary == float("inf"):
                continue
            secondary = (
                secondary_dist_fn(a, b)
                if secondary_dist_fn is not None
                else 0.0
            )
            # secondary scaled down so it only breaks ties in primary.
            cost[i, j] = primary + 0.001 * secondary

    rows, cols = linear_sum_assignment(cost)
    matched_pairs: list[tuple[dict, dict]] = []
    matched_a: set[int] = set()
    for r, c in zip(rows, cols):
        if cost[r, c] >= INF:
            continue  # forced INF slot, not a real match
        matched_pairs.append((items_a[r], items_b[c]))
        matched_a.add(id(items_a[r]))

    unmatched_a = [a for a in items_a if id(a) not in matched_a]
    return matched_pairs, unmatched_a


# --- flags (for orphan instances, for downstream review) ---


def ensure_flags(shape: dict) -> dict:
    """Ensure the shape has a writable flags dict, return it."""
    flags = shape.get("flags")
    if not isinstance(flags, dict):
        flags = {}
        shape["flags"] = flags
    return flags


def mark_orphan_head(shape: dict, has_face: bool) -> None:
    """Tag an orphan head shape (no person box above it)."""
    flags = ensure_flags(shape)
    flags["orphan_head"] = True
    flags["has_face"] = has_face
    flags["entity_source"] = "orphan_generated"


def mark_unmatched_orphan_face(shape: dict) -> None:
    """Tag a face that could not be matched to any head."""
    flags = ensure_flags(shape)
    flags["unmatched_orphan_face"] = True


def clear_transform_flags(shape: dict) -> None:
    """Clear stale transform flags on re-run (idempotency)."""
    flags = ensure_flags(shape)
    for key in (
        "orphan_head",
        "has_face",
        "entity_source",
        "unmatched_orphan_face",
    ):
        flags.pop(key, None)


# --- label normalization (regex, matches the source data format) ---


def normalize_labels(shapes: list[dict]) -> int:
    """Normalize raw labels to person/head/face and reset head/face gid.

    Source data encodes group_id inside the label string in several
    formats. This extracts it and resets head/face group_id to None so
    that the matching stage can reassign them uniformly. Re-runs are
    safe: already-normalized head/face rectangles are also reset.

    Recognized label patterns:
      - ``\\d+_person``        -> label=person, gid from prefix
      - ``person_\\d+_<rest>`` -> label=<rest>,  gid from middle
      - ``\\d+_head``          -> label=head,    gid=None
      - ``\\d+_face``          -> label=face,    gid=None

    Args:
        shapes: Shape list (mutated in place).

    Returns:
        The max existing int group_id (for orphan id allocation), -1 if
        none.
    """
    max_gid = -1
    for shape in shapes:
        clear_transform_flags(shape)
        label = shape.get("label", "")
        stype = shape.get("shape_type")

        m = re.match(r"^(\d+)_person$", label)
        if m:
            gid = int(m.group(1))
            shape["label"] = "person"
            shape["group_id"] = gid
            if gid > max_gid:
                max_gid = gid
            continue

        m = re.match(r"^person_(\d+)_(.+)$", label)
        if m:
            gid = int(m.group(1))
            shape["label"] = m.group(2)
            shape["group_id"] = gid
            if gid > max_gid:
                max_gid = gid
            continue

        m = re.match(r"^\d+_head$", label)
        if m:
            shape["label"] = "head"
            shape["group_id"] = None
            continue

        m = re.match(r"^\d+_face$", label)
        if m:
            shape["label"] = "face"
            shape["group_id"] = None
            continue

        # Re-run safety: normalized head/face get re-inferred too.
        if stype == "rectangle" and label in ("head", "face"):
            shape["group_id"] = None

    # Max gid must reflect ALL existing int gids, including labels that
    # were already canonical (e.g. plain "person") and thus untouched by
    # the regex branches above. Otherwise orphan allocation (max_gid+1)
    # can collide with an existing person group_id.
    for shape in shapes:
        gid = shape.get("group_id")
        if isinstance(gid, int) and gid > max_gid:
            max_gid = gid
    return max_gid


# --- validation: structured issues ---


def validate_entity_rules(shapes: list[dict]) -> list[dict]:
    """Post-unify sanity checks; returns structured issue records.

    Checks:
      - no label has a duplicate group_id,
      - every face's group_id also has a head.

    Args:
        shapes: Shape list after unification.

    Returns:
        Issue dicts: ``{shape_index, rule_name, severity, message}``.
    """
    issues: list[dict] = []
    for label in ("person", "head", "face"):
        gid_to_shapes: dict[Any, list[tuple[int, dict]]] = {}
        for idx, shape in enumerate(shapes):
            if shape.get("label") != label:
                continue
            gid = shape.get("group_id")
            if gid is None:
                continue
            gid_to_shapes.setdefault(gid, []).append((idx, shape))
        for gid, same in sorted(
            gid_to_shapes.items(), key=lambda kv: str(kv[0])
        ):
            if len(same) <= 1:
                continue
            for idx, shape in same:
                issues.append(
                    {
                        "shape_index": idx,
                        "rule_name": "duplicate_group_id",
                        "severity": "warning",
                        "message": (
                            f"duplicate {label} group_id={gid}: "
                            f"count={len(same)}"
                        ),
                    }
                )

    head_gid_set = {
        shape.get("group_id")
        for shape in shapes
        if shape.get("label") == "head"
        and shape.get("group_id") is not None
    }
    for idx, shape in enumerate(shapes):
        if shape.get("label") != "face":
            continue
        gid = shape.get("group_id")
        if gid is None:
            issues.append(
                {
                    "shape_index": idx,
                    "rule_name": "face_missing_group_id",
                    "severity": "warning",
                    "message": (
                        f"face missing group_id: "
                        f"points={shape.get('points')}"
                    ),
                }
            )
            continue
        if gid not in head_gid_set:
            issues.append(
                {
                    "shape_index": idx,
                    "rule_name": "face_without_head",
                    "severity": "warning",
                    "message": (
                        f"face without head group_id={gid}: "
                        f"points={shape.get('points')}"
                    ),
                }
            )
    return issues


def _shape_index_of(shapes: list[dict], target: dict) -> int:
    """Find the array index of a target shape dict (by identity).

    Args:
        shapes: Shape list.
        target: The shape to locate (matched by ``is``).

    Returns:
        Index, or -1 if not found.
    """
    for i, s in enumerate(shapes):
        if s is target:
            return i
    return -1


# --- core: per-file unification ---


def process_json_data(data: dict) -> tuple[dict, list[dict]]:
    """Unify group_id within one annotation dict.

    Steps:
      1. Normalize labels; reset head/face gid.
      2. head -> person by |head.top - person.top| (Hungarian one-to-one).
      3. face -> head  by |face.bottom - head.bottom| (Hungarian one-to-one).
      4. Orphan face -> orphan head; matched pairs get fresh group_ids
         (a head+face is a valid instance even without a person).
      5. Bare orphan heads get their own fresh group_id.
      6. Validate; collect structured issues (with shape_index).

    Each unmatched head/face is recorded as an issue so the caller can
    emit an Inspector-importable TSV for manual follow-up.

    Args:
        data: The loaded annotation JSON object (mutated).

    Returns:
        (data, issues) where each issue is
        ``{shape_index, rule_name, severity, message}``.
    """
    shapes = data.get("shapes", [])
    if not shapes:
        data["imageData"] = None
        return data, []

    max_gid = normalize_labels(shapes)
    issues: list[dict] = []

    persons = [
        s
        for s in shapes
        if s.get("label") == "person"
        and s.get("shape_type") == "rectangle"
    ]
    heads = [
        s
        for s in shapes
        if s.get("label") == "head"
        and s.get("shape_type") == "rectangle"
    ]
    faces = [
        s
        for s in shapes
        if s.get("label") == "face"
        and s.get("shape_type") == "rectangle"
    ]

    # 2. head -> person
    def head_person_dist(head: dict, person: dict) -> float:
        hc = get_rect_coords(head)
        pc = get_rect_coords(person)
        if hc is None or pc is None:
            return float("inf")
        return abs(hc["top"] - pc["top"])

    head_person_pairs, orphan_heads = hungarian_one_to_one_match(
        heads, persons, head_person_dist,
        candidate_fn=head_person_candidate_ok,
    )
    for head, person in head_person_pairs:
        head["group_id"] = person["group_id"]
    matched_heads = [h for h in heads if h.get("group_id") is not None]

    # 3. face -> matched head
    def face_head_dist(face: dict, head: dict) -> float:
        fc = get_rect_coords(face)
        hc = get_rect_coords(head)
        if fc is None or hc is None:
            return float("inf")
        return abs(fc["bottom"] - hc["bottom"])

    def face_head_center_x_dist(face: dict, head: dict) -> float:
        fc = rect_center(get_rect_coords(face))
        hc = rect_center(get_rect_coords(head))
        if fc is None or hc is None:
            return float("inf")
        return abs(fc[0] - hc[0])

    face_head_pairs, orphan_faces = hungarian_one_to_one_match(
        faces, matched_heads, face_head_dist,
        candidate_fn=face_head_candidate_ok,
        secondary_dist_fn=face_head_center_x_dist,
    )
    for face, head in face_head_pairs:
        face["group_id"] = head["group_id"]

    # 4. orphan face -> orphan head (a head+face with NO person)
    orphan_face_head_pairs, remaining_orphan_faces = (
        hungarian_one_to_one_match(
            orphan_faces, orphan_heads, face_head_dist,
            candidate_fn=face_head_candidate_ok,
            secondary_dist_fn=face_head_center_x_dist,
        )
    )
    orphan_head_to_faces: dict[int, dict] = {}
    for face, head in orphan_face_head_pairs:
        orphan_head_to_faces.setdefault(
            id(head), {"head": head, "faces": []}
        )["faces"].append(face)
    for item in orphan_head_to_faces.values():
        max_gid += 1
        head = item["head"]
        head["group_id"] = max_gid
        mark_orphan_head(head, has_face=True)
        for face in item["faces"]:
            face["group_id"] = max_gid

    # 5. bare orphan faces (no head at all)
    for face in remaining_orphan_faces:
        mark_unmatched_orphan_face(face)
        issues.append(
            {
                "shape_index": _shape_index_of(shapes, face),
                "rule_name": "orphan_face_no_head",
                "severity": "warning",
                "message": (
                    "face 未匹配到任何 head/person，需人工确认归属"
                ),
            }
        )

    # 6. bare orphan heads (no person, no face)
    matched_orphan_head_ids = set(orphan_head_to_faces.keys())
    for head in orphan_heads:
        if id(head) not in matched_orphan_head_ids:
            max_gid += 1
            head["group_id"] = max_gid
            mark_orphan_head(head, has_face=False)
            issues.append(
                {
                    "shape_index": _shape_index_of(shapes, head),
                    "rule_name": "orphan_head_no_person",
                    "severity": "info",
                    "message": (
                        "head 未匹配到 person 框，已分配独立 group_id，"
                        "请确认是否漏标 person"
                    ),
                }
            )

    issues.extend(validate_entity_rules(shapes))
    data["imageData"] = None
    return data, issues


def process_single_file(
    input_path: str, output_path: str
) -> tuple[bool, Optional[str], list[dict]]:
    """Load, unify, and save one JSON.

    Args:
        input_path: Source annotation JSON path.
        output_path: Destination JSON path (corrected copy).

    Returns:
        (success, error_msg_or_None, issues) where each issue is a dict
        with shape_index/rule_name/severity/message.
    """
    try:
        with open(input_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        data, issues = process_json_data(data)
        out_dir = os.path.dirname(output_path)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True, None, issues
    except json.JSONDecodeError as e:
        return False, f"JSON parse error: {e}", []
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}", []


# --- CLI / driver ---


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Unify group_id across person/head/face by edge-alignment."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-i", "--input-dir", help="Input JSON directory."
    )
    parser.add_argument(
        "-o", "--output-dir", help="Output directory (created if missing)."
    )
    parser.add_argument(
        "-w", "--workers", type=int,
        help="Thread pool size (default: min(16, cpu_count)).",
    )
    return parser.parse_args()


def write_inspector_tsv(
    records: list[tuple[str, list[dict]]], tsv_path: str
) -> int:
    """Write issues to an Inspector-importable TSV.

    Format matches the native Inspector external-result table (same as
    pose_qa/qa/export_for_inspector.py)::

        file_path  shape_index  rule_name  severity  message

    So a reviewer can import the TSV and click any row to jump to the
    unmatched head/face shape for manual follow-up.

    Args:
        records: List of (filename, issues) tuples.
        tsv_path: Output TSV path.

    Returns:
        Number of rows written.
    """
    header = ["file_path", "shape_index", "rule_name", "severity", "message"]
    rows = 0
    with open(tsv_path, "w", encoding="utf-8", newline="") as f:
        f.write("\t".join(header) + "\n")
        for filename, issues in records:
            for iss in issues:
                f.write(
                    "\t".join(
                        [
                            filename,
                            str(iss.get("shape_index", -1)),
                            iss.get("rule_name", ""),
                            iss.get("severity", ""),
                            iss.get("message", ""),
                        ]
                    )
                    + "\n"
                )
                rows += 1
    return rows


def main() -> int:
    """Run the unification over a directory.

    Returns:
        Exit code: 0 on success, non-zero on error.
    """
    args = parse_args()
    input_dir = args.input_dir or INPUT_DIR
    output_dir = args.output_dir or OUTPUT_DIR
    workers = args.workers or WORKERS or min(16, os.cpu_count() or 1)

    if not input_dir or not output_dir:
        print("ERROR: --input-dir and --output-dir are required.")
        return 1
    if not osp.isdir(input_dir):
        print(f"ERROR: input dir not found: {input_dir}")
        return 1

    os.makedirs(output_dir, exist_ok=True)
    filenames = [
        f for f in os.listdir(input_dir) if f.lower().endswith(".json")
    ]
    if not filenames:
        print(f"WARN: no .json files in {input_dir}")
        return 0

    print(f"Found {len(filenames)} JSON files")
    print(f"Output dir: {output_dir}")
    print(f"Workers: {workers}")
    print("Processing...\n")

    success_count = 0
    fail_count = 0
    issue_count = 0
    errors: list[str] = []
    # (filename, issues) for the Inspector TSV.
    issue_records: list[tuple[str, list[dict]]] = []
    # Plain-text warnings for quick scanning.
    warning_lines: list[str] = []
    lock = threading.Lock()

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures: dict = {}
        for filename in filenames:
            in_path = osp.join(input_dir, filename)
            out_path = osp.join(output_dir, filename)
            futures[executor.submit(process_single_file, in_path, out_path)] = (
                filename
            )

        it = as_completed(futures)
        it = tqdm(it, total=len(futures), desc="Processing")
        for future in it:
            filename = futures[future]
            try:
                ok, err, file_issues = future.result()
            except Exception as e:  # noqa: BLE001
                ok, err, file_issues = (
                    False,
                    f"thread error: {type(e).__name__}: {e}",
                    [],
                )
            with lock:
                if ok:
                    success_count += 1
                    if file_issues:
                        issue_count += len(file_issues)
                        issue_records.append((filename, file_issues))
                        for iss in file_issues:
                            warning_lines.append(
                                f"{filename}: [{iss.get('severity')}] "
                                f"{iss.get('rule_name')} "
                                f"(shape {iss.get('shape_index')}): "
                                f"{iss.get('message')}"
                            )
                else:
                    fail_count += 1
                    errors.append(f"{filename}: {err}")

    total = len(filenames)
    print(f"\nDone: success {success_count} / fail {fail_count} / {total}")

    if errors:
        error_log = osp.join(output_dir, "error_log.txt")
        with open(error_log, "w", encoding="utf-8") as f:
            f.write("\n".join(errors))
        print(f"Error log saved to: {error_log}")
    else:
        print("All files processed, no errors.")

    if warning_lines:
        warning_log = osp.join(output_dir, "warning_log.txt")
        with open(warning_log, "w", encoding="utf-8") as f:
            f.write("\n".join(warning_lines))
        print(f"{issue_count} issues saved to: {warning_log}")

    # Inspector-importable TSV: jump to every unmatched head/face.
    tsv_path = osp.join(output_dir, "grouping_review.tsv")
    rows = write_inspector_tsv(issue_records, tsv_path)
    if rows:
        print(
            f"Inspector TSV ({rows} rows) saved to: {tsv_path}\n"
            "Import via Inspector -> 导入 to review unmatched boxes."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
