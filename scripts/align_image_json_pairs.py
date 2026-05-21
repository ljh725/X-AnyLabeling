#!/usr/bin/env python3
"""Align single-level image and JSON folders for YOLO training."""

import argparse
import csv
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path


IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".bmp",
    ".webp",
    ".tif",
    ".tiff",
}


@dataclass(frozen=True)
class DatasetFile:
    """File metadata used for stem-based alignment."""

    stem: str
    path: Path


def collect_files(directory, suffixes):
    """Collect files in one directory level by allowed suffixes."""
    return [
        DatasetFile(path.stem, path)
        for path in sorted(directory.iterdir(), key=lambda item: item.name.lower())
        if path.is_file() and path.suffix.lower() in suffixes
    ]


def group_by_stem(files):
    """Group files by filename stem."""
    grouped = {}
    for file_info in files:
        grouped.setdefault(file_info.stem, []).append(file_info.path)
    return grouped


def write_csv(path, rows, fieldnames):
    """Write rows to a UTF-8 CSV file."""
    with path.open("w", newline="", encoding="utf-8-sig") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def add_report_row(rows, status, stem, source_path, target_path="", note=""):
    """Append a normalized operation row to the report."""
    rows.append(
        {
            "status": status,
            "stem": stem,
            "source_path": str(source_path),
            "target_path": str(target_path) if target_path else "",
            "note": note,
        }
    )


def move_or_report(source_path, target_dir, apply_changes, stem, status, rows, errors):
    """Move a file when safe, otherwise record the skipped operation."""
    target_path = target_dir / source_path.name
    if target_path.exists():
        note = "Skipped because target file already exists."
        add_report_row(rows, status, stem, source_path, target_path, note)
        errors.append(
            {
                "error_type": "target_exists",
                "stem": stem,
                "source_path": str(source_path),
                "target_path": str(target_path),
                "message": note,
            }
        )
        return False

    if apply_changes:
        shutil.move(str(source_path), str(target_path))
        note = "Moved."
    else:
        note = "Dry run; not moved. Use --apply to move this file."

    add_report_row(rows, status, stem, source_path, target_path, note)
    return True


def count_successful_operations(rows, status):
    """Count rows that were not skipped by safety checks."""
    return sum(
        1
        for row in rows
        if row["status"] == status
        and not row["note"].startswith("Skipped")
    )


def validate_directory(path, label):
    """Resolve and validate an input directory."""
    directory = Path(path).expanduser().resolve()
    if not directory.is_dir():
        print(f"Error: {label} is not a directory: {directory}", file=sys.stderr)
        sys.exit(1)
    return directory


def align_dataset(images_dir, json_dir, output_dir, apply_changes=False):
    """Move unpaired files out of image and JSON folders."""
    images_dir = validate_directory(images_dir, "images_dir")
    json_dir = validate_directory(json_dir, "json_dir")
    output_dir = Path(output_dir).expanduser().resolve()

    image_without_json_dir = output_dir / "image_without_json"
    json_without_image_dir = output_dir / "json_without_image"
    output_dir.mkdir(parents=True, exist_ok=True)
    image_without_json_dir.mkdir(parents=True, exist_ok=True)
    json_without_image_dir.mkdir(parents=True, exist_ok=True)

    images = group_by_stem(collect_files(images_dir, IMAGE_EXTENSIONS))
    jsons = group_by_stem(collect_files(json_dir, {".json"}))

    image_stems = set(images)
    json_stems = set(jsons)
    matched_stems = sorted(image_stems & json_stems)
    image_only_stems = sorted(image_stems - json_stems)
    json_only_stems = sorted(json_stems - image_stems)

    report_rows = []
    error_rows = []

    for stem in matched_stems:
        for image_path in images[stem]:
            add_report_row(
                report_rows,
                "matched_image",
                stem,
                image_path,
                note="Kept in place.",
            )
        for json_path in jsons[stem]:
            add_report_row(
                report_rows,
                "matched_json",
                stem,
                json_path,
                note="Kept in place.",
            )

    for stem in image_only_stems:
        for image_path in images[stem]:
            move_or_report(
                image_path,
                image_without_json_dir,
                apply_changes,
                stem,
                "image_without_json",
                report_rows,
                error_rows,
            )

    for stem in json_only_stems:
        for json_path in jsons[stem]:
            move_or_report(
                json_path,
                json_without_image_dir,
                apply_changes,
                stem,
                "json_without_image",
                report_rows,
                error_rows,
            )

    duplicate_rows = collect_duplicate_errors(images, "image")
    duplicate_rows.extend(collect_duplicate_errors(jsons, "json"))
    error_rows.extend(duplicate_rows)

    report_path = output_dir / "align_report.csv"
    error_path = output_dir / "error_report.csv"
    write_csv(
        report_path,
        report_rows,
        ["status", "stem", "source_path", "target_path", "note"],
    )
    write_csv(
        error_path,
        error_rows,
        ["error_type", "stem", "source_path", "target_path", "message"],
    )

    print_summary(
        images_dir,
        json_dir,
        output_dir,
        len(images),
        len(jsons),
        len(matched_stems),
        sum(len(images[stem]) for stem in image_only_stems),
        sum(len(jsons[stem]) for stem in json_only_stems),
        count_successful_operations(report_rows, "image_without_json"),
        count_successful_operations(report_rows, "json_without_image"),
        len(error_rows),
        apply_changes,
        report_path,
        error_path,
    )


