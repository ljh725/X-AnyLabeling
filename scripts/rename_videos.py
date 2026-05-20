#!/usr/bin/env python3
"""Batch rename video files with sequential numbering."""

import argparse
import os
import re
import sys
from pathlib import Path


VIDEO_EXTENSIONS = {'.mp4', '.avi', '.mov', '.mkv', '.wmv', '.flv', '.webm', '.m4v', '.mpg', '.mpeg', '.3gp'}


def natural_sort_key(path):
    """Sort key for natural (human-friendly) ordering."""
    name = path.name
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', name)]


def rename_videos(directory, pattern, start=1, dry_run=False):
    """Rename video files in directory using pattern with sequential numbers.

    Args:
        directory: Path to directory containing videos.
        pattern: Filename pattern with {n} placeholder, e.g. "video_{n:03d}.mp4".
        start: Starting number for sequence.
        dry_run: If True, only print what would be renamed.

    """
    directory = Path(directory).resolve()
    if not directory.is_dir():
        print(f"Error: Not a directory: {directory}", file=sys.stderr)
        sys.exit(1)

    # Find video files
    videos = [p for p in directory.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS]
    videos.sort(key=natural_sort_key)

    if not videos:
        print("No video files found.")
        return

    print(f"Found {len(videos)} video(s) in: {directory}")
    if dry_run:
        print("(Dry run — no changes will be made)")
    print()

    renamed = 0
    for i, old_path in enumerate(videos, start=start):
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
        print(f"Would rename {len(videos)} file(s). Use --execute to apply.")
    else:
        print(f"Renamed {renamed} file(s).")


# ---------------------------------------------------------------------------
# IDE Launch Configuration
# ---------------------------------------------------------------------------
# When running from an IDE (PyCharm / VS Code / etc.), set these defaults:
IDE_DIRECTORY = r"D:\body-shadow-1"          # <-- 修改为你的视频目录
IDE_PATTERN = "shadow_{n:06d}.mp4"      # <-- 修改为你的命名格式
IDE_START = 1                          # <-- 起始编号
IDE_DRY_RUN = False                     # <-- True=仅预览, False=执行重命名
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Batch rename video files with sequential numbering.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  %(prog)s ./my_videos "scene_{n:03d}.mp4"
  %(prog)s ./my_videos "video_{n}.mp4" --start 10
  %(prog)s ./my_videos "episode_{n:02d}.mkv" --dry-run

IDE Usage:
  Edit the IDE_* constants at the top of this file, then run directly.
"""
    )
    parser.add_argument("directory", nargs="?", help="Directory containing video files")
    parser.add_argument("pattern", nargs="?", help='New filename pattern with {n} placeholder, e.g. "video_{n:03d}.mp4"')
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

    rename_videos(directory, pattern, start, dry_run)


if __name__ == "__main__":
    main()
