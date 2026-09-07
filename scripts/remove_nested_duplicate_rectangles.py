#!/usr/bin/env python3
"""Remove nested and near-duplicate rectangles from annotation JSON files.

The cleaner follows two deterministic rules:

1. When the smaller rectangle is at least 98 percent contained by the
   larger rectangle, keep the smaller rectangle.
2. When two rectangles have IoU greater than or equal to 0.95, keep the
   smaller rectangle. Equal-area ties keep the earlier JSON entry.

Images are scanned first. Their filename stems are matched to JSON filename
stems under a separate annotation directory. Only JSON files whose ``shapes``
arrays actually change are written to the output directory; source JSON files
are never modified.
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


@dataclass(frozen=True)
class RemovalEvidence:
    """Explain why one rectangle is removed in favor of another."""

    removed_index: int
    kept_index: int
    reason: str
    containment: float
    iou: float
    removed_label: str
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
    """Return smaller-box containment and IoU for a bbox pair."""
    left_area = bbox_area(left)
    right_area = bbox_area(right)
    intersection = intersection_area(left, right)
    smaller_area = min(left_area, right_area)
    union = left_area + right_area - intersection
    containment = intersection / smaller_area if smaller_area > 0.0 else 0.0
    iou = intersection / union if union > 0.0 else 0.0
    return containment, iou


def _kept_and_removed(
    left_index: int,
    left_bbox: BBox,
    right_index: int,
    right_bbox: BBox,
) -> Tuple[int, int]:
    """Choose a deterministic survivor, preferring the smaller bbox."""
    left_key = (bbox_area(left_bbox), left_index)
    right_key = (bbox_area(right_bbox), right_index)
    if left_key <= right_key:
        return left_index, right_index
    return right_index, left_index


def find_removals(
    shapes: Sequence[Dict[str, Any]],
    containment_threshold: float = 0.98,
    iou_threshold: float = 0.95,
    same_label: bool = False,
) -> Tuple[List[int], List[RemovalEvidence]]:
    """Find rectangle indexes to remove using the configured rules.

    Args:
        shapes: Annotation shapes in their original JSON order.
        containment_threshold: Minimum smaller-box containment ratio.
        iou_threshold: Minimum intersection-over-union ratio.
        same_label: When true, compare only rectangles with equal labels.

    Returns:
        Sorted unique removal indexes and evidence for every triggering pair.
    """
    rectangles = [
        (index, shape, rectangle_bbox(shape))
        for index, shape in enumerate(shapes)
    ]
    valid = [item for item in rectangles if item[2] is not None]
    removed_indexes = set()
    evidence: List[RemovalEvidence] = []

    for position, (left_index, left_shape, left_bbox) in enumerate(valid):
        assert left_bbox is not None
        for right_index, right_shape, right_bbox in valid[position + 1 :]:
            assert right_bbox is not None
            if same_label and left_shape.get("label") != right_shape.get(
                "label"
            ):
                continue
            containment, iou = pair_metrics(left_bbox, right_bbox)
            nested = containment >= containment_threshold
            high_iou = iou >= iou_threshold
            if not nested and not high_iou:
                continue
            kept_index, removed_index = _kept_and_removed(
                left_index,
                left_bbox,
                right_index,
                right_bbox,
            )
            removed_indexes.add(removed_index)
            kept_shape = shapes[kept_index]
            removed_shape = shapes[removed_index]
            if nested and high_iou:
                reason = "nested_and_iou"
            elif nested:
                reason = "nested"
            else:
                reason = "iou"
            evidence.append(
                RemovalEvidence(
                    removed_index=removed_index,
                    kept_index=kept_index,
                    reason=reason,
                    containment=containment,
                    iou=iou,
                    removed_label=str(removed_shape.get("label", "")),
                    kept_label=str(kept_shape.get("label", "")),
                )
            )

    return sorted(removed_indexes), evidence


def clean_shapes(
    shapes: Sequence[Dict[str, Any]],
    containment_threshold: float = 0.98,
    iou_threshold: float = 0.95,
    same_label: bool = False,
) -> Tuple[List[Dict[str, Any]], List[int], List[RemovalEvidence]]:
    """Return shapes after removing nested and high-IoU rectangles."""
    removed, evidence = find_removals(
        shapes,
        containment_threshold=containment_threshold,
        iou_threshold=iou_threshold,
        same_label=same_label,
    )
    removed_set = set(removed)
    cleaned = [
        shape for index, shape in enumerate(shapes) if index not in removed_set
    ]
    return cleaned, removed, evidence


def _write_json_atomically(path: Path, data: Dict[str, Any]) -> None:
    """Write one generated JSON through a temporary sibling file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(str(path) + ".cleanup.tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def process_file(
    source: Path,
    destination: Path,
    containment_threshold: float,
    iou_threshold: float,
    same_label: bool,
    overwrite: bool,
) -> Tuple[int, List[RemovalEvidence]]:
    """Write a cleaned copy only when at least one shape is removed."""
    if source.resolve() == destination.resolve():
        raise ValueError("输出路径与源文件相同: {}".format(destination))
    data = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("JSON 根不是对象: {}".format(source))
    shapes = data.get("shapes")
    if not isinstance(shapes, list):
        return 0, []
    cleaned, removed, evidence = clean_shapes(
        shapes,
        containment_threshold=containment_threshold,
        iou_threshold=iou_threshold,
        same_label=same_label,
    )
    if not removed:
        return 0, evidence
    if destination.exists() and not overwrite:
        raise FileExistsError(
            "输出已存在；使用 --overwrite 允许覆盖: {}".format(destination)
        )
    data["shapes"] = cleaned
    _write_json_atomically(destination, data)
    return len(removed), evidence


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
            "先按图片文件名匹配同名 JSON，再删除嵌套大框和 "
            "IoU>=阈值的重复框；仅为发生变化的标注生成新 JSON。"
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
        default=0.98,
        help="较小框的最小包含率，默认 0.98",
    )
    parser.add_argument(
        "--iou-threshold",
        type=float,
        default=0.95,
        help="重复框 IoU 阈值，默认 0.95",
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
    """Run the cleaner and return a process exit code."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = parse_args(argv)
    try:
        _validate_threshold(
            args.containment_threshold, "--containment-threshold"
        )
        _validate_threshold(args.iou_threshold, "--iou-threshold")
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
    removed_shapes = 0
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
                iou_threshold=args.iou_threshold,
                same_label=args.same_label,
                overwrite=args.overwrite,
            )
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            failures += 1
            print("处理失败 {}: {}".format(source, exc), file=sys.stderr)
            continue
        if not count:
            continue
        changed_files += 1
        removed_shapes += count
        print("生成 {}: 删除 {} 个框".format(destination, count))
        for item in evidence:
            print(
                "  删除 #{}, 保留 #{} | {} | containment={:.4f} "
                "IoU={:.4f} | {} -> {}".format(
                    item.removed_index,
                    item.kept_index,
                    item.reason,
                    item.containment,
                    item.iou,
                    item.removed_label,
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
        "生成 {} 个新 JSON | 删除 {} 个框 | 缺失 {} 个 | "
        "同名冲突 {} 个 | 失败 {} 个".format(
            len(image_paths),
            len(image_stems),
            matched_files,
            changed_files,
            removed_shapes,
            len(missing_stems),
            len(ambiguous_stems),
            failures,
        )
    )
    return 1 if failures or ambiguous_stems else 0


if __name__ == "__main__":
    sys.exit(main())
