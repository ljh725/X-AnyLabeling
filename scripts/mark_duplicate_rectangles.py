#!/usr/bin/env python
"""Mark fully overlapping duplicate rectangles in labelme JSON files.

For every ``*.json`` file under the input directory the script:

1. Groups ``rectangle`` shapes whose corner coordinates are exactly the
   same. Both storage layouts are accepted and normalized to
   ``(x_min, y_min, x_max, y_max)``: the classic labelme two-point form
   and the X-AnyLabeling four-corner form (any corner order matches).
   Labels are ignored by default because nesting boxes of different
   classes never share all four coordinates exactly; pass ``--same-label``
   to only group shapes that also share the same label.
2. Randomly keeps one shape per duplicate group with its original label
   and renames the remaining ones to ``重复检测`` (configurable), moving
   them to the end of the ``shapes`` list.
3. Writes modified files to the output directory while preserving the
   relative folder structure. Source files are never touched and files
   without duplicates are skipped entirely.

Paths accept CLI arguments with environment-variable fallbacks (CLI
wins), so the script runs both from a terminal and from a VSCode launch
configuration. Files are processed on a thread pool.
"""

import argparse
import json
import os
import random
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_DUPLICATE_LABEL = "重复检测"
ENV_INPUT_DIR = "DEDUPE_INPUT_DIR"
ENV_OUTPUT_DIR = "DEDUPE_OUTPUT_DIR"
ENV_DUPLICATE_LABEL = "DEDUPE_DUPLICATE_LABEL"
ENV_SEED = "DEDUPE_SEED"
ENV_WORKERS = "DEDUPE_WORKERS"


def rect_bbox_key(
    shape: Dict[str, Any],
) -> Optional[Tuple[float, float, float, float]]:
    """Build a normalized geometry key for a rectangle shape.

    Both the labelme two-point form ``[[x1, y1], [x2, y2]]`` and the
    X-AnyLabeling four-corner form are normalized to
    ``(x_min, y_min, x_max, y_max)`` so any corner order matches.
    Non-rectangle shapes and invalid geometry return ``None``.
    """
    if not isinstance(shape, dict):
        return None
    if shape.get("shape_type") != "rectangle":
        return None
    points = shape.get("points")
    if not isinstance(points, list) or len(points) < 2:
        return None
    try:
        coords = [(float(p[0]), float(p[1])) for p in points]
    except (TypeError, ValueError, IndexError):
        return None
    xs = [x for x, _ in coords]
    ys = [y for _, y in coords]
    return (min(xs), min(ys), max(xs), max(ys))


def mark_duplicate_shapes(
    shapes: List[Dict[str, Any]],
    rng: random.Random,
    duplicate_label: str,
    same_label: bool,
) -> Tuple[List[Dict[str, Any]], List[int], int]:
    """Rename duplicate rectangles and move them to the end of the list.

    A duplicate group is a set of ``rectangle`` shapes with exactly the
    same normalized corner coordinates; when ``same_label`` is true the
    label must match as well. One randomly chosen member keeps its
    label; the others are renamed to ``duplicate_label``. All other
    shape fields stay untouched.

    Args:
        shapes: The ``shapes`` array of a labelme JSON file.
        rng: Random generator used to pick the surviving shape.
        duplicate_label: Replacement label for the losing shapes.
        same_label: Only group shapes that also share the same label.

    Returns:
        ``(new_shapes, marked_indices, group_count)`` where
        ``marked_indices`` refers to positions in the original list.
    """
    groups: Dict[Tuple[Any, ...], List[int]] = {}
    for index, shape in enumerate(shapes):
        key = rect_bbox_key(shape)
        if key is None:
            continue
        if same_label:
            key = (shape.get("label"),) + key
        groups.setdefault(key, []).append(index)

    keep = set(range(len(shapes)))
    marked: List[int] = []
    group_count = 0
    for indexes in groups.values():
        if len(indexes) < 2:
            continue
        group_count += 1
        kept = rng.choice(indexes)
        for index in indexes:
            if index != kept:
                marked.append(index)
                keep.discard(index)
    if not marked:
        return shapes, [], 0
    for index in marked:
        shapes[index]["label"] = duplicate_label
    new_shapes = [shape for index, shape in enumerate(shapes) if index in keep]
    new_shapes.extend(shapes[index] for index in sorted(marked))
    return new_shapes, sorted(marked), group_count