def collect_duplicate_errors(grouped_files, file_type):
    """Return error rows for duplicated stems in one folder."""
    rows = []
    for stem, paths in grouped_files.items():
        if len(paths) <= 1:
            continue
        message = f"Multiple {file_type} files share the same filename stem."
        for path in paths:
            rows.append(
                {
                    "error_type": f"duplicate_{file_type}_stem",
                    "stem": stem,
                    "source_path": str(path),
                    "target_path": "",
                    "message": message,
                }
            )
    return rows


def print_summary(
    images_dir,
    json_dir,
    output_dir,
    image_stem_count,
    json_stem_count,
    matched_count,
    image_extra_count,
    json_extra_count,
    image_operation_count,
    json_operation_count,
    error_count,
    apply_changes,
    report_path,
    error_path,
):
    """Print operation summary and usage examples."""
    action = "Moved" if apply_changes else "Would move"
    print("Dataset alignment finished.")
    print(f"Mode: {'apply' if apply_changes else 'dry-run'}")
    print(f"Images folder: {images_dir}")
    print(f"JSON folder: {json_dir}")
    print(f"Output folder: {output_dir}")
    print(f"Image stems: {image_stem_count}")
    print(f"JSON stems: {json_stem_count}")
    print(f"Matched stems: {matched_count}")
    print(f"Image_without_json files found: {image_extra_count}")
    print(f"Json_without_image files found: {json_extra_count}")
    print(f"{action} image_without_json files: {image_operation_count}")
    print(f"{action} json_without_image files: {json_operation_count}")
    print(f"Errors reported: {error_count}")
    print(f"Report: {report_path}")
    print(f"Error report: {error_path}")
    print()
    print("Usage:")
    print(
        "  Dry run: python scripts/align_image_json_pairs.py "
        "--images-dir <images_dir> --json-dir <json_dir> "
        "--output-dir <output_dir>"
    )
    print(
        "  Apply:   python scripts/align_image_json_pairs.py "
        "--images-dir <images_dir> --json-dir <json_dir> "
        "--output-dir <output_dir> --apply"
    )


def main():
    """Parse command-line arguments and run alignment."""
    parser = argparse.ArgumentParser(
        description=(
            "Strictly align single-level image and JSON folders by filename "
            "stem. Unpaired files are moved only when --apply is provided."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  Dry run:
    %(prog)s --images-dir ./images --json-dir ./json --output-dir ./unpaired

  Move unpaired files:
    %(prog)s --images-dir ./images --json-dir ./json --output-dir ./unpaired --apply
""",
    )
    parser.add_argument("--images-dir", required=True, help="Single-level image folder.")
    parser.add_argument("--json-dir", required=True, help="Single-level JSON folder.")
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Folder for unpaired files and CSV reports.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually move unpaired files. Default is dry-run.",
    )

    args = parser.parse_args()
    align_dataset(args.images_dir, args.json_dir, args.output_dir, args.apply)


if __name__ == "__main__":
    main()


"""
功能说明：
    这个脚本用来把图片和对应的 JSON 标注文件一一配对。
    按文件名（去掉后缀）来匹配，如果某个图片找不到对应的 JSON，
    或者某个 JSON 找不到对应的图片，就把这些落单的文件移到单独的文件夹里。
    默认先试运行，看看哪些文件会被移动，只有加了 --apply 才会真动文件。

运行命令样例：

  # 预览模式（只生成报告，不实际移动）
  python scripts/align_image_json_pairs.py \
      --images-dir ./images \
      --json-dir ./json \
      --output-dir ./unpaired

  # 实际执行移动
  python scripts/align_image_json_pairs.py \
      --images-dir ./images \
      --json-dir ./json \
      --output-dir ./unpaired \
      --apply
"""
