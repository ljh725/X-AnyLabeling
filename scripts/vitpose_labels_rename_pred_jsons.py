#!/usr/bin/env python3
"""Rename `_pred.json` annotations to match image stems.

For every JSON file in `json_dir` ending with `{suffix}.json`, check whether an
image with the same stem exists in `images_dir`. If so, copy the JSON to
`output_dir` with the suffix removed.
"""

import argparse
import csv
import shutil
import sys
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
IDE_JSON_DIR = r"D:\A0_part1_kps_3_class_dataset\HK-Hard\sort_json_preds_1458"
IDE_OUTPUT_DIR = r"D:\A0_part1_kps_3_class_dataset\HK-Hard\renamed_jsons"
IDE_SUFFIX = "_pred"
IDE_DRY_RUN = True
# ---------------------------------------------------------------------------


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


def rename_pred_jsons(
    images_dir: Path,
    json_dir: Path,
    output_dir: Path,
    suffix: str = "_pred",
    dry_run: bool = False,
) -> list[dict]:
    """Copy matched `_pred.json` files to output_dir without the suffix."""
    image_stems = collect_image_stems(images_dir)
    if not image_stems:
        print("Error: no image files found.", file=sys.stderr)
        sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    copied = 0
    skipped_no_image = 0
    skipped_exists = 0
    seen_targets = set()

    for json_path in sorted(json_dir.iterdir(), key=lambda p: p.name.lower()):
        if not json_path.is_file() or json_path.suffix.lower() != ".json":
            continue

        name = json_path.stem
        if not name.endswith(suffix):
            continue

        stem = name[: -len(suffix)]
        if stem not in image_stems:
            skipped_no_image += 1
            rows.append(
                {
                    "source": str(json_path),
                    "target": "",
                    "status": "skipped_no_image",
                    "note": f"no image for stem '{stem}'",
                }
            )
            continue

        target_name = f"{stem}.json"
        target_path = output_dir / target_name

        if target_name in seen_targets:
            skipped_exists += 1
            rows.append(
                {
                    "source": str(json_path),
                    "target": str(target_path),
                    "status": "skipped_duplicate_target",
                    "note": f"target '{target_name}' already used",
                }
            )
            continue

        if target_path.exists():
            skipped_exists += 1
            rows.append(
                {
                    "source": str(json_path),
                    "target": str(target_path),
                    "status": "skipped_target_exists",
                    "note": "target file already exists",
                }
            )
            continue

        seen_targets.add(target_name)
        if not dry_run:
            shutil.copy2(str(json_path), str(target_path))

        copied += 1
        rows.append(
            {
                "source": str(json_path),
                "target": str(target_path),
                "status": "copied" if not dry_run else "would_copy",
                "note": "",
            }
        )

    total_scanned = copied + skipped_no_image + skipped_exists
    print(f"Image stems found: {len(image_stems)}")
    print(f"JSON files scanned: {total_scanned}")
    print(f"Copied: {copied}")
    print(f"Skipped (no matching image): {skipped_no_image}")
    print(f"Skipped (target exists/duplicate): {skipped_exists}")

    return rows


def write_report(report_path: Path, rows: list[dict]) -> None:
    """Write operation report as UTF-8 CSV."""
    fieldnames = ["source", "target", "status", "note"]
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    """Parse arguments and run the rename workflow."""
    parser = argparse.ArgumentParser(
        description=(
            "Copy JSON files ending with `{suffix}.json` to output_dir, "
            "removing the suffix when a matching image stem exists."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  %(prog)s --images-dir ./images --json-dir ./json --output-dir ./out
  %(prog)s --images-dir ./images --json-dir ./json --output-dir ./out --dry-run
""",
    )
    parser.add_argument(
        "--images-dir",
        type=Path,
        default=None,
        help="Directory containing images.",
    )
    parser.add_argument(
        "--json-dir",
        type=Path,
        default=None,
        help="Directory containing JSON files.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for renamed JSON files.",
    )
    parser.add_argument(
        "--suffix",
        default="_pred",
        help="Suffix before .json to remove (default: _pred).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=None,
        help="Preview changes without copying files.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Optional CSV report path.",
    )

    args = parser.parse_args()

    using_ide_defaults = not any(
        [args.images_dir, args.json_dir, args.output_dir]
    )
    images_dir = args.images_dir if args.images_dir else Path(IDE_IMAGES_DIR)
    json_dir = args.json_dir if args.json_dir else Path(IDE_JSON_DIR)
    output_dir = args.output_dir if args.output_dir else Path(IDE_OUTPUT_DIR)
    if using_ide_defaults:
        dry_run = IDE_DRY_RUN if args.dry_run is None else args.dry_run
    else:
        dry_run = bool(args.dry_run)

    images_dir = validate_directory(images_dir, "--images-dir")
    json_dir = validate_directory(json_dir, "--json-dir")

    rows = rename_pred_jsons(
        images_dir,
        json_dir,
        output_dir,
        suffix=args.suffix,
        dry_run=dry_run,
    )

    if args.report:
        write_report(args.report, rows)
        print(f"Report saved to: {args.report}")


if __name__ == "__main__":
    main()


"""
功能说明：
    这个脚本用来把 `_pred.json` 结尾的标注文件重命名为与图片同名的 `.json`，
    并复制到指定输出目录。

    处理逻辑：
    - 扫描图片目录，收集所有图片文件的 stem（去掉扩展名）。
    - 扫描 JSON 目录，找出以 `_pred.json` 结尾的文件。
    - 去掉 `_pred` 后缀得到候选 stem，若该 stem 在图片 stem 集合中存在，
      则复制为 `{stem}.json` 到输出目录。
    - 没有对应图片的 JSON 文件直接跳过。

    支持命令行参数，也支持在脚本顶部的 IDE_* 常量中设置默认参数，方便
    在 IDE 中直接运行。

运行命令样例：

  # 基础用法
  python scripts/rename_pred_jsons.py \
      --images-dir "D:\\A0_part1_kps_3_class_dataset\\HK-Hard\\images" \
      --json-dir "D:\\A0_part1_kps_3_class_dataset\\HK-Hard\\sort_json_preds_1458" \
      --output-dir "D:\\A0_part1_kps_3_class_dataset\\HK-Hard\\renamed_jsons"

  # 仅预览，不复制
  python scripts/rename_pred_jsons.py \
      --images-dir "D:\\A0_part1_kps_3_class_dataset\\HK-Hard\\images" \
      --json-dir "D:\\A0_part1_kps_3_class_dataset\\HK-Hard\\sort_json_preds_1458" \
      --output-dir "D:\\A0_part1_kps_3_class_dataset\\HK-Hard\\renamed_jsons" \
      --dry-run

  # 自定义后缀
  python scripts/rename_pred_jsons.py \
      --images-dir ./images \
      --json-dir ./json \
      --output-dir ./out \
      --suffix "_prediction"

  # 生成 CSV 报告
  python scripts/rename_pred_jsons.py \
      --images-dir ./images \
      --json-dir ./json \
      --output-dir ./out \
      --report ./report.csv

  # 在 IDE 中直接运行（不用命令行参数）
  # 修改脚本顶部的 IDE_IMAGES_DIR、IDE_JSON_DIR、IDE_OUTPUT_DIR、
  # IDE_SUFFIX、IDE_DRY_RUN 即可
"""
