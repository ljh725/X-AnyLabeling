#!/usr/bin/env python3
"""Mark overlapping near-duplicate rectangles in annotation JSON files.

The marker flags a rectangle pair as a duplicate annotation when both
conditions hold:

1. Containment: the smaller rectangle is at least 70 percent contained
   by the larger rectangle (intersection over smaller-box area).
2. Comparable size: the smaller-box area is at least 20 percent of the
   larger-box area, which excludes legitimate deep hierarchies such as
   a face box inside a person box.

The larger rectangle of a flagged pair gets its ``label`` rewritten to
``dele`` (configurable). Shapes are never deleted and coordinates are
never touched. Equal-area ties mark the later JSON entry.

Images are scanned first. Their filename stems are matched to JSON
filename stems under a separate annotation directory. Only JSON files
whose ``shapes`` arrays actually change are written to the output
directory; source JSON files are never modified.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

BBox = Tuple[float, float, float, float]
IMAGE_SUFFIXES = frozenset(
    {".bmp", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}
)

DEFAULT_CONTAINMENT_THRESHOLD = 0.70
DEFAULT_MIN_AREA_RATIO = 0.20
DEFAULT_MARK_LABEL = "dele"


@dataclass(frozen=True)
class MarkEvidence:
    """Explain why one rectangle is marked in favor of another."""

    marked_index: int
    kept_index: int
    containment: float
    area_ratio: float
    marked_label: str
    kept_label: str


def rectangle_bbox(shape: Dict[str, Any]) -> Optional[BBox]:
    """Return a normalized bbox for a valid rectangle shape."""
    if not isinstance(shape, dict) or shape.get("shape_type") != "rectangle":
        return None
    points = shape.get("points")
    if not isinstance(points, list) or len(points) < 2:
        return None
    try:
        coords = [(float(point[0]), float(point[1])) for point in points]
    except (IndexError, TypeError, ValueError):
        return None
    xs = [coord[0] for coord in coords]
    ys = [coord[1] for coord in coords]
    bbox = (min(xs), min(ys), max(xs), max(ys))
    if bbox_area(bbox) <= 0.0:
        return None
    return bbox


def bbox_area(bbox: BBox) -> float:
    """Return the non-negative bbox area."""
    return max(0.0, bbox[2] - bbox[0]) * max(0.0, bbox[3] - bbox[1])


def intersection_area(left: BBox, right: BBox) -> float:
    """Return the intersection area of two bboxes."""
    width = max(0.0, min(left[2], right[2]) - max(left[0], right[0]))
    height = max(0.0, min(left[3], right[3]) - max(left[1], right[1]))
    return width * height


def pair_metrics(left: BBox, right: BBox) -> Tuple[float, float]:
    """Return smaller-box containment and area ratio for a bbox pair."""
    left_area = bbox_area(left)
    right_area = bbox_area(right)
    intersection = intersection_area(left, right)
    smaller_area = min(left_area, right_area)
    larger_area = max(left_area, right_area)
    containment = intersection / smaller_area if smaller_area > 0.0 else 0.0
    area_ratio = smaller_area / larger_area if larger_area > 0.0 else 0.0
    return containment, area_ratio


def _marked_and_kept(
    left_index: int,
    left_bbox: BBox,
    right_index: int,
    right_bbox: BBox,
) -> Tuple[int, int]:
    """Choose a deterministic duplicate, marking the larger bbox."""
    left_key = (bbox_area(left_bbox), left_index)
    right_key = (bbox_area(right_bbox), right_index)
    if left_key <= right_key:
        return right_index, left_index
    return left_index, right_index


def find_marks(
    shapes: Sequence[Dict[str, Any]],
    containment_threshold: float = DEFAULT_CONTAINMENT_THRESHOLD,
    min_area_ratio: float = DEFAULT_MIN_AREA_RATIO,
    same_label: bool = False,
) -> Tuple[List[int], List[MarkEvidence]]:
    """Find rectangle indexes to mark using the configured rules.

    Args:
        shapes: Annotation shapes in their original JSON order.
        containment_threshold: Minimum smaller-box containment ratio.
        min_area_ratio: Minimum smaller-to-larger area ratio.
        same_label: When true, compare only rectangles with equal labels.

    Returns:
        Sorted unique mark indexes and evidence for every triggering
        pair.
    """
    rectangles = [
        (index, shape, rectangle_bbox(shape))
        for index, shape in enumerate(shapes)
    ]
    valid = [item for item in rectangles if item[2] is not None]
    marked_indexes = set()
    evidence: List[MarkEvidence] = []

    for position, (left_index, left_shape, left_bbox) in enumerate(valid):
        assert left_bbox is not None
        for right_index, right_shape, right_bbox in valid[position + 1 :]:
            assert right_bbox is not None
            if same_label and left_shape.get("label") != right_shape.get(
                "label"
            ):
                continue
            containment, area_ratio = pair_metrics(left_bbox, right_bbox)
            if containment < containment_threshold:
                continue
            if area_ratio < min_area_ratio:
                continue
            marked_index, kept_index = _marked_and_kept(
                left_index,
                left_bbox,
                right_index,
                right_bbox,
            )
            marked_indexes.add(marked_index)
            marked_shape = shapes[marked_index]
            kept_shape = shapes[kept_index]
            evidence.append(
                MarkEvidence(
                    marked_index=marked_index,
                    kept_index=kept_index,
                    containment=containment,
                    area_ratio=area_ratio,
                    marked_label=str(marked_shape.get("label", "")),
                    kept_label=str(kept_shape.get("label", "")),
                )
            )

    return sorted(marked_indexes), evidence


def mark_shapes(
    shapes: Sequence[Dict[str, Any]],
    containment_threshold: float = DEFAULT_CONTAINMENT_THRESHOLD,
    min_area_ratio: float = DEFAULT_MIN_AREA_RATIO,
    same_label: bool = False,
    mark_label: str = DEFAULT_MARK_LABEL,
) -> Tuple[List[Dict[str, Any]], List[int], List[MarkEvidence]]:
    """Return shapes with duplicate labels rewritten and mark indexes."""
    marked, evidence = find_marks(
        shapes,
        containment_threshold=containment_threshold,
        min_area_ratio=min_area_ratio,
        same_label=same_label,
    )
    changed = [
        index for index in marked if shapes[index].get("label") != mark_label
    ]
    if not changed:
        return list(shapes), [], evidence
    changed_set = set(changed)
    updated: List[Dict[str, Any]] = []
    for index, shape in enumerate(shapes):
        if index in changed_set:
            shape = dict(shape)
            shape["label"] = mark_label
        updated.append(shape)
    return updated, changed, evidence


def _write_json_atomically(path: Path, data: Dict[str, Any]) -> None:
    """Write one generated JSON through a temporary sibling file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(str(path) + ".mark.tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def process_file(
    source: Path,
    destination: Path,
    containment_threshold: float,
    min_area_ratio: float,
    same_label: bool,
    mark_label: str,
    overwrite: bool,
) -> Tuple[int, List[MarkEvidence]]:
    """Write a marked copy only when at least one label is rewritten."""
    if source.resolve() == destination.resolve():
        raise ValueError("输出路径与源文件相同: {}".format(destination))
    data = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("JSON 根不是对象: {}".format(source))
    shapes = data.get("shapes")
    if not isinstance(shapes, list):
        return 0, []
    updated, changed, evidence = mark_shapes(
        shapes,
        containment_threshold=containment_threshold,
        min_area_ratio=min_area_ratio,
        same_label=same_label,
        mark_label=mark_label,
    )
    if not changed:
        return 0, evidence
    if destination.exists() and not overwrite:
        raise FileExistsError(
            "输出已存在；使用 --overwrite 允许覆盖: {}".format(destination)
        )
    data["shapes"] = updated
    _write_json_atomically(destination, data)
    return len(changed), evidence


