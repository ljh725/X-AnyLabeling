#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Convert a pose QA report into an Inspector-importable TSV file.

Output format matches Inspector's native external-result table (the same
shape produced by its own structural rules), e.g.:

    file_path    shape_index    rule_name    severity    message
    s10064.json  142    pose_qa_disagreement    error    [PoseQA] gid=2 r_hip 偏移0.206 (person OKS=0.735)
    s10064.json  148    pose_qa_disagreement    warning  [PoseQA] gid=2 r_ank 偏移0.100 (person OKS=0.735)

Every keypoint whose normalized distance is above the threshold is emitted
as its own row (one suspicious point = one row), regardless of tail/risk
filters — the goal is to fix every off point, so nothing is filtered out.

Columns (tab-separated, with a header row):
    file_path     - JSON annotation basename (e.g. s10064.json)
    shape_index   - index of the keypoint shape in shapes[]
    rule_name     - always "pose_qa_disagreement"
    severity      - error / warning / info (by distance)
    message       - human-readable description

The shape_index is resolved per row by scanning the original annotation
JSON for the point shape matching BOTH group_id and keypoint label. This
is done at conversion time (not stored in the QA report) because
shape_index is volatile — it shifts whenever shapes are edited — so it is
computed against the current on-disk JSON at the moment of import.

Usage:
    python pose_qa/qa/export_for_inspector.py \
        --qa-report D:/report/pose_qa.json \
        --gt-dir D:/data/labels \
        --output D:/report/pose_qa_inspector.tsv

    # Lower the distance threshold to catch more points:
    python pose_qa/qa/export_for_inspector.py \
        --qa-report D:/report/pose_qa.json \
        --gt-dir D:/data/labels \
        --output D:/report/pose_qa_inspector.tsv \
        --kpt-dist-thr 0.05
