#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Statistic shapes in JSON annotation files.

Supports both command-line arguments and top-level script variables.
Priority: CLI > script variables.

Statistics per file:
- point_count: number of shapes with shape_type == "point"
- rectangle_count: number of shapes with shape_type == "rectangle"
- group_id_count: number of distinct group_id values in the file
- person_group_ids: distinct group_ids of shapes labeled "person"
- face_group_ids: distinct group_ids of shapes labeled "face"
- head_group_ids: distinct group_ids of shapes labeled "head"

Outputs both JSON and Markdown reports.
"""

from __future__ import annotations

import argparse
import json
import os
import os.path as osp
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
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

# 输入目录（仅包含单层 JSON 文件）
INPUT_DIR: str = r"D:\xinjiegou-X-AnyLabeling-4.0.0-beta.4\scripts"

# 输出报告路径前缀（会生成 .json 和 .md 两个文件）
OUTPUT_PREFIX: str = r"D:\A000_report_txt\json_shape_stats"

# 线程数（默认自动）
WORKERS: int = min(8, os.cpu_count() or 4)

# 禁用进度条（服务器/CI环境建议设为 True）
NO_PROGRESS: bool = False


# ============================================
# 核心逻辑
# ============================================


def collect_json_paths(directory: Path) -> list[Path]:
    """Collect JSON file paths from a single-level directory."""
    json_paths: list[Path] = []
    try:
        with os.scandir(directory) as entries:
            for entry in entries:
                try:
                    is_file = entry.is_file(follow_symlinks=False)
                except OSError:
                    continue
                if not is_file:
                    continue
                if Path(entry.name).suffix.lower() == ".json":
                    json_paths.append(Path(entry.path))
    except OSError as e:
        print(f"Error: Failed to scan {directory}: {e}", file=sys.stderr)
        sys.exit(1)
    return json_paths


def analyze_json_file(json_path: Path) -> dict[str, Any] | None:
    """Analyze a single JSON annotation file.

    Returns:
        dict with file, point_count, rectangle_count, group_id_count,
        group_ids, total_shapes, error fields; or None on failure.
    """
    result: dict[str, Any] = {
        "file": str(json_path),
        "stem": json_path.stem,
        "point_count": 0,
        "rectangle_count": 0,
        "group_id_count": 0,
        "group_ids": [],
        "person_group_ids": [],
        "face_group_ids": [],
        "head_group_ids": [],
        "total_shapes": 0,
        "error": None,
    }
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        result["error"] = f"{type(e).__name__}: {e}"
        return result

    shapes = data.get("shapes", []) if isinstance(data, dict) else []
    result["total_shapes"] = len(shapes)

    group_ids: set[int | str | None] = set()
    person_group_ids: set[int | str | None] = set()
    face_group_ids: set[int | str | None] = set()
    head_group_ids: set[int | str | None] = set()
    for shape in shapes:
        if not isinstance(shape, dict):
            continue
        shape_type = shape.get("shape_type", "")
        label = shape.get("label", "")
        if shape_type == "point":
            result["point_count"] += 1
        elif shape_type == "rectangle":
            result["rectangle_count"] += 1
        group_id = shape.get("group_id")
        if group_id is not None:
            group_ids.add(group_id)
            if label == "person":
                person_group_ids.add(group_id)
            elif label == "face":
                face_group_ids.add(group_id)
            elif label == "head":
                head_group_ids.add(group_id)

    result["group_id_count"] = len(group_ids)
    result["group_ids"] = sorted(
        group_ids,
        key=lambda x: (x is None, str(x), isinstance(x, (int, float))),
    )
    result["person_group_ids"] = sorted(
        person_group_ids,
        key=lambda x: (x is None, str(x), isinstance(x, (int, float))),
    )
    result["face_group_ids"] = sorted(
        face_group_ids,
        key=lambda x: (x is None, str(x), isinstance(x, (int, float))),
    )
    result["head_group_ids"] = sorted(
        head_group_ids,
        key=lambda x: (x is None, str(x), isinstance(x, (int, float))),
    )
    return result


def merge_config(args: argparse.Namespace) -> dict[str, Any]:
    """Merge configs with priority: CLI > script variables."""
    cfg: dict[str, Any] = {}

    # 1. 脚本变量（最低优先级）
    if INPUT_DIR:
        cfg["input_dir"] = INPUT_DIR
    if OUTPUT_PREFIX:
        cfg["output_prefix"] = OUTPUT_PREFIX
    cfg.setdefault("workers", WORKERS)
    cfg.setdefault("no_progress", NO_PROGRESS)

    # 2. 命令行参数（最高优先级）
    if getattr(args, "input_dir", None):
        cfg["input_dir"] = args.input_dir
    if getattr(args, "output_prefix", None):
        cfg["output_prefix"] = args.output_prefix
    if getattr(args, "workers", None) is not None:
        cfg["workers"] = args.workers
    if getattr(args, "no_progress", False):
        cfg["no_progress"] = True

    return cfg


def generate_markdown(
    results: list[dict[str, Any]],
    summary: dict[str, Any],
) -> str:
    """Generate Markdown report from results."""
    lines: list[str] = []
    lines.append("# JSON Shape Statistics Report")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Total JSON files | {summary['total_files']} |")
    lines.append(f"| Successful files | {summary['success_files']} |")
    lines.append(f"| Failed files | {summary['failed_files']} |")
    lines.append(f"| Total shapes | {summary['total_shapes']} |")
    lines.append(f"| Total point shapes | {summary['total_points']} |")
    lines.append(f"| Total rectangle shapes | {summary['total_rectangles']} |")
    lines.append(
        f"| Total distinct group_ids | {summary['total_group_ids']} |"
    )
    lines.append(
        f"| Person group_ids | {len(summary.get('person_group_ids', []))} |"
    )
    lines.append(
        f"| Face group_ids | {len(summary.get('face_group_ids', []))} |"
    )
    lines.append(
        f"| Head group_ids | {len(summary.get('head_group_ids', []))} |"
    )
    lines.append("")

    lines.append("## Per File Details")
    lines.append("")
    lines.append(
        "| File | Shapes | Points | Rectangles | "
        "Group IDs | Person IDs | Face IDs | Head IDs |"
    )
    lines.append(
        "|------|--------|--------|------------|"
        "-----------|------------|----------|----------|"
    )
    for r in results:
        file_name = Path(r["file"]).name
        if r.get("error"):
            lines.append(
                f"| {file_name} | - | - | - | - | "
                f"ERROR: {r['error']} | - | - |"
            )
        else:
            lines.append(
                f"| {file_name} | {r['total_shapes']} | "
                f"{r['point_count']} | {r['rectangle_count']} | "
                f"{r['group_id_count']} | "
                f"{len(r['person_group_ids'])} | "
                f"{len(r['face_group_ids'])} | "
                f"{len(r['head_group_ids'])} |"
            )
    lines.append("")

    lines.append("## Per File Group ID Lists")
    lines.append("")
    for r in results:
        file_name = Path(r["file"]).name
        if r.get("error"):
            continue
        lines.append(f"### {file_name}")
        lines.append("")
        lines.append(f"- **Person group_ids**: `{r['person_group_ids']}`")
        lines.append(f"- **Face group_ids**: `{r['face_group_ids']}`")
        lines.append(f"- **Head group_ids**: `{r['head_group_ids']}`")
        lines.append("")

    failed = [r for r in results if r.get("error")]
    if failed:
        lines.append("## Failed Files")
        lines.append("")
        for r in failed:
            lines.append(f"- `{r['file']}`: {r['error']}")
        lines.append("")

    return "\n".join(lines)


def compute_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute aggregate summary from per-file results."""
    success = [r for r in results if not r.get("error")]
    failed = [r for r in results if r.get("error")]
    all_group_ids: set[int | str | None] = set()
    all_person_group_ids: set[int | str | None] = set()
    all_face_group_ids: set[int | str | None] = set()
    all_head_group_ids: set[int | str | None] = set()
    for r in success:
        all_group_ids.update(r.get("group_ids", []))
        all_person_group_ids.update(r.get("person_group_ids", []))
        all_face_group_ids.update(r.get("face_group_ids", []))
        all_head_group_ids.update(r.get("head_group_ids", []))

    return {
        "total_files": len(results),
        "success_files": len(success),
        "failed_files": len(failed),
        "total_shapes": sum(r.get("total_shapes", 0) for r in success),
        "total_points": sum(r.get("point_count", 0) for r in success),
        "total_rectangles": sum(r.get("rectangle_count", 0) for r in success),
        "total_group_ids": len(all_group_ids),
        "person_group_ids": sorted(
            all_person_group_ids,
            key=lambda x: (x is None, str(x), isinstance(x, (int, float))),
        ),
        "face_group_ids": sorted(
            all_face_group_ids,
            key=lambda x: (x is None, str(x), isinstance(x, (int, float))),
        ),
        "head_group_ids": sorted(
            all_head_group_ids,
            key=lambda x: (x is None, str(x), isinstance(x, (int, float))),
        ),
    }


