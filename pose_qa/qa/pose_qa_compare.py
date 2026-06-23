#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pose annotation QA: compare human annotation vs ViTPose prediction.

This is the **CPU-only comparison stage** of the pose QA pipeline (see
pose_qa/docs/pipeline_design.md). It consumes:
    - Human annotation JSONs (X-AnyLabeling format)
    - Model prediction JSONs (from pose_qa/inference/vitpose_inference_demo.py
      --pred-out, or a batched version)

...and produces:
    - <prefix>.json  : full report with per-image, per-person OKS
    - <prefix>.md    : human-readable report with Top-N suspicious targets
    - <prefix>_tail.txt : list of suspicious image filenames

Pipeline (方式 A):
    for each image:
        pair persons by group_id
        -> for each visible keypoint: OKS term + normalized distance
        -> aggregate to per-person risk score
    sort all persons by risk score desc
    mark the top `tail_percent`% as suspicious

Design notes (see docs 3.4):
    - Invisible / missing GT keypoints do NOT participate (COCO convention).
    - Scale `s` = person-box diagonal length (robust for side-view / thin
      boxes; COCO's area-based scale is too optimistic for large boxes).
    - Model keypoints with score < kpt_score_thr are treated as "model
      uncertain" and excluded from the worst-point pick (avoids false
      disagreements where the model itself is unsure).

Usage:
    python pose_qa/qa/pose_qa_compare.py \
        --gt-dir D:/data/labels \
        --pred-dir D:/data/preds \
        --output D:/report/pose_qa
