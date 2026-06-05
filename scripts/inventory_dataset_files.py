#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Inventory image and JSON files for dataset synchronization checks."""

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


IMAGE_EXTENSIONS = {
    ".bmp",
    ".jpeg",
    ".jpg",
    ".png",
    ".tif",
    ".tiff",
    ".webp",
}
JSON_EXTENSIONS = {".json"}
ALL_EXTENSIONS = IMAGE_EXTENSIONS | JSON_EXTENSIONS
FIELDNAMES = [
    "dataset",
    "role",
    "kind",
    "stem",
    "name",
    "suffix",
    "path",
    "rel_path",
    "size_bytes",
    "mtime_iso",
    "sha1",
    "json_status",
    "json_image_path",
    "json_image_stem",
    "image_width",
    "image_height",
    "shapes_count",
    "labels",
    "label_counts",
    "group_ids",
    "group_count",
    "person_count",
    "rectangle_count",
    "point_count",
]


def parse_source(value: str) -> Tuple[str, str, Path]:
    """Parse one NAME:ROLE:PATH source argument."""
    parts = value.split(":", 2)
    if len(parts) != 3:
        raise argparse.ArgumentTypeError(
            "--source must use NAME:ROLE:PATH, for example "
            "origin:image:D:\\data\\images"
        )

    name, role, path_text = parts
    role = role.lower().strip()
    if role not in {"image", "json", "both", "all"}:
        raise argparse.ArgumentTypeError(
            "ROLE must be one of: image, json, both, all"
        )
    if not name.strip():
        raise argparse.ArgumentTypeError("NAME cannot be empty")
    return name.strip(), role, Path(path_text).expanduser()


def allowed_suffixes(role: str) -> set:
    """Return suffixes that should be scanned for a source role."""
    if role == "image":
        return IMAGE_EXTENSIONS
    if role == "json":
        return JSON_EXTENSIONS
    return ALL_EXTENSIONS


def detect_kind(path: Path) -> str:
    """Return the file kind used by comparison reports."""
    suffix = path.suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    if suffix in JSON_EXTENSIONS:
        return "json"
    return "other"


def iter_files(root: Path, suffixes: set) -> Iterable[Path]:
    """Yield matching files below root in a stable order."""
    for path in sorted(root.rglob("*"), key=lambda item: str(item).lower()):
        if path.is_file() and path.suffix.lower() in suffixes:
            yield path


def file_sha1(path: Path) -> str:
    """Return the SHA1 digest for a file."""
    digest = hashlib.sha1()
    with path.open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def format_mtime(timestamp: float) -> str:
    """Return a local ISO timestamp without microseconds."""
    return datetime.fromtimestamp(timestamp).replace(microsecond=0).isoformat()


def sorted_join(values: Iterable[Any]) -> str:
    """Return a comma-separated stable string for report cells."""
    text_values = [str(value) for value in values if value is not None]
    return ",".join(sorted(set(text_values)))


def counter_cell(counter: Mapping[str, int]) -> str:
    """Return a stable key=value counter string."""
    return ";".join(
        f"{key}={counter[key]}" for key in sorted(counter, key=str.lower)
    )


def parse_json_metadata(path: Path) -> Dict[str, str]:
    """Extract lightweight X-AnyLabeling metadata from a JSON file."""
    metadata = {
        "json_status": "ok",
        "json_image_path": "",
        "json_image_stem": "",
        "image_width": "",
        "image_height": "",
        "shapes_count": "",
        "labels": "",
        "label_counts": "",
        "group_ids": "",
        "group_count": "",
        "person_count": "",
        "rectangle_count": "",
        "point_count": "",
    }
    try:
        with path.open("r", encoding="utf-8") as file_obj:
            payload = json.load(file_obj)
    except Exception as exc:  # noqa: BLE001
        metadata["json_status"] = f"parse_error:{exc.__class__.__name__}"
        return metadata

    if not isinstance(payload, dict):
        metadata["json_status"] = "not_object"
        return metadata

    image_path = payload.get("imagePath")
    if isinstance(image_path, str):
        metadata["json_image_path"] = image_path
        metadata["json_image_stem"] = Path(image_path).stem

    image_width = payload.get("imageWidth")
    image_height = payload.get("imageHeight")
    metadata["image_width"] = "" if image_width is None else str(image_width)
    metadata["image_height"] = (
        "" if image_height is None else str(image_height)
    )

    shapes = payload.get("shapes")
    if not isinstance(shapes, list):
        metadata["json_status"] = "shapes_not_list"
        return metadata

    labels = []
    groups = []
    label_counts: Counter = Counter()
    shape_type_counts: Counter = Counter()
    for shape in shapes:
        if not isinstance(shape, dict):
            continue
        label = shape.get("label")
        if isinstance(label, str):
            labels.append(label)
            label_counts[label] += 1
        group_id = shape.get("group_id")
        if group_id is not None:
            groups.append(group_id)
        shape_type = shape.get("shape_type")
        if isinstance(shape_type, str):
            shape_type_counts[shape_type] += 1

    metadata["shapes_count"] = str(len(shapes))
    metadata["labels"] = sorted_join(labels)
    metadata["label_counts"] = counter_cell(label_counts)
    metadata["group_ids"] = sorted_join(groups)
    metadata["group_count"] = str(len(set(map(str, groups))))
    metadata["person_count"] = str(label_counts.get("person", 0))
    metadata["rectangle_count"] = str(shape_type_counts.get("rectangle", 0))
    metadata["point_count"] = str(shape_type_counts.get("point", 0))
    return metadata


