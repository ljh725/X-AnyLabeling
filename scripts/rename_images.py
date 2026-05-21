#!/usr/bin/env python3
"""Batch rename image files with sequential numbering."""

import argparse
import os
import re
import sys
from pathlib import Path


IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif', '.webp', '.gif', '.ico', '.svg'}


def natural_sort_key(path):
    """Sort key for natural (human-friendly) ordering."""
    name = path.name
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', name)]


def rename_images(directory, pattern, start=1, dry_run=False):
    """Rename image files in directory using pattern with sequential numbers.

    Args:
        directory: Path to directory containing images.
        pattern: Filename pattern with {n} placeholder, e.g. "img_{n:03d}.jpg".
        start: Starting number for sequence.
        dry_run: If True, only print what would be renamed.

    """
    directory = Path(directory).resolve()
    if not directory.is_dir():
        print(f"Error: Not a directory: {directory}", file=sys.stderr)
        sys.exit(1)

    # Find image files
    images = [p for p in directory.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS]
    images.sort(key=natural_sort_key)

    if not images:
        print("No image files found.")
        return

    print(f"Found {len(images)} image(s) in: {directory}")
    if dry_run:
        print("(Dry run — no changes will be made)")
    print()

    renamed = 0
    for i, old_path in enumerate(images, start=start):
        # Replace {n} or {n:03d} style placeholders
        try:
            new_name = pattern.format(n=i)
        except (KeyError, ValueError) as e:
            print(f"Error: Invalid pattern '{pattern}': {e}", file=sys.stderr)
            sys.exit(1)

        new_path = directory / new_name

        # Avoid overwriting existing files
        if new_path.exists() and new_path != old_path:
            print(f"SKIP (target exists): {old_path.name} -> {new_name}")
            continue

        if new_path == old_path:
            print(f"SKIP (same name): {old_path.name}")
            continue

        print(f"{old_path.name:50s} -> {new_name}")
        if not dry_run:
            old_path.rename(new_path)
            renamed += 1

    print()
    if dry_run:
        print(f"Would rename {len(images)} file(s). Use --execute to apply.")
    else:
        print(f"Renamed {renamed} file(s).")


# ---------------------------------------------------------------------------
# IDE Launch Configuration
# ---------------------------------------------------------------------------
# When running from an IDE (PyCharm / VS Code / etc.), set these defaults:
IDE_DIRECTORY = r"\\192.168.3.248\opt\chengdu\椅子误检\10"              # <-- 修改为你的图片目录
IDE_PATTERN = "Chair_{n:06d}.jpg"          # <-- 修改为你的命名格式
IDE_START = 289                           # <-- 起始编号
IDE_DRY_RUN = False                      # <-- True=仅预览, False=执行重命名
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Batch rename image files with sequential numbering.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  %(prog)s ./my_images "photo_{n:03d}.jpg"
  %(prog)s ./my_images "img_{n}.png" --start 10
  %(prog)s ./my_images "frame_{n:02d}.jpg" --dry-run

IDE Usage:
  Edit the IDE_* constants at the top of this file, then run directly.
"""
    )
    parser.add_argument("directory", nargs="?", help="Directory containing image files")
    parser.add_argument("pattern", nargs="?", help='New filename pattern with {n} placeholder, e.g. "img_{n:03d}.jpg"')
    parser.add_argument("--start", type=int, help="Starting number (default: 1)")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without renaming")

    args = parser.parse_args()

    # Fallback to IDE defaults if arguments are not provided
    directory = args.directory if args.directory else IDE_DIRECTORY
    pattern = args.pattern if args.pattern else IDE_PATTERN
    start = args.start if args.start is not None else IDE_START
    dry_run = args.dry_run or IDE_DRY_RUN

    if not directory or not pattern:
        parser.print_help()
        sys.exit(1)

    rename_images(directory, pattern, start, dry_run)


if __name__ == "__main__":
    main()


"""
功能说明：
    这个脚本用来批量重命名文件夹里的图片文件。
    它会按自然排序（把数字当数字排，不是当字符串）排好图片，
    然后按你指定的格式重新命名，比如 "img_001.jpg"、"img_002.jpg" 这样。
    你可以自定义编号从几开始、编号几位数、文件后缀是什么。
    默认先预览不会真改名，加 --dry-run 或把 IDE_DRY_RUN 改成 True 就是只看不改。
    如果不带命令行参数，会自动用脚本里 IDE_* 开头的默认配置，方便在 IDE 里直接运行。

运行命令样例：

  # 基础用法：把 images 文件夹里的图片重命名为 img_001.jpg, img_002.jpg ...
  python scripts/rename_images.py ./images "img_{n:03d}.jpg"

  # 编号从 10 开始
  python scripts/rename_images.py ./images "photo_{n:03d}.jpg" --start 10

  # 只预览，不真正改名
  python scripts/rename_images.py ./images "frame_{n:02d}.jpg" --dry-run

  # 在 IDE 里直接运行（不用命令行参数）
  # 修改脚本顶部的 IDE_DIRECTORY、IDE_PATTERN、IDE_START、IDE_DRY_RUN 即可
"""
