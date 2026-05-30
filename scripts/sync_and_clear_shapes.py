#!/usr/bin/env python3
"""
对比两个 JSON 文件夹，将 A 中存在但 B 中缺失的 JSON 文件复制到目标路径，
并清空其 shapes 字段。

用法:
    python sync_and_clear_shapes.py -a <文件夹A> -b <文件夹B> -o <输出目录>
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
        description="Copy JSON files present in A but missing in B, with shapes cleared."
    )
    parser.add_argument(
        "-a", "--dir-a",
        required=True,
        help="Source directory A containing JSON files.",
    )
    parser.add_argument(
        "-b", "--dir-b",
        required=True,
        help="Reference directory B containing JSON files to compare against.",
    )
    parser.add_argument(
        "-o", "--output",
        required=True,
        help="Destination directory to copy processed JSON files.",
    )
    parser.add_argument(
        "-w", "--workers",
        type=int,
        default=cpu_count() * 2,
        help="Number of worker threads (default: CPU count * 2).",
    )
    return parser.parse_args()


def process_one(src_path: Path, dst_path: Path) -> tuple[bool, str]:
    """读取 JSON，清空 shapes，写入目标路径。"""
    try:
        with open(src_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return False, f"[ERROR] Failed to read {src_path.name}: {e}"

    # 清空 shapes
    if "shapes" in data:
        data["shapes"] = []

    try:
        with open(dst_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True, f"[COPY] {src_path.name} -> {dst_path.parent}"
    except Exception as e:
        return False, f"[ERROR] Failed to write {dst_path.name}: {e}"


def main() -> int:
    args = parse_args()
    dir_a = Path(args.dir_a).resolve()
    dir_b = Path(args.dir_b).resolve()
    out_dir = Path(args.output).resolve()

    if not dir_a.is_dir():
        print(f"Directory A does not exist: {dir_a}", file=sys.stderr)
        return 1
    if not dir_b.is_dir():
        print(f"Directory B does not exist: {dir_b}", file=sys.stderr)
        return 1

    out_dir.mkdir(parents=True, exist_ok=True)

    # 收集文件名（不含扩展名）
    files_a = {p.stem: p for p in dir_a.glob("*.json")}
    files_b = {p.stem for p in dir_b.glob("*.json")}

    missing_names = set(files_a.keys()) - files_b
    if not missing_names:
        print("No missing files found. A and B are identical.")
        return 0

    print(f"A: {len(files_a)} files | B: {len(files_b)} files | Missing in B: {len(missing_names)}")
    print(f"Processing with {args.workers} workers...\n")

    copied = 0
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {}
        for name in missing_names:
            src = files_a[name]
            dst = out_dir / src.name
            futures[executor.submit(process_one, src, dst)] = name

        for future in as_completed(futures):
            success, msg = future.result()
            print(msg)
            if success:
                copied += 1

    print(f"\nDone. Copied {copied} / {len(missing_names)} files to {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
