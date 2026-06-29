#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Distribution-based QA for person/head/face via a baseline.

This is the **statistical outlier stage** of the pose QA pipeline. Unlike
spatial_check.py (fixed-threshold rules), this compares each new
annotation against a distribution learned from a trusted BASELINE corpus
to catch values that are "not wrong by a hard rule, but abnormal relative
to how good data usually looks".

Two modes, one tool:

    --build-baseline   Scan a trusted, hand-verified corpus and save its
                       per-metric distribution (median, p1, p5, p95, p99)
                       to a baseline JSON. Run this ONCE your baseline
                       data is ready.

    --check            Score a NEW batch against the baseline. Any metric
                       value outside [p5, p95] is medium-risk, outside
                       [p1, p99] is high-risk. Emits json + md + Inspector
                       TSV (same format as the other QA stages).

Metrics (all stable in real data, verified on 300-file sample)::

    head_area/person_area     head box area / person box area
    face_area/head_area       face box area / head box area
    head_cy_ratio             head center y / person height (upper body)
    head_aspect_ratio         head width / head height
    face_aspect_ratio         face width / face height

All metrics are computed WITHIN a group_id (a person + its head/face),
so the input should be group_id-unified first (group_merger.py).

Usage::

    # 1. Build a baseline from a hand-verified corpus (run once)
    python pose_qa/qa/baseline_stats.py \\
        --build-baseline --gt-dir D:/data/baseline_corpus \\
        -o D:/report/baseline.json

    # 2. Check a new batch against that baseline
    python pose_qa/qa/baseline_stats.py \\
        --check --gt-dir D:/data/labels_fixed \\
        --baseline D:/report/baseline.json \\
        -o D:/report/baseline_check
"""

from __future__ import annotations

import argparse
import json
import math
import os.path as osp
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Optional

import numpy as np

try:
    from tqdm import tqdm
except ImportError:

    def tqdm(iterable=None, *args, **kwargs):
        """Minimal fallback for tqdm when not installed."""
        return iterable


# ============================================
# CONFIG
# ============================================
GT_DIR: str = r"D:\data\labels_fixed"
OUTPUT: str = r"D:\report\baseline"
BASELINE_PATH: str = r"D:\report\baseline.json"

# Metrics to track. Each entry: name -> (kind, numerator, denominator)
#   kind "ratio_area":    area(num_box) / area(den_box)
#   kind "center_y":      num center y normalized into den height
#   kind "aspect_ratio":  num box width / height
# All are computed within a group_id (num and den share the gid).
METRICS = [
    ("head_area/person_area", "ratio_area", "head", "person"),
    ("face_area/head_area", "ratio_area", "face", "head"),
    ("head_cy_ratio", "center_y", "head", "person"),
    ("head_aspect_ratio", "aspect_ratio", "head", None),
    ("face_aspect_ratio", "aspect_ratio", "face", None),
]
METRIC_NAMES = [m[0] for m in METRICS]

WORKERS: int = 8
NO_PROGRESS: bool = False
TOP_N_REPORT: int = 50

BOX_TYPES = {"rectangle", "bbox", "box"}
TARGET_LABELS = {"person", "head", "face"}

# Percentile bands for outlier severity.
P_LOW_HIGH = (5, 95)  # outside -> warning (medium risk)
P_LOW_ERR = (1, 99)  # outside -> error (high risk)


# ============================================
# Parsing & geometry
# ============================================


def box_from_points(
    points: list,
) -> Optional[tuple[float, float, float, float]]:
    """Normalize rectangle points to (x1, y1, x2, y2).

    Args:
        points: The shape's points list (2-corner or 4-corner).

    Returns:
        (x1,y1,x2,y2) with x1<=x2, y1<=y2, or None if degenerate.
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


def _area(b: tuple[float, float, float, float]) -> float:
    """Area of an (x1,y1,x2,y2) box."""
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def _center_y(b: tuple[float, float, float, float]) -> float:
    """Center y of a box."""
    return (b[1] + b[3]) / 2.0