# ============================================
# CLI
# ============================================


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Statistic point/rectangle shapes and group_ids in JSONs.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Usage:

1. Variable mode (edit script top CONFIG section, then run):
   python stats_json_shapes.py

2. CLI mode:
   python stats_json_shapes.py \\
       --input D:\\path\\to\\jsons \\
       --output D:\\reports\\stats \\
       --workers 8

Output files:
  <output_prefix>.json
  <output_prefix>.md
""",
    )
    parser.add_argument(
        "--input",
        "-i",
        dest="input_dir",
        help="Input directory containing JSON files (single level).",
    )
    parser.add_argument(
        "--output",
        "-o",
        dest="output_prefix",
        help="Output report path prefix (without extension).",
    )
    parser.add_argument(
        "--workers",
        "-w",
        type=int,
        help=f"Worker threads (default: {min(8, os.cpu_count() or 4)}).",
    )
    parser.add_argument(
        "--no-progress",
        action="store_true",
        dest="no_progress",
        help="Disable progress bars.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cfg = merge_config(args)

    if not cfg.get("input_dir"):
        print(
            "Error: Input directory not set. Use --input or edit INPUT_DIR.",
            file=sys.stderr,
        )
        sys.exit(1)
    if not cfg.get("output_prefix"):
        print(
            "Error: Output prefix not set. Use --output or edit OUTPUT_PREFIX.",
            file=sys.stderr,
        )
        sys.exit(1)

    input_dir = Path(cfg["input_dir"])
    output_prefix = Path(cfg["output_prefix"])
    workers = int(cfg.get("workers", min(8, os.cpu_count() or 4)))
    no_progress = bool(cfg.get("no_progress", False))

    if not input_dir.exists():
        print(
            f"Error: Input directory not found: {input_dir}", file=sys.stderr
        )
        sys.exit(1)
    if not input_dir.is_dir():
        print(f"Error: Not a directory: {input_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"[INFO] Input: {input_dir}")
    print(f"[INFO] Output prefix: {output_prefix}")
    print(f"[INFO] Workers: {workers}")

    json_paths = collect_json_paths(input_dir)
    print(f"[INFO] Found {len(json_paths)} JSON files")

    if not json_paths:
        print("[INFO] No JSON files to process.")
        sys.exit(0)

    results: list[dict[str, Any]] = []
    start = time.time()

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_path = {
            executor.submit(analyze_json_file, p): p for p in json_paths
        }
        iterator = as_completed(future_to_path)
        if not no_progress:
            iterator = tqdm(
                iterator,
                total=len(json_paths),
                desc="Analyze JSONs",
                unit="file",
            )
        for future in iterator:
            result = future.result()
            if result is not None:
                results.append(result)

    # Sort results by filename for stable output.
    results.sort(key=lambda r: Path(r["file"]).name)

    elapsed = time.time() - start
    print(f"[INFO] Analysis done ({elapsed:.2f}s)")

    summary = compute_summary(results)
    report: dict[str, Any] = {
        "input_dir": str(input_dir),
        "output_prefix": str(output_prefix),
        "summary": summary,
        "files": results,
    }

    output_prefix.parent.mkdir(parents=True, exist_ok=True)

    json_path = output_prefix.with_suffix(".json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"[INFO] JSON report saved: {json_path}")

    md_path = output_prefix.with_suffix(".md")
    md_path.write_text(generate_markdown(results, summary), encoding="utf-8")
    print(f"[INFO] Markdown report saved: {md_path}")

    print("\nSummary:")
    for key, value in summary.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
