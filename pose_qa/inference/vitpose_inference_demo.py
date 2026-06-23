#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ViTPose inference demo: run ViTPose on human-annotated person boxes.

This is the single-image sanity check after exporting the ONNX (see
pose_qa/docs/pipeline_design.md, step "集成验证"). It proves the
exported ONNX + the affine-crop recipe produce sensible keypoints on a
real image, and that COCO keypoint order matches.

Pipeline (方式 A from the design doc):
    1. Read annotation JSON -> extract person boxes (by group_id).
    2. Read image (BGR).
    3. For each person box:
         bbox_xyxy2cs(padding=1.25)
         -> top_down_affine(192x256)   [reused from dwpose_onnx.py]
         -> normalize (ImageNet mean/std, /255)
    4. Batch-infer the ONNX -> heatmaps (N, 17, 64, 48).
    5. Decode: argmax -> *stride(4) -> remap to original image coords.
    6. Visualize: draw human boxes, model keypoints, and (if present)
       human-annotated keypoints side-by-side. Save image.

Requires (run in the x-anylabeling-cu12 env, NOT vitpose_export):
    conda activate x-anylabeling-cu12
    pip install onnxruntime opencv-python numpy

Usage:
    python pose_qa/inference/vitpose_inference_demo.py ^
        --image D:/data/s1860.jpg ^
        --json D:/.../s1860.json ^
        --onnx D:/models/vitpose-base-simple.onnx ^
        --output D:/out/s1860_demo.jpg