"""

from __future__ import annotations

import argparse
import json
import os.path as osp
import sys
from typing import Any, Optional


# --- Severity mapping by normalized keypoint distance ---
# dist > 0.3  -> error
# dist > 0.15 -> warning
# else        -> info
SEVERITY_ERROR_THR = 0.3
SEVERITY_WARN_THR = 0.15
RULE_NAME = "pose_qa_disagreement"
DEFAULT_KPT_DIST_THR = 0.1


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Convert pose QA report to Inspector-importable TSV.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--qa-report", required=True,
        help="Path to the pose_qa_compare.py output JSON.",
    )
    parser.add_argument(
        "--gt-dir", required=True,
        help="Directory of original annotation JSONs (X-AnyLabeling format).",
    )
    parser.add_argument(
        "--output", required=True,
        help="Output TSV path.",
    )
    parser.add_argument(
        "--kpt-dist-thr", type=float, default=DEFAULT_KPT_DIST_THR,
        help=(
            "Normalized-distance threshold to export a keypoint "
            f"(default: {DEFAULT_KPT_DIST_THR}). Keypoints below this are "
            "considered fine and skipped."
        ),
    )
    return parser.parse_args()


def find_keypoint_shape_index(
    gt_json_path: str, group_id: Any, kpt_label: str
) -> int:
    """Find the shape_index of a specific keypoint in a group.

    Scans the annotation JSON's `shapes[]` for a point shape matching both
    `group_id` and `label == kpt_label`.

    Args:
        gt_json_path: Path to the original X-AnyLabeling annotation JSON.
        group_id: The group_id to match.
        kpt_label: The keypoint label (e.g. "r_hip").

    Returns:
        The array index, or -1 if not found.
    """
    try:
        with open(gt_json_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return -1

    shapes = data.get("shapes", [])
    if not isinstance(shapes, list):
        return -1

    for i, sh in enumerate(shapes):
        if not isinstance(sh, dict):
            continue
        if sh.get("label") == kpt_label and sh.get("group_id") == group_id:
            return i
    return -1


def severity_for_distance(dist: float) -> str:
    """Map a normalized keypoint distance to an Inspector severity.

    Args:
        dist: Normalized distance (keypoint offset / person-box diagonal).

    Returns:
        One of "error", "warning", "info".
    """
    if dist > SEVERITY_ERROR_THR:
        return "error"
    if dist > SEVERITY_WARN_THR:
        return "warning"
    return "info"


def build_message(
    image_basename: str,
    group_id: Any,
    kpt_label: str,
    dist: float,
    oks: Optional[float],
) -> str:
    """Build a human-readable message for one keypoint issue.

    Args:
        image_basename: The image filename, for context.
        group_id: The person's group_id.
        kpt_label: The suspicious keypoint name.
        dist: The keypoint's normalized distance.
        oks: The person's overall OKS (for context), may be None.

    Returns:
        Message string like:
        "[PoseQA] s10064.jpg gid=2 r_hip 偏移0.206 (person OKS=0.735)"
    """
    oks_str = f"{oks:.3f}" if isinstance(oks, (int, float)) else "-"
    return (
        f"[PoseQA] {image_basename} gid={group_id} {kpt_label} "
        f"偏移{dist:.3f} (person OKS={oks_str})"
    )


def resolve_gt_path(
    gt_dir: str, gt_path_hint: Optional[str], image_name: Optional[str]
) -> Optional[str]:
    """Resolve the absolute GT JSON path for one image.

    Args:
        gt_dir: Directory passed via --gt-dir.
        gt_path_hint: The `gt_path` field from the QA report.
        image_name: The image basename.

    Returns:
        Absolute path if found, else None.
    """
    if gt_path_hint:
        candidate = osp.abspath(gt_path_hint)
        if osp.isfile(candidate):
            return candidate
        candidate = osp.join(gt_dir, osp.basename(gt_path_hint))
        if osp.isfile(candidate):
            return candidate
    if image_name:
        stem = osp.splitext(image_name)[0]
        candidate = osp.join(gt_dir, stem + ".json")
        if osp.isfile(candidate):
            return candidate
        candidate = osp.join(gt_dir, image_name)
        if osp.isfile(candidate):
            return candidate
    return None


def qa_report_to_rows(
    qa_json_path: str,
    gt_dir: str,
    kpt_dist_thr: float = DEFAULT_KPT_DIST_THR,
) -> tuple[list[dict], list[str]]:
    """Convert a QA report into per-keypoint rows (all above threshold).

    No tail/risk filtering — every keypoint above kpt_dist_thr is emitted,
    because the goal is to fix every off point.

    Args:
        qa_json_path: Path to the pose_qa_compare.py output JSON.
        gt_dir: Directory of original annotation JSONs.
        kpt_dist_thr: Minimum normalized distance to export a keypoint.

    Returns:
        Tuple of (rows, warnings). Each row has keys: file_basename,
        shape_index, message, severity.
    """
    with open(qa_json_path, "r", encoding="utf-8") as fh:
        report = json.load(fh)

    rows: list[dict] = []
    warnings: list[str] = []

    for rec in report.get("per_image", []):
        if rec.get("error"):
            warnings.append(
                f"skipped (report error): {rec.get('gt_path')} - "
                f"{rec['error']}"
            )
            continue

        gt_path_hint = rec.get("gt_path")
        image_name = rec.get("image")
        gt_json = resolve_gt_path(gt_dir, gt_path_hint, image_name)
        if not gt_json:
            warnings.append(
                f"skipped (gt json not found): image={image_name} "
                f"hint={gt_path_hint}"
            )
            continue

        gt_basename = osp.basename(gt_json)
        image_basename = osp.basename(image_name or gt_json)

        for person in rec.get("persons", []):
            gid = person.get("group_id")
            oks = person.get("oks")
            per_kpt = person.get("per_kpt_norm_dist", {})
            if not isinstance(per_kpt, dict) or not per_kpt:
                continue

            for kpt_label, dist in per_kpt.items():
                if not isinstance(dist, (int, float)) or dist < kpt_dist_thr:
                    continue

                shape_index = find_keypoint_shape_index(
                    gt_json, gid, kpt_label
                )
                if shape_index < 0:
                    warnings.append(
                        f"skipped (no shape): {image_basename} "
                        f"gid={gid} {kpt_label}"
                    )
                    continue

                severity = severity_for_distance(dist)
                message = build_message(
                    image_basename, gid, kpt_label, dist, oks
                )
                rows.append(
                    {
                        "file_basename": gt_basename,
                        "shape_index": shape_index,
                        "severity": severity,
                        "message": message,
                    }
                )

    return rows, warnings


def write_tsv(rows: list[dict], out_path: str) -> None:
    """Write rows to a TSV file with the Inspector-native header.

    Args:
        rows: List of row dicts from qa_report_to_rows.
        out_path: Output TSV path.
    """
    import os  # noqa: E402

    os.makedirs(osp.dirname(osp.abspath(out_path)), exist_ok=True)
    header = ["file_path", "shape_index", "rule_name", "severity", "message"]
    with open(out_path, "w", encoding="utf-8", newline="") as fh:
        fh.write("\t".join(header) + "\n")
        for r in rows:
            fh.write(
                "\t".join(
                    [
                        r["file_basename"],
                        str(r["shape_index"]),
                        RULE_NAME,
                        r["severity"],
                        r["message"],
                    ]
                )
                + "\n"
            )


def main() -> int:
    """Run the conversion.

    Returns:
        Exit code: 0 on success, non-zero on error.
    """
    args = parse_args()

    if not osp.isfile(args.qa_report):
        print(f"ERROR: qa-report not found: {args.qa_report}",
              file=sys.stderr)
        return 1
    if not osp.isdir(args.gt_dir):
        print(f"ERROR: gt-dir not found: {args.gt_dir}", file=sys.stderr)
        return 1

    print(
        f"[INFO] QA report:    {args.qa_report}\n"
        f"[INFO] GT dir:       {args.gt_dir}\n"
        f"[INFO] Output:       {args.output}\n"
        f"[INFO] kpt-dist-thr: {args.kpt_dist_thr}"
    )

    rows, warnings = qa_report_to_rows(
        args.qa_report, args.gt_dir, kpt_dist_thr=args.kpt_dist_thr,
    )

    write_tsv(rows, args.output)

    sev_counts: dict[str, int] = {}
    kpt_counts: dict[str, int] = {}
    file_counts: dict[str, int] = {}
    for r in rows:
        sev_counts[r["severity"]] = sev_counts.get(r["severity"], 0) + 1
        # Extract kpt label from message for the top-keypoints stat.
        msg = r["message"]
        parts = msg.split()
        if len(parts) >= 4:
            kpt_counts[parts[3]] = kpt_counts.get(parts[3], 0) + 1
        file_counts[r["file_basename"]] = (
            file_counts.get(r["file_basename"], 0) + 1
        )
    print()
    print("=" * 50)
    print("CONVERSION SUMMARY")
    print("=" * 50)
    print(f"  Exported keypoint rows: {len(rows)}")
    print(f"  Across {len(file_counts)} files")
    for sev in ("error", "warning", "info"):
        print(f"    {sev}: {sev_counts.get(sev, 0)}")
    if kpt_counts:
        top_kpts = sorted(kpt_counts.items(), key=lambda x: -x[1])[:5]
        print("  Top suspicious keypoints:")
        for kpt, cnt in top_kpts:
            print(f"    {kpt}: {cnt}")
    if warnings:
        print(f"  Skipped ({len(warnings)}):")
        for w in warnings[:10]:
            print(f"    {w}")
        if len(warnings) > 10:
            print(f"    ... and {len(warnings) - 10} more")
    print(f"\nOutput written: {osp.abspath(args.output)}")
    print(
        "Next: in X-AnyLabeling, open the image dir, then Inspector -> "
        "\"导入\" -> select this TSV file. Clicking a row jumps to that "
        "keypoint."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
