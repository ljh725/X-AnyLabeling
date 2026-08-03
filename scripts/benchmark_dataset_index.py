#!/usr/bin/env python3
"""Benchmark a full dataset-index rebuild against real annotation files."""

from __future__ import annotations

import argparse
import json
import os
import os.path as osp
import statistics
import sys
import tempfile
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Sequence

_PROJECT_ROOT = osp.dirname(osp.dirname(osp.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from anylabeling.views.labeling.dataset_index import (  # noqa: E402
    INDEX_READ_PREFETCH_LIMIT,
    INDEX_READ_WORKERS,
    DatasetFilterIndex,
)

IMAGE_EXTENSIONS = {
    ".bmp",
    ".gif",
    ".jpeg",
    ".jpg",
    ".png",
    ".tif",
    ".tiff",
    ".webp",
}


def collect_image_paths(image_dir: str, *, recursive: bool) -> list[str]:
    """Collect supported image paths in stable navigation order.

    Args:
        image_dir: Directory containing the images to benchmark.
        recursive: Whether to include nested directories.

    Returns:
        Absolute image paths sorted case-insensitively.
    """
    root = Path(image_dir)
    iterator = root.rglob("*") if recursive else root.iterdir()
    paths = [
        str(path.resolve())
        for path in iterator
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    ]
    paths.sort(key=str.casefold)
    return paths


def run_benchmark(
    image_files: Sequence[str],
    *,
    output_dir: str | None,
    dataset_root: str,
    repeat: int,
    work_dir: str | None,
    defer_query_indexes: bool,
) -> dict[str, Any]:
    """Run repeated isolated rebuilds and return machine-readable metrics.

    Args:
        image_files: Complete image list used by the application.
        output_dir: Optional directory containing annotation JSON files.
        dataset_root: Dataset identity persisted into the cache metadata.
        repeat: Number of isolated rebuild runs.
        work_dir: Optional parent for temporary SQLite databases.
        defer_query_indexes: Whether to build query indexes after data loading.

    Returns:
        Benchmark configuration, per-run metrics, and median summary.
    """
    runs = []
    for run_number in range(1, repeat + 1):
        with tempfile.TemporaryDirectory(
            prefix="xanylabeling-index-benchmark-",
            dir=work_dir,
        ) as temp_dir:
            db_path = osp.join(temp_dir, "dataset-index.db")
            index = DatasetFilterIndex(
                db_path,
                journal_mode="delete",
                defer_query_indexes=defer_query_indexes,
            )
            try:
                result = index.rebuild(
                    list(image_files),
                    output_dir=output_dir,
                    dataset_root=dataset_root,
                )
                integrity_started = time.perf_counter()
                integrity_valid = index.integrity_check()
                result.performance.integrity_check_seconds = (
                    time.perf_counter() - integrity_started
                )
                foreign_key_started = time.perf_counter()
                foreign_keys_valid = index.foreign_key_check()
                result.performance.foreign_key_check_seconds = (
                    time.perf_counter() - foreign_key_started
                )
                if not integrity_valid or not foreign_keys_valid:
                    raise RuntimeError("Benchmark database validation failed")
            finally:
                index.close()

        elapsed = result.elapsed_seconds
        run_metrics = {
            "run": run_number,
            "files": len(image_files),
            "inserted": result.inserted,
            "failed": result.failed,
            "missing": result.missing,
            "shapes": result.shape_count,
            "elapsed_seconds": elapsed,
            "files_per_second": (
                len(image_files) / elapsed if elapsed > 0 else 0.0
            ),
            "performance": asdict(result.performance),
        }
        runs.append(run_metrics)

    elapsed_values = [run["elapsed_seconds"] for run in runs]
    throughput_values = [run["files_per_second"] for run in runs]
    return {
        "configuration": {
            "dataset_root": dataset_root,
            "output_dir": output_dir,
            "files": len(image_files),
            "repeat": repeat,
            "read_workers": INDEX_READ_WORKERS,
            "prefetch_limit": INDEX_READ_PREFETCH_LIMIT,
            "defer_query_indexes": defer_query_indexes,
        },
        "runs": runs,
        "median": {
            "elapsed_seconds": statistics.median(elapsed_values),
            "files_per_second": statistics.median(throughput_values),
        },
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse benchmark command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Benchmark the X-AnyLabeling SQLite dataset index rebuild.",
    )
    parser.add_argument(
        "--image-dir",
        required=True,
        help="directory containing dataset images",
    )
    parser.add_argument(
        "--output-dir",
        help="optional directory containing annotation JSON files",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="scan image-dir recursively",
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=3,
        help="number of isolated rebuild runs (default: 3)",
    )
    parser.add_argument(
        "--work-dir",
        help="optional parent directory for temporary SQLite databases",
    )
    parser.add_argument(
        "--defer-query-indexes",
        action="store_true",
        help="create query indexes after loading all rows",
    )
    parser.add_argument(
        "--json-output",
        help="optional path for the complete benchmark JSON report",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the benchmark CLI and return its process exit code."""
    args = parse_args(argv)
    if args.repeat < 1:
        raise SystemExit("--repeat must be at least 1")

    image_dir = osp.abspath(args.image_dir)
    output_dir = osp.abspath(args.output_dir) if args.output_dir else None
    image_files = collect_image_paths(
        image_dir,
        recursive=args.recursive,
    )
    if not image_files:
        raise SystemExit(f"No supported images found in {image_dir}")

    report = run_benchmark(
        image_files,
        output_dir=output_dir,
        dataset_root=image_dir,
        repeat=args.repeat,
        work_dir=args.work_dir,
        defer_query_indexes=args.defer_query_indexes,
    )
    rendered = json.dumps(report, indent=2, ensure_ascii=False)
    print(rendered)
    if args.json_output:
        output_path = Path(args.json_output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
