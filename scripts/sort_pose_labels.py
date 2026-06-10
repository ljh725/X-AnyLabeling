"""Sort pose labels in JSON files.

Batch-process JSON label files and reorder shapes according to:
- Rectangles first, sorted by area descending.
- Points with group_id next, sorted by group_id ascending, then by label order.
- Points without group_id last, sorted by label order.

中文排序规则：
- 矩形框排在最前面，按面积从大到小排序；
- 关键点（point）按 group_id 从小到大排序；
- 没有 group_id 的关键点排在最后，按标签顺序排序。
"""

import argparse
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

LABEL_ORDER = [
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

LABEL_ORDER_MAP = {label: idx for idx, label in enumerate(LABEL_ORDER)}


def rectangle_area(points: List[List[float]]) -> float:
    """Calculate rectangle area from points."""
    if not points:
        return 0.0
    xs = [float(p[0]) for p in points]
    ys = [float(p[1]) for p in points]
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)
    return width * height


def sort_key(shape: Dict[str, Any]) -> Tuple[int, float, int]:
    """Return sort key for a single shape."""
    shape_type = shape.get("shape_type", "")
    label = shape.get("label", "")
    group_id = shape.get("group_id")

    if shape_type == "rectangle":
        area = rectangle_area(shape.get("points", []))
        # Category 0 (rectangles), sort by descending area
        return (0, -area, 0)

    # Point shapes
    label_idx = LABEL_ORDER_MAP.get(label, 9999)
    if group_id is None:
        # Category 2 (no group_id), sort by label order
        return (2, 0.0, label_idx)
    else:
        # Category 1 (has group_id), sort by group_id ascending, then label order
        return (1, float(group_id), label_idx)


def process_file(input_path: Path, output_path: Path) -> Tuple[str, bool, Optional[str]]:
    """Process a single JSON file.

    Returns:
        (relative_path, success, error_message)
    """
    try:
        with open(input_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return (str(input_path), False, f"Read error: {e}")

    shapes = data.get("shapes", [])
    if not shapes:
        # Write file even if empty shapes
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            return (str(input_path), False, f"Write error: {e}")
        return (str(input_path), True, None)

    sorted_shapes = sorted(shapes, key=sort_key)
    data["shapes"] = sorted_shapes

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        return (str(input_path), False, f"Write error: {e}")

    return (str(input_path), True, None)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sort pose labels in JSON annotation files."
    )
    parser.add_argument(
        "input_dir",
        help="Directory containing input JSON files (recursively searched).",
    )
    parser.add_argument(
        "output_dir",
        help="Directory to write sorted JSON files.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=os.cpu_count() or 4,
        help="Number of parallel workers (default: number of CPU cores).",
    )
    args = parser.parse_args()

    input_dir = Path(args.input_dir).resolve()
    output_dir = Path(args.output_dir).resolve()

    if not input_dir.exists():
        print(f"Error: Input directory does not exist: {input_dir}", file=sys.stderr)
        return 1

    json_files = list(input_dir.rglob("*.json"))
    total = len(json_files)
    if total == 0:
        print("No JSON files found in input directory.", file=sys.stderr)
        return 0

    print(f"Found {total} JSON files. Processing with {args.workers} workers...")

    success_count = 0
    error_count = 0

    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures = {}
        for json_file in json_files:
            rel_path = json_file.relative_to(input_dir)
            out_path = output_dir / rel_path
            future = executor.submit(process_file, json_file, out_path)
            futures[future] = str(rel_path)

        for future in as_completed(futures):
            rel_path, success, error = future.result()
            if success:
                success_count += 1
            else:
                error_count += 1
                print(f"ERROR {rel_path}: {error}", file=sys.stderr)

            if (success_count + error_count) % 1000 == 0:
                print(f"Progress: {success_count + error_count}/{total}")

    print(f"\nDone. Success: {success_count}, Errors: {error_count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""
调用说明 / Usage:

    python scripts/sort_pose_labels.py <input_dir> <output_dir> [--workers N]

参数:
    input_dir   : 输入目录，包含原始 JSON 标注文件（会递归搜索所有 .json）
    output_dir  : 输出目录，排序后的 JSON 文件将按原目录结构写入此处
    --workers N : 并行进程数，默认使用全部 CPU 核心

示例:
    python scripts/sort_pose_labels.py D:/labels_raw D:/labels_sorted --workers 8

说明:
    - 输出目录会自动创建，不会覆盖原始文件；
    - 排序规则：矩形框按面积从大到小 -> 关键点按 group_id 从小到大 -> 无 group_id 关键点按标签顺序；
    - 处理 3.5 万张 JSON 时建议用 SSD 并适当调高 --workers 以提升速度。
"""