def blank_json_metadata(status: str = "") -> Dict[str, str]:
    """Return empty JSON metadata cells for non-JSON rows."""
    return {
        "json_status": status,
        "json_image_path": "",
        "json_image_stem": "",
        "image_width": "",
        "image_height": "",
        "shapes_count": "",
        "labels": "",
        "label_counts": "",
        "group_ids": "",
        "group_count": "",
        "person_count": "",
        "rectangle_count": "",
        "point_count": "",
    }


def build_file_row(
    dataset: str,
    role: str,
    root: Path,
    path: Path,
    include_hash: bool,
) -> Dict[str, str]:
    """Build one inventory row for a file."""
    stat = path.stat()
    kind = detect_kind(path)
    row = {
        "dataset": dataset,
        "role": role,
        "kind": kind,
        "stem": path.stem,
        "name": path.name,
        "suffix": path.suffix.lower(),
        "path": str(path),
        "rel_path": str(path.relative_to(root)),
        "size_bytes": str(stat.st_size),
        "mtime_iso": format_mtime(stat.st_mtime),
        "sha1": file_sha1(path) if include_hash else "",
    }
    if kind == "json":
        row.update(parse_json_metadata(path))
    else:
        row.update(blank_json_metadata())
    return row


def build_inventory(
    sources: Sequence[Tuple[str, str, Path]],
    include_hash: bool = False,
) -> List[Dict[str, str]]:
    """Build inventory rows for all configured sources."""
    rows: List[Dict[str, str]] = []
    for dataset, role, root in sources:
        root = root.resolve()
        if not root.is_dir():
            raise FileNotFoundError(f"{dataset} is not a directory: {root}")
        suffixes = allowed_suffixes(role)
        for path in iter_files(root, suffixes):
            rows.append(
                build_file_row(dataset, role, root, path.resolve(), include_hash)
            )
    return rows


def write_tsv(path: Path, rows: Sequence[Mapping[str, str]]) -> None:
    """Write rows to a UTF-8 TSV file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as file_obj:
        writer = csv.DictWriter(
            file_obj, fieldnames=FIELDNAMES, delimiter="\t"
        )
        writer.writeheader()
        writer.writerows(rows)


def print_summary(rows: Sequence[Mapping[str, str]], output: Path) -> None:
    """Print a compact inventory summary."""
    by_dataset: Dict[str, Counter] = {}
    for row in rows:
        dataset = row["dataset"]
        by_dataset.setdefault(dataset, Counter())
        by_dataset[dataset][row["kind"]] += 1
        by_dataset[dataset]["files"] += 1
        if row["json_status"].startswith("parse_error"):
            by_dataset[dataset]["json_parse_errors"] += 1

    print(f"Wrote inventory: {output}")
    for dataset in sorted(by_dataset):
        counts = by_dataset[dataset]
        print(
            f"- {dataset}: files={counts['files']}, "
            f"images={counts['image']}, jsons={counts['json']}, "
            f"json_parse_errors={counts['json_parse_errors']}"
        )


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(
        description=(
            "Scan multiple dataset directories and write one TSV inventory."
        )
    )
    parser.add_argument(
        "--source",
        action="append",
        required=True,
        type=parse_source,
        help=(
            "Dataset source in NAME:ROLE:PATH format. ROLE is image, json, "
            "both, or all. Repeat this option for multiple directories."
        ),
    )
    parser.add_argument(
        "--output",
        default="docs/dataset_inventory.tsv",
        help="Output TSV path.",
    )
    parser.add_argument(
        "--hash",
        action="store_true",
        help="Calculate SHA1 for every file. Slower, but useful for renames.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run the inventory command."""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        rows = build_inventory(args.source, args.hash)
    except Exception as exc:  # noqa: BLE001
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    output = Path(args.output).expanduser().resolve()
    write_tsv(output, rows)
    print_summary(rows, output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
