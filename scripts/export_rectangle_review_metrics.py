#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Export local rectangle-review refinement metrics.

The input is the JSONL file written by the opt-in refinement telemetry. The
script emits a row-preserving CSV and a stage-level aggregate CSV. Corrupt or
unknown-schema rows are skipped and reported without aborting valid exports.
"""

from __future__ import annotations

import argparse
import csv
import json
import os.path as osp
import sys
from pathlib import Path
from typing import Any

_PROJECT_ROOT = osp.dirname(osp.dirname(osp.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from anylabeling.views.labeling.review_refinement.metrics import (  # noqa: E402
    aggregate_records,
    read_records,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Export local rectangle review refinement metrics."
    )
    parser.add_argument("--input", required=True, help="input JSONL path")
    parser.add_argument(
        "--output", required=True, help="row-preserving episode CSV path"
    )
    parser.add_argument(
        "--summary-output",
        help="optional stage aggregate CSV path",
    )
    return parser.parse_args(argv)


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    """Write dictionaries to a UTF-8 CSV, creating parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("\n", encoding="utf-8")
        return
    fieldnames = list(rows[0])
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    """Read JSONL metrics and write episode/aggregate CSV files."""
    args = parse_args(argv)
    input_path = Path(args.input)
    if not input_path.is_file():
        print(f"Error: --input not found: {input_path}", file=sys.stderr)
        return 2

    records, skipped = read_records(input_path)
    _write_csv(Path(args.output), records)
    summary_path = (
        Path(args.summary_output)
        if args.summary_output
        else Path(args.output).with_name(
            f"{Path(args.output).stem}_summary.csv"
        )
    )
    _write_csv(summary_path, aggregate_records(records))
    print(
        json.dumps(
            {
                "records": len(records),
                "skipped": skipped,
                "episodes": str(Path(args.output)),
                "summary": str(summary_path),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
