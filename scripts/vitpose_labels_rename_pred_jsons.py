#!/usr/bin/env python3
"""Merge VitPose prediction JSONs into X-AnyLabeling base JSONs by group_id.

For every prediction JSON `{stem}_pred.json` in `pred_json_dir`, find the
matching base annotation `{stem}.json` in `base_json_dir` and image `{stem}` in
`images_dir`. Clear the keypoint `points` in the base JSON and inject the
keypoints from the prediction JSON by `group_id`, preserving all other metadata.

Original files are never modified; output is written to `output_dir`.
"""

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path

IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".bmp",
    ".webp",
    ".tif",
    ".tiff",
    ".gif",
}


# ---------------------------------------------------------------------------
# IDE Launch Configuration
# ---------------------------------------------------------------------------
# When running from an IDE (PyCharm / VS Code / etc.), set these defaults:
IDE_IMAGES_DIR = r"D:\A0_part1_kps_3_class_dataset\HK-Hard\images"
IDE_BASE_JSON_DIR = r"D:\A0_part1_kps_3_class_dataset\HK-Hard\sort_json_1458"
IDE_PRED_JSON_DIR = (
    r"D:\A0_part1_kps_3_class_dataset\HK-Hard\sort_json_preds_1458"
)
IDE_OUTPUT_DIR = r"D:\A0_part1_kps_3_class_dataset\HK-Hard\merged_jsons"
IDE_SUFFIX = "_pred"
IDE_DRY_RUN = True
# ---------------------------------------------------------------------------


