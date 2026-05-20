"""Rename or delete labels in X-AnyLabeling JSON annotations.

Edit RENAME_FROM, RENAME_TO, and DELETE_LABELS below, then run:

    python scripts/label_rename_converter.py --src_path input --dst_path output

Use --recursive to process subdirectories, or --inplace to overwrite inputs.
"""

import argparse
import json
import os
import os.path as osp
from dataclasses import dataclass
from typing import Dict, Iterable, List, Tuple


# Source labels to rename. Keep the order aligned with RENAME_TO.
RENAME_FROM = [
    # "old_label",
]

# Target labels. Each item maps to the same index in RENAME_FROM.
RENAME_TO = [
    # "new_label",
]

# Labels listed here will be removed from shapes.
DELETE_LABELS = [
    # "ignore_label",
]


@dataclass
class ConvertStats:
    """Statistics collected during conversion."""

    files: int = 0
    renamed_shapes: int = 0
    deleted_shapes: int = 0
    unchanged_shapes: int = 0


def build_rename_map() -> Dict[str, str]:
    """Build and validate the fixed label rename mapping."""
    if len(RENAME_FROM) != len(RENAME_TO):
        raise ValueError("RENAME_FROM and RENAME_TO must have same length.")

    rename_map = dict(zip(RENAME_FROM, RENAME_TO))
    if len(rename_map) != len(RENAME_FROM):
        raise ValueError("RENAME_FROM contains duplicate labels.")
    return rename_map


def iter_json_files(src_path: str, recursive: bool) -> Iterable[str]:
    """Yield JSON files from a file or directory input path."""
    if osp.isfile(src_path):
        if src_path.lower().endswith(".json"):
            yield src_path
        return

    if recursive:
        for root, _, files in os.walk(src_path):
            for file_name in files:
                if file_name.lower().endswith(".json"):
                    yield osp.join(root, file_name)
        return

    for file_name in os.listdir(src_path):
        file_path = osp.join(src_path, file_name)
        if osp.isfile(file_path) and file_name.lower().endswith(".json"):
            yield file_path


def resolve_output_file(
    src_file: str,
    src_path: str,
    dst_path: str,
    inplace: bool,
) -> str:
    """Resolve output path while preserving directory structure."""
    if inplace:
        return src_file

    if osp.isfile(src_path):
        return dst_path

    relative_path = osp.relpath(src_file, src_path)
    return osp.join(dst_path, relative_path)


def convert_shapes(
    shapes: List[dict], rename_map: Dict[str, str], delete_labels: set
) -> Tuple[List[dict], int, int, int]:
    """Apply label delete and rename rules to annotation shapes."""
    converted_shapes = []
    renamed_count = 0
    deleted_count = 0
    unchanged_count = 0

    for shape in shapes:
        label = shape.get("label")
        if label in delete_labels:
            deleted_count += 1
            continue

        if label in rename_map:
            shape["label"] = rename_map[label]
            renamed_count += 1
        else:
            unchanged_count += 1

        converted_shapes.append(shape)

    return converted_shapes, renamed_count, deleted_count, unchanged_count


def convert_file(
    src_file: str,
    dst_file: str,
    rename_map: Dict[str, str],
    delete_labels: set,
) -> ConvertStats:
    """Convert one X-AnyLabeling JSON annotation file."""
    with open(src_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    shapes = data.get("shapes", [])
    converted_shapes, renamed_count, deleted_count, unchanged_count = (
        convert_shapes(shapes, rename_map, delete_labels)
    )
    data["shapes"] = converted_shapes

    output_dir = osp.dirname(dst_file)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    with open(dst_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    return ConvertStats(
        files=1,
        renamed_shapes=renamed_count,
        deleted_shapes=deleted_count,
        unchanged_shapes=unchanged_count,
    )


def validate_args(args: argparse.Namespace) -> None:
    """Validate command line arguments."""
    if not osp.exists(args.src_path):
        raise FileNotFoundError(f"Input path does not exist: {args.src_path}")

    if args.inplace:
        return

    if not args.dst_path:
        raise ValueError("--dst_path is required unless --inplace is used.")

    if osp.isfile(args.src_path) and osp.isdir(args.dst_path):
        raise ValueError(
            "When --src_path is a file, --dst_path must be an output file."
        )


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Rename/delete labels in X-AnyLabeling JSON files."
    )
    parser.add_argument(
        "--src_path",
        required=True,
        help="Input JSON file or directory containing JSON annotations.",
    )
    parser.add_argument(
        "--dst_path",
        default=None,
        help="Output JSON file or directory. Required unless --inplace is used.",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Recursively process JSON files in subdirectories.",
    )
    parser.add_argument(
        "--inplace",
        action="store_true",
        help="Overwrite input JSON files in place.",
    )
    return parser.parse_args()


def main() -> None:
    """Run label rename/delete conversion."""
    args = parse_args()
    validate_args(args)

    rename_map = build_rename_map()
    delete_labels = set(DELETE_LABELS)

    totals = ConvertStats()
    json_files = list(iter_json_files(args.src_path, args.recursive))
    if not json_files:
        print("No JSON files found.")
        return

    for src_file in json_files:
        dst_file = resolve_output_file(
            src_file, args.src_path, args.dst_path, args.inplace
        )
        stats = convert_file(src_file, dst_file, rename_map, delete_labels)
        totals.files += stats.files
        totals.renamed_shapes += stats.renamed_shapes
        totals.deleted_shapes += stats.deleted_shapes
        totals.unchanged_shapes += stats.unchanged_shapes

    print("Label conversion completed.")
    print(f"Files processed: {totals.files}")
    print(f"Shapes renamed: {totals.renamed_shapes}")
    print(f"Shapes deleted: {totals.deleted_shapes}")
    print(f"Shapes unchanged: {totals.unchanged_shapes}")


if __name__ == "__main__":
    main()
