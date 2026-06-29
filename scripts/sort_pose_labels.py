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


def shape_signature(shape: Dict[str, Any]) -> Tuple:
    """Build a comparison signature for a shape (order-determining fields).

    Only the fields that affect sort_key are included, so a file whose
    shapes merely gained/lost unrelated fields (e.g. flags) is still
    recognized as "already sorted" and skipped.

    Args:
        shape: One shape dict.

    Returns:
        Tuple of (label, group_id, shape_type, points-as-tuple).
    """
    pts = shape.get("points", [])
    points_tuple = (
        tuple((float(p[0]), float(p[1])) for p in pts) if pts else ()
    )
    return (
        shape.get("label"),
        shape.get("group_id"),
        shape.get("shape_type"),
        points_tuple,
    )


def process_file(
    input_path: Path,
    output_path: Path,
    dry_run: bool = False,
) -> Tuple[str, bool, Optional[str], bool]:
    """Process a single JSON file; write it ONLY if the sort order changed.

    Compares the current shape order against the sorted order using only
    order-determining fields. If they already match, the file is skipped
    entirely (not copied, not written) — the output dir ends up
    containing only the files that needed re-sorting, preserving the
    input's relative directory structure so they can be copied back.

    Args:
        input_path: Source JSON path.
        output_path: Destination JSON path (used only when changed).
        dry_run: If True, report what WOULD change but write nothing.

    Returns:
        (path, success, error_message, changed) where ``changed`` is
        True if the sort order differs from the original.
    """
    try:
        with open(input_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return (str(input_path), False, f"Read error: {e}", False)

    shapes = data.get("shapes", [])
    if not shapes:
        # Nothing to sort, nothing to write.
        return (str(input_path), True, None, False)

    sorted_shapes = sorted(shapes, key=sort_key)
    before = [shape_signature(s) for s in shapes]
    after = [shape_signature(s) for s in sorted_shapes]
    changed = before != after

    if not changed or dry_run:
        # Unchanged: skip. dry-run: report only, never write.
        return (str(input_path), True, None, changed)

    data["shapes"] = sorted_shapes
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        return (str(input_path), False, f"Write error: {e}", True)

    return (str(input_path), True, None, True)


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
        help=(
            "Directory to write ONLY the re-sorted JSON files. Files "
            "already in correct order are skipped (not copied). The "
            "input's relative directory structure is preserved so the "
            "outputs can be copied back over the originals."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Only report which files WOULD be resorted; write nothing. "
            "Use to preview before running."
        ),
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

    mode = "DRY-RUN" if args.dry_run else "OUTPUT"
    print(f"Found {total} JSON files. Mode: {mode}. Workers: {args.workers}")
    print(f"Input:  {input_dir}")
    print(f"Output: {output_dir}")

    success_count = 0
    error_count = 0
    copied_count = 0
    changed_count = 0
    changed_files: list[str] = []

    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures = {}
        for json_file in json_files:
            rel_path = json_file.relative_to(input_dir)
            out_path = output_dir / rel_path
            future = executor.submit(
                process_file, json_file, out_path, args.dry_run
            )
            futures[future] = str(rel_path)

        for future in as_completed(futures):
            rel_path, success, error, changed = future.result()
            if not success:
                error_count += 1
                print(f"ERROR {rel_path}: {error}", file=sys.stderr)
                continue
            success_count += 1
            if changed:
                changed_count += 1
                changed_files.append(rel_path)
            else:
                copied_count += 1

            done = success_count + error_count
            if done % 1000 == 0:
                print(f"Progress: {done}/{total}")

    print(f"\nDone. Success: {success_count}, Errors: {error_count}")
    print(f"  Skipped (already sorted): {copied_count}")
    print(f"  Written (resorted):       {changed_count}")
    if args.dry_run:
        print("  (dry-run: nothing was written)")
    if changed_files:
        label = "would be" if args.dry_run else "were"
        print(f"\nFiles that {label} rewritten:")
        for f in sorted(changed_files)[:50]:
            print(f"  {f}")
        rest = len(changed_files) - 50
        if rest > 0:
            print(f"  ... and {rest} more")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""
调用说明 / Usage:

    # 输出目录只包含重排过的文件（保持原目录结构，可整体拷回原目录覆盖）
    python scripts/sort_pose_labels.py <input_dir> <output_dir> [--workers N]

    # 先预览会改哪些文件，不实际写
    python scripts/sort_pose_labels.py <input_dir> <output_dir> --dry-run

参数:
    input_dir   : 输入目录，包含 JSON 标注文件（递归搜索所有 .json）
    output_dir  : 输出目录。只写入排序发生变化的文件；已排好的不输出。
                  保持输入的相对目录结构，便于整体拷回原目录覆盖。
    --dry-run   : 只报告哪些文件需要重排，不写入任何文件
    --workers N : 并行进程数，默认全部 CPU 核心

排序规则（不变）:
    - 矩形框按面积从大到小（面积越大越靠底，避免新增小框压住大框影响标注软件选中）
    - 关键点按 group_id 从小到大，同 gid 内按标签顺序（nose→eye→...→ank）
    - 无 group_id 的关键点排最后

输出说明:
    - 输出目录只包含"排序结果发生变化"的文件（新增框、改面积、改 gid 等）
    - 未变化的文件不输出，避免无谓的复制
    - 输出文件保持原相对路径，可直接整体拷回 input_dir 覆盖
    - 比对只看决定排序的字段（label / group_id / shape_type / points）
"""
