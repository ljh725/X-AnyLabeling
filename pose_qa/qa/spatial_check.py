#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Spatial geometric validation for person/head/face rectangles.

This is the **post-unification geometric QA stage** of the pose QA
pipeline. It runs AFTER ``group_merger.py`` has unified the group_id, so
every person/head/face rectangle of the same real target shares one id.
Spatial rules then check the geometric relationships WITHIN each group
(person ⊃ head ⊃ face) to catch boxes that are correct in label/gid but
wrong in position or size.

It is read-only: it never modifies annotations, only reports issues.

Rules (per group_id; thresholds mirror quality_strategy.md:510-519)::

    head_inside_person        head should be mostly inside person  (error)
    face_inside_head          face should be mostly inside head    (error)
    face_not_larger_than_head face area must not exceed head       (error)
    head_in_upper_body        head center should be in person's
                              upper body region                    (warning)
    duplicate_box_in_group    two same-label boxes in one group
                              overlap heavily (IoU > thr)          (warning)
    person_missing_head       a group has a person but no head     (warning)

Output (three files, matches pose_qa_compare.py / group_merger.py)::

    <prefix>.json         full report (config + summary + per_image)
    <prefix>.md           human-readable summary + per-rule table
    <prefix>_spatial.tsv  Inspector-importable TSV (jump to each issue)

Pipeline position::

    group_merger.py -> unified data -> spatial_check.py -> TSV
                                              -> pose_qa_compare.py (keypoints)

Usage::

    python pose_qa/qa/spatial_check.py \\
        --gt-dir D:/data/labels_fixed \\
        --output D:/report/spatial
