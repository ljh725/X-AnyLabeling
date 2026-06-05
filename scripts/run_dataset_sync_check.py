#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Run dataset inventory and comparison as one synchronization workflow."""

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

from compare_dataset_inventory import compare_inventory
from inventory_dataset_files import build_inventory, parse_source, write_tsv


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(
        description=(
            "Run the full dataset sync check: inventory first, then compare."
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
        "--output-dir",
        default="docs/dataset_sync_reports",
        help="Directory for the inventory and comparison reports.",
    )
    parser.add_argument(
        "--baseline",
        help="Dataset name used as the baseline for cross-dataset comparison.",
    )
    parser.add_argument(
        "--stem-kind",
        choices=["any", "image", "json", "both"],
        default="any",
        help="Which stems to compare across datasets.",
    )
    parser.add_argument(
        "--hash",
        action="store_true",
        help="Calculate SHA1 for every file during inventory.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run the full dataset synchronization check."""
    parser = build_parser()
    args = parser.parse_args(argv)
    output_dir = Path(args.output_dir).expanduser().resolve()
    inventory_path = output_dir / "dataset_inventory.tsv"

    try:
        rows = build_inventory(args.source, args.hash)
        write_tsv(inventory_path, rows)
        compare_inventory(
            inventory_path,
            output_dir,
            baseline=args.baseline,
            stem_kind=args.stem_kind,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Full sync check finished. Inventory: {inventory_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
