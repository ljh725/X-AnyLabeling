#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Data copy script with variable-based configuration.

支持三种配置方式（优先级：命令行参数 > 配置文件 > 脚本变量）：
1. 直接修改脚本顶部的 CONFIG 变量
2. 使用 --config 指定 JSON/YAML 配置文件
3. 使用命令行参数（覆盖其他配置）

功能：
- 从源目录复制指定文件到目标目录
- 支持多个源目录
- 支持文件名列表或通配符匹配
- 保留原文件名，支持保留目录结构或扁平化
- 显示复制进度和统计信息

示例：
    # 变量模式（修改 CONFIG 后直接运行）
    python copy_data.py

    # 命令行模式
    python copy_data.py --source ./data1 ./data2 --target ./output --files "*.jpg" "*.png"

    # 配置文件模式
    python copy_data.py --config copy_config.yaml
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import shutil
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Sequence

try:
    from tqdm import tqdm
except ModuleNotFoundError:

    class _TqdmFallback:
        def __init__(self, iterable=None, total=None, desc="", unit="", disable=False, **kwargs):
            self.iterable = iterable
            self.total = total
            self.n = 0

        def __iter__(self):
            if self.iterable:
                for item in self.iterable:
                    self.n += 1
                    yield item
            else:
                return iter([])

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def update(self, n=1):
            self.n += n

    def tqdm(iterable=None, total=None, desc="", unit="", disable=False, **kwargs):
        return _TqdmFallback(iterable, total=total, desc=desc, unit=unit, disable=disable, **kwargs)


# ============================================
# CONFIG 区域 - 直接修改这些变量即可使用
# ============================================

# 源目录列表（支持一个或多个）
SOURCE_DIRS: list[str] = [
    # 示例: "/path/to/source1",
    # 示例: "/path/to/source2",
]

# 目标目录（文件将复制到这里）
TARGET_DIR: str = ""  # 示例: "/path/to/target"

# 要复制的文件名列表（精确匹配，支持通配符如 "*.jpg"）
# 如果为空列表，则复制所有文件
FILE_PATTERNS: list[str] = [
    # 示例: "*.jpg",
    # 示例: "*.png",
    # 示例: "data_001.json",
]

# 是否保留源目录结构（True: 保留相对路径，False: 扁平化复制到根目录）
KEEP_STRUCTURE: bool = True

# 遇到同名文件时的处理方式: "skip", "overwrite", "rename"
# skip: 跳过不复制
# overwrite: 覆盖已有文件
# rename: 自动重命名（添加序号后缀）
DUPLICATE_ACTION: str = "rename"

# 是否验证文件完整性（复制后比较文件大小）
VERIFY: bool = True

# 最大重试次数（网络文件系统可能不稳定）
MAX_RETRIES: int = 3

# 是否显示进度条
SHOW_PROGRESS: bool = True

# 配置文件路径（可选，YAML/JSON 格式）
CONFIG_FILE: str = ""


# ============================================
# 配置加载
# ============================================


