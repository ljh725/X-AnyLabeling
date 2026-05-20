#!/usr/bin/env python3
"""Generate JSON labels for augmented images."""

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    Image = None


IMAGE_EXTENSIONS = {
    ".bmp",
    ".jpg",
    ".jpeg",
    ".png",
    ".tif",
    ".tiff",
    ".webp",
}
DEFAULT_AUGMENT_MARKER = "__jpg__gen_"
STATUS_CREATED = "CREATE"
STATUS_SKIPPED = "SKIP"


def parse_original_stem(image_stem, augment_marker):
    """Return the original image stem from an augmented image stem."""
    if augment_marker not in image_stem:
        return None
    return image_stem.split(augment_marker, 1)[0]


def read_image_size(image_path):
    """Return image width and height."""
    if Image is None:
        return None

    with Image.open(image_path) as image:
        return image.size


def iter_images(directory):
    """Yield image files in deterministic order."""
    return sorted(
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    )


def process_image(
    image_path,
    src_json_dir,
    out_json_dir,
    augment_marker,
    overwrite,
    dry_run,
):
    """Generate one JSON label file from one augmented image."""
    original_stem = parse_original_stem(image_path.stem, augment_marker)
    if not original_stem:
        return (
            STATUS_SKIPPED,
            f"name does not match marker: {image_path.name}",
        )

    src_json_path = src_json_dir / f"{original_stem}.json"
    if not src_json_path.is_file():
        return (STATUS_SKIPPED, f"source JSON missing: {src_json_path.name}")

    out_json_path = out_json_dir / f"{image_path.stem}.json"
    if out_json_path.exists() and not overwrite:
        return (STATUS_SKIPPED, f"output exists: {out_json_path.name}")

    with src_json_path.open("r", encoding="utf-8") as src_file:
        data = json.load(src_file)

    image_size = read_image_size(image_path)
    data["imagePath"] = image_path.name
    if image_size is not None:
        image_width, image_height = image_size
        data["imageWidth"] = image_width
        data["imageHeight"] = image_height

    if not dry_run:
        with out_json_path.open("w", encoding="utf-8") as out_file:
            json.dump(data, out_file, ensure_ascii=False, indent=2)
            out_file.write("\n")

    return (
        STATUS_CREATED,
        f"{out_json_path.name} <- {src_json_path.name}",
    )


def generate_augmented_jsons(
    src_json_dir,
    aug_image_dir,
    out_json_dir,
    augment_marker=DEFAULT_AUGMENT_MARKER,
    overwrite=False,
    dry_run=False,
    workers=4,
):
    """Generate label JSON files for augmented images."""
    src_json_dir = Path(src_json_dir).resolve()
    aug_image_dir = Path(aug_image_dir).resolve()
    out_json_dir = Path(out_json_dir).resolve()

    if not src_json_dir.is_dir():
        raise NotADirectoryError(f"Source JSON directory not found: {src_json_dir}")
    if not aug_image_dir.is_dir():
        raise NotADirectoryError(
            f"Augmented image directory not found: {aug_image_dir}"
        )

    images = list(iter_images(aug_image_dir))
    if not images:
        print(f"No augmented images found in: {aug_image_dir}")
        return 0, 0

    if dry_run:
        print("Dry run: no files will be written.")
    else:
        out_json_dir.mkdir(parents=True, exist_ok=True)

    if Image is None:
        print(
            "Pillow is not installed. Keeping original imageWidth/imageHeight."
        )

    created = 0
    skipped = 0
    workers = max(1, workers)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        results = executor.map(
            lambda image_path: process_image(
                image_path=image_path,
                src_json_dir=src_json_dir,
                out_json_dir=out_json_dir,
                augment_marker=augment_marker,
                overwrite=overwrite,
                dry_run=dry_run,
            ),
            images,
        )

        for status, message in results:
            print(f"{status}: {message}")
            if status == STATUS_CREATED:
                created += 1
            else:
                skipped += 1

    print(
        f"Generated {created} JSON file(s), skipped {skipped} file(s) "
        f"with {workers} worker(s)."
    )
    return created, skipped


def main():
    """Parse command line arguments and generate labels."""
    parser = argparse.ArgumentParser(
        description="Generate JSON labels for augmented images.",
    )
    parser.add_argument(
        "--src-json-dir",
        required=True,
        help="Directory containing original JSON label files.",
    )
    parser.add_argument(
        "--aug-image-dir",
        required=True,
        help="Directory containing augmented image files.",
    )
    parser.add_argument(
        "--out-json-dir",
        required=True,
        help="Directory where generated JSON files will be saved.",
    )
    parser.add_argument(
        "--augment-marker",
        default=DEFAULT_AUGMENT_MARKER,
        help=(
            "Marker used to split augmented names from original names "
            f"(default: {DEFAULT_AUGMENT_MARKER})."
        ),
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing output JSON files.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview generated files without writing them.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Number of worker threads for batch processing (default: 4).",
    )

    args = parser.parse_args()

    try:
        generate_augmented_jsons(
            src_json_dir=args.src_json_dir,
            aug_image_dir=args.aug_image_dir,
            out_json_dir=args.out_json_dir,
            augment_marker=args.augment_marker,
            overwrite=args.overwrite,
            dry_run=args.dry_run,
            workers=args.workers,
        )
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

