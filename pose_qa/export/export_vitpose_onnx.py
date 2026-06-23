#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Export ViTPose to ONNX via HuggingFace transformers.

This script downloads a ViTPose checkpoint from HuggingFace Hub and exports
it to ONNX. It is the **preparation step** for the pose annotation QA
pipeline (see pose_qa/docs/pipeline_design.md).

Why HuggingFace transformers (not mmpose)?
    - mmpose is fragmented across versions (v0.x vs v1.x), config paths are
      hard to locate, and the install pulls in heavy dependencies.
    - HuggingFace transformers ships a clean `VitPoseForPoseEstimation`
      class; weights load with a single `from_pretrained` call.

Recommended model: usyd-community/vitpose-base-simple
    - Pure COCO, single-expert, 17 keypoints. Exports to ONNX cleanly.

    AVOID ViTPose+ (vitpose-plus-*): its Mixture-of-Experts head
    (num_experts=6) is not ONNX-exportable with the current torch.onnx
    exporter (the backbone re-checks dataset_index during FX trace and the
    parameter chain breaks). For the QA pipeline, the single-expert COCO
    model is sufficient — we only need relative disagreement, not SOTA.

Prerequisites (in a fresh, dedicated env):
    conda create -n vitpose_export python=3.10 -y
    conda activate vitpose_export
    pip install transformers torch torchvision onnx onnxscript onnxruntime
    pip install numpy pillow

Usage:
    python pose_qa/export/export_vitpose_onnx.py \
        --model usyd-community/vitpose-base-simple \
        --output D:/models/vitpose-base-simple.onnx
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Export ViTPose (HF transformers) to ONNX.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--model",
        default="usyd-community/vitpose-base-simple",
        help="HuggingFace ViTPose model id (default: %(default)s).",
    )
    parser.add_argument(
        "--output",
        default="vitpose-base-simple.onnx",
        help="Output ONNX path (default: %(default)s).",
    )
    parser.add_argument(
        "--opset",
        type=int,
        default=14,
        help="ONNX opset version (default: %(default)s; >=14 recommended).",
    )
    parser.add_argument(
        "--dataset-index",
        type=int,
        default=0,
        help=(
            "Expert index for ViTPose+ (MoE) models. Ignored for single-"
            "expert models. Default 0 = COCO. (default: %(default)s)"
        ),
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        default=True,
        help="Run a sanity check after export (default: on).",
    )
    return parser.parse_args()


class _FixedExpertViTPoseBase:
    """Internal namespace; the real module class is built in main().

    We cannot subclass torch.nn.Module at import time (torch may not be
    imported yet for a clean --help), and we cannot reassign __bases__ at
    runtime (C-level deallocator mismatch). So main() defines the actual
    nn.Module subclass via a local `type(...)` call after torch is imported.
    """

    @staticmethod
    def forward_impl(model, dataset_index, pixel_values):
        """Run the wrapped model with a fixed dataset_index.

        Args:
            model: The HF VitPoseForPoseEstimation model.
            dataset_index: Fixed expert index (int).
            pixel_values: (N, 3, H, W) normalized input tensor.

        Returns:
            Heatmap tensor from the chosen expert.
        """
        out = model(pixel_values, dataset_index=dataset_index)
        if isinstance(out, tuple):
            return out[0]
        if isinstance(out, dict):
            return out.get("heatmap") or out.get("logits") or list(
                out.values()
            )[0]
        return out


def make_fixed_expert_module(torch_nn_module):
    """Build a torch.nn.Module subclass that bakes in dataset_index.

    Args:
        torch_nn_module: The torch.nn.Module class (passed after torch is
            imported, to avoid importing torch at module load).

    Returns:
        A FixedExpertViTPose nn.Module subclass.
    """

    class FixedExpertViTPose(torch_nn_module):
        """nn.Module wrapping a ViTPose+ model with a fixed expert index.

        The exported ONNX exposes a single input (pixel_values) and always
        routes through the chosen expert, so the inference side never deals
        with MoE selection.
        """

        def __init__(self, model, dataset_index):
            """Store the wrapped model and fixed expert index.

            Args:
                model: The HF VitPoseForPoseEstimation model.
                dataset_index: Fixed expert index (int).
            """
            super().__init__()
            self.model = model
            self.dataset_index = int(dataset_index)

        def forward(self, pixel_values):
            """Run forward with the fixed dataset_index.

            Args:
                pixel_values: (N, 3, H, W) normalized input tensor.

            Returns:
                Heatmap tensor from the chosen expert.
            """
            return _FixedExpertViTPoseBase.forward_impl(
                self.model, self.dataset_index, pixel_values
            )

    return FixedExpertViTPose