"""

from __future__ import annotations

import argparse
import json
import math
import os.path as osp
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, Optional

try:
    from tqdm import tqdm
except ImportError:

    def tqdm(iterable=None, *args, **kwargs):
        """Minimal fallback for tqdm when not installed."""
        return iterable


# ============================================
# CONFIG - edit here for variable-config mode
# ============================================
GT_DIR: str = r"D:\data\labels_fixed"
OUTPUT_PREFIX: str = r"D:\report\spatial"
GT_SUFFIX: str = ".json"

# Rule thresholds (mirror pose_qa/docs/quality_strategy.md:510-519).
HEAD_INSIDE_PERSON_THR: float = 0.40  # < this inside_ratio -> error
FACE_INSIDE_HEAD_THR: float = 0.50  # < this inside_ratio -> error
FACE_OVERFLOW_THR: float = 0.10  # face area exceeding head > this -> error
FACE_AREA_RATIO_MAX: float = 1.10  # face_area/head_area > this -> error
HEAD_UPPER_BODY_Y_RATIO: float = 0.70  # head center y / person h -> warn
DUPLICATE_IOU_THR: float = 0.85  # same-label IoU in one group -> warn

WORKERS: int = 8
NO_PROGRESS: bool = False
TOP_N_REPORT: int = 50

# Rectangle shape_types accepted as a box.
BOX_TYPES = {"rectangle", "bbox", "box"}
TARGET_LABELS = {"person", "head", "face"}


# ============================================
# Parsing
# ============================================


def box_from_points(
    points: list,
) -> Optional[tuple[float, float, float, float]]:
    """Normalize rectangle points to (x1, y1, x2, y2).

    Tolerates 2-diagonal-corner and 4-corner formats via min/max.

    Args:
        points: The shape's ``points`` list.

    Returns:
        ``(x1, y1, x2, y2)`` with x1<=x2, y1<=y2, or None if degenerate.
    """
    if not points or len(points) < 2:
        return None
    try:
        xs = [float(p[0]) for p in points]
        ys = [float(p[1]) for p in points]
    except (TypeError, ValueError, IndexError):
        return None
    x1, x2 = min(xs), max(xs)
    y1, y2 = min(ys), max(ys)
    if x2 <= x1 or y2 <= y1:
        return None
    return (x1, y1, x2, y2)


def load_groups(
    json_path: str,
) -> tuple[list[dict], dict]:
    """Load a JSON and group its person/head/face rectangles by group_id.

    Only rectangles with a non-None int group_id participate (group_id
    is assumed already unified by group_merger.py). Shapes with
    group_id=None are skipped — they are ungrouped orphans, handled by
    the grouping stage, not by these per-group spatial rules.

    Args:
        json_path: Path to the annotation JSON.

    Returns:
        Tuple ``(groups, info)`` where ``groups`` is a list of::

            {"gid": int,
             "person": {"box":..., "shape_index": int} | None,
             "heads":  [{"box":..., "shape_index": int}, ...],
             "faces":  [{"box":..., "shape_index": int}, ...]}

        and ``info`` holds imagePath/width/height.
    """
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    info = {
        "imagePath": data.get("imagePath"),
        "imageHeight": data.get("imageHeight"),
        "imageWidth": data.get("imageWidth"),
    }

    by_gid: dict[int, dict] = {}
    for idx, sh in enumerate(data.get("shapes", [])):
        if not isinstance(sh, dict):
            continue
        if sh.get("shape_type") not in BOX_TYPES:
            continue
        label = sh.get("label", "")
        if label not in TARGET_LABELS:
            continue
        gid = sh.get("group_id")
        if not isinstance(gid, int):
            continue  # skip ungrouped / non-int gid
        box = box_from_points(sh.get("points", []))
        if box is None:
            continue
        rec = {"box": box, "shape_index": idx}
        g = by_gid.setdefault(
            gid, {"gid": gid, "person": None, "heads": [], "faces": []}
        )
        if label == "person":
            # Keep the first person; if multiple, report via duplicate rule.
            if g["person"] is None:
                g["person"] = rec
            else:
                g["heads"].append(rec)  # mis-routed, rare; duplicate rule catches
        elif label == "head":
            g["heads"].append(rec)
        else:
            g["faces"].append(rec)
    return list(by_gid.values()), info


# ============================================
# Geometry (pure-python, self-contained)
# ============================================


def _area(box: tuple[float, float, float, float]) -> float:
    """Area of an (x1,y1,x2,y2) box."""
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def _intersection(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> float:
    """Intersection area of two axis-aligned boxes."""
    iw = min(a[2], b[2]) - max(a[0], b[0])
    ih = min(a[3], b[3]) - max(a[1], b[1])
    if iw <= 0 or ih <= 0:
        return 0.0
    return iw * ih


def _inside_ratio(
    child: tuple[float, float, float, float],
    parent: tuple[float, float, float, float],
) -> float:
    """Fraction of child's area inside parent (inter / child_area).

    Tolerates partial overflow (e.g. head crown slightly above person).
    """
    ca = _area(child)
    if ca <= 0:
        return 0.0
    return min(1.0, _intersection(child, parent) / ca)


def _iou(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> float:
    """Intersection-over-union of two boxes."""
    inter = _intersection(a, b)
    if inter <= 0:
        return 0.0
    union = _area(a) + _area(b) - inter
    if union <= 0:
        return 0.0
    return inter / union


def _center_y_ratio(
    head: tuple[float, float, float, float],
    person: tuple[float, float, float, float],
) -> float:
    """Head center y normalized into [0,1] over the person height.

    0 = head center at the person top, 1 = at the person bottom. Values
    >~0.7 mean the head is sitting in the lower body — suspicious.
    """
    ph = person[3] - person[1]
    if ph <= 0:
        return 0.0
    head_cy = (head[1] + head[3]) / 2.0
    return (head_cy - person[1]) / ph


# ============================================
# Issue helpers
# ============================================


def _issue(
    shape_index: int,
    rule_name: str,
    severity: str,
    message: str,
) -> dict:
    """Build one issue dict (same shape as group_merger / export_for_inspector).

    Args:
        shape_index: Index of the offending shape.
        rule_name: Stable rule id.
        severity: error / warning / info.
        message: Human-readable description.

    Returns:
        Issue dict.
    """
    return {
        "shape_index": shape_index,
        "rule_name": rule_name,
        "severity": severity,
        "message": message,
    }


# ============================================
# Rules (each returns a list of issues for one group)
# ============================================


def check_head_inside_person(
    group: dict, cfg: dict
) -> list[dict]:
    """Rule: head should be mostly inside its person box.

    Args:
        group: One group dict from load_groups.
        cfg: Config dict with thresholds.

    Returns:
        Issue list (empty if OK).
    """
    person = group["person"]
    if person is None:
        return []
    issues: list[dict] = []
    thr = cfg["head_inside_person_thr"]
    for h in group["heads"]:
        ratio = _inside_ratio(h["box"], person["box"])
        if ratio < thr:
            issues.append(
                _issue(
                    h["shape_index"],
                    "head_inside_person",
                    "error",
                    f"head 仅 {ratio:.0%} 位于 person 内，"
                    f"低于 {thr:.0%} 阈值，疑似 head 归属或位置错误",
                )
            )
    return issues


def check_face_inside_head(
    group: dict, cfg: dict
) -> list[dict]:
    """Rule: each face should be mostly inside its group's head box.

    A face is matched to the head in its group with the highest
    inside_ratio. Unmatched faces (no head at all) are handled by the
    grouping stage, not here.

    Args:
        group: One group dict.
        cfg: Config dict.

    Returns:
        Issue list.
    """
    if not group["heads"] or not group["faces"]:
        return []
    inside_thr = cfg["face_inside_head_thr"]
    overflow_thr = cfg["face_overflow_thr"]
    issues: list[dict] = []
    for f in group["faces"]:
        best_ratio = 0.0
        best_head = None
        for h in group["heads"]:
            r = _inside_ratio(f["box"], h["box"])
            if r > best_ratio:
                best_ratio = r
                best_head = h
        if best_head is None:
            continue
        face_area = _area(f["box"])
        overflow = max(
            0.0, 1.0 - _intersection(f["box"], best_head["box"]) / max(
                face_area, 1e-9
            )
        )
        if best_ratio < inside_thr or overflow > overflow_thr:
            issues.append(
                _issue(
                    f["shape_index"],
                    "face_inside_head",
                    "error",
                    f"face 仅 {best_ratio:.0%} 位于 head 内"
                    f"（超出 {overflow:.0%}），疑似 face/head 关系错误",
                )
            )
    return issues


def check_face_not_larger_than_head(
    group: dict, cfg: dict
) -> list[dict]:
    """Rule: face area must not exceed head area.

    Args:
        group: One group dict.
        cfg: Config dict.

    Returns:
        Issue list.
    """
    if not group["heads"] or not group["faces"]:
        return []
    ratio_max = cfg["face_area_ratio_max"]
    issues: list[dict] = []
    for f in group["faces"]:
        for h in group["heads"]:
            head_area = _area(h["box"])
            if head_area <= 0:
                continue
            r = _area(f["box"]) / head_area
            if r > ratio_max:
                issues.append(
                    _issue(
                        f["shape_index"],
                        "face_not_larger_than_head",
                        "error",
                        f"face 面积是 head 的 {r:.2f} 倍，"
                        f"超过 {ratio_max:.2f}，face 不应大于 head",
                    )
                )
                break  # one report per face is enough
    return issues


def check_head_in_upper_body(
    group: dict, cfg: dict
) -> list[dict]:
    """Rule: head center should be in the person's upper-body region.

    head_center_y / person_height > threshold means the head is sitting
    low (in the torso/legs) — likely a wrong box or wrong group.

    Args:
        group: One group dict.
        cfg: Config dict.

    Returns:
        Issue list.
    """
    person = group["person"]
    if person is None:
        return []
    y_thr = cfg["head_upper_body_y_ratio"]
    issues: list[dict] = []
    for h in group["heads"]:
        yr = _center_y_ratio(h["box"], person["box"])
        if yr > y_thr:
            issues.append(
                _issue(
                    h["shape_index"],
                    "head_in_upper_body",
                    "warning",
                    f"head 中心位于 person 高度 {yr:.0%} 处"
                    f"（>{y_thr:.0%}），疑似 head 偏离上半身",
                )
            )
    return issues


def check_duplicate_box_in_group(
    group: dict, cfg: dict
) -> list[dict]:
    """Rule: same-label boxes in one group should not heavily overlap.

    Args:
        group: One group dict.
        cfg: Config dict.

    Returns:
        Issue list.
    """
    iou_thr = cfg["duplicate_iou_thr"]
    issues: list[dict] = []
    for label, boxes in (("head", group["heads"]), ("face", group["faces"])):
        n = len(boxes)
        for i in range(n):
            for j in range(i + 1, n):
                iou = _iou(boxes[i]["box"], boxes[j]["box"])
                if iou > iou_thr:
                    issues.append(
                        _issue(
                            boxes[j]["shape_index"],
                            "duplicate_box_in_group",
                            "warning",
                            f"同组 {label} 框 IoU={iou:.2f}"
                            f"（>{iou_thr:.2f}），疑似重复标注",
                        )
                    )
    return issues


def check_person_missing_head(
    group: dict, cfg: dict
) -> list[dict]:
    """Rule: a group with a person but no head is a likely miss.

    Kept conservative: only reported when a person box exists and the
    group has zero heads. (Grouping stage handles orphan head/face.)

    Args:
        group: One group dict.
        cfg: Config dict (unused, kept for uniform signature).

    Returns:
        Issue list.
    """
    person = group["person"]
    if person is None:
        return []
    if group["heads"]:
        return []
    return [
        _issue(
            person["shape_index"],
            "person_missing_head",
            "warning",
            "person 组内缺少 head 框，疑似漏标 head",
        )
    ]


# Ordered rule registry.
RULES: list[Callable[[dict, dict], list[dict]]] = [
    check_head_inside_person,
    check_face_inside_head,
    check_face_not_larger_than_head,
    check_head_in_upper_body,
    check_duplicate_box_in_group,
    check_person_missing_head,
]


# ============================================
# Per-image driver
# ============================================


def process_one_image(gt_path: str, cfg: dict) -> dict:
    """Run all spatial rules over one annotation JSON.

    Args:
        gt_path: Path to the (unified) annotation JSON.
        cfg: Merged config dict.

    Returns:
        Per-image report record.
    """
    try:
        groups, info = load_groups(gt_path)
    except Exception as e:  # noqa: BLE001
        return {
            "gt_path": gt_path,
            "image": osp.basename(gt_path),
            "error": f"parse: {e}",
            "groups": [],
            "issues": [],
        }

    issues: list[dict] = []
    for g in groups:
        for rule_fn in RULES:
            issues.extend(rule_fn(g, cfg))

    return {
        "gt_path": gt_path,
        "image": info.get("imagePath") or osp.basename(gt_path),
        "error": None,
        "group_count": len(groups),
        "issues": issues,
    }


# ============================================
# Batch driver & reporting
# ============================================


def collect_gt_files(gt_dir: str, suffix: str) -> list[Path]:
    """List annotation JSON files by suffix (sorted).

    Args:
        gt_dir: Directory of annotation JSONs.
        suffix: Filename suffix.

    Returns:
        Sorted list of file Paths.
    """
    return sorted(
        p
        for p in Path(gt_dir).iterdir()
        if p.is_file() and p.name.endswith(suffix)
    )


def compute_summary(records: list[dict]) -> dict:
    """Aggregate per-image records into a summary + per-rule counts.

    Args:
        records: Per-image records.

    Returns:
        Summary dict with totals and per-rule hit counts.
    """
    total = len(records)
    failed = sum(1 for r in records if r.get("error"))
    per_rule: dict[str, dict[str, int]] = {}
    total_issues = 0
    for r in records:
        if r.get("error"):
            continue
        for iss in r.get("issues", []):
            total_issues += 1
            name = iss["rule_name"]
            sev = iss["severity"]
            slot = per_rule.setdefault(
                name, {"error": 0, "warning": 0, "info": 0}
            )
            slot[sev] = slot.get(sev, 0) + 1
    return {
        "total_images": total,
        "failed_images": failed,
        "total_issues": total_issues,
        "images_with_issues": sum(
            1 for r in records if not r.get("error") and r.get("issues")
        ),
        "per_rule": per_rule,
    }


def generate_markdown(
    records: list[dict], summary: dict, top_n: int
) -> str:
    """Generate a Markdown report.

    Args:
        records: Per-image records.
        summary: Summary dict.
        top_n: Rows in the Top-N table.

    Returns:
        Markdown string.
    """
    lines: list[str] = []
    lines.append("# Person/Head/Face Spatial QA Report")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Total images | {summary['total_images']} |")
    lines.append(f"| Failed images | {summary['failed_images']} |")
    lines.append(f"| Images with issues | {summary['images_with_issues']} |")
    lines.append(f"| Total issues | {summary['total_issues']} |")
    lines.append("")

    per_rule = summary.get("per_rule", {})
    if per_rule:
        lines.append("## Per-Rule Hits")
        lines.append("")
        lines.append("| Rule | error | warning | info |")
        lines.append("|------|-------|---------|------|")
        for name in [r.__name__.replace("check_", "") for r in RULES]:
            slot = per_rule.get(name, {})
            e = slot.get("error", 0)
            w = slot.get("warning", 0)
            i = slot.get("info", 0)
            if e or w or i:
                lines.append(f"| {name} | {e} | {w} | {i} |")
        lines.append("")

    # Top-N issues.
    flat: list[tuple[str, dict]] = []
    for rec in records:
        if rec.get("error"):
            continue
        img = osp.basename(rec.get("gt_path", ""))
        for iss in rec.get("issues", []):
            flat.append((img, iss))
    # error first, then warning, then info.
    sev_rank = {"error": 0, "warning": 1, "info": 2}
    flat.sort(key=lambda x: sev_rank.get(x[1]["severity"], 9))

    lines.append(f"## Top {min(top_n, len(flat))} Issues")
    lines.append("")
    lines.append("| Rank | Image | shape# | Rule | Sev | Message |")
    lines.append("|------|-------|--------|------|-----|---------|")
    for rank, (img, iss) in enumerate(flat[:top_n], 1):
        lines.append(
            f"| {rank} | {img} | {iss['shape_index']} "
            f"| {iss['rule_name']} | {iss['severity']} "
            f"| {iss['message']} |"
        )
    lines.append("")

    failed = [r for r in records if r.get("error")]
    if failed:
        lines.append("## Failed Files")
        lines.append("")
        for r in failed:
            lines.append(f"- `{r['gt_path']}`: {r['error']}")
        lines.append("")
    return "\n".join(lines)


def write_inspector_tsv(
    records: list[dict], tsv_path: str
) -> int:
    """Write issues to an Inspector-importable TSV.

    Columns match the native Inspector external-result table (identical
    to pose_qa/grouping/group_merger.py and pose_qa/qa/export_for_inspector.py)::

        file_path  shape_index  rule_name  severity  message

    Args:
        records: Per-image records.
        tsv_path: Output TSV path.

    Returns:
        Number of rows written.
    """
    header = ["file_path", "shape_index", "rule_name", "severity", "message"]
    rows = 0
    with open(tsv_path, "w", encoding="utf-8", newline="") as f:
        f.write("\t".join(header) + "\n")
        for rec in records:
            if rec.get("error"):
                continue
            filename = osp.basename(rec.get("gt_path", ""))
            for iss in rec.get("issues", []):
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


# ============================================
# Config & CLI
# ============================================


def merge_config(args: argparse.Namespace) -> dict[str, Any]:
    """Merge configs with priority: CLI > script variables.

    Args:
        args: Parsed CLI args.

    Returns:
        Merged config dict.
    """
    cfg: dict[str, Any] = {}
    if GT_DIR:
        cfg["gt_dir"] = GT_DIR
    if OUTPUT_PREFIX:
        cfg["output_prefix"] = OUTPUT_PREFIX
    cfg.setdefault("gt_suffix", GT_SUFFIX)
    cfg.setdefault("head_inside_person_thr", HEAD_INSIDE_PERSON_THR)
    cfg.setdefault("face_inside_head_thr", FACE_INSIDE_HEAD_THR)
    cfg.setdefault("face_overflow_thr", FACE_OVERFLOW_THR)
    cfg.setdefault("face_area_ratio_max", FACE_AREA_RATIO_MAX)
    cfg.setdefault("head_upper_body_y_ratio", HEAD_UPPER_BODY_Y_RATIO)
    cfg.setdefault("duplicate_iou_thr", DUPLICATE_IOU_THR)
    cfg.setdefault("workers", WORKERS)
    cfg.setdefault("no_progress", NO_PROGRESS)
    cfg.setdefault("top_n", TOP_N_REPORT)

    if getattr(args, "gt_dir", None):
        cfg["gt_dir"] = args.gt_dir
    if getattr(args, "output", None):
        cfg["output_prefix"] = args.output
    if getattr(args, "gt_suffix", None):
        cfg["gt_suffix"] = args.gt_suffix
    if getattr(args, "no_progress", False):
        cfg["no_progress"] = True
    return cfg


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Spatial geometric validation for person/head/face.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--gt-dir", help="Directory of (unified) annotation JSONs."
    )
    parser.add_argument(
        "--output", "-o", help="Output report prefix (no extension)."
    )
    parser.add_argument(
        "--gt-suffix", default=".json",
        help=f"Annotation filename suffix (default: {GT_SUFFIX}).",
    )
    parser.add_argument(
        "--no-progress", action="store_true", help="Disable progress bar."
    )
    return parser.parse_args()


def main() -> int:
    """Run the spatial QA pipeline over a directory.

    Returns:
        Exit code: 0 on success, non-zero on error.
    """
    cfg = merge_config(parse_args())
    for key in ("gt_dir", "output_prefix"):
        if not cfg.get(key):
            print(
                f"ERROR: {key} not set. Use CLI or edit script CONFIG.",
                file=sys.stderr,
            )
            return 1

    print(f"[INFO] GT dir:    {cfg['gt_dir']}")
    print(f"[INFO] Output:    {cfg['output_prefix']}")

    files = collect_gt_files(cfg["gt_dir"], cfg["gt_suffix"])
    print(f"[INFO] Found {len(files)} annotation files")
    if not files:
        print("[INFO] Nothing to process.", file=sys.stderr)
        return 0

    records: list[dict] = []
    workers = int(cfg["workers"])

    def _do(path: Path) -> dict:
        return process_one_image(str(path), cfg)

    if workers > 1 and len(files) > 1:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(_do, p): p for p in files}
            it = as_completed(futs)
            if not cfg["no_progress"]:
                it = tqdm(it, total=len(files), desc="Spatial", unit="img")
            for fut in it:
                records.append(fut.result())
    else:
        it = files
        if not cfg["no_progress"]:
            it = tqdm(it, total=len(files), desc="Spatial", unit="img")
        for p in it:
            records.append(_do(p))

    summary = compute_summary(records)

    out_prefix = Path(cfg["output_prefix"])
    out_prefix.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "config": {
            "gt_dir": cfg["gt_dir"],
            "gt_suffix": cfg["gt_suffix"],
            "thresholds": {
                "head_inside_person_thr": cfg["head_inside_person_thr"],
                "face_inside_head_thr": cfg["face_inside_head_thr"],
                "face_overflow_thr": cfg["face_overflow_thr"],
                "face_area_ratio_max": cfg["face_area_ratio_max"],
                "head_upper_body_y_ratio": cfg["head_upper_body_y_ratio"],
                "duplicate_iou_thr": cfg["duplicate_iou_thr"],
            },
        },
        "summary": summary,
        "per_image": records,
    }
    json_path = out_prefix.with_suffix(".json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"[INFO] JSON report: {json_path}")

    md_path = out_prefix.with_suffix(".md")
    md_path.write_text(
        generate_markdown(records, summary, int(cfg["top_n"])),
        encoding="utf-8",
    )
    print(f"[INFO] Markdown report: {md_path}")

    tsv_path = out_prefix.with_name(out_prefix.name + "_review.tsv")
    rows = write_inspector_tsv(records, str(tsv_path))
    print(f"[INFO] Inspector TSV ({rows} rows): {tsv_path}")

    print("\nSummary:")
    print(f"  images: {summary['total_images']}, "
          f"with issues: {summary['images_with_issues']}, "
          f"total issues: {summary['total_issues']}")
    if summary["per_rule"]:
        print("  per-rule:")
        for name in [r.__name__.replace("check_", "") for r in RULES]:
            slot = summary["per_rule"].get(name, {})
            hits = sum(slot.values())
            if hits:
                print(f"    {name}: {hits} ({slot})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
