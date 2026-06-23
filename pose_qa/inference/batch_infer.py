#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Batch ViTPose inference over a directory of annotations.

This is the **batch stage** of the pose QA pipeline (see
pose_qa/docs/pipeline_design.md). It loops vitpose_inference_demo's
single-image logic over every annotation JSON in a directory, producing
one `<stem>_pred.json` per image. Those prediction files are then fed
to pose_qa/qa/pose_qa_compare.py for OKS ranking.

Pipeline (方式 A):
    for each <stem>.json in json_dir:
        parse -> extract person boxes (by group_id)
        read image (from image_dir, matched by stem)
        for each person box: crop+align+normalize (reused from demo)
        ViTPose ONNX inference -> decode heatmaps -> remap
        save <stem>_pred.json next to the annotation

Design:
    - Reuses the demo's functions (parse_annotation, crop_and_align,
      decode_heatmaps, save_prediction_json) — no logic duplication.
    - Resume-safe: skips images whose _pred.json already exists.
    - Read images concurrently (IO-bound), infer serially (GPU-bound;
      ONNX sessions are not thread-safe). The default worker count is for
      image *reading* only.
    - JSON <-> image pairing by stem (supports image/json in separate dirs).

Environment: x-anylabeling-cu12 (needs onnxruntime, opencv, numpy, and the
project's geometry helpers via the demo module).

Usage:
    python pose_qa/inference/batch_infer.py ^
        --json-dir D:/data/labels ^
        --image-dir D:/data/images ^
        --onnx D:/AI_yolo_mode/vitPose/vitpose-base-simple.onnx ^
        --pred-dir D:/data/preds ^
        --workers 4

    # Dry run (list what would be done, no inference):
    python pose_qa/inference/batch_infer.py ^
        --json-dir D:/data/labels --image-dir D:/data/images ^
        --onnx model.onnx --pred-dir D:/data/preds --dry-run
"""

from __future__ import annotations

import argparse
import os.path as osp
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np

# Import the demo as a sibling module (shares the same inference/ dir).
_THIS_DIR = osp.dirname(osp.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)
import vitpose_inference_demo as demo  # noqa: E402


# ============================================
# CONFIG - variable-config mode (edit here)
# ============================================
JSON_DIR: str = r"D:\A0_part1_kps_3_class_dataset\HK-Hard\sort_json_1458"
IMAGE_DIR: str = r"D:\A0_part1_kps_3_class_dataset\HK-Hard\images"
ONNX_PATH: str = r"D:\AI_yolo_mode\vitPose\vitpose-base-simple.onnx"
PRED_DIR: str = r"D:\A0_part1_kps_3_class_dataset\HK-Hard\sort_json_preds_1458"
GT_SUFFIX: str = ".json"
PRED_SUFFIX: str = ".json"      # SAME basename as GT (s55.json), caller
                                # MUST use a separate --pred-dir to avoid
                                # overwriting the human annotation.
SCORE_THR: float = 0.3
WORKERS: int = 8            # image *reading* threads (inference is serial)
NO_PROGRESS: bool = False
IMAGE_EXTS: tuple = (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff")


# ============================================
# Pairing
# ============================================


def find_image_for_stem(stem: str, image_dir: Path) -> Path | None:
    """Find an image file matching the JSON stem.

    Args:
        stem: JSON filename stem (without suffix).
        image_dir: Directory to search.

    Returns:
        Path to the image, or None if not found.
    """
    for ext in IMAGE_EXTS:
        cand = image_dir / f"{stem}{ext}"
        if cand.is_file():
            return cand
    # Case-insensitive fallback.
    lower = stem.lower()
    for p in image_dir.iterdir():
        if not p.is_file():
            continue
        if p.stem.lower() == lower and p.suffix.lower() in IMAGE_EXTS:
            return p
    return None


def collect_jobs(
    json_dir: Path,
    image_dir: Path,
    pred_dir: Path,
    gt_suffix: str,
    pred_suffix: str,
    skip_existing: bool,
) -> list[dict]:
    """Collect per-image jobs to run.

    Args:
        json_dir: Directory of annotation JSONs.
        image_dir: Directory of images.
        pred_dir: Where to write <stem>_pred.json.
        gt_suffix: GT filename suffix.
        pred_suffix: Prediction filename suffix.
        skip_existing: If True, skip images whose pred file already exists.

    Returns:
        List of job dicts {stem, json_path, image_path, pred_path,
        skipped_reason}.
    """
    # Collect GT JSONs. GT and predictions are expected to live in SEPARATE
    # directories (pred uses the same basename as GT), so we don't need to
    # filter out pred files here.
    json_files = [
        p for p in json_dir.iterdir() if p.is_file()
        and p.name.endswith(gt_suffix)
    ]
    jobs = []
    skipped_no_image = 0
    skipped_done = 0
    for jf in json_files:
        stem = jf.name[: -len(gt_suffix)]
        img = find_image_for_stem(stem, image_dir)
        pred_path = pred_dir / f"{stem}{pred_suffix}"
        if img is None:
            jobs.append({
                "stem": stem, "json_path": str(jf),
                "image_path": None, "pred_path": str(pred_path),
                "skipped_reason": "image_not_found",
            })
            skipped_no_image += 1
            continue
        if skip_existing and pred_path.is_file():
            jobs.append({
                "stem": stem, "json_path": str(jf),
                "image_path": str(img), "pred_path": str(pred_path),
                "skipped_reason": "already_done",
            })
            skipped_done += 1
            continue
        jobs.append({
            "stem": stem, "json_path": str(jf),
            "image_path": str(img), "pred_path": str(pred_path),
            "skipped_reason": None,
        })
    return jobs


# ============================================
# Per-image processing
# ============================================


def process_one(
    job: dict,
    sess,
    in_name: str,
    input_h: int,
    input_w: int,
    score_thr: float,
) -> dict:
    """Run inference for one image and save predictions.

    Args:
        job: Job dict from collect_jobs.
        sess: onnxruntime InferenceSession.
        in_name: ONNX input name.
        input_h: Model input height.
        input_w: Model input width.
        score_thr: Keypoint score threshold for counting valid keypoints.

    Returns:
        Result dict {stem, status, n_persons, n_valid, elapsed}.
    """
    t0 = time.time()
    if job["skipped_reason"]:
        return {
            "stem": job["stem"], "status": "skipped",
            "reason": job["skipped_reason"], "n_persons": 0,
            "n_valid": 0, "elapsed": 0.0,
        }
    try:
        persons, info = demo.parse_annotation(job["json_path"])
        if not persons:
            return {
                "stem": job["stem"], "status": "no_person",
                "n_persons": 0, "n_valid": 0,
                "elapsed": time.time() - t0,
            }
        image_bgr = demo.load_image(job["image_path"])
        bboxes = np.array([p["bbox"] for p in persons], dtype=np.float32)
        blob, warp_mats = demo.crop_and_align(
            image_bgr, bboxes, input_w=input_w, input_h=input_h
        )

        pred_kpts_list, pred_scores_list = [], []
        for bi in range(blob.shape[0]):
            single = blob[bi:bi + 1]
            heatmaps = sess.run(None, {in_name: single})[0]
            kpts, scs = demo.decode_heatmaps(
                heatmaps, [warp_mats[bi]],
                input_w=input_w, input_h=input_h,
            )
            pred_kpts_list.append(kpts[0])
            pred_scores_list.append(scs[0])
        pred_kpts = np.stack(pred_kpts_list, axis=0)
        pred_scores = np.stack(pred_scores_list, axis=0)

        demo.save_prediction_json(
            job["json_path"], job["image_path"], persons, pred_kpts,
            pred_scores, score_thr, job["pred_path"],
        )
        return {
            "stem": job["stem"], "status": "ok",
            "n_persons": len(persons), "n_valid": int(
                (pred_scores >= score_thr).sum()
            ),
            "elapsed": time.time() - t0,
        }
    except Exception as e:  # noqa
        return {
            "stem": job["stem"], "status": "error",
            "reason": f"{type(e).__name__}: {e}",
            "n_persons": 0, "n_valid": 0,
            "elapsed": time.time() - t0,
        }


# ============================================
# Driver
# ============================================


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Batch ViTPose inference over an annotation directory.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--json-dir", help="Directory of annotation JSONs.")
    parser.add_argument("--image-dir", help="Directory of images.")
    parser.add_argument("--onnx", help="Path to ViTPose ONNX.")
    parser.add_argument("--pred-dir", help="Output dir for <stem>_pred.json.")
    parser.add_argument(
        "--gt-suffix", default=GT_SUFFIX,
        help=f"GT suffix (default: {GT_SUFFIX}).",
    )
    parser.add_argument(
        "--pred-suffix", default=PRED_SUFFIX,
        help=f"Pred suffix (default: {PRED_SUFFIX}).",
    )
    parser.add_argument(
        "--score-thr", type=float, default=SCORE_THR,
        help=f"Keypoint score threshold (default: {SCORE_THR}).",
    )
    parser.add_argument(
        "--workers", "-w", type=int, default=WORKERS,
        help=f"Image-reading threads; inference is serial "
        f"(default: {WORKERS}).",
    )
    parser.add_argument(
        "--no-progress", action="store_true", help="Disable progress bar."
    )
    parser.add_argument(
        "--overwrite", action="store_true",
        help="Re-run images whose pred file already exists.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="List jobs without running inference.",
    )
    return parser.parse_args()


def merge_config(args: argparse.Namespace) -> dict:
    """Merge configs: CLI > script variables.

    Args:
        args: Parsed CLI args.

    Returns:
        Merged config dict.
    """
    cfg = {
        "json_dir": JSON_DIR,
        "image_dir": IMAGE_DIR,
        "onnx": ONNX_PATH,
        "pred_dir": PRED_DIR,
        "gt_suffix": GT_SUFFIX,
        "pred_suffix": PRED_SUFFIX,
        "score_thr": SCORE_THR,
        "workers": WORKERS,
        "no_progress": NO_PROGRESS,
    }
    if getattr(args, "json_dir", None):
        cfg["json_dir"] = args.json_dir
    if getattr(args, "image_dir", None):
        cfg["image_dir"] = args.image_dir
    if getattr(args, "onnx", None):
        cfg["onnx"] = args.onnx
    if getattr(args, "pred_dir", None):
        cfg["pred_dir"] = args.pred_dir
    if getattr(args, "gt_suffix", None):
        cfg["gt_suffix"] = args.gt_suffix
    if getattr(args, "pred_suffix", None):
        cfg["pred_suffix"] = args.pred_suffix
    if getattr(args, "score_thr", None):
        cfg["score_thr"] = args.score_thr
    if getattr(args, "workers", None):
        cfg["workers"] = args.workers
    if getattr(args, "no_progress", False):
        cfg["no_progress"] = True
    cfg["overwrite"] = bool(getattr(args, "overwrite", False))
    cfg["dry_run"] = bool(getattr(args, "dry_run", False))
    return cfg


def main() -> int:
    """Run the batch inference pipeline.

    Returns:
        Exit code: 0 on success, non-zero on error.
    """
    cfg = merge_config(parse_args())
    for key in ("json_dir", "image_dir", "onnx", "pred_dir"):
        if not cfg.get(key):
            print(
                f"ERROR: {key} not set. Use CLI or edit script CONFIG.",
                file=sys.stderr,
            )
            return 1

    json_dir = Path(cfg["json_dir"])
    image_dir = Path(cfg["image_dir"])
    pred_dir = Path(cfg["pred_dir"])
    if not json_dir.is_dir():
        print(f"ERROR: json-dir not found: {json_dir}", file=sys.stderr)
        return 1
    if not image_dir.is_dir():
        print(f"ERROR: image-dir not found: {image_dir}", file=sys.stderr)
        return 1
    if not osp.isfile(cfg["onnx"]):
        print(f"ERROR: onnx not found: {cfg['onnx']}", file=sys.stderr)
        return 1

    print(f"[INFO] JSON dir:   {json_dir}")
    print(f"[INFO] Image dir:  {image_dir}")
    print(f"[INFO] ONNX:       {cfg['onnx']}")
    print(f"[INFO] Pred dir:   {pred_dir}")
    print(f"[INFO] Workers:    {cfg['workers']} (reading only)")

    jobs = collect_jobs(
        json_dir, image_dir, pred_dir,
        cfg["gt_suffix"], cfg["pred_suffix"],
        skip_existing=not cfg["overwrite"],
    )
    todo = [j for j in jobs if not j["skipped_reason"]]
    n_skip_img = sum(1 for j in jobs if j["skipped_reason"] == "image_not_found")
    n_skip_done = sum(1 for j in jobs if j["skipped_reason"] == "already_done")
    print(
        f"[INFO] Total JSONs: {len(jobs)} | to-run: {len(todo)} | "
        f"skipped(image): {n_skip_img} | skipped(done): {n_skip_done}"
    )

    if cfg["dry_run"]:
        print("\n[DRY RUN] Jobs to run:")
        for j in todo[:20]:
            print(f"  {j['stem']}  <-  {j['image_path']}")
        if len(todo) > 20:
            print(f"  ... and {len(todo) - 20} more")
        return 0

    if not todo:
        print("[INFO] Nothing to do (all skipped or done).")
        return 0

    pred_dir.mkdir(parents=True, exist_ok=True)

    # Load ONNX once (shared across all images; inference is serial).
    import onnxruntime as ort

    providers = ["CPUExecutionProvider"]
    try:
        # Prefer GPU if available.
        avail = ort.get_available_providers()
        if "CUDAExecutionProvider" in avail:
            providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
    except Exception:  # noqa
        pass
    sess = ort.InferenceSession(cfg["onnx"], providers=providers)
    in_name = sess.get_inputs()[0].name
    in_shape = sess.get_inputs()[0].shape
    input_h, input_w = int(in_shape[2]), int(in_shape[3])
    print(f"[INFO] Providers: {sess.get_providers()}")

    # Serial inference over the todo list. Image reading (IO) is the only
    # part worth parallelizing; we keep it simple here and read inside
    # process_one. For 35k images the model itself is the bottleneck, so
    # pre-reading would only help marginally.
    try:
        from tqdm import tqdm
        has_tqdm = not cfg["no_progress"]
    except ModuleNotFoundError:
        has_tqdm = False

    results = []
    it = todo
    if has_tqdm:
        it = tqdm(it, total=len(todo), desc="Infer", unit="img")
    t_start = time.time()
    for job in it:
        r = process_one(
            job, sess, in_name, input_h, input_w, cfg["score_thr"]
        )
        results.append(r)
        if has_tqdm and r["status"] == "error":
            it.write(f"  ERROR {r['stem']}: {r.get('reason')}")
    elapsed = time.time() - t_start

    # Summary.
    n_ok = sum(1 for r in results if r["status"] == "ok")
    n_err = sum(1 for r in results if r["status"] == "error")
    n_noperson = sum(1 for r in results if r["status"] == "no_person")
    total_persons = sum(r.get("n_persons", 0) for r in results)
    print()
    print("=" * 50)
    print("BATCH INFERENCE SUMMARY")
    print("=" * 50)
    print(f"  Processed:  {n_ok}")
    print(f"  Errors:     {n_err}")
    print(f"  No-person:  {n_noperson}")
    print(f"  Total persons: {total_persons}")
    print(f"  Elapsed:    {elapsed:.1f}s ({n_ok / max(elapsed, 1e-9):.1f} img/s)")
    if n_err:
        print("\n  Errors (first 10):")
        for r in [x for x in results if x["status"] == "error"][:10]:
            print(f"    {r['stem']}: {r.get('reason')}")
    print(f"\nNext step: run pose_qa/qa/pose_qa_compare.py with "
          f"--pred-dir {pred_dir}")
    return 0 if n_err == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