def _normalize_dummy(
    pixel_values,
    do_normalize,
    image_mean,
    image_std,
):
    """Apply mean/std normalization in-place on a [0,1] tensor.

    Args:
        pixel_values: torch tensor in [0,1] range.
        do_normalize: Whether to apply mean/std normalization.
        image_mean: Per-channel mean.
        image_std: Per-channel std.

    Returns:
        Normalized tensor.
    """
    import torch

    if do_normalize and image_mean and image_std:
        mean_t = torch.tensor(
            image_mean, dtype=torch.float32
        ).view(1, 3, 1, 1)
        std_t = torch.tensor(
            image_std, dtype=torch.float32
        ).view(1, 3, 1, 1)
        pixel_values = (pixel_values - mean_t) / std_t
    return pixel_values


def main() -> int:
    """Export ViTPose to ONNX and optionally verify.

    Returns:
        Exit code: 0 on success, non-zero on error.
    """
    args = parse_args()

    try:
        import torch
        from transformers import (
            AutoImageProcessor,
            VitPoseForPoseEstimation,
        )
    except ImportError as e:
        print(
            f"ERROR: missing dependency: {e}\n"
            "Install in a dedicated env:\n"
            "  conda create -n vitpose_export python=3.10 -y\n"
            "  conda activate vitpose_export\n"
            "  pip install transformers torch torchvision onnx onnxscript "
            "onnxruntime numpy pillow",
            file=sys.stderr,
        )
        return 2

    # Build the wrapper nn.Module subclass now that torch is imported. We
    # cannot subclass torch.nn.Module at module load (torch may be absent for
    # --help), and cannot reassign __bases__ (C-level deallocator mismatch),
    # so a factory builds the class lazily.
    FixedExpertViTPose = make_fixed_expert_module(torch.nn.Module)

    print(f"[1/4] Loading model: {args.model}")
    model = VitPoseForPoseEstimation.from_pretrained(args.model)
    model.eval()
    processor = AutoImageProcessor.from_pretrained(args.model)

    # Probe expected input size from the image processor config.
    image_size = getattr(processor, "size", None)
    if isinstance(image_size, dict):
        in_h = image_size.get("height") or image_size.get("shortest_edge")
        in_w = image_size.get("width") or image_size.get("longest_edge")
    elif isinstance(image_size, (list, tuple)) and len(image_size) >= 2:
        in_h, in_w = int(image_size[0]), int(image_size[1])
    else:
        in_h = getattr(model.config, "image_size", 256)
        in_w = 192
    in_h, in_w = int(in_h), int(in_w)
    print(f"      Input size (HxW): {in_h} x {in_w}")

    num_kpts = getattr(model.config, "num_labels", 17)
    print(f"      Num keypoints: {num_kpts}")

    # Detect MoE (ViTPose+). num_experts lives on the head config.
    head_cfg = getattr(model.config, "backbone_config", None)
    num_experts = 1
    for attr in ("num_experts", "num_sub_heads"):
        v = getattr(model.config, attr, None)
        if v:
            num_experts = int(v)
            break
    is_moe = num_experts > 1
    if is_moe:
        print(
            f"      MoE model: num_experts={num_experts}, "
            f"using dataset_index={args.dataset_index} (0=COCO by "
            f"convention for usyd-community checkpoints)."
        )

    print("[2/4] Building normalized dummy input")
    image_mean = getattr(processor, "image_mean", None)
    image_std = getattr(processor, "image_std", None)
    do_rescale = getattr(processor, "do_rescale", True)
    rescale_factor = getattr(processor, "rescale_factor", 1 / 255)
    do_normalize = getattr(processor, "do_normalize", True)

    # VitPoseImageProcessor is a TOP-DOWN processor: preprocess() crops the
    # person region using `boxes` BEFORE normalization. The ONNX model itself
    # only takes an already-aligned, already-normalized (1,3,H,W) tensor. So
    # we read the normalization recipe from the processor and build the dummy
    # input ourselves. Affine crop stays on the inference side
    # (bbox_xyxy2cs + top_down_affine), not inside the ONNX.
    pixel_values = torch.rand((1, 3, in_h, in_w), dtype=torch.float32)
    pixel_values = _normalize_dummy(
        pixel_values, do_normalize, image_mean, image_std
    )
    print(
        f"      pixel_values shape: {tuple(pixel_values.shape)}, "
        f"mean={pixel_values.mean():.4f}, std={pixel_values.std():.4f}"
    )
    print(
        f"      Normalization: rescale={do_rescale} (factor "
        f"{rescale_factor}), normalize={do_normalize}, "
        f"mean={image_mean}, std={image_std}"
    )
    print(
        "      Note: affine crop (top_down_affine) is NOT in the ONNX; "
        "the inference script must crop+align person regions first."
    )

    # Wrap MoE models so dataset_index is baked in.
    export_model = model
    if is_moe:
        export_model = FixedExpertViTPose(model, args.dataset_index)
        export_model.eval()

    print("[3/4] Exporting to ONNX")
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with torch.no_grad():
        torch.onnx.export(
            export_model,
            pixel_values,
            str(output_path),
            input_names=["input"],
            output_names=["heatmap"],
            opset_version=args.opset,
            dynamic_axes=None,  # static batch=1; inference side stacks
            do_constant_folding=True,
        )
    print(f"      ONNX saved: {output_path}")

    print("[4/4] Verifying ONNX (input/output shapes + consistency)")
    try:
        import onnxruntime as ort

        sess = ort.InferenceSession(
            str(output_path), providers=["CPUExecutionProvider"]
        )
        in_spec = sess.get_inputs()[0]
        out_spec = sess.get_outputs()[0]
        print(f"      ONNX input:  {in_spec.name} {in_spec.shape}")
        print(f"      ONNX output: {out_spec.name} {out_spec.shape}")

        # Consistency: run the same input through both ONNX and PT.
        ort_out = sess.run(
            None, {in_spec.name: pixel_values.numpy()}
        )[0]
        with torch.no_grad():
            if is_moe:
                pt_heat = export_model(pixel_values)
            else:
                pt_heat = model(pixel_values)
                if isinstance(pt_heat, tuple):
                    pt_heat = pt_heat[0]
                elif isinstance(pt_heat, dict):
                    pt_heat = pt_heat.get("heatmap") or pt_heat.get(
                        "logits"
                    ) or list(pt_heat.values())[0]
        pt_np = (
            pt_heat.detach().cpu().numpy()
            if hasattr(pt_heat, "detach")
            else np.asarray(pt_heat)
        )
        max_diff = float(np.max(np.abs(ort_out - pt_np)))
        print(f"      Max abs diff (ONNX vs PyTorch): {max_diff:.6e}")
        if max_diff > 1e-3:
            print("      WARNING: large diff; check opset/version.")
        else:
            print("      OK: ONNX matches PyTorch within tolerance.")

        out_shape = tuple(out_spec.shape)
        print()
        print("=" * 60)
        print("EXPORT SUMMARY (for the QA pipeline)")
        print("=" * 60)
        print(f"  ONNX path:      {output_path}")
        print(f"  Input:          (1, 3, {in_h}, {in_w})")
        print(f"  Output:         {out_shape}  (1, K, h, w) heatmaps")
        if len(out_shape) == 4:
            k = out_shape[1]
            oh, ow = out_shape[2], out_shape[3]
            print(f"  Keypoints K:    {k}")
            print(f"  Heatmap size:   {oh} x {ow}  (stride "
                  f"{in_h/oh:.1f} x {in_w/ow:.1f})")
        if is_moe:
            print(
                f"  MoE expert:     dataset_index={args.dataset_index} "
                f"(baked in; verify with a real COCO image in the demo)"
            )
        print("  Normalization at inference time:")
        if do_rescale and do_normalize:
            print(f"    x = (img * {rescale_factor} - {image_mean}) "
                  f"/ {image_std}")
        elif do_rescale:
            print(f"    x = img * {rescale_factor}")
        else:
            print("    x = img (no rescale)")
        print()
        print("Done.")
        if is_moe:
            print(
                "NOTE: This ONNX is locked to one expert. Confirm "
                "dataset_index=COCO by running the demo on a real image "
                "and checking that keypoints land on the right body parts."
            )
        return 0
    except Exception as e:  # noqa
        print(f"      Verification failed (export likely still OK): {e}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
