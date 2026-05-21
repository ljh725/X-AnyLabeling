"""Copy listed JSON files and matching images into an output dataset."""

from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path


IMAGE_EXTENSIONS = (
    ".jpg",
    ".jpeg",
    ".png",
    ".bmp",
    ".gif",
    ".webp",
    ".tiff",
)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Extract JSON names from an error report and copy matching "
            "single-level image/JSON files into output/images and output/jsons."
        )
    )
    parser.add_argument(
        "--txt",
        required=True,
        type=Path,
        help="Path to the error report txt file.",
    )
    parser.add_argument(
        "--src-images",
        required=True,
        type=Path,
        help="Source images directory. Only this directory is scanned.",
    )
    parser.add_argument(
        "--src-jsons",
        required=True,
        type=Path,
        help="Source jsons directory. Only this directory is scanned.",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Output directory. images/ and jsons/ will be created below it.",
    )
    parser.add_argument(
        "--log",
        type=Path,
        default=None,
        help="Optional log txt path. Defaults to output/extract_log.txt.",
    )
    return parser.parse_args()


def extract_json_names(report_path: Path) -> list[str]:
    """Extract unique JSON file names from the error report."""
    content = report_path.read_text(encoding="utf-8")
    names = re.findall(r"文件:\s*([^\s]+\.json)", content)

    unique_names = []
    seen = set()
    for name in names:
        base_name = Path(name).name
        if base_name not in seen:
            unique_names.append(base_name)
            seen.add(base_name)
    return unique_names


def find_image(src_images_dir: Path, stem: str) -> Path | None:
    """Find the image matching a JSON stem in a single directory."""
    for extension in IMAGE_EXTENSIONS:
        image_path = src_images_dir / f"{stem}{extension}"
        if image_path.is_file():
            return image_path

    lower_stem = stem.lower()
    for image_path in src_images_dir.iterdir():
        if not image_path.is_file():
            continue
        if image_path.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        if image_path.stem.lower() == lower_stem:
            return image_path
    return None


def copy_if_absent(src_path: Path, dst_path: Path) -> str:
    """Copy a file if the destination does not exist."""
    if dst_path.exists():
        return f"SKIP exists: {dst_path}"

    shutil.copy2(src_path, dst_path)
    return f"COPY: {src_path} -> {dst_path}"


def validate_input_paths(args: argparse.Namespace) -> None:
    """Validate required input paths before copying."""
    if not args.txt.is_file():
        raise FileNotFoundError(f"Error report not found: {args.txt}")
    if not args.src_images.is_dir():
        raise NotADirectoryError(f"Images directory not found: {args.src_images}")
    if not args.src_jsons.is_dir():
        raise NotADirectoryError(f"JSON directory not found: {args.src_jsons}")


def main() -> None:
    """Run the extraction workflow."""
    args = parse_args()
    validate_input_paths(args)

    output_images_dir = args.output / "images"
    output_jsons_dir = args.output / "jsons"
    output_images_dir.mkdir(parents=True, exist_ok=True)
    output_jsons_dir.mkdir(parents=True, exist_ok=True)

    log_path = args.log or args.output / "extract_log.txt"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    json_names = extract_json_names(args.txt)
    log_lines = [
        f"TXT: {args.txt}",
        f"SRC_IMAGES: {args.src_images}",
        f"SRC_JSONS: {args.src_jsons}",
        f"OUTPUT: {args.output}",
        f"TOTAL_JSON_NAMES: {len(json_names)}",
        "",
    ]

    copied_jsons = 0
    copied_images = 0
    skipped = 0
    missing_jsons = 0
    missing_images = 0

    for json_name in json_names:
        stem = Path(json_name).stem
        src_json = args.src_jsons / json_name
        image_path = find_image(args.src_images, stem)

        log_lines.append(f"[{stem}]")
        if src_json.is_file():
            result = copy_if_absent(src_json, output_jsons_dir / json_name)
            log_lines.append(f"JSON {result}")
            if result.startswith("COPY"):
                copied_jsons += 1
            else:
                skipped += 1
        else:
            missing_jsons += 1
            log_lines.append(f"JSON MISSING: {src_json}")

        if image_path is not None:
            result = copy_if_absent(
                image_path,
                output_images_dir / image_path.name,
            )
            log_lines.append(f"IMAGE {result}")
            if result.startswith("COPY"):
                copied_images += 1
            else:
                skipped += 1
        else:
            missing_images += 1
            log_lines.append(f"IMAGE MISSING: {stem}{IMAGE_EXTENSIONS}")
        log_lines.append("")

    log_lines.extend(
        [
            "SUMMARY",
            f"COPIED_JSONS: {copied_jsons}",
            f"COPIED_IMAGES: {copied_images}",
            f"SKIPPED_EXISTING: {skipped}",
            f"MISSING_JSONS: {missing_jsons}",
            f"MISSING_IMAGES: {missing_images}",
        ]
    )
    log_path.write_text("\n".join(log_lines) + "\n", encoding="utf-8")
    print(f"Done. Log saved to: {log_path}")


if __name__ == "__main__":
    main()


"""
功能说明：
    这个脚本用来从错误报告里提取出 JSON 文件名，
    然后到指定的图片文件夹和 JSON 文件夹里找到对应的文件，
    把它们复制到一个新的输出目录里（分别放在 output/images 和 output/jsons 下）。
    适合用来把报错的数据单独挑出来，方便复查或修复。
    如果目标位置已经有同名文件，会自动跳过，不会重复复制。
    操作结果会保存到日志文件里，方便查看哪些文件复制了、哪些跳过了、哪些找不到。

运行命令样例：

  # 基础用法：从错误报告中提取文件，复制到 output 目录
  python scripts/extract_error_files.py \
      --txt ./error_report.txt \
      --src-images ./images \
      --src-jsons ./jsons \
      --output ./output

  # 指定自定义日志文件路径
  python scripts/extract_error_files.py \
      --txt ./error_report.txt \
      --src-images ./images \
      --src-jsons ./jsons \
      --output ./output \
      --log ./my_log.txt
"""