# COCO-style 17 keypoints order used by VitPose / data2.
KEYPOINT_LABELS = [
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


def validate_directory(path: Path, label: str) -> Path:
    """Resolve and validate an input directory."""
    directory = path.expanduser().resolve()
    if not directory.is_dir():
        print(
            f"Error: {label} is not a directory: {directory}", file=sys.stderr
        )
        sys.exit(1)
    return directory


def collect_image_stems(images_dir: Path) -> set[str]:
    """Return filename stems for all image files in the directory."""
    stems = set()
    for path in images_dir.iterdir():
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
            stems.add(path.stem)
    return stems


def load_json(path: Path) -> dict:
    """Load a JSON file and return its content."""
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: dict) -> None:
    """Save data to a JSON file with readable formatting."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def merge_keypoints_into_base(
    base_data: dict,
    pred_persons: list[dict],
) -> dict:
    """Return a new base JSON with pred keypoints injected by group_id.

    Keypoint `points` in the base JSON are cleared first. Then for each person
    in `pred_persons`, the 17 COCO keypoints are written into the matching
    keypoint shapes by `group_id` and label.
    """
    merged_data = deepcopy(base_data)

    label_to_index = {label: idx for idx, label in enumerate(KEYPOINT_LABELS)}

    # Build lookup: (group_id, label) -> shape
    shape_lookup = {}
    for shape in merged_data.get("shapes", []):
        label = shape.get("label")
        group_id = shape.get("group_id")
        if label in label_to_index and group_id is not None:
            shape_lookup[(group_id, label)] = shape

    # Clear keypoint points first.
    for shape in merged_data.get("shapes", []):
        if shape.get("label") in label_to_index:
            shape["points"] = []

    # Inject predicted keypoints.
    for person in pred_persons:
        group_id = person.get("group_id")
        keypoints = person.get("keypoints", [])

        if group_id is None or not keypoints:
            continue

        for idx, point in enumerate(keypoints):
            if idx >= len(KEYPOINT_LABELS):
                continue
            label = KEYPOINT_LABELS[idx]
            shape = shape_lookup.get((group_id, label))
            if shape is not None:
                shape["points"] = [point]

    return merged_data


def merge_pred_jsons(
    images_dir: Path,
    base_json_dir: Path,
    pred_json_dir: Path,
    output_dir: Path,
    suffix: str = "_pred",
    dry_run: bool = False,
) -> list[dict]:
    """Merge prediction JSONs into base JSONs for matching image stems."""
    image_stems = collect_image_stems(images_dir)
    if not image_stems:
        print("Error: no image files found.", file=sys.stderr)
        sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    merged = 0
    skipped_no_image = 0
    skipped_no_base = 0
    skipped_malformed = 0

    for pred_path in sorted(
        pred_json_dir.iterdir(), key=lambda p: p.name.lower()
    ):
        if not pred_path.is_file() or pred_path.suffix.lower() != ".json":
            continue

        name = pred_path.stem
        if not name.endswith(suffix):
            continue

        stem = name[: -len(suffix)]

        if stem not in image_stems:
            skipped_no_image += 1
            rows.append(
                {
                    "source": str(pred_path),
                    "target": "",
                    "status": "skipped_no_image",
                    "note": f"no image for stem '{stem}'",
                }
            )
            continue

        base_path = base_json_dir / f"{stem}.json"
        if not base_path.is_file():
            skipped_no_base += 1
            rows.append(
                {
                    "source": str(pred_path),
                    "target": "",
                    "status": "skipped_no_base_json",
                    "note": f"no base JSON for stem '{stem}'",
                }
            )
            continue

        try:
            base_data = load_json(base_path)
            pred_data = load_json(pred_path)
        except json.JSONDecodeError as exc:
            skipped_malformed += 1
            rows.append(
                {
                    "source": str(pred_path),
                    "target": "",
                    "status": "skipped_malformed",
                    "note": str(exc),
                }
            )
            continue

        pred_persons = pred_data.get("persons", [])
        if not pred_persons:
            skipped_malformed += 1
            rows.append(
                {
                    "source": str(pred_path),
                    "target": "",
                    "status": "skipped_no_persons",
                    "note": "prediction JSON has no 'persons'",
                }
            )
            continue

        merged_data = merge_keypoints_into_base(base_data, pred_persons)
        target_path = output_dir / f"{stem}.json"

        if not dry_run:
            save_json(target_path, merged_data)

        merged += 1
        rows.append(
            {
                "source": str(pred_path),
                "target": str(target_path),
                "status": "merged" if not dry_run else "would_merge",
                "note": "",
            }
        )

    total_scanned = (
        merged + skipped_no_image + skipped_no_base + skipped_malformed
    )
    print(f"Image stems found: {len(image_stems)}")
    print(f"Prediction JSON files scanned: {total_scanned}")
    print(f"Merged: {merged}")
    print(f"Skipped (no matching image): {skipped_no_image}")
    print(f"Skipped (no base JSON): {skipped_no_base}")
    print(f"Skipped (malformed/empty): {skipped_malformed}")

    return rows


def main() -> None:
    """Parse arguments and run the merge workflow."""
    parser = argparse.ArgumentParser(
        description=(
            "Merge VitPose prediction JSONs into X-AnyLabeling base JSONs. "
            "Keypoints are injected by group_id; original files are preserved."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  %(prog)s --images-dir ./images --base-json-dir ./base --pred-json-dir ./pred --output-dir ./out
  %(prog)s --images-dir ./images --base-json-dir ./base --pred-json-dir ./pred --output-dir ./out --dry-run
""",
    )
    parser.add_argument(
        "--images-dir",
        type=Path,
        default=None,
        help="Directory containing images.",
    )
    parser.add_argument(
        "--base-json-dir",
        type=Path,
        default=None,
        help="Directory containing base X-AnyLabeling JSON files.",
    )
    parser.add_argument(
        "--pred-json-dir",
        type=Path,
        default=None,
        help="Directory containing prediction JSON files (e.g. *_pred.json).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for merged JSON files.",
    )
    parser.add_argument(
        "--suffix",
        default="_pred",
        help="Suffix before .json in prediction files (default: _pred).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=None,
        help="Preview changes without writing files.",
    )

    args = parser.parse_args()

    using_ide_defaults = not any(
        [
            args.images_dir,
            args.base_json_dir,
            args.pred_json_dir,
            args.output_dir,
        ]
    )

    images_dir = args.images_dir if args.images_dir else Path(IDE_IMAGES_DIR)
    base_json_dir = (
        args.base_json_dir if args.base_json_dir else Path(IDE_BASE_JSON_DIR)
    )
    pred_json_dir = (
        args.pred_json_dir if args.pred_json_dir else Path(IDE_PRED_JSON_DIR)
    )
    output_dir = args.output_dir if args.output_dir else Path(IDE_OUTPUT_DIR)

    if using_ide_defaults:
        dry_run = IDE_DRY_RUN if args.dry_run is None else args.dry_run
    else:
        dry_run = bool(args.dry_run)

    images_dir = validate_directory(images_dir, "--images-dir")
    base_json_dir = validate_directory(base_json_dir, "--base-json-dir")
    pred_json_dir = validate_directory(pred_json_dir, "--pred-json-dir")

    merge_pred_jsons(
        images_dir,
        base_json_dir,
        pred_json_dir,
        output_dir,
        suffix=args.suffix,
        dry_run=dry_run,
    )