def load_config_file(config_path: str) -> dict[str, Any]:
    """Load configuration from YAML or JSON file."""
    path = Path(config_path)
    if not path.exists():
        print(f"Error: Config file not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    suffix = path.suffix.lower()
    if suffix in (".yaml", ".yml"):
        try:
            import yaml
            return yaml.safe_load(content) or {}
        except ImportError:
            print(
                "Error: PyYAML required for YAML config. Install: pip install pyyaml",
                file=sys.stderr,
            )
            sys.exit(1)
    elif suffix == ".json":
        return json.loads(content)
    else:
        print(
            f"Error: Unsupported config format '{suffix}'. Use .yaml, .yml, or .json",
            file=sys.stderr,
        )
        sys.exit(1)


def merge_config(args: argparse.Namespace) -> dict[str, Any]:
    """Merge configs with priority: CLI > config file > script variables."""
    cfg: dict[str, Any] = {}

    # 1. 脚本变量（最低优先级）
    if SOURCE_DIRS:
        cfg["source_dirs"] = SOURCE_DIRS
    if TARGET_DIR:
        cfg["target_dir"] = TARGET_DIR
    if FILE_PATTERNS:
        cfg["file_patterns"] = FILE_PATTERNS
    cfg.setdefault("keep_structure", KEEP_STRUCTURE)
    cfg.setdefault("duplicate_action", DUPLICATE_ACTION)
    cfg.setdefault("verify", VERIFY)
    cfg.setdefault("max_retries", MAX_RETRIES)
    cfg.setdefault("show_progress", SHOW_PROGRESS)

    # 2. 配置文件（中优先级）
    file_path = CONFIG_FILE or getattr(args, "config", "") or ""
    if file_path:
        file_cfg = load_config_file(file_path)
        cfg.update(file_cfg)

    # 3. 命令行参数（最高优先级）
    if getattr(args, "source_dirs", None):
        cfg["source_dirs"] = args.source_dirs
    if getattr(args, "target_dir", None):
        cfg["target_dir"] = str(args.target_dir)
    if getattr(args, "file_patterns", None):
        cfg["file_patterns"] = args.file_patterns
    if getattr(args, "keep_structure", None) is not None:
        cfg["keep_structure"] = args.keep_structure
    if getattr(args, "duplicate_action", None):
        cfg["duplicate_action"] = args.duplicate_action
    if getattr(args, "no_verify", False):
        cfg["verify"] = False
    if getattr(args, "no_progress", False):
        cfg["show_progress"] = False

    return cfg


# ============================================
# 核心逻辑
# ============================================


def match_patterns(file_name: str, patterns: Sequence[str]) -> bool:
    """Check if filename matches any of the given patterns."""
    if not patterns:
        return True
    return any(fnmatch.fnmatch(file_name, pat) for pat in patterns)


def resolve_duplicate(path: Path, action: str) -> Path:
    """Resolve duplicate file path based on action strategy."""
    if not path.exists():
        return path

    if action == "skip":
        return None

    if action == "overwrite":
        return path

    if action == "rename":
        stem = path.stem
        suffix = path.suffix
        parent = path.parent
        counter = 1
        while True:
            new_name = f"{stem}_{counter:03d}{suffix}"
            new_path = parent / new_name
            if not new_path.exists():
                return new_path
            counter += 1
            if counter > 9999:
                print(f"Warning: Too many duplicates for {path.name}, skipping.", file=sys.stderr)
                return None

    return path


def copy_with_retry(src: Path, dst: Path, max_retries: int) -> bool:
    """Copy file with retry logic."""
    for attempt in range(1, max_retries + 1):
        try:
            shutil.copy2(str(src), str(dst))
            return True
        except (OSError, shutil.Error) as e:
            if attempt < max_retries:
                time.sleep(0.1 * attempt)
                continue
            print(f"Error: Failed to copy {src} after {max_retries} attempts: {e}", file=sys.stderr)
            return False
    return False


def verify_copy(src: Path, dst: Path) -> bool:
    """Verify copied file by comparing sizes."""
    try:
        return src.stat().st_size == dst.stat().st_size
    except OSError:
        return False


def collect_files(source_dirs: list[Path], patterns: list[str]) -> dict[Path, list[Path]]:
    """Collect files from source directories matching patterns.

    Returns:
        dict mapping source_dir -> list of relative file paths
    """
    files_by_dir: dict[Path, list[Path]] = defaultdict(list)

    for src_dir in source_dirs:
        print(f"[INFO] Scanning: {src_dir}")
        count = 0
        skipped = 0

        for root, _, filenames in os.walk(src_dir):
            root_path = Path(root)
            for fname in filenames:
                if match_patterns(fname, patterns):
                    rel_path = root_path.relative_to(src_dir) / fname
                    files_by_dir[src_dir].append(rel_path)
                    count += 1
                else:
                    skipped += 1

        print(f"[INFO] Found {count} matching files (skipped {skipped})")

    return dict(files_by_dir)


def copy_files(
    source_dirs: list[Path],
    target_dir: Path,
    files_by_dir: dict[Path, list[Path]],
    keep_structure: bool,
    duplicate_action: str,
    verify: bool,
    max_retries: int,
    show_progress: bool,
) -> dict[str, int]:
    """Execute copy operation and return statistics."""
    stats = {
        "total": 0,
        "success": 0,
        "failed": 0,
        "skipped": 0,
        "verified": 0,
    }

    # 扁平化所有文件任务
    tasks: list[tuple[Path, Path, Path]] = []  # (src_dir, rel_path, src_full_path)
    for src_dir, rel_paths in files_by_dir.items():
        for rel_path in rel_paths:
            src_full = src_dir / rel_path
            tasks.append((src_dir, rel_path, src_full))

    stats["total"] = len(tasks)

    if not tasks:
        print("[INFO] No files to copy.")
        return stats

    print(f"[INFO] Starting copy: {len(tasks)} files to {target_dir}")

    target_dir.mkdir(parents=True, exist_ok=True)

    for src_dir, rel_path, src_full in tqdm(
        tasks,
        desc="Copying",
        unit="file",
        disable=not show_progress,
        file=sys.stdout,
    ):
        try:
            # 确定目标路径
            if keep_structure:
                dst_path = target_dir / rel_path
            else:
                dst_path = target_dir / rel_path.name

            # 处理重复文件
            dst_path = resolve_duplicate(dst_path, duplicate_action)
            if dst_path is None:
                stats["skipped"] += 1
                continue

            # 创建目标目录
            dst_path.parent.mkdir(parents=True, exist_ok=True)

            # 执行复制
            if copy_with_retry(src_full, dst_path, max_retries):
                stats["success"] += 1
                if verify and verify_copy(src_full, dst_path):
                    stats["verified"] += 1
                elif verify:
                    print(f"Warning: Verification failed for {rel_path}", file=sys.stderr)
            else:
                stats["failed"] += 1

        except Exception as e:
            print(f"Error: Unexpected error copying {rel_path}: {e}", file=sys.stderr)
            stats["failed"] += 1

    return stats


# ============================================
# CLI
# ============================================


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Copy files from source directories to target directory.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Usage examples:

1. Variable mode (edit CONFIG at top of script):
   python copy_data.py

2. CLI mode - copy specific files:
   python copy_data.py --source ./data --target ./output --files "*.jpg" "*.png"

3. CLI mode - multiple sources, flat output:
   python copy_data.py \\
       --source ./data1 ./data2 \\
       --target ./output \\
       --files "*.json" \\
       --no-structure \\
       --duplicate-action overwrite

4. Config file mode:
   python copy_data.py --config copy_config.yaml

Config file example (copy_config.yaml):
  source_dirs:
    - /data/source1
    - /data/source2
  target_dir: /data/output
  file_patterns:
    - "*.jpg"
    - "*.png"
  keep_structure: true
  duplicate_action: rename
  verify: true
""",
    )
    parser.add_argument(
        "--source",
        nargs="+",
        dest="source_dirs",
        help="Source directories (one or more).",
    )
    parser.add_argument(
        "--target",
        type=Path,
        dest="target_dir",
        help="Target directory.",
    )
    parser.add_argument(
        "--files",
        nargs="+",
        dest="file_patterns",
        help="File patterns to match (e.g., '*.jpg', '*.json'). If empty, copies all files.",
    )
    parser.add_argument(
        "--no-structure",
        action="store_false",
        dest="keep_structure",
        help="Flatten output (do not preserve directory structure).",
    )
    parser.add_argument(
        "--duplicate-action",
        choices=["skip", "overwrite", "rename"],
        dest="duplicate_action",
        help="Action when target file exists.",
    )
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="Skip file size verification after copy.",
    )
    parser.add_argument(
        "--no-progress",
        action="store_true",
        help="Disable progress bar.",
    )
    parser.add_argument(
        "--config",
        help="Config file path (YAML or JSON).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cfg = merge_config(args)

    # 验证必填项
    if not cfg.get("source_dirs"):
        print(
            "Error: Source directories not set. Use --source, config file, or edit SOURCE_DIRS.",
            file=sys.stderr,
        )
        sys.exit(1)
    if not cfg.get("target_dir"):
        print(
            "Error: Target directory not set. Use --target, config file, or edit TARGET_DIR.",
            file=sys.stderr,
        )
        sys.exit(1)

    source_dirs = [Path(d) for d in cfg["source_dirs"]]
    target_dir = Path(cfg["target_dir"])
    patterns = cfg.get("file_patterns", [])
    keep_structure = cfg.get("keep_structure", True)
    duplicate_action = cfg.get("duplicate_action", "rename")
    verify = cfg.get("verify", True)
    max_retries = cfg.get("max_retries", 3)
    show_progress = cfg.get("show_progress", True)

    # 验证源目录
    valid_sources = []
    for d in source_dirs:
        if not d.exists():
            print(f"Warning: Source not found, skipping: {d}", file=sys.stderr)
            continue
        if not d.is_dir():
            print(f"Warning: Not a directory, skipping: {d}", file=sys.stderr)
            continue
        valid_sources.append(d)

    if not valid_sources:
        print("Error: No valid source directories.", file=sys.stderr)
        sys.exit(1)

    print(f"[INFO] Source dirs: {len(valid_sources)}")
    for d in valid_sources:
        print(f"  - {d}")
    print(f"[INFO] Target dir: {target_dir}")
    print(f"[INFO] Patterns: {patterns if patterns else '*(all files)'}")
    print(f"[INFO] Keep structure: {keep_structure}")
    print(f"[INFO] Duplicate action: {duplicate_action}")
    print(f"[INFO] Verify: {verify}")

    # 收集文件
    files_by_dir = collect_files(valid_sources, patterns)
    total_files = sum(len(v) for v in files_by_dir.values())
    if total_files == 0:
        print("[INFO] No files matched the given patterns.")
        sys.exit(0)

    print(f"[INFO] Total files to copy: {total_files}")

    # 执行复制
    start = time.time()
    stats = copy_files(
        valid_sources,
        target_dir,
        files_by_dir,
        keep_structure,
        duplicate_action,
        verify,
        max_retries,
        show_progress,
    )
    elapsed = time.time() - start

    # 输出统计
    print(f"\n[INFO] Copy complete ({elapsed:.2f}s)")
    print(f"  Total:   {stats['total']}")
    print(f"  Success: {stats['success']}")
    print(f"  Failed:  {stats['failed']}")
    print(f"  Skipped: {stats['skipped']}")
    if verify:
        print(f"  Verified:{stats['verified']}")

    if stats["failed"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
