#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compare filename stems between two groups of dataset directories.

支持三种参数配置方式（优先级从高到低）：
1. 命令行参数（--group-a, --group-b, --output 等）
2. 配置文件（--config 指定 YAML/JSON）
3. 脚本顶部变量（CONFIG 区域直接修改）

对比模式：
- 一对一：A组1个目录 vs B组1个目录
- 一对多：A组1个目录 vs B组多个目录
- 多对一：A组多个目录 vs B组1个目录
- 多对多：A组多个目录 vs B组多个目录

每组内的多个目录会被合并处理，最终按 stem 做集合对比。

输出：Markdown 格式报告，包含摘要、只在A、只在B、共有的详细列表。
"""

from __future__ import annotations

import argparse
import json
import os
import os.path as osp
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

try:
    from tqdm import tqdm
except ModuleNotFoundError:

    class _TqdmFallback:
        def __init__(self, iterable=None, *args, **kwargs):
            self.iterable = iterable

        def __iter__(self):
            return iter(self.iterable or [])

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def update(self, value: int = 1) -> None:
            pass

    def tqdm(iterable=None, *args, **kwargs):
        return _TqdmFallback(iterable, *args, **kwargs)


# ============================================
# CONFIG 区域 - 变量配置模式（直接修改此处）
# ============================================

# A组目录列表（支持一个或多个）
GROUP_A_DIRS: list[str] = [
    # 示例: "/path/to/images",
    # 示例: "/path/to/more_images",
    # "\\\\192.168.3.248\opt\chengdu\images"
    "D:\A0_part1_kps_3_class_dataset\Sample\images"
]

# B组目录列表（支持一个或多个）
GROUP_B_DIRS: list[str] = [
    # 示例: "/path/to/labels",
    # 示例: "/path/to/more_labels",
    # "\\\\192.168.3.248\opt\chengdu\images2\images"
    "D:\A0_part2_kps_3_class_dataset\Phase_2_1217_personheadface_points_33076\HK_不要计入统计\hk_image_1800"
]

# 输出报告路径
OUTPUT_PATH: str = r"D:\A000_report_txt\20260608_001.txt"  # 示例: "/path/to/report.md"

# 线程数（默认自动）
WORKERS: int = min(8, os.cpu_count() or 4)

# 禁用进度条（服务器/CI环境建议设为 True）
NO_PROGRESS: bool = False

# 仅输出摘要（大数据集建议设为 True）
SUMMARY_ONLY: bool = False

# 配置文件路径（YAML/JSON，可选）
CONFIG_FILE: str = ""


# ============================================
# 常量
# ============================================

IMAGE_EXTENSIONS = frozenset(
    {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp", ".tiff", ".tif"}
)
LABEL_EXTENSIONS = frozenset({".txt", ".json", ".xml"})


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
                "Error: PyYAML required for YAML config. "
                "Install: pip install pyyaml",
                file=sys.stderr,
            )
            sys.exit(1)
    elif suffix == ".json":
        return json.loads(content)
    else:
        print(
            f"Error: Unsupported config format '{suffix}'. "
            "Use .yaml, .yml, or .json",
            file=sys.stderr,
        )
        sys.exit(1)


def merge_config(args: argparse.Namespace) -> dict[str, Any]:
    """Merge configs with priority: CLI > config file > script variables."""
    cfg: dict[str, Any] = {}

    # 1. 脚本变量（最低优先级）
    if GROUP_A_DIRS:
        cfg["group_a"] = GROUP_A_DIRS
    if GROUP_B_DIRS:
        cfg["group_b"] = GROUP_B_DIRS
    if OUTPUT_PATH:
        cfg["output"] = OUTPUT_PATH
    cfg.setdefault("workers", WORKERS)
    cfg.setdefault("no_progress", NO_PROGRESS)
    cfg.setdefault("summary_only", SUMMARY_ONLY)

    # 2. 配置文件（中优先级）
    file_path = CONFIG_FILE or getattr(args, "config", "") or ""
    if file_path:
        file_cfg = load_config_file(file_path)
        cfg.update(file_cfg)

    # 3. 命令行参数（最高优先级）
    if getattr(args, "group_a", None):
        cfg["group_a"] = args.group_a
    if getattr(args, "group_b", None):
        cfg["group_b"] = args.group_b
    if getattr(args, "output", None):
        cfg["output"] = str(args.output)
    if getattr(args, "workers", None) is not None:
        cfg["workers"] = args.workers
    if getattr(args, "no_progress", False):
        cfg["no_progress"] = True
    if getattr(args, "summary_only", False):
        cfg["summary_only"] = True

    return cfg


# ============================================
# 核心逻辑
# ============================================


def classify_extension(ext: str) -> str:
    """Classify file by extension."""
    ext_lower = ext.lower()
    if ext_lower in IMAGE_EXTENSIONS:
        return "image"
    if ext_lower in LABEL_EXTENSIONS:
        return "label"
    return "other"


def validate_directories(dir_list: list[str]) -> list[Path]:
    """Validate and return existing directories."""
    valid: list[Path] = []
    for d in dir_list:
        path = Path(d)
        if not path.exists():
            print(f"Warning: Not found, skipping: {d}", file=sys.stderr)
            continue
        if not path.is_dir():
            print(f"Warning: Not a directory, skipping: {d}", file=sys.stderr)
            continue
        valid.append(path)
    if not valid:
        print("Error: No valid directories.", file=sys.stderr)
        sys.exit(1)
    return valid


def collect_stems(
    directories: list[Path],
    disable_progress: bool = False,
) -> dict[str, dict[str, list[str]]]:
    """Collect filename stems from multiple directories.

    Returns:
        dict: stem -> {category -> [full_file_paths]}
    """
    all_stems: dict[str, dict[str, list[str]]] = defaultdict(
        lambda: defaultdict(list)
    )

    for directory in directories:
        print(f"[INFO] Scanning: {directory}")
        start = time.time()

        file_names: list[str] = []
        skipped = 0
        failed = 0

        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    try:
                        is_file = entry.is_file(follow_symlinks=False)
                    except OSError:
                        failed += 1
                        continue
                    if not is_file:
                        skipped += 1
                        continue
                    file_names.append(entry.name)
        except OSError as e:
            print(f"Warning: Failed to scan {directory}: {e}", file=sys.stderr)
            continue

        total = len(file_names)
        if not file_names:
            print(f"[INFO] Empty directory: {directory}")
            continue

        print(
            f"[INFO] Found {total} files (skipped={skipped}, "
            f"inaccessible={failed})"
        )

        for file_name in tqdm(
            sorted(file_names, key=str.lower),
            desc=f"Scan {directory.name}",
            unit="file",
            disable=disable_progress,
            file=sys.stdout,
            miniters=max(1, total // 100),
        ):
            stem, ext = osp.splitext(file_name)
            category = classify_extension(ext.lower())
            all_stems[stem][category].append(str(directory / file_name))

        elapsed = time.time() - start
        print(f"[INFO] Done {directory.name} ({elapsed:.2f}s)")

    return dict(all_stems)


def generate_report(
    group_a_dirs: list[Path],
    group_b_dirs: list[Path],
    stems_a: dict[str, dict[str, list[str]]],
    stems_b: dict[str, dict[str, list[str]]],
    only_a: set[str],
    only_b: set[str],
    common: set[str],
    disable_progress: bool = False,
    summary_only: bool = False,
) -> str:
    """Generate Markdown comparison report."""
    print("[INFO] Generating report...")
    start = time.time()

    lines: list[str] = []

    # Header
    lines.append("# Dataset Stem Comparison Report")
    lines.append("")
    lines.append("## Group A Directories")
    for d in group_a_dirs:
        lines.append(f"- `{d}`")
    lines.append("")
    lines.append("## Group B Directories")
    for d in group_b_dirs:
        lines.append(f"- `{d}`")
    lines.append("")

    # Summary
    lines.append("## Summary")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Total stems in Group A | {len(stems_a)} |")
    lines.append(f"| Total stems in Group B | {len(stems_b)} |")
    lines.append(f"| Only in Group A | {len(only_a)} |")
    lines.append(f"| Only in Group B | {len(only_b)} |")
    lines.append(f"| Common to both | {len(common)} |")
    lines.append("")

    if summary_only:
        lines.append("## Files Only in Group A")
        lines.append("")
        if not only_a:
            lines.append("*None found.*")
        else:
            for stem in sorted(only_a):
                for cat in ("image", "label", "other"):
                    for fp in stems_a.get(stem, {}).get(cat, []):
                        lines.append(f"- `{fp}`")
        lines.append("")

        lines.append("## Files Only in Group B")
        lines.append("")
        if not only_b:
            lines.append("*None found.*")
        else:
            for stem in sorted(only_b):
                for cat in ("image", "label", "other"):
                    for fp in stems_b.get(stem, {}).get(cat, []):
                        lines.append(f"- `{fp}`")
        lines.append("")

        print(f"[INFO] Report done ({time.time() - start:.2f}s)")
        return "\n".join(lines)

    # Detailed sections
    def fmt_entry(stem: str, source: dict) -> list[str]:
        out: list[str] = []
        files = source.get(stem, {})
        out.append(f"- `{stem}`")
        for cat in ("image", "label", "other"):
            paths = files.get(cat, [])
            if paths:
                out.append(
                    f"  - {cat.capitalize()}: "
                    f"{', '.join(f'`{p}`' for p in paths)}"
                )
        return out

    def fmt_common(stem: str) -> list[str]:
        out: list[str] = []
        files_a = stems_a.get(stem, {})
        files_b = stems_b.get(stem, {})
        out.append(f"- `{stem}`")
        for cat in ("image", "label", "other"):
            a_paths = files_a.get(cat, [])
            b_paths = files_b.get(cat, [])
            if a_paths:
                out.append(
                    f"  - Group A {cat}: "
                    f"{', '.join(f'`{p}`' for p in a_paths)}"
                )
            if b_paths:
                out.append(
                    f"  - Group B {cat}: "
                    f"{', '.join(f'`{p}`' for p in b_paths)}"
                )
        return out

    # Only in A
    lines.append("## Stems Only in Group A")
    lines.append("")
    if not only_a:
        lines.append("*None found.*")
    else:
        for stem in tqdm(
            sorted(only_a),
            desc="Format Only A",
            unit="stem",
            disable=disable_progress,
            file=sys.stdout,
        ):
            lines.extend(fmt_entry(stem, stems_a))
    lines.append("")

    # Only in B
    lines.append("## Stems Only in Group B")
    lines.append("")
    if not only_b:
        lines.append("*None found.*")
    else:
        for stem in tqdm(
            sorted(only_b),
            desc="Format Only B",
            unit="stem",
            disable=disable_progress,
            file=sys.stdout,
        ):
            lines.extend(fmt_entry(stem, stems_b))
    lines.append("")

    # Common
    lines.append("## Common Stems")
    lines.append("")
    if not common:
        lines.append("*None found.*")
    else:
        for stem in tqdm(
            sorted(common),
            desc="Format Common",
            unit="stem",
            disable=disable_progress,
            file=sys.stdout,
        ):
            lines.extend(fmt_common(stem))
    lines.append("")

    print(f"[INFO] Report done ({time.time() - start:.2f}s)")
    return "\n".join(lines)


# ============================================
# CLI
# ============================================


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compare filename stems between two groups of directories. "
            "Supports variable config, config file, and CLI args."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Usage modes:

1. Variable mode (edit script top CONFIG section, then run):
   python compare_dataset_stems_v2.py

2. CLI mode - one-to-many:
   python compare_dataset_stems_v2.py \\
       --group-a ./images \\
       --group-b ./labels1 ./labels2 ./labels3 \\
       --output report.md

3. CLI mode - many-to-many:
   python compare_dataset_stems_v2.py \\
       --group-a ./batch1 ./batch2 \\
       --group-b ./batch3 ./batch4 \\
       --output report.md

4. Config file mode:
   python compare_dataset_stems_v2.py --config config.yaml --output report.md

Config file example (config.yaml):
  group_a:
    - /data/images
    - /data/more_images
  group_b:
    - /data/labels
  workers: 16
  no_progress: true
""",
    )
    parser.add_argument(
        "--group-a",
        nargs="+",
        dest="group_a",
        help="Group A directories (one or more).",
    )
    parser.add_argument(
        "--group-b",
        nargs="+",
        dest="group_b",
        help="Group B directories (one or more).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output report file path.",
    )
    parser.add_argument(
        "--config",
        help="Config file path (YAML or JSON).",
    )
    parser.add_argument(
        "--workers",
        type=int,
        help=f"Worker threads (default: {min(8, os.cpu_count() or 4)}).",
    )
    parser.add_argument(
        "--no-progress",
        action="store_true",
        dest="no_progress",
        help="Disable progress bars.",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        dest="summary_only",
        help="Only output summary.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cfg = merge_config(args)

    # Validate required fields
    if not cfg.get("group_a"):
        print(
            "Error: Group A not set. Use --group-a, config file, or "
            "edit GROUP_A_DIRS in script.",
            file=sys.stderr,
        )
        sys.exit(1)
    if not cfg.get("group_b"):
        print(
            "Error: Group B not set. Use --group-b, config file, or "
            "edit GROUP_B_DIRS in script.",
            file=sys.stderr,
        )
        sys.exit(1)
    if not cfg.get("output"):
        print(
            "Error: Output not set. Use --output, config file, or "
            "edit OUTPUT_PATH in script.",
            file=sys.stderr,
        )
        sys.exit(1)

    group_a_dirs = validate_directories(cfg["group_a"])
    group_b_dirs = validate_directories(cfg["group_b"])

    print(f"[INFO] Group A: {len(group_a_dirs)} dirs")
    for d in group_a_dirs:
        print(f"  - {d}")
    print(f"[INFO] Group B: {len(group_b_dirs)} dirs")
    for d in group_b_dirs:
        print(f"  - {d}")

    workers = cfg.get("workers", min(8, os.cpu_count() or 4))
    no_progress = cfg.get("no_progress", False)
    summary_only = cfg.get("summary_only", False)
    output_path = Path(cfg["output"])

    # Collect
    stems_a = collect_stems(group_a_dirs, disable_progress=no_progress)
    stems_b = collect_stems(group_b_dirs, disable_progress=no_progress)

    set_a = set(stems_a.keys())
    set_b = set(stems_b.keys())

    only_a = set_a - set_b
    only_b = set_b - set_a
    common = set_a & set_b

    print(
        f"[INFO] Result: A={len(set_a)}, B={len(set_b)}, "
        f"OnlyA={len(only_a)}, OnlyB={len(only_b)}, Common={len(common)}"
    )

    # Report
    report = generate_report(
        group_a_dirs,
        group_b_dirs,
        stems_a,
        stems_b,
        only_a,
        only_b,
        common,
        disable_progress=no_progress,
        summary_only=summary_only,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")
    print(f"\n[INFO] Report saved: {output_path}")
    print(f"  Only in A: {len(only_a)}")
    print(f"  Only in B: {len(only_b)}")
    print(f"  Common:    {len(common)}")


if __name__ == "__main__":
    main()