def collect_image_paths(input_path: Path) -> Iterable[Path]:
    """Yield supported image files from one file or directory tree."""
    if input_path.is_file():
        if input_path.suffix.lower() in IMAGE_SUFFIXES:
            yield input_path
        return
    yield from (
        path
        for path in sorted(input_path.rglob("*"))
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    )


def collect_json_paths(input_path: Path) -> Iterable[Path]:
    """Yield JSON files from one file or directory tree."""
    if input_path.is_file():
        if input_path.suffix.lower() == ".json":
            yield input_path
        return
    yield from sorted(input_path.rglob("*.json"))


def index_json_paths(json_root: Path) -> Dict[str, List[Path]]:
    """Index annotation paths by case-insensitive filename stem."""
    index: Dict[str, List[Path]] = {}
    for path in collect_json_paths(json_root):
        index.setdefault(path.stem.casefold(), []).append(path)
    return index


def destination_for(source: Path, json_root: Path, output_root: Path) -> Path:
    """Preserve a source JSON's relative path below the output root."""
    if json_root.is_file():
        return output_root / source.name
    return output_root / source.relative_to(json_root)


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """Parse command-line options."""
    parser = argparse.ArgumentParser(
        description=(
            "先按图片文件名匹配同名 JSON，再将 containment 达标且面积比 "
            "达标的重叠对中较大框的 label 改为标记值；仅为发生变化的标注"
            "生成新 JSON，源 JSON 永不修改。"
        )
    )
    parser.add_argument("--images", required=True, help="图片文件或目录")
    parser.add_argument("--jsons", required=True, help="源 JSON 文件或目录")
    parser.add_argument(
        "--output",
        required=True,
        help="新 JSON 输出目录；源 JSON 永不修改",
    )
    parser.add_argument(
        "--containment-threshold",
        type=float,
        default=DEFAULT_CONTAINMENT_THRESHOLD,
        help="较小框的最小包含率，默认 0.70",
    )
    parser.add_argument(
        "--min-area-ratio",
        type=float,
        default=DEFAULT_MIN_AREA_RATIO,
        help="较小框与大框的最小面积比，默认 0.20",
    )
    parser.add_argument(
        "--mark-label",
        default=DEFAULT_MARK_LABEL,
        help='重叠对中较大框替换后的 label，默认 "{}"'.format(
            DEFAULT_MARK_LABEL
        ),
    )
    parser.add_argument(
        "--same-label",
        action="store_true",
        help="仅比较相同 label；默认所有矩形互相比较",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="允许覆盖输出目录中已经存在的同名结果",
    )
    return parser.parse_args(argv)


