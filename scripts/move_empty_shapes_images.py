#!/usr/bin/env python3
"""
根据 JSON 标注文件中的 shapes 是否为空，移动对应图片到目标目录。

用法:
    python move_empty_shapes_images.py --img-dir <图片目录> --json-dir <JSON目录> --dst-dir <目标目录>
"""

import argparse
import json
import os
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from multiprocessing import cpu_count
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Move images whose JSON has empty shapes."
    )
    parser.add_argument(
        "--img-dir",
        required=True,
        help="Directory containing images.",
    )
    parser.add_argument(
        "--json-dir",
        required=True,
        help="Directory containing JSON annotation files.",
    )
    parser.add_argument(
        "--dst-dir",
        required=True,
        help="Destination directory to move matched images.",
    )
    return parser.parse_args()


def process_one(json_path: Path, img_dir: Path, dst_dir: Path) -> tuple[bool, str]:
    """处理单个 JSON 文件，若 shapes 为空则移动对应图片。"""
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return False, f"[ERROR] Failed to load {json_path}: {e}"

    shapes = data.get("shapes", None)
    if shapes is None:
        return False, f"[SKIP] {json_path.name}: no 'shapes' key"

    # shapes 为空列表时才移动
    if len(shapes) != 0:
        return False, f"[SKIP] {json_path.name}: shapes not empty ({len(shapes)} items)"

    # 尝试从 JSON 的 imagePath 获取图片名，否则用同名的图片文件
    image_name = data.get("imagePath", "")
    if not image_name:
        # 尝试按同名不同后缀匹配
        base_name = json_path.stem
        candidates = list(img_dir.glob(f"{base_name}.*"))
        # 过滤掉 JSON 本身（如果图片目录和 JSON 目录相同）
        candidates = [c for c in candidates if c.suffix.lower() != ".json"]
        if not candidates:
            return False, f"[SKIP] {json_path.name}: no matching image found"
        img_path = candidates[0]
    else:
        img_path = img_dir / image_name
        if not img_path.exists():
            # 如果 imagePath 带子目录但只按 basename 找
            img_path = img_dir / Path(image_name).name

    if not img_path.exists():
        return False, f"[SKIP] {json_path.name}: image not found -> {img_path.name}"

    dst_path = dst_dir / img_path.name
    try:
        shutil.move(str(img_path), str(dst_path))
        return True, f"[MOVE] {img_path.name} -> {dst_dir}"
    except Exception as e:
        return False, f"[ERROR] Failed to move {img_path.name}: {e}"


def main() -> int:
    args = parse_args()
    img_dir = Path(args.img_dir).resolve()
    json_dir = Path(args.json_dir).resolve()
    dst_dir = Path(args.dst_dir).resolve()

    if not img_dir.is_dir():
        print(f"Image directory does not exist: {img_dir}", file=sys.stderr)
        return 1
    if not json_dir.is_dir():
        print(f"JSON directory does not exist: {json_dir}", file=sys.stderr)
        return 1

    dst_dir.mkdir(parents=True, exist_ok=True)

    json_files = list(json_dir.glob("*.json"))
    if not json_files:
        print("No JSON files found.")
        return 0

    max_workers = cpu_count() * 2
    print(f"Found {len(json_files)} JSON files, using {max_workers} workers...")

    moved = 0
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(process_one, jp, img_dir, dst_dir): jp
            for jp in json_files
        }
        for future in as_completed(futures):
            success, msg = future.result()
            print(msg)
            if success:
                moved += 1

    print(f"\nDone. Moved {moved} / {len(json_files)} images.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