def load_groups(json_path: str) -> tuple[list[dict], dict]:
    """Load a JSON and group person/head/face rectangles by group_id.

    Args:
        json_path: Path to the annotation JSON.

    Returns:
        (groups, info) where each group is
        ``{"gid": int, "person": [boxes], "head": [boxes],
        "face": [boxes]}`` and each box is
        ``{"box": (x1,y1,x2,y2), "shape_index": int}``.
        Ungrouped shapes (group_id=None) are skipped.
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
            continue
        box = box_from_points(sh.get("points", []))
        if box is None:
            continue
        rec = {"box": box, "shape_index": idx}
        g = by_gid.setdefault(
            gid,
            {"gid": gid, "person": [], "head": [], "face": []},
        )
        if label == "person":
            g["person"].append(rec)
        elif label == "head":
            g["head"].append(rec)
        else:
            g["face"].append(rec)
    return list(by_gid.values()), info


def compute_metrics_for_group(group: dict) -> list[dict]:
    """Compute all metric values for one group.

    Each (num, den) box pair within the group yields one sample per
    applicable metric. A group with multiple heads/faces yields several
    samples.

    Args:
        group: One group dict from load_groups.

    Returns:
        List of ``{name, value, shape_index}`` samples.
    """
    samples: list[dict] = []
    for name, kind, num_lbl, den_lbl in METRICS:
        num_boxes = group.get(num_lbl, [])
        if kind == "aspect_ratio":
            for nb in num_boxes:
                b = nb["box"]
                h = b[3] - b[1]
                if h <= 0:
                    continue
                samples.append(
                    {
                        "name": name,
                        "value": (b[2] - b[0]) / h,
                        "shape_index": nb["shape_index"],
                    }
                )
            continue

        den_boxes = group.get(den_lbl, [])
        for nb in num_boxes:
            for db in den_boxes:
                if kind == "ratio_area":
                    da = _area(db["box"])
                    if da <= 0:
                        continue
                    samples.append(
                        {
                            "name": name,
                            "value": _area(nb["box"]) / da,
                            "shape_index": nb["shape_index"],
                        }
                    )
                elif kind == "center_y":
                    dh = db["box"][3] - db["box"][1]
                    if dh <= 0:
                        continue
                    samples.append(
                        {
                            "name": name,
                            "value": (_center_y(nb["box"]) - db["box"][1])
                            / dh,
                            "shape_index": nb["shape_index"],
                        }
                    )
    return samples


# ============================================
# Baseline build
# ============================================


def build_baseline(
    gt_dir: str, suffix: str, workers: int, no_progress: bool
) -> dict:
    """Scan a trusted corpus and compute the baseline distribution.

    Args:
        gt_dir: Directory of baseline annotation JSONs.
        suffix: Filename suffix.
        workers: Thread pool size.
        no_progress: Disable progress bar.

    Returns:
        Baseline dict::

            {"metrics": {name: {n, median, p1, p5, p95, p99, min, max}},
             "config": {...}}
    """
    files = sorted(
        p
        for p in Path(gt_dir).iterdir()
        if p.is_file() and p.name.endswith(suffix)
    )
    print(f"[baseline] scanning {len(files)} files in {gt_dir}")
    if not files:
        print("[baseline] no files found", file=sys.stderr)
        return {}

    by_metric: dict[str, list[float]] = {n: [] for n in METRIC_NAMES}

    def _scan(path: Path) -> list[dict]:
        groups, _ = load_groups(str(path))
        out: list[dict] = []
        for g in groups:
            out.extend(compute_metrics_for_group(g))
        return out

    it = files
    if workers > 1 and len(files) > 1:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(_scan, p): p for p in files}
            it_f = as_completed(futs)
            if not no_progress:
                it_f = tqdm(
                    it_f, total=len(files), desc="Baseline", unit="img"
                )
            for fut in it_f:
                for s in fut.result():
                    by_metric[s["name"]].append(s["value"])
    else:
        if not no_progress:
            it = tqdm(it, total=len(files), desc="Baseline", unit="img")
        for p in it:
            for s in _scan(p):
                by_metric[s["name"]].append(s["value"])

    metrics_out: dict[str, dict] = {}
    for name in METRIC_NAMES:
        vals = by_metric[name]
        if len(vals) < 10:
            print(
                f"[baseline] WARNING: metric '{name}' has only "
                f"{len(vals)} samples; distribution may be unreliable. "
                f"Need >=10, recommend >=200.",
                file=sys.stderr,
            )
        if not vals:
            continue
        arr = np.array(vals, dtype=np.float64)
        metrics_out[name] = {
            "n": int(len(arr)),
            "median": float(np.median(arr)),
            "p1": float(np.percentile(arr, 1)),
            "p5": float(np.percentile(arr, 5)),
            "p95": float(np.percentile(arr, 95)),
            "p99": float(np.percentile(arr, 99)),
            "min": float(arr.min()),
            "max": float(arr.max()),
        }

    return {
        "config": {
            "gt_dir": gt_dir,
            "n_files": len(files),
            "metrics_defined": METRIC_NAMES,
        },
        "metrics": metrics_out,
    }


# ============================================
# Check against baseline
# ============================================


def classify_value(
    value: float, band: dict
) -> tuple[Optional[str], Optional[str]]:
    """Classify one metric value against the baseline band.

    Severity bands (a value is in exactly one):
      - within [p5, p95]            -> normal (None)
      - outside [p5, p95] but within [p1, p99] -> warning (medium risk)
      - outside [p1, p99]           -> error (high risk)

    Note p1 <= p5 <= median <= p95 <= p99, so "outside [p1,p99]" is the
    stricter (more extreme) condition and implies "outside [p5,p95]".

    Args:
        value: The observed value.
        band: Baseline entry for this metric (has p1/p5/p95/p99/median).

    Returns:
        (severity, direction) where severity is None/"warning"/"error"
        and direction is "low"/"high" (which tail of the distribution).
    """
    # High risk: outside the widest band.
    if value < band["p1"] or value > band["p99"]:
        sev = "error"
    # Medium risk: outside the inner band but within the outer band.
    elif value < band["p5"] or value > band["p95"]:
        sev = "warning"
    else:
        return None, None
    direction = "low" if value < band["median"] else "high"
    return sev, direction


def process_one_image(
    gt_path: str, baseline: dict
) -> dict:
    """Score one annotation against the baseline.

    Args:
        gt_path: Path to the new annotation JSON.
        baseline: Baseline dict (with "metrics").

    Returns:
        Per-image record with issues.
    """
    bands = baseline.get("metrics", {})
    try:
        groups, info = load_groups(gt_path)
    except Exception as e:  # noqa: BLE001
        return {
            "gt_path": gt_path,
            "image": osp.basename(gt_path),
            "error": f"parse: {e}",
            "issues": [],
        }

    issues: list[dict] = []
    for g in groups:
        for s in compute_metrics_for_group(g):
            band = bands.get(s["name"])
            if band is None:
                continue
            sev, direction = classify_value(s["value"], band)
            if sev is None:
                continue
            issues.append(
                {
                    "shape_index": s["shape_index"],
                    "rule_name": f"baseline_outlier_{s['name']}",
                    "severity": sev,
                    "message": _build_message(
                        s["name"], s["value"], band, direction
                    ),
                }
            )

    return {
        "gt_path": gt_path,
        "image": info.get("imagePath") or osp.basename(gt_path),
        "error": None,
        "group_count": len(groups),
        "issues": issues,
    }


def _build_message(
    name: str, value: float, band: dict, direction: str
) -> str:
    """Build a human-readable outlier message.

    Args:
        name: Metric name.
        value: Observed value.
        band: Baseline entry.
        direction: "low" or "high".

    Returns:
        Message string.
    """
    lo, hi = (band["p5"], band["p95"])
    verb = "偏低" if direction == "low" else "偏高"
    return (
        f"{name}={value:.3f}{verb}（正常范围 p5~p95: "
        f"{lo:.3f}~{hi:.3f}，中位数 {band['median']:.3f}）"
    )


# ============================================
# Reporting
# ============================================


def compute_summary(records: list[dict]) -> dict:
    """Aggregate per-image records into a summary.

    Args:
        records: Per-image records.

    Returns:
        Summary dict.
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
        "images_with_issues": sum(
            1 for r in records if not r.get("error") and r.get("issues")
        ),
        "total_issues": total_issues,
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
    lines.append("# Baseline Distribution QA Report")
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
        lines.append("## Per-Metric Outliers")
        lines.append("")
        lines.append("| Metric | error | warning |")
        lines.append("|--------|-------|---------|")
        for name in METRIC_NAMES:
            rname = f"baseline_outlier_{name}"
            slot = per_rule.get(rname, {})
            e = slot.get("error", 0)
            w = slot.get("warning", 0)
            if e or w:
                lines.append(f"| {name} | {e} | {w} |")
        lines.append("")

    flat: list[tuple[str, dict]] = []
    for rec in records:
        if rec.get("error"):
            continue
        img = osp.basename(rec.get("gt_path", ""))
        for iss in rec.get("issues", []):
            flat.append((img, iss))
    sev_rank = {"error": 0, "warning": 1, "info": 2}
    flat.sort(key=lambda x: sev_rank.get(x[1]["severity"], 9))

    lines.append(f"## Top {min(top_n, len(flat))} Outliers")
    lines.append("")
    lines.append("| Rank | Image | shape# | Metric | Sev | Message |")
    lines.append("|------|-------|--------|--------|-----|---------|")
    for rank, (img, iss) in enumerate(flat[:top_n], 1):
        metric = iss["rule_name"].replace("baseline_outlier_", "")
        lines.append(
            f"| {rank} | {img} | {iss['shape_index']} | {metric} "
            f"| {iss['severity']} | {iss['message']} |"
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


def write_inspector_tsv(records: list[dict], tsv_path: str) -> int:
    """Write issues to an Inspector-importable TSV.

    Columns match the native Inspector external-result table (identical
    to the other QA stages)::

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
# CLI
# ============================================


def collect_files(gt_dir: str, suffix: str) -> list[Path]:
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


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Distribution-based QA via a baseline: build baseline or "
            "check new data against it."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--build-baseline",
        action="store_true",
        help="Scan a trusted corpus and save its distribution.",
    )
    mode.add_argument(
        "--check",
        action="store_true",
        help="Score new data against a saved baseline.",
    )
    parser.add_argument(
        "--gt-dir", help="Directory of annotation JSONs."
    )
    parser.add_argument(
        "--baseline", help="Baseline JSON path (for --check)."
    )
    parser.add_argument(
        "-o", "--output", help="Output path: baseline JSON (build) or report prefix (check)."
    )
    parser.add_argument(
        "--gt-suffix", default=".json",
        help="Annotation filename suffix (default: .json).",
    )
    parser.add_argument(
        "--workers", type=int, default=WORKERS,
        help=f"Thread pool size (default: {WORKERS}).",
    )
    parser.add_argument(
        "--no-progress", action="store_true", help="Disable progress bar."
    )
    return parser.parse_args()


def main() -> int:
    """Run build-baseline or check.

    Returns:
        Exit code: 0 on success, non-zero on error.
    """
    args = parse_args()
    gt_dir = args.gt_dir or GT_DIR
    if not gt_dir or not osp.isdir(gt_dir):
        print(f"ERROR: --gt-dir required and must exist: {gt_dir}",
              file=sys.stderr)
        return 1

    if args.build_baseline:
        output = args.output or OUTPUT + ".json"
        baseline = build_baseline(
            gt_dir, args.gt_suffix, args.workers, args.no_progress
        )
        if not baseline:
            print("ERROR: baseline is empty", file=sys.stderr)
            return 1
        out_path = Path(output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(baseline, f, ensure_ascii=False, indent=2)
        print(f"\n[baseline] saved to: {out_path}")
        print("[baseline] distribution:")
        for name, b in baseline["metrics"].items():
            print(
                f"  {name}: n={b['n']}, median={b['median']:.3f}, "
                f"p5~p95=[{b['p5']:.3f}, {b['p95']:.3f}], "
                f"p1~p99=[{b['p1']:.3f}, {b['p99']:.3f}]"
            )
        return 0

    # --check mode
    baseline_path = args.baseline or BASELINE_PATH
    if not osp.isfile(baseline_path):
        print(
            f"ERROR: --baseline required and must exist: {baseline_path}",
            file=sys.stderr,
        )
        return 1
    with open(baseline_path, "r", encoding="utf-8") as f:
        baseline = json.load(f)
    if "metrics" not in baseline or not baseline["metrics"]:
        print("ERROR: baseline has no metrics", file=sys.stderr)
        return 1

    output = args.output or OUTPUT
    print(f"[check] baseline: {baseline_path}")
    print(f"[check] gt-dir:   {gt_dir}")
    print(f"[check] output:   {output}")

    files = collect_files(gt_dir, args.gt_suffix)
    print(f"[check] found {len(files)} files")
    if not files:
        return 0

    records: list[dict] = []
    workers = int(args.workers)

    def _do(path: Path) -> dict:
        return process_one_image(str(path), baseline)

    if workers > 1 and len(files) > 1:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(_do, p): p for p in files}
            it = as_completed(futs)
            if not args.no_progress:
                it = tqdm(it, total=len(files), desc="Check", unit="img")
            for fut in it:
                records.append(fut.result())
    else:
        it = files
        if not args.no_progress:
            it = tqdm(it, total=len(files), desc="Check", unit="img")
        for p in it:
            records.append(_do(p))

    summary = compute_summary(records)

    out_prefix = Path(output)
    out_prefix.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "config": {
            "gt_dir": gt_dir,
            "baseline": baseline_path,
            "baseline_corpus_n_files": baseline.get("config", {}).get(
                "n_files"
            ),
        },
        "summary": summary,
        "baseline_metrics": baseline["metrics"],
        "per_image": records,
    }
    json_path = out_prefix.with_suffix(".json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"[check] JSON report: {json_path}")

    md_path = out_prefix.with_suffix(".md")
    md_path.write_text(
        generate_markdown(records, summary, TOP_N_REPORT),
        encoding="utf-8",
    )
    print(f"[check] Markdown report: {md_path}")

    tsv_path = out_prefix.with_name(out_prefix.name + "_review.tsv")
    rows = write_inspector_tsv(records, str(tsv_path))
    print(f"[check] Inspector TSV ({rows} rows): {tsv_path}")

    print("\nSummary:")
    print(
        f"  images: {summary['total_images']}, "
        f"with issues: {summary['images_with_issues']}, "
        f"total issues: {summary['total_issues']}"
    )
    if summary["per_rule"]:
        print("  per-metric:")
        for name in METRIC_NAMES:
            rname = f"baseline_outlier_{name}"
            slot = summary["per_rule"].get(rname, {})
            hits = sum(slot.values())
            if hits:
                print(f"    {name}: {hits} ({slot})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