def process_file(
    src: Path,
    rel_path: Path,
    out_root: Path,
    duplicate_label: str,
    seed: int,
    dry_run: bool,
    same_label: bool,
) -> Tuple[Path, int, int]:
    """Process one JSON file, writing a fixed copy when needed.

    Args:
        src: Source JSON path.
        rel_path: Path relative to the input root (kept in output).
        out_root: Destination directory for modified copies.
        duplicate_label: Replacement label for duplicate shapes.
        seed: Global random seed; ``-1`` enables true randomness.
        dry_run: When true, only report instead of writing.
        same_label: Only treat same-label rectangles as duplicates.

    Returns:
        ``(src, marked_count, duplicate_group_count)``.

    Raises:
        OSError: On read/write failures.
        json.JSONDecodeError: On malformed JSON input.
    """
    data = json.loads(src.read_text(encoding="utf-8"))
    shapes = data.get("shapes")
    if not isinstance(shapes, list) or not shapes:
        return src, 0, 0
    if seed < 0:
        rng = random.Random()
    else:
        rng = random.Random("{}|{}".format(seed, rel_path.as_posix()))
    new_shapes, marked, groups = mark_duplicate_shapes(
        shapes, rng, duplicate_label, same_label
    )
    if not marked:
        return src, 0, 0
    if not dry_run:
        data["shapes"] = new_shapes
        dst = out_root / rel_path
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return src, len(marked), groups


def _int_env(name: str, default: int) -> int:
    """Read an integer environment variable with a fallback default."""
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """Parse CLI arguments with environment-variable fallbacks.

    Every option first honours an explicit CLI value, then the matching
    ``DEDUPE_*`` environment variable, then a built-in default.
    """
    parser = argparse.ArgumentParser(
        description=(
            "检测坐标完全一致的重复矩形框（兼容 2 点 / 4 角点两种存储格式，"
            "默认不区分 label）：每组随机保留一个，其余改名为重复标签并移到"
            " shapes 末尾；有修改的文件复制到输出目录，源文件不动。"
        )
    )
    parser.add_argument(
        "-i",
        "--input",
        default=os.environ.get(ENV_INPUT_DIR),
        help="输入目录（递归扫描 *.json），env: " + ENV_INPUT_DIR,
    )
    parser.add_argument(
        "-o",
        "--output",
        default=os.environ.get(ENV_OUTPUT_DIR),
        help="输出目录（只存放有修改的副本），env: " + ENV_OUTPUT_DIR,
    )
    parser.add_argument(
        "--duplicate-label",
        default=(
            os.environ.get(ENV_DUPLICATE_LABEL) or DEFAULT_DUPLICATE_LABEL
        ),
        help="重复 shape 的新标签名，env: " + ENV_DUPLICATE_LABEL,
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=_int_env(ENV_SEED, 0),
        help="随机种子（默认 0，结果可复现；-1 为真随机），env: " + ENV_SEED,
    )
    parser.add_argument(
        "-w",
        "--workers",
        type=int,
        default=_int_env(ENV_WORKERS, 8),
        help="线程数（默认 8），env: " + ENV_WORKERS,
    )
    parser.add_argument(
        "--same-label",
        action="store_true",
        help="仅同 label 且坐标一致的矩形才算重复（默认只按坐标判重）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只报告将发生的变化，不写任何文件",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    """Run the batch duplicate-marking pass and return an exit code."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = parse_args(argv)
    if not args.input or not args.output:
        print(
            "错误：必须提供 --input 和 --output"
            "（或环境变量 DEDUPE_INPUT_DIR / DEDUPE_OUTPUT_DIR）",
            file=sys.stderr,
        )
        return 2
    in_root = Path(args.input)
    out_root = Path(args.output)
    if not in_root.is_dir():
        print("错误：输入目录不存在: {}".format(in_root), file=sys.stderr)
        return 2
    if in_root.resolve() == out_root.resolve():
        print("错误：输出目录不能与输入目录相同", file=sys.stderr)
        return 2
    out_resolved = out_root.resolve()
    files = [
        path
        for path in sorted(in_root.rglob("*.json"))
        if out_resolved not in path.resolve().parents
    ]
    if not files:
        print("未找到任何 JSON 文件: {}".format(in_root))
        return 0

    results: List[Tuple[Path, int, int]] = []
    failure_count = 0
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {
            pool.submit(
                process_file,
                path,
                path.relative_to(in_root),
                out_root,
                args.duplicate_label,
                args.seed,
                args.dry_run,
                args.same_label,
            ): path
            for path in files
        }
        for future in as_completed(futures):
            path = futures[future]
            try:
                results.append(future.result())
            except Exception as exc:
                failure_count += 1
                print(
                    "警告：处理失败 {}: {}".format(path, exc),
                    file=sys.stderr,
                )

    modified = sorted(
        (item for item in results if item[1] > 0), key=lambda i: i[0]
    )
    prefix = "[dry-run] " if args.dry_run else ""
    for path, marked, groups in modified:
        print(
            "{}{}: {} 组重复，标记 {} 个 shape -> {}".format(
                prefix, path, groups, marked, out_root
            )
        )
    print(
        "{}扫描 {} 个 JSON | 修改并复制 {} 个 | 重复组 {} 个 | "
        "标记 shape {} 个 | 跳过 {} 个 | 失败 {} 个".format(
            prefix,
            len(files),
            len(modified),
            sum(item[2] for item in modified),
            sum(item[1] for item in modified),
            len(files) - len(modified) - failure_count,
            failure_count,
        )
    )
    return 1 if failure_count else 0


if __name__ == "__main__":
    sys.exit(main())
