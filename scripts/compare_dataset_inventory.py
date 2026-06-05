#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compare dataset inventory rows and report synchronization mismatches."""

import argparse
import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Set, Tuple


SUMMARY_FIELDS = ["section", "dataset", "metric", "value", "note"]
PAIR_FIELDS = ["dataset", "status", "stem", "image_paths", "json_paths"]
DUPLICATE_FIELDS = ["dataset", "kind", "stem", "count", "paths"]
CROSS_SUMMARY_FIELDS = [
    "baseline",
    "dataset",
    "baseline_stems",
    "dataset_stems",
    "matched_stems",
    "missing_in_dataset",
    "extra_in_dataset",
    "overlap_rate_vs_baseline",
]
CROSS_MISMATCH_FIELDS = [
    "baseline",
    "dataset",
    "status",
    "stem",
    "baseline_paths",
    "dataset_paths",
]


RowsByKind = Dict[str, Dict[str, List[Mapping[str, str]]]]


def read_tsv(path: Path) -> List[Dict[str, str]]:
    """Read a UTF-8 TSV inventory file."""
    with path.open("r", newline="", encoding="utf-8-sig") as file_obj:
        return list(csv.DictReader(file_obj, delimiter="\t"))


def write_tsv(
    path: Path,
    fieldnames: Sequence[str],
    rows: Sequence[Mapping[str, object]],
) -> None:
    """Write report rows to a UTF-8 TSV file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as file_obj:
        writer = csv.DictWriter(
            file_obj, fieldnames=fieldnames, delimiter="\t"
        )
        writer.writeheader()
        writer.writerows(rows)


def index_rows(rows: Sequence[Mapping[str, str]]) -> Dict[str, RowsByKind]:
    """Index inventory rows by dataset, kind, and filename stem."""
    indexed: Dict[str, RowsByKind] = {}
    for row in rows:
        dataset = row.get("dataset", "")
        kind = row.get("kind", "")
        stem = row.get("stem", "")
        if not dataset or not kind or not stem:
            continue
        indexed.setdefault(dataset, defaultdict(lambda: defaultdict(list)))
        indexed[dataset][kind][stem].append(row)
    return indexed


def row_paths(rows: Sequence[Mapping[str, str]]) -> str:
    """Return report-friendly file paths for rows."""
    return ";".join(row.get("path", "") for row in rows)


def stem_paths_by_any_kind(kind_map: RowsByKind, stem: str) -> str:
    """Return all file paths for one stem across all kinds."""
    paths = []
    for by_stem in kind_map.values():
        paths.extend(row.get("path", "") for row in by_stem.get(stem, []))
    return ";".join(paths)


def stems_for_kind(kind_map: RowsByKind, stem_kind: str) -> Set[str]:
    """Return the comparable stem set for a dataset."""
    image_stems = set(kind_map.get("image", {}))
    json_stems = set(kind_map.get("json", {}))
    all_stems = set()
    for by_stem in kind_map.values():
        all_stems.update(by_stem)

    if stem_kind == "image":
        return image_stems
    if stem_kind == "json":
        return json_stems
    if stem_kind == "both":
        return image_stems & json_stems
    return all_stems


def count_unique_stems(kind_map: RowsByKind, kind: str) -> int:
    """Count unique stems for one kind."""
    return len(kind_map.get(kind, {}))


def count_files(kind_map: RowsByKind, kind: str) -> int:
    """Count files for one kind."""
    return sum(len(rows) for rows in kind_map.get(kind, {}).values())


def count_duplicate_stems(kind_map: RowsByKind, kind: str) -> int:
    """Count stems that appear more than once for one kind."""
    return sum(1 for rows in kind_map.get(kind, {}).values() if len(rows) > 1)


def build_summary_rows(
    indexed: Mapping[str, RowsByKind]
) -> List[Mapping[str, object]]:
    """Build per-dataset inventory metric rows."""
    rows: List[Mapping[str, object]] = []
    metrics = [
        ("image_files", lambda data: count_files(data, "image")),
        ("json_files", lambda data: count_files(data, "json")),
        ("unique_image_stems", lambda data: count_unique_stems(data, "image")),
        ("unique_json_stems", lambda data: count_unique_stems(data, "json")),
        (
            "matched_image_json_stems",
            lambda data: len(
                set(data.get("image", {})) & set(data.get("json", {}))
            ),
        ),
        (
            "image_without_json_stems",
            lambda data: len(
                set(data.get("image", {})) - set(data.get("json", {}))
            ),
        ),
        (
            "json_without_image_stems",
            lambda data: len(
                set(data.get("json", {})) - set(data.get("image", {}))
            ),
        ),
        (
            "duplicate_image_stems",
            lambda data: count_duplicate_stems(data, "image"),
        ),
        (
            "duplicate_json_stems",
            lambda data: count_duplicate_stems(data, "json"),
        ),
    ]
    for dataset, kind_map in sorted(indexed.items()):
        for metric, getter in metrics:
            rows.append(
                {
                    "section": "dataset",
                    "dataset": dataset,
                    "metric": metric,
                    "value": getter(kind_map),
                    "note": "",
                }
            )
    return rows


def build_pair_rows(
    indexed: Mapping[str, RowsByKind]
) -> List[Mapping[str, object]]:
    """Build image-vs-JSON pairing rows inside each dataset."""
    rows: List[Mapping[str, object]] = []
    for dataset, kind_map in sorted(indexed.items()):
        image_map = kind_map.get("image", {})
        json_map = kind_map.get("json", {})
        all_stems = sorted(set(image_map) | set(json_map))
        for stem in all_stems:
            image_paths = row_paths(image_map.get(stem, []))
            json_paths = row_paths(json_map.get(stem, []))
            if stem in image_map and stem in json_map:
                status = "matched"
            elif stem in image_map:
                status = "image_without_json"
            else:
                status = "json_without_image"
            rows.append(
                {
                    "dataset": dataset,
                    "status": status,
                    "stem": stem,
                    "image_paths": image_paths,
                    "json_paths": json_paths,
                }
            )
    return rows


def build_duplicate_rows(
    indexed: Mapping[str, RowsByKind]
) -> List[Mapping[str, object]]:
    """Build duplicate-stem report rows."""
    rows: List[Mapping[str, object]] = []
    for dataset, kind_map in sorted(indexed.items()):
        for kind in sorted(kind_map):
            for stem, stem_rows in sorted(kind_map[kind].items()):
                if len(stem_rows) <= 1:
                    continue
                rows.append(
                    {
                        "dataset": dataset,
                        "kind": kind,
                        "stem": stem,
                        "count": len(stem_rows),
                        "paths": row_paths(stem_rows),
                    }
                )
    return rows


def build_cross_rows(
    indexed: Mapping[str, RowsByKind],
    baseline: str,
    stem_kind: str,
) -> Tuple[List[Mapping[str, object]], List[Mapping[str, object]]]:
    """Build cross-dataset summary and mismatch rows."""
    if baseline not in indexed:
        raise ValueError(f"baseline dataset not found: {baseline}")

    summary_rows: List[Mapping[str, object]] = []
    mismatch_rows: List[Mapping[str, object]] = []
    baseline_map = indexed[baseline]
    baseline_stems = stems_for_kind(baseline_map, stem_kind)

    for dataset, kind_map in sorted(indexed.items()):
        if dataset == baseline:
            continue
        dataset_stems = stems_for_kind(kind_map, stem_kind)
        matched = baseline_stems & dataset_stems
        missing = sorted(baseline_stems - dataset_stems)
        extra = sorted(dataset_stems - baseline_stems)
        rate = 0.0
        if baseline_stems:
            rate = len(matched) / len(baseline_stems)

        summary_rows.append(
            {
                "baseline": baseline,
                "dataset": dataset,
                "baseline_stems": len(baseline_stems),
                "dataset_stems": len(dataset_stems),
                "matched_stems": len(matched),
                "missing_in_dataset": len(missing),
                "extra_in_dataset": len(extra),
                "overlap_rate_vs_baseline": f"{rate:.6f}",
            }
        )
        for stem in missing:
            mismatch_rows.append(
                {
                    "baseline": baseline,
                    "dataset": dataset,
                    "status": "missing_in_dataset",
                    "stem": stem,
                    "baseline_paths": stem_paths_by_any_kind(
                        baseline_map, stem
                    ),
                    "dataset_paths": "",
                }
            )
        for stem in extra:
            mismatch_rows.append(
                {
                    "baseline": baseline,
                    "dataset": dataset,
                    "status": "extra_in_dataset",
                    "stem": stem,
                    "baseline_paths": "",
                    "dataset_paths": stem_paths_by_any_kind(kind_map, stem),
                }
            )
    return summary_rows, mismatch_rows


def manifest_fieldnames(datasets: Sequence[str]) -> List[str]:
    """Return dynamic manifest fieldnames."""
    fields = ["stem", "present_dataset_count", "present_datasets"]
    for dataset in datasets:
        fields.extend(
            [
                f"{dataset}_present",
                f"{dataset}_image_count",
                f"{dataset}_json_count",
            ]
        )
    return fields


def build_manifest_rows(
    indexed: Mapping[str, RowsByKind]
) -> Tuple[List[str], List[Mapping[str, object]]]:
    """Build a multi-dataset presence manifest."""
    datasets = sorted(indexed)
    all_stems: Set[str] = set()
    for kind_map in indexed.values():
        all_stems.update(stems_for_kind(kind_map, "any"))

    rows: List[Mapping[str, object]] = []
    for stem in sorted(all_stems):
        row: Dict[str, object] = {"stem": stem}
        present = []
        for dataset in datasets:
            kind_map = indexed[dataset]
            image_count = len(kind_map.get("image", {}).get(stem, []))
            json_count = len(kind_map.get("json", {}).get(stem, []))
            exists = image_count > 0 or json_count > 0
            if exists:
                present.append(dataset)
            row[f"{dataset}_present"] = "yes" if exists else "no"
            row[f"{dataset}_image_count"] = image_count
            row[f"{dataset}_json_count"] = json_count
        row["present_dataset_count"] = len(present)
        row["present_datasets"] = ",".join(present)
        rows.append(row)
    return manifest_fieldnames(datasets), rows


def print_summary(
    output_dir: Path,
    cross_rows: Sequence[Mapping[str, object]],
    mismatch_rows: Sequence[Mapping[str, object]],
) -> None:
    """Print a compact comparison summary."""
    mismatch_counts = Counter(row["status"] for row in mismatch_rows)
    print(f"Wrote comparison reports: {output_dir}")
    for row in cross_rows:
        print(
            f"- {row['baseline']} -> {row['dataset']}: "
            f"matched={row['matched_stems']}, "
            f"missing={row['missing_in_dataset']}, "
            f"extra={row['extra_in_dataset']}"
        )
    if mismatch_counts:
        text = ", ".join(
            f"{key}={mismatch_counts[key]}" for key in sorted(mismatch_counts)
        )
        print(f"Mismatch rows: {text}")


def compare_inventory(
    inventory_path: Path,
    output_dir: Path,
    baseline: Optional[str] = None,
    stem_kind: str = "any",
) -> None:
    """Compare one inventory file and write report files."""
    rows = read_tsv(inventory_path)
    indexed = index_rows(rows)
    if not indexed:
        raise ValueError("inventory has no usable dataset rows")

    dataset_names = sorted(indexed)
    baseline_name = baseline or dataset_names[0]

    summary_rows = build_summary_rows(indexed)
    pair_rows = build_pair_rows(indexed)
    duplicate_rows = build_duplicate_rows(indexed)
    cross_rows, mismatch_rows = build_cross_rows(
        indexed, baseline_name, stem_kind
    )
    manifest_fields, manifest_rows = build_manifest_rows(indexed)

    output_dir.mkdir(parents=True, exist_ok=True)
    write_tsv(output_dir / "dataset_summary.tsv", SUMMARY_FIELDS, summary_rows)
    write_tsv(output_dir / "pair_report.tsv", PAIR_FIELDS, pair_rows)
    write_tsv(
        output_dir / "duplicate_stems.tsv",
        DUPLICATE_FIELDS,
        duplicate_rows,
    )
    write_tsv(
        output_dir / "cross_dataset_summary.tsv",
        CROSS_SUMMARY_FIELDS,
        cross_rows,
    )
    write_tsv(
        output_dir / "cross_dataset_mismatch.tsv",
        CROSS_MISMATCH_FIELDS,
        mismatch_rows,
    )
    write_tsv(
        output_dir / "multi_dataset_manifest.tsv",
        manifest_fields,
        manifest_rows,
    )
    print_summary(output_dir, cross_rows, mismatch_rows)


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(
        description="Compare a dataset inventory TSV and write sync reports."
    )
    parser.add_argument(
        "--inventory",
        default="docs/dataset_inventory.tsv",
        help="Inventory TSV generated by inventory_dataset_files.py.",
    )
    parser.add_argument(
        "--output-dir",
        default="docs/dataset_sync_reports",
        help="Directory for comparison report TSV files.",
    )
    parser.add_argument(
        "--baseline",
        help=(
            "Dataset name used as the baseline. Defaults to the first dataset "
            "name in sorted order."
        ),
    )
    parser.add_argument(
        "--stem-kind",
        choices=["any", "image", "json", "both"],
        default="any",
        help=(
            "Which stems to compare across datasets. 'both' means stems that "
            "have both image and JSON inside a dataset."
        ),
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run the comparison command."""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        compare_inventory(
            Path(args.inventory).expanduser().resolve(),
            Path(args.output_dir).expanduser().resolve(),
            args.baseline,
            args.stem_kind,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
