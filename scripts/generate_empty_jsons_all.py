#!/usr/bin/env python3
"""
为图片批量生成空的 X-AnyLabeling JSON 标注文件，支持指定起始文件位置。

用法:
    python generate_empty_jsons_all.py --img-dir <图片目录> --out-dir <输出目录> [--start-index <起始索引>]
"""

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from multiprocessing import cpu_count
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    print("Error: Pillow is required. Run: pip install Pillow", file=sys.stderr)
    sys.exit(1)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate empty X-AnyLabeling JSON files for all images, with optional start index."
    )
    parser.add_argument(
        "--img-dir",
        required=True,
        help="Directory containing images.",
    )
    parser.add_argument(
        "--out-dir",
        required=True,
        help="Output directory for generated JSON files.",
    )
    parser.add_argument(
        "--img-path-prefix",
        default="",
        help="Prefix for imagePath field (e.g. ..\\ima-half\\).",
    )
    parser.add_argument(
        "--start-index",
        type=int,
        default=0,
        help="Start from the N-th image (0-based, sorted by filename). Default: 0.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=cpu_count() * 2,
        help="Number of worker threads (default: CPU count * 2).",
    )
    return parser.parse_args()


def generate_empty_json(img_path: Path, out_path: Path, img_path_prefix: str) -> tuple[bool, str]:
    """为单张图片生成空的 JSON 标注文件。"""
    try:
        with Image.open(img_path) as im:
            width, height = im.size
    except Exception as e:
        return False, f"[ERROR] Cannot open image {img_path.name}: {e}"

    data = {
        "version": "4.0.0-beta.4",
        "flags": {},
        "checked": False,
        "shapes": [],
        "imagePath": f"{img_path_prefix}{img_path.name}",
        "imageData": None,
        "imageHeight": height,
        "imageWidth": width,
    }

    try:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True, f"[GEN] {out_path.name}"
    except Exception as e:
        return False, f"[ERROR] Failed to write {out_path.name}: {e}"


def main() -> int:
    args = parse_args()
    img_dir = Path(args.img_dir).resolve()
    out_dir = Path(args.out_dir).resolve()

    if not img_dir.is_dir():
        print(f"Image directory does not exist: {img_dir}", file=sys.stderr)
        return 1

    out_dir.mkdir(parents=True, exist_ok=True)

    # 支持的图片扩展名
    img_exts = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}
    img_files = sorted(
        [p for p in img_dir.iterdir() if p.is_file() and p.suffix.lower() in img_exts],
        key=lambda p: p.name
    )

    total = len(img_files)
    if total == 0:
        print("No images found.")
        return 0

    # 应用起始位置
    start_idx = max(0, args.start_index)
    if start_idx >= total:
        print(f"Start index ({start_idx}) exceeds total image count ({total}). Nothing to do.")
        return 0

    img_files = img_files[start_idx:]

    print(f"Total images: {total} | Processing from index {start_idx}: {len(img_files)} files")
    print(f"Output directory: {out_dir}")
    print(f"Processing with {args.workers} workers...\n")

    generated = 0
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {}
        for img_path in img_files:
            out_path = out_dir / f"{img_path.stem}.json"
            futures[executor.submit(generate_empty_json, img_path, out_path, args.img_path_prefix)] = img_path.name

        for future in as_completed(futures):
            success, msg = future.result()
            print(msg)
            if success:
                generated += 1

    print(f"\nDone. Generated {generated} / {len(img_files)} empty JSON files in {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