"""

from __future__ import annotations

import argparse
import json
import os.path as osp
import sys
from collections import defaultdict

import cv2
import numpy as np


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

# COCO skeleton edges (index pairs) for drawing.
SKELETON = [
    (0, 1), (0, 2), (1, 3), (2, 4),           # face
    (5, 6),                                   # shoulders
    (5, 7), (7, 9), (6, 8), (8, 10),          # arms
    (5, 11), (6, 12), (11, 12),               # torso
    (11, 13), (13, 15), (12, 14), (14, 16),   # legs
]

# ImageNet normalization (baked into the HF processor config).
IMAGE_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
IMAGE_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="ViTPose inference demo on human-annotated person boxes.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--image", required=True, help="Path to the image file."
    )
    parser.add_argument(
        "--json", required=True, help="Path to the X-AnyLabeling JSON."
    )
    parser.add_argument(
        "--onnx",
        required=True,
        help="Path to the ViTPose ONNX (from export_vitpose_onnx.py).",
    )
    parser.add_argument(
        "--output",
        default="vitpose_demo.jpg",
        help="Output visualization path (default: %(default)s).",
    )
    parser.add_argument(
        "--pred-out",
        default=None,
        help=(
            "Optional: save model predictions as JSON to this path. "
            "If omitted, defaults to <json_dir>/<json_stem>_pred.json. "
            "This file is the 'external model results' input for the QA "
            "pipeline (see pose_qa/docs/pipeline_design.md)."
        ),
    )
    parser.add_argument(
        "--score-thr",
        type=float,
        default=0.3,
        help="Keypoint score threshold (default: %(default)s).",
    )
    return parser.parse_args()


def parse_annotation(json_path: str) -> tuple[list, dict]:
    """Parse X-AnyLabeling JSON into person boxes + keypoints.

    Args:
        json_path: Path to the annotation JSON.

    Returns:
        Tuple of:
        - persons: list of dicts {group_id, bbox (x1,y1,x2,y2), kpts (17,2)
          or NaN, vis (17,) bool}. Only groups with a 'person' rectangle
          are included.
        - info: dict with image metadata (imagePath, imageHeight,
          imageWidth).
    """
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    shapes = data.get("shapes", [])
    info = {
        "imagePath": data.get("imagePath"),
        "imageHeight": data.get("imageHeight"),
        "imageWidth": data.get("imageWidth"),
    }

    # Group shapes by group_id.
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
            # Rectangle may be stored as 2 diagonal points OR 4 corners
            # (the project's native format uses 4 corners). Take min/max
            # across ALL listed points so the box is correct either way.
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            box = (
                float(min(xs)),
                float(min(ys)),
                float(max(xs)),
                float(max(ys)),
            )
            groups[gid]["person_box"] = box
        elif stype == "point" and label in LABEL_TO_IDX and len(pts) >= 1:
            x, y = pts[0]
            visible = not (isinstance(desc, str) and desc.strip() == "invisible")
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
    return persons, info


def load_image(image_path: str) -> np.ndarray:
    """Load image as BGR uint8.

    Args:
        image_path: Path to image.

    Returns:
        BGR uint8 HxWx3 array.
    """
    img = cv2.imread(image_path, cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(f"Cannot read image: {image_path}")
    return img


def crop_and_align(
    image_bgr: np.ndarray,
    bboxes: np.ndarray,
    input_w: int = 192,
    input_h: int = 256,
) -> tuple[np.ndarray, list, list]:
    """Top-down affine crop of person boxes to (input_w, input_h).

    Reuses bbox_xyxy2cs + top_down_affine from the project's dwpose_onnx.

    Args:
        image_bgr: Original image (BGR uint8).
        bboxes: (N, 4) person boxes (x1,y1,x2,y2).
        input_w: Model input width.
        input_h: Model input height.

    Returns:
        Tuple of:
        - blob: (N, 3, input_h, input_w) normalized float32.
        - warp_mats: list of (2,3) forward affine matrices (original ->
          cropped). Kept so decode_heatmaps can invert the transform
          exactly (the scale returned by bbox_xyxy2cs is a relative scale
          wrt /200, NOT pixel w/h, so the old linear remap was wrong and
          keypoints flew off the box).
    """
    # Import the project's geometry helpers (no need to reimplement).
    # This file lives at <proj_root>/pose_qa/inference/, so the project
    # root is three levels up.
    proj_root = osp.dirname(
        osp.dirname(osp.dirname(osp.abspath(__file__)))
    )
    if proj_root not in sys.path:
        sys.path.insert(0, proj_root)
    from anylabeling.services.auto_labeling.pose.dwpose_onnx import (  # noqa: E402
        _fix_aspect_ratio,
        bbox_xyxy2cs,
        get_warp_matrix,
    )

    # Replicate top_down_affine's geometry so we can keep the affine matrix.
    # top_down_affine itself only returns (img, scale), not the matrix, so
    # we redo the same steps here and retain warp_mat for exact inversion.
    aspect_ratio = input_w / input_h
    blobs, warp_mats = [], []
    for bbox in bboxes:
        center, scale = bbox_xyxy2cs(
            np.array(bbox, dtype=np.float32), padding=1.25
        )
        scale_fixed = _fix_aspect_ratio(scale, aspect_ratio=aspect_ratio)
        warp_mat = get_warp_matrix(
            center, scale_fixed, rot=0.0, output_size=(input_w, input_h)
        )
        resized = cv2.warpAffine(
            image_bgr, warp_mat, (input_w, input_h),
            flags=cv2.INTER_LINEAR,
        )
        # resized is BGR uint8 -> RGB -> /255 -> normalize.
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB).astype(np.float32)
        normed = (rgb / 255.0 - IMAGE_MEAN) / IMAGE_STD
        blob = np.transpose(normed, (2, 0, 1))  # (3, H, W)
        blobs.append(blob)
        warp_mats.append(warp_mat.astype(np.float32))
    blob = np.stack(blobs, axis=0).astype(np.float32)
    return blob, warp_mats


def decode_heatmaps(
    heatmaps: np.ndarray,
    warp_mats: list,
    input_w: int = 192,
    input_h: int = 256,
) -> tuple[np.ndarray, np.ndarray]:
    """Decode (N, 17, h, w) heatmaps to original-image coordinates.

    Uses the INVERSE of the forward affine matrix to map cropped-image
    coordinates back to the original image. This exactly reverses the
    crop+align transform (including aspect-ratio padding), so keypoints
    land correctly even for thin/side-view boxes.

    Args:
        heatmaps: (N, 17, h, w) raw model output.
        warp_mats: list of (2,3) forward affine matrices (from
            crop_and_align).
        input_w: Model input width.
        input_h: Model input height.

    Returns:
        Tuple of:
        - keypoints: (N, 17, 2) original-image coords.
        - scores: (N, 17) keypoint confidence.
    """
    n, k, hm_h, hm_w = heatmaps.shape
    stride_x = input_w / hm_w
    stride_y = input_h / hm_h
    keypoints = np.zeros((n, k, 2), dtype=np.float32)
    scores = np.zeros((n, k), dtype=np.float32)

    for i in range(n):
        # Vectorized argmax over (17, h*w).
        flat = heatmaps[i].reshape(k, -1)
        idx = np.argmax(flat, axis=1)            # (17,)
        scores[i] = flat[np.arange(k), idx]
        py = (idx // hm_w).astype(np.float32)
        px = (idx % hm_w).astype(np.float32)
        # Cropped-image coords of each keypoint (stride maps heatmap -> input).
        kpts_in = np.stack(
            [px * stride_x, py * stride_y], axis=1
        )  # (17, 2)

        # Map back to original image via the inverse affine transform.
        # cv2.invertAffineTransform inverts the (2,3) forward matrix from
        # crop_and_align exactly, undoing the aspect-ratio padding too.
        inv_mat = cv2.invertAffineTransform(warp_mats[i])  # (2, 3)
        ones = np.ones((k, 1), dtype=np.float32)
        homog = np.hstack([kpts_in, ones])  # (17, 3)
        keypoints[i] = homog @ inv_mat.T    # (17, 2)
    return keypoints, scores


def visualize(
    image_bgr: np.ndarray,
    persons: list,
    pred_kpts: np.ndarray,
    pred_scores: np.ndarray,
    score_thr: float,
    output_path: str,
) -> None:
    """Draw human boxes, model keypoints, and human keypoints.

    Args:
        image_bgr: Original image (BGR uint8).
        persons: Parsed annotation list (from parse_annotation).
        pred_kpts: (N, 17, 2) model keypoints.
        pred_scores: (N, 17) model scores.
        score_thr: Score threshold for drawing model keypoints.
        output_path: Where to save the visualization.
    """
    canvas = image_bgr.copy()
    # Distinct color per person for box + skeleton.
    person_colors = [
        (0, 0, 255), (0, 255, 0), (255, 0, 0), (0, 255, 255),
        (255, 0, 255), (255, 255, 0), (128, 0, 255), (0, 128, 255),
        (255, 128, 0), (128, 255, 0),
    ]
    gt_color = (0, 165, 255)  # orange for human-annotated points.

    for i, p in enumerate(persons):
        color = person_colors[i % len(person_colors)]
        x1, y1, x2, y2 = [int(v) for v in p["bbox"]]
        cv2.rectangle(canvas, (x1, y1), (x2, y2), color, 2)
        cv2.putText(
            canvas, f"p{p['group_id']}", (x1, max(0, y1 - 5)),
            cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2,
        )

        # Model skeleton + keypoints (filled circles).
        kpts = pred_kpts[i]
        scs = pred_scores[i]
        for a, b in SKELETON:
            if scs[a] < score_thr or scs[b] < score_thr:
                continue
            pa = tuple(kpts[a].astype(int))
            pb = tuple(kpts[b].astype(int))
            cv2.line(canvas, pa, pb, color, 2)
        for j in range(17):
            if scs[j] < score_thr:
                continue
            pt = tuple(kpts[j].astype(int))
            cv2.circle(canvas, pt, 4, color, -1)
            cv2.putText(
                canvas, str(j), (pt[0] + 4, pt[1] - 4),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1,
            )

        # Human-annotated keypoints (hollow orange circles) for comparison.
        gt = p["kpts"]
        for j in range(17):
            if np.isnan(gt[j, 0]):
                continue
            pt = tuple(gt[j].astype(int))
            cv2.circle(canvas, pt, 4, gt_color, 1)

    cv2.imwrite(output_path, canvas)
    print(f"[INFO] Visualization saved: {output_path}")


def save_prediction_json(
    gt_json_path: str,
    image_path: str,
    persons: list,
    pred_kpts: np.ndarray,
    pred_scores: np.ndarray,
    score_thr: float,
    out_path: str,
) -> None:
    """Save ViTPose predictions as a project-native annotation JSON.

    The output uses the SAME structure as a human annotation file
    (version/flags/shapes[]/imagePath/...), so it can be opened directly in
    X-AnyLabeling. shapes[] contains, per person group:
      - the person rectangle (copied verbatim from the GT, same group_id)
      - 17 keypoint points (label = COCO name, coords = model prediction)

    keypoints below `score_thr` are still written (with their low score in
    the shape's `score` field) so nothing is silently dropped; downstream
    code can filter by score.

    File name uses the same basename as the GT (e.g. s55.json); the caller
    is responsible for putting it in a separate directory to avoid
    overwriting the human annotation.

    Args:
        gt_json_path: Path to the source annotation JSON (for metadata).
        image_path: Path to the source image.
        persons: Parsed annotation list (from parse_annotation).
        pred_kpts: (N, 17, 2) model keypoints.
        pred_scores: (N, 17) model scores.
        score_thr: Score threshold (informational; all points are written).
        out_path: Output JSON path.
    """
    # Load GT to copy top-level metadata + the person rectangle shapes.
    with open(gt_json_path, "r", encoding="utf-8") as f:
        gt_data = json.load(f)

    # Index person rectangles by group_id so we can copy them verbatim.
    person_rects_by_gid: dict = {}
    for sh in gt_data.get("shapes", []):
        if (
            isinstance(sh, dict)
            and sh.get("label") == "person"
            and sh.get("shape_type") == "rectangle"
            and sh.get("group_id") is not None
        ):
            person_rects_by_gid[sh["group_id"]] = sh

    shapes_out: list = []
    for i, p in enumerate(persons):
        gid = p["group_id"]

        # 1. Person rectangle (verbatim from GT, same group_id).
        rect = person_rects_by_gid.get(gid)
        if rect is not None:
            shapes_out.append(rect)

        # 2. 17 keypoint points (coords from the model).
        for j, kpt_name in enumerate(COCO_17_ORDER):
            x = float(pred_kpts[i][j][0])
            y = float(pred_kpts[i][j][1])
            s = float(pred_scores[i][j])
            shapes_out.append(
                {
                    "mask": None,
                    "label": kpt_name,
                    "score": s,
                    "points": [[x, y]],
                    "group_id": gid,
                    "description": None,
                    "difficult": False,
                    "shape_type": "point",
                    "flags": {},
                    "attributes": {},
                    "kie_linking": [],
                }
            )

    record = {
        "version": gt_data.get("version", "4.0.0-beta.4"),
        "flags": gt_data.get("flags", {}),
        "checked": gt_data.get("checked", False),
        "shapes": shapes_out,
        "imagePath": osp.basename(image_path),
        "imageData": None,
        "imageHeight": gt_data.get("imageHeight"),
        "imageWidth": gt_data.get("imageWidth"),
        "description": (
            f"ViTPose predictions (score_thr={score_thr}); "
            "keypoint coords are model output."
        ),
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)
    print(f"[INFO] Predictions JSON saved: {out_path}")


def main() -> int:
    """Run the demo end-to-end.

    Returns:
        Exit code: 0 on success, non-zero on error.
    """
    args = parse_args()

    if not osp.isfile(args.image):
        print(f"ERROR: image not found: {args.image}", file=sys.stderr)
        return 1
    if not osp.isfile(args.json):
        print(f"ERROR: json not found: {args.json}", file=sys.stderr)
        return 1
    if not osp.isfile(args.onnx):
        print(f"ERROR: onnx not found: {args.onnx}", file=sys.stderr)
        return 1

    print(f"[1/4] Parsing annotation: {args.json}")
    persons, info = parse_annotation(args.json)
    if not persons:
        print("ERROR: no person boxes with group_id found", file=sys.stderr)
        return 1
    print(f"      Found {len(persons)} persons with boxes")

    print(f"[2/4] Loading image: {args.image}")
    image_bgr = load_image(args.image)
    print(f"      Image size: {image_bgr.shape[1]} x {image_bgr.shape[0]}")

    print("[3/4] ViTPose inference")
    import onnxruntime as ort

    sess = ort.InferenceSession(
        args.onnx, providers=["CPUExecutionProvider"]
    )
    in_name = sess.get_inputs()[0].name
    in_shape = sess.get_inputs()[0].shape  # e.g. [1,3,256,192]
    input_h, input_w = int(in_shape[2]), int(in_shape[3])

    bboxes = np.array([p["bbox"] for p in persons], dtype=np.float32)
    blob, warp_mats = crop_and_align(
        image_bgr, bboxes, input_w=input_w, input_h=input_h
    )
    print(
        f"      Input blob: {blob.shape}, dtype={blob.dtype}, "
        f"range=[{blob.min():.3f}, {blob.max():.3f}]"
    )

    # Run all persons in one forward (static batch=1 ONNX -> loop).
    pred_kpts_list = []
    pred_scores_list = []
    for bi in range(blob.shape[0]):
        single = blob[bi:bi + 1]  # (1,3,H,W)
        heatmaps = sess.run(None, {in_name: single})[0]  # (1,17,h,w)
        kpts, scs = decode_heatmaps(
            heatmaps, [warp_mats[bi]],
            input_w=input_w, input_h=input_h,
        )
        pred_kpts_list.append(kpts[0])
        pred_scores_list.append(scs[0])
    pred_kpts = np.stack(pred_kpts_list, axis=0)
    pred_scores = np.stack(pred_scores_list, axis=0)

    # Print a compact summary.
    print("      Per-person mean score (model confidence):")
    for i, p in enumerate(persons):
        valid = pred_scores[i] >= args.score_thr
        mean_s = pred_scores[i][valid].mean() if valid.any() else 0.0
        print(
            f"        p{p['group_id']}: mean_score={mean_s:.3f}, "
            f"valid_kpts={int(valid.sum())}/17"
        )

    print(f"[4/4] Visualizing -> {args.output}")
    visualize(
        image_bgr, persons, pred_kpts, pred_scores,
        args.score_thr, args.output,
    )

    # Save predictions as JSON (default: alongside the annotation JSON).
    pred_out = args.pred_out
    if not pred_out:
        json_dir = osp.dirname(osp.abspath(args.json))
        pred_out = osp.join(
            json_dir, osp.splitext(osp.basename(args.json))[0] + "_pred.json"
        )
    save_prediction_json(
        args.json, args.image, persons, pred_kpts, pred_scores,
        args.score_thr, pred_out,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