"""

from __future__ import annotations

import argparse
import json
import math
import os.path as osp
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import numpy as np

try:
    from tqdm import tqdm
except ModuleNotFoundError:

    def tqdm(iterable=None, *args, **kwargs):
        """Minimal fallback for tqdm when not installed."""
        return iterable


# --- COCO 17-keypoint layout (matches pose_constants.COCO_KEYPOINT_ORDER) ---
COCO_17_ORDER = [
    "nose",
    "l_eye",
    "r_eye",
    "l_ear",
    "r_ear",
    "l_sho",
    "r_sho",
    "l_elb",
    "r_elb",
    "l_wri",
    "r_wri",
    "l_hip",
    "r_hip",
    "l_knee",
    "r_knee",
    "l_ank",
    "r_ank",
]
LABEL_TO_IDX = {name: i for i, name in enumerate(COCO_17_ORDER)}

# COCO official per-keypoint scale factors (k) for OKS.
KAPPA = np.array(
    [
        0.026,  # 0  nose
        0.025,  # 1  l_eye
        0.025,  # 2  r_eye
        0.035,  # 3  l_ear
        0.035,  # 4  r_ear
        0.079,  # 5  l_sho
        0.079,  # 6  r_sho
        0.072,  # 7  l_elb
        0.072,  # 8  r_elb
        0.062,  # 9  l_wri
        0.062,  # 10 r_wri
        0.107,  # 11 l_hip
        0.107,  # 12 r_hip
        0.087,  # 13 l_knee
        0.087,  # 14 r_knee
        0.089,  # 15 l_ank
        0.089,  # 16 r_ank
    ],
    dtype=np.float32,
)


# ============================================
# CONFIG - edit here for variable-config mode
# ============================================
GT_DIR: str = r"D:\data\labels"
PRED_DIR: str = r"D:\data\preds"
OUTPUT_PREFIX: str = r"D:\report\pose_qa"
GT_SUFFIX: str = ".json"
PRED_SUFFIX: str = ".json"      # SAME basename as GT (s55.json); pred must
                                # live in a separate --pred-dir.
TAIL_PERCENT: float = 10.0
KPT_SCORE_THR: float = 0.3
OKS_WARN: float = 0.5          # OKS below this -> directly suspicious
NORM_DIST_WARN: float = 0.2   # normalized distance above -> suspicious
TOP_N_REPORT: int = 50        # how many rows in the markdown Top-N table
WORKERS: int = 8
NO_PROGRESS: bool = False


# ============================================
# Parsing
# ============================================


def parse_gt_json(
    json_path: str, pred_suffix: str, gt_suffix: str
) -> tuple[list, dict, str | None]:
    """Parse a human annotation JSON.

    Args:
        json_path: Path to the annotation JSON.
        pred_suffix: Suffix to strip when deriving the pred filename.
        gt_suffix: The gt suffix.

    Returns:
        Tuple of:
        - persons: list of {group_id, bbox, kpts (17,2 NaN-filled),
          vis (17,) bool}.
        - info: image metadata.
        - pred_stem: stem used to locate the matching prediction file.
    """
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    shapes = data.get("shapes", [])
    info = {
        "imagePath": data.get("imagePath"),
        "imageHeight": data.get("imageHeight"),
        "imageWidth": data.get("imageWidth"),
    }

    groups: dict = defaultdict(
        lambda: {"person_box": None, "points": {}}
    )
    for sh in shapes:
        if not isinstance(sh, dict):
            continue
        gid = sh.get("group_id")
        if gid is None:
            continue
        label = sh.get("label", "")
        stype = sh.get("shape_type", "")
        pts = sh.get("points", [])
        desc = sh.get("description")

        if label == "person" and stype == "rectangle" and len(pts) >= 2:
            (x1, y1), (x2, y2) = pts[0], pts[1]
            box = (
                float(min(x1, x2)),
                float(min(y1, y2)),
                float(max(x1, x2)),
                float(max(y1, y2)),
            )
            groups[gid]["person_box"] = box
        elif stype == "point" and label in LABEL_TO_IDX and len(pts) >= 1:
            x, y = pts[0]
            visible = not (
                isinstance(desc, str) and desc.strip() == "invisible"
            )
            groups[gid]["points"][label] = (float(x), float(y), visible)

    persons = []
    for gid, g in groups.items():
        if g["person_box"] is None:
            continue
        kpts = np.full((17, 2), np.nan, dtype=np.float32)
        vis = np.zeros((17,), dtype=bool)
        for label, (x, y, v) in g["points"].items():
            i = LABEL_TO_IDX[label]
            kpts[i] = [x, y]
            vis[i] = v
        persons.append(
            {"group_id": gid, "bbox": g["person_box"], "kpts": kpts,
             "vis": vis}
        )

    stem = osp.basename(json_path)
    if stem.endswith(gt_suffix):
        stem = stem[: -len(gt_suffix)]
    pred_stem = stem  # pred file = <stem><pred_suffix>
    return persons, info, pred_stem


def parse_pred_json(
    pred_path: str,
) -> list:
    """Parse a model prediction JSON (project-native annotation format).

    The prediction file uses the SAME structure as a human annotation
    (version/flags/shapes[]/...), produced by save_prediction_json /
    batch_infer. shapes[] contains person rectangles + keypoint points;
    each keypoint's confidence is stored in the shape's `score` field.

    Args:
        pred_path: Path to the prediction JSON (same basename as GT).

    Returns:
        List of {group_id, bbox, keypoints (17,2 NaN-filled),
        scores (17,)}. bbox is the person rectangle; keypoints are the
        model-predicted coords; scores are the per-keypoint confidences.
    """
    with open(pred_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    shapes = data.get("shapes", [])

    groups: dict = defaultdict(
        lambda: {"person_box": None, "points": {}}
    )
    for sh in shapes:
        if not isinstance(sh, dict):
            continue
        gid = sh.get("group_id")
        if gid is None:
            continue
        label = sh.get("label", "")
        stype = sh.get("shape_type", "")
        pts = sh.get("points", [])
        score = sh.get("score")

        if label == "person" and stype == "rectangle" and len(pts) >= 2:
            # Person rectangle may be stored as 2 corners or 4 corners;
            # normalize to (x1,y1,x2,y2).
            xs = [p[0] for p in pts[:4]]
            ys = [p[1] for p in pts[:4]]
            box = (
                float(min(xs)),
                float(min(ys)),
                float(max(xs)),
                float(max(ys)),
            )
            groups[gid]["person_box"] = box
        elif stype == "point" and label in LABEL_TO_IDX and len(pts) >= 1:
            x, y = pts[0]
            s = float(score) if isinstance(score, (int, float)) else 0.0
            groups[gid]["points"][label] = (float(x), float(y), s)

    out = []
    for gid, g in groups.items():
        kpts = np.full((17, 2), np.nan, dtype=np.float32)
        scores = np.zeros((17,), dtype=np.float32)
        for label, (x, y, s) in g["points"].items():
            i = LABEL_TO_IDX[label]
            kpts[i] = [x, y]
            scores[i] = s
        out.append(
            {
                "group_id": gid,
                "bbox": g["person_box"],
                "keypoints": kpts,
                "scores": scores,
            }
        )
    return out


# ============================================
# Comparison
# ============================================


def compute_oks_and_distance(
    gt_kpts: np.ndarray,
    gt_vis: np.ndarray,
    pred_kpts: np.ndarray,
    pred_scores: np.ndarray,
    bbox: tuple,
    kpt_score_thr: float,
    oks_warn: float,
    norm_dist_warn: float,
) -> dict:
    """Compute OKS + normalized distance for one person.

    Args:
        gt_kpts: (17,2) human keypoints, NaN = missing.
        gt_vis: (17,) human visibility (True = visible).
        pred_kpts: (17,2) model keypoints.
        pred_scores: (17,) model confidence.
        bbox: (x1,y1,x2,y2) person box.
        kpt_score_thr: Model score threshold; low-score preds excluded from
            the worst-point pick.
        oks_warn: OKS threshold for direct suspicious flag.
        norm_dist_warn: Normalized-distance threshold for direct suspicious
            flag.

    Returns:
        Dict with oks, max_norm_dist, worst_kpt, per_kpt_norm_dist,
        valid_kpts, flags.
    """
    x1, y1, x2, y2 = bbox
    diag = math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)
    if diag <= 0:
        return {
            "oks": None, "max_norm_dist": None, "worst_kpt": None,
            "per_kpt_norm_dist": {}, "valid_kpts": 0, "risk_score": 0.0,
            "flag": "degenerate_bbox",
        }

    # Valid mask: human-visible AND human-present AND model-confident.
    gt_present = ~np.isnan(gt_kpts[:, 0])
    model_conf = pred_scores >= kpt_score_thr
    mask = gt_vis & gt_present & model_conf

    if mask.sum() == 0:
        return {
            "oks": None, "max_norm_dist": None, "worst_kpt": None,
            "per_kpt_norm_dist": {}, "valid_kpts": 0, "risk_score": 0.0,
            "flag": "no_comparable_kpts",
        }

    d = np.linalg.norm(gt_kpts - pred_kpts, axis=1)  # (17,)
    norm_d = d / diag

    # OKS over comparable keypoints.
    # COCO formula: exp(-d^2 / (2 * s^2 * k^2)).
    # With norm_d = d / s (s = diag), this becomes exp(-norm_d^2 / (2*k^2)),
    # which cancels the scale out of the exponent. This is the standard,
    # scale-normalized form.
    oks_terms = np.exp(-(norm_d[mask] ** 2) / (2 * KAPPA[mask] ** 2))
    oks = float(oks_terms.mean())

    # Worst comparable keypoint.
    masked_norm_d = np.where(mask, norm_d, -1.0)
    worst_local = int(np.argmax(masked_norm_d))
    worst_kpt = COCO_17_ORDER[worst_local]
    max_norm_dist = float(norm_d[worst_local])

    # Risk score: 1 - OKS, boosted if a single point is badly off.
    risk = 1.0 - oks
    if max_norm_dist > 0.3:
        risk += 0.2 * min(max_norm_dist, 1.0)

    flag = "normal"
    if oks < oks_warn or max_norm_dist > norm_dist_warn:
        flag = "suspicious"

    per_kpt = {
        COCO_17_ORDER[i]: float(norm_d[i]) for i in range(17) if mask[i]
    }
    return {
        "oks": oks,
        "max_norm_dist": max_norm_dist,
        "worst_kpt": worst_kpt,
        "per_kpt_norm_dist": per_kpt,
        "valid_kpts": int(mask.sum()),
        "risk_score": float(risk),
        "flag": flag,
    }


def compare_one_file(
    gt_path: str,
    pred_path: str,
    pred_suffix: str,
    gt_suffix: str,
    kpt_score_thr: float,
    oks_warn: float,
    norm_dist_warn: float,
) -> dict:
    """Compare one GT file against its prediction.

    Args:
        gt_path: Path to human annotation JSON.
        pred_path: Path to model prediction JSON.
        pred_suffix: Suffix of prediction files.
        gt_suffix: Suffix of gt files.
        kpt_score_thr: Model score threshold.
        oks_warn: OKS threshold.
        norm_dist_warn: Normalized-distance threshold.

    Returns:
        Dict record for this image (per_image entry).
    """
    try:
        gt_persons, info, pred_stem = parse_gt_json(
            gt_path, pred_suffix, gt_suffix
        )
    except Exception as e:  # noqa
        return {
            "gt_path": gt_path, "pred_path": pred_path,
            "error": f"gt parse: {e}", "persons": [],
        }
    if not osp.isfile(pred_path):
        return {
            "gt_path": gt_path, "pred_path": pred_path,
            "error": "pred not found", "persons": [],
        }
    try:
        pred_persons = parse_pred_json(pred_path)
    except Exception as e:  # noqa
        return {
            "gt_path": gt_path, "pred_path": pred_path,
            "error": f"pred parse: {e}", "persons": [],
        }

    pred_by_gid = {p["group_id"]: p for p in pred_persons}
    persons_out = []
    for gp in gt_persons:
        gid = gp["group_id"]
        pp = pred_by_gid.get(gid)
        if pp is None:
            persons_out.append(
                {"group_id": gid, "bbox": gp["bbox"],
                 "error": "no matching prediction"}
            )
            continue
        metrics = compute_oks_and_distance(
            gp["kpts"], gp["vis"], pp["keypoints"], pp["scores"],
            gp["bbox"], kpt_score_thr, oks_warn, norm_dist_warn,
        )
        persons_out.append({"group_id": gid, "bbox": gp["bbox"], **metrics})

    return {
        "gt_path": gt_path,
        "pred_path": pred_path,
        "image": info.get("imagePath"),
        "persons": persons_out,
        "error": None,
    }


# ============================================
# Reporting
# ============================================


def compute_summary(
    records: list, tail_percent: float
) -> dict:
    """Aggregate per-image records into a summary + mark tail persons.

    Args:
        records: List of per-image records from compare_one_file.
        tail_percent: Percentage of top-risk persons to mark as tail.

    Returns:
        Summary dict.
    """
    # Flatten all persons with a risk_score into one list.
    flat = []
    for rec in records:
        if rec.get("error"):
            continue
        for p in rec["persons"]:
            if "risk_score" in p:
                flat.append((rec, p))
    flat.sort(key=lambda x: x[1]["risk_score"], reverse=True)

    n_total = len(flat)
    n_tail = int(math.ceil(n_total * tail_percent / 100.0))
    tail_cutoff = (
        flat[n_tail - 1][1]["risk_score"]
        if 0 < n_tail <= n_total
        else float("inf")
    )

    # Mark in_tail.
    suspicious_count = 0
    oks_vals = []
    for i, (rec, p) in enumerate(flat):
        p["in_tail"] = i < n_tail
        if p.get("flag") == "suspicious":
            suspicious_count += 1
        if p.get("oks") is not None:
            oks_vals.append(p["oks"])

    summary: dict[str, Any] = {
        "total_images": len(records),
        "failed_images": sum(1 for r in records if r.get("error")),
        "total_persons": n_total,
        "tail_persons": n_tail,
        "suspicious_persons": suspicious_count,
        "tail_cutoff_risk_score": float(tail_cutoff)
        if tail_cutoff != float("inf")
        else None,
    }
    if oks_vals:
        arr = np.array(oks_vals)
        summary["oks_distribution"] = {
            "mean": float(arr.mean()),
            "median": float(np.median(arr)),
            "p10": float(np.percentile(arr, 10)),
            "p90": float(np.percentile(arr, 90)),
        }
    return summary


def generate_markdown(
    records: list, summary: dict, top_n: int
) -> str:
    """Generate a Markdown report.

    Args:
        records: Per-image records.
        summary: Summary dict.
        top_n: Number of rows in the Top-N table.

    Returns:
        Markdown string.
    """
    lines: list[str] = []
    lines.append("# Pose Annotation QA Report")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Total images | {summary['total_images']} |")
    lines.append(f"| Failed images | {summary['failed_images']} |")
    lines.append(f"| Total persons | {summary['total_persons']} |")
    lines.append(f"| Tail persons (top risk) | {summary['tail_persons']} |")
    lines.append(
        f"| Suspicious (OKS<{OKS_WARN} or dist>{NORM_DIST_WARN}) | "
        f"{summary['suspicious_persons']} |"
    )
    if "oks_distribution" in summary:
        od = summary["oks_distribution"]
        lines.append(
            f"| OKS mean / median | {od['mean']:.3f} / {od['median']:.3f} |"
        )
        lines.append(
            f"| OKS p10 / p90 | {od['p10']:.3f} / {od['p90']:.3f} |"
        )
    lines.append("")

    # Flatten for Top-N.
    flat = []
    for rec in records:
        if rec.get("error"):
            continue
        for p in rec["persons"]:
            if "risk_score" in p:
                flat.append((rec, p))
    flat.sort(key=lambda x: x[1]["risk_score"], reverse=True)

    lines.append(f"## Top {min(top_n, len(flat))} Suspicious Targets")
    lines.append("")
    lines.append(
        "| Rank | Image | GID | OKS | MaxNormDist | WorstKpt | "
        "ValidKpts | Risk | Tail |"
    )
    lines.append(
        "|------|-------|-----|-----|-------------|----------|"
        "----------|------|------|"
    )
    for rank, (rec, p) in enumerate(flat[:top_n], 1):
        img = osp.basename(rec.get("gt_path", ""))
        oks = f"{p['oks']:.3f}" if p.get("oks") is not None else "-"
        dist = (
            f"{p['max_norm_dist']:.3f}"
            if p.get("max_norm_dist") is not None
            else "-"
        )
        worst = p.get("worst_kpt") or "-"
        valid = p.get("valid_kpts", 0)
        risk = f"{p['risk_score']:.3f}"
        tail = "YES" if p.get("in_tail") else ""
        lines.append(
            f"| {rank} | {img} | {p['group_id']} | {oks} | {dist} "
            f"| {worst} | {valid} | {risk} | {tail} |"
        )
    lines.append("")

    failed = [r for r in records if r.get("error")]
    if failed:
        lines.append("## Failed Files")
        lines.append("")
        for r in failed:
            lines.append(
                f"- `{r['gt_path']}`: {r['error']}"
            )
        lines.append("")

    return "\n".join(lines)


# ============================================
# Driver
# ============================================


def collect_pairs(
    gt_dir: str, pred_dir: str, gt_suffix: str, pred_suffix: str
) -> list:
    """Collect (gt_path, pred_path) pairs by stem matching.

    GT and predictions are matched by filename stem. Since both now use the
    same basename (e.g. s55.json) but live in SEPARATE directories, no
    suffix-based exclusion is needed.

    Args:
        gt_dir: Directory of human annotation JSONs.
        pred_dir: Directory of model prediction JSONs (separate from gt_dir).
        gt_suffix: GT filename suffix.
        pred_suffix: Prediction filename suffix (usually same as gt_suffix).

    Returns:
        List of (gt_path, pred_path) tuples.
    """
    gt_files = [
        p for p in Path(gt_dir).iterdir()
        if p.is_file() and p.name.endswith(gt_suffix)
    ]
    pred_stems = {
        p.name[: -len(pred_suffix)]
        if p.name.endswith(pred_suffix)
        else p.stem: p
        for p in Path(pred_dir).iterdir()
        if p.is_file() and p.name.endswith(pred_suffix)
    }
    pairs = []
    for gt in gt_files:
        stem = gt.name[: -len(gt_suffix)]
        pred = pred_stems.get(stem)
        if pred is not None:
            pairs.append((str(gt), str(pred)))
    return pairs


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
    if PRED_DIR:
        cfg["pred_dir"] = PRED_DIR
    if OUTPUT_PREFIX:
        cfg["output_prefix"] = OUTPUT_PREFIX
    cfg.setdefault("gt_suffix", GT_SUFFIX)
    cfg.setdefault("pred_suffix", PRED_SUFFIX)
    cfg.setdefault("tail_percent", TAIL_PERCENT)
    cfg.setdefault("kpt_score_thr", KPT_SCORE_THR)
    cfg.setdefault("oks_warn", OKS_WARN)
    cfg.setdefault("norm_dist_warn", NORM_DIST_WARN)
    cfg.setdefault("top_n", TOP_N_REPORT)
    cfg.setdefault("workers", WORKERS)
    cfg.setdefault("no_progress", NO_PROGRESS)

    if getattr(args, "gt_dir", None):
        cfg["gt_dir"] = args.gt_dir
    if getattr(args, "pred_dir", None):
        cfg["pred_dir"] = args.pred_dir
    if getattr(args, "output", None):
        cfg["output_prefix"] = args.output
    if getattr(args, "gt_suffix", None):
        cfg["gt_suffix"] = args.gt_suffix
    if getattr(args, "pred_suffix", None):
        cfg["pred_suffix"] = args.pred_suffix
    if getattr(args, "tail_percent", None) is not None:
        cfg["tail_percent"] = args.tail_percent
    if getattr(args, "kpt_score_thr", None) is not None:
        cfg["kpt_score_thr"] = args.kpt_score_thr
    if getattr(args, "no_progress", False):
        cfg["no_progress"] = True
    return cfg


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Pose QA: compare human vs ViTPose, rank by OKS.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--gt-dir", help="Directory of human annotation JSONs."
    )
    parser.add_argument(
        "--pred-dir", help="Directory of model prediction JSONs."
    )
    parser.add_argument(
        "--output", "-o", help="Output report prefix (no extension)."
    )
    parser.add_argument(
        "--gt-suffix", default=".json",
        help=f"GT filename suffix (default: {GT_SUFFIX}).",
    )
    parser.add_argument(
        "--pred-suffix", default=".json",
        help=f"Pred filename suffix (default: {PRED_SUFFIX}; same basename "
        "as GT, so pred must be in a separate --pred-dir).",
    )
    parser.add_argument(
        "--tail-percent", "-t", type=float,
        help=f"Top-risk%% to mark as tail (default: {TAIL_PERCENT}).",
    )
    parser.add_argument(
        "--kpt-score-thr", type=float,
        help=f"Model score threshold (default: {KPT_SCORE_THR}).",
    )
    parser.add_argument(
        "--no-progress", action="store_true", help="Disable progress bar."
    )
    return parser.parse_args()


def main() -> int:
    """Run the QA comparison pipeline.

    Returns:
        Exit code: 0 on success, non-zero on error.
    """
    cfg = merge_config(parse_args())
    for key in ("gt_dir", "pred_dir", "output_prefix"):
        if not cfg.get(key):
            print(
                f"ERROR: {key} not set. Use CLI or edit script CONFIG.",
                file=sys.stderr,
            )
            return 1

    print(f"[INFO] GT dir:     {cfg['gt_dir']}")
    print(f"[INFO] Pred dir:   {cfg['pred_dir']}")
    print(f"[INFO] Output:     {cfg['output_prefix']}")
    print(
        f"[INFO] Tail%%:      {cfg['tail_percent']}, "
        f"OKS_warn={cfg['oks_warn']}, dist_warn={cfg['norm_dist_warn']}"
    )

    pairs = collect_pairs(
        cfg["gt_dir"], cfg["pred_dir"],
        cfg["gt_suffix"], cfg["pred_suffix"],
    )
    print(f"[INFO] Found {len(pairs)} GT/pred pairs")
    if not pairs:
        print("[INFO] Nothing to compare.", file=sys.stderr)
        return 0

    records: list[dict] = []
    workers = int(cfg["workers"])

    def _do(pair):
        gt_path, pred_path = pair
        return compare_one_file(
            gt_path, pred_path,
            cfg["pred_suffix"], cfg["gt_suffix"],
            cfg["kpt_score_thr"], cfg["oks_warn"], cfg["norm_dist_warn"],
        )

    if workers > 1 and len(pairs) > 1:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(_do, p): p for p in pairs}
            it = as_completed(futs)
            if not cfg["no_progress"]:
                it = tqdm(it, total=len(pairs), desc="Compare", unit="img")
            for fut in it:
                records.append(fut.result())
    else:
        it = pairs
        if not cfg["no_progress"]:
            it = tqdm(it, total=len(pairs), desc="Compare", unit="img")
        for p in it:
            records.append(_do(p))

    summary = compute_summary(records, cfg["tail_percent"])

    # Write JSON report.
    out_prefix = Path(cfg["output_prefix"])
    out_prefix.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "config": {
            "gt_dir": cfg["gt_dir"],
            "pred_dir": cfg["pred_dir"],
            "gt_suffix": cfg["gt_suffix"],
            "pred_suffix": cfg["pred_suffix"],
            "tail_percent": cfg["tail_percent"],
            "kpt_score_thr": cfg["kpt_score_thr"],
            "oks_warn": cfg["oks_warn"],
            "norm_dist_warn": cfg["norm_dist_warn"],
        },
        "summary": summary,
        "per_image": records,
    }
    json_path = out_prefix.with_suffix(".json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"[INFO] JSON report: {json_path}")

    # Write Markdown report.
    md_path = out_prefix.with_suffix(".md")
    md_path.write_text(
        generate_markdown(records, summary, int(cfg["top_n"])),
        encoding="utf-8",
    )
    print(f"[INFO] Markdown report: {md_path}")

    # Write tail image list (deduped).
    tail_path = out_prefix.with_name(out_prefix.name + "_tail.txt")
    tail_imgs = sorted(
        {
            osp.basename(r["gt_path"])
            for r in records
            if not r.get("error")
            and any(p.get("in_tail") for p in r["persons"])
        }
    )
    tail_path.write_text(
        "\n".join(tail_imgs) + ("\n" if tail_imgs else ""),
        encoding="utf-8",
    )
    print(f"[INFO] Tail image list ({len(tail_imgs)}): {tail_path}")

    print("\nSummary:")
    for k, v in summary.items():
        if isinstance(v, dict):
            print(f"  {k}:")
            for kk, vv in v.items():
                print(f"    {kk}: {vv}")
        else:
            print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