if __name__ == "__main__":
    main()


"""
功能说明：
    这个脚本把 VitPose 预测生成的 `_pred.json` 关键点数据合并到
    X-AnyLabeling 的基础标注 JSON 中。

    处理逻辑：
    - 扫描图片目录，收集所有图片文件的 stem。
    - 扫描预测 JSON 目录，找出以 `_pred.json` 结尾的文件。
    - 对每个预测文件，检查是否存在同名的基础 JSON `{stem}.json`。
    - 加载基础 JSON，复制完整结构（深拷贝），不会修改原始文件。
    - 清空基础 JSON 中所有关键点 shape 的 `points`。
    - 按 `group_id` 匹配 person，把预测 JSON 中的 17 个关键点按
      COCO 顺序写入对应 label 的 `points`。
    - 将合并后的新 JSON 保存到 `--output-dir`，文件名为 `{stem}.json`。

    原始数据不会被修改。

关键点顺序映射（数据2 index -> 数据1 label）：
    0 nose, 1 l_eye, 2 r_eye, 3 l_ear, 4 r_ear,
    5 l_sho, 6 r_sho, 7 l_elb, 8 r_elb, 9 l_wri, 10 r_wri,
    11 l_hip, 12 r_hip, 13 l_knee, 14 r_knee, 15 l_ank, 16 r_ank

运行命令样例：

  # 基础用法
  python scripts/vitpose_labels_rename_pred_jsons.py \
      --images-dir "D:\\A0_part1_kps_3_class_dataset\\HK-Hard\\images" \
      --base-json-dir "D:\\A0_part1_kps_3_class_dataset\\HK-Hard\\sort_json_1458" \
      --pred-json-dir "D:\\A0_part1_kps_3_class_dataset\\HK-Hard\\sort_json_preds_1458" \
      --output-dir "D:\\A0_part1_kps_3_class_dataset\\HK-Hard\\merged_jsons"

  # 仅预览，不写入
  python scripts/vitpose_labels_rename_pred_jsons.py \
      --images-dir "D:\\A0_part1_kps_3_class_dataset\\HK-Hard\\images" \
      --base-json-dir "D:\\A0_part1_kps_3_class_dataset\\HK-Hard\\sort_json_1458" \
      --pred-json-dir "D:\\A0_part1_kps_3_class_dataset\\HK-Hard\\sort_json_preds_1458" \
      --output-dir "D:\\A0_part1_kps_3_class_dataset\\HK-Hard\\merged_jsons" \
      --dry-run

  # 在 IDE 中直接运行（不用命令行参数）
  # 修改脚本顶部的 IDE_IMAGES_DIR、IDE_BASE_JSON_DIR、IDE_PRED_JSON_DIR、
  # IDE_OUTPUT_DIR、IDE_SUFFIX、IDE_DRY_RUN 即可
"""