def _validate_threshold(value: float, name: str) -> None:
    """Raise a parser-friendly error for a ratio outside zero to one."""
    if not 0.0 <= value <= 1.0:
        raise ValueError("{} 必须位于 0.0 到 1.0".format(name))


def main(argv: Optional[List[str]] = None) -> int:
    """Run the marker and return a process exit code."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = parse_args(argv)
    try:
        _validate_threshold(
            args.containment_threshold, "--containment-threshold"
        )
        _validate_threshold(args.min_area_ratio, "--min-area-ratio")
    except ValueError as exc:
        print("错误：{}".format(exc), file=sys.stderr)
        return 2

    image_root = Path(args.images)
    json_root = Path(args.jsons)
    output_root = Path(args.output)
    if not image_root.exists():
        print("错误：图片路径不存在: {}".format(image_root), file=sys.stderr)
        return 2
    if not json_root.exists():
        print("错误：JSON 路径不存在: {}".format(json_root), file=sys.stderr)
        return 2
    if json_root.resolve() == output_root.resolve():
        print("错误：输出目录不能等于源 JSON 路径", file=sys.stderr)
        return 2

    image_paths = list(collect_image_paths(image_root))
    if not image_paths:
        print("未找到支持的图片: {}".format(image_root))
        return 0
    image_stems = sorted({path.stem.casefold() for path in image_paths})
    json_index = index_json_paths(json_root)

    changed_files = 0
    marked_shapes = 0
    failures = 0
    matched_files = 0
    missing_stems: List[str] = []
    ambiguous_stems: List[str] = []
    for stem in image_stems:
        candidates = json_index.get(stem, [])
        if not candidates:
            missing_stems.append(stem)
            continue
        if len(candidates) > 1:
            ambiguous_stems.append(stem)
            print(
                "同名 JSON 冲突 {}: {}".format(
                    stem, ", ".join(str(path) for path in candidates)
                ),
                file=sys.stderr,
            )
            continue
        source = candidates[0]
        destination = destination_for(source, json_root, output_root)
        matched_files += 1
        try:
            count, evidence = process_file(
                source,
                destination,
                containment_threshold=args.containment_threshold,
                min_area_ratio=args.min_area_ratio,
                same_label=args.same_label,
                mark_label=args.mark_label,
                overwrite=args.overwrite,
            )
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            failures += 1
            print("处理失败 {}: {}".format(source, exc), file=sys.stderr)
            continue
        if not count:
            continue
        changed_files += 1
        marked_shapes += count
        print(
            "生成 {}: 标记 {} 个框为 {}".format(
                destination, count, args.mark_label
            )
        )
        for item in evidence:
            print(
                "  标记 #{}, 保留 #{} | containment={:.4f} "
                "area_ratio={:.4f} | {} -> {}".format(
                    item.marked_index,
                    item.kept_index,
                    item.containment,
                    item.area_ratio,
                    item.marked_label,
                    item.kept_label,
                )
            )

    for stem in missing_stems[:20]:
        print("未找到同名 JSON: {}".format(stem), file=sys.stderr)
    if len(missing_stems) > 20:
        print(
            "另有 {} 个图片文件名未找到同名 JSON".format(
                len(missing_stems) - 20
            ),
            file=sys.stderr,
        )

    print(
        "扫描 {} 张图片（{} 个唯一文件名） | 匹配 {} 个 JSON | "
        "生成 {} 个新 JSON | 标记 {} 个框为 {} | 缺失 {} 个 | "
        "同名冲突 {} 个 | 失败 {} 个".format(
            len(image_paths),
            len(image_stems),
            matched_files,
            changed_files,
            marked_shapes,
            args.mark_label,
            len(missing_stems),
            len(ambiguous_stems),
            failures,
        )
    )
    return 1 if failures or ambiguous_stems else 0


if __name__ == "__main__":
    sys.exit(main())
