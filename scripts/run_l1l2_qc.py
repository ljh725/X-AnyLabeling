#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage-1 L1/L2 quality checker CLI.

Scans a directory of LabelMe / X-AnyLabeling annotation JSON files, runs
the L1 + L2 rules, and emits the two-file output described in the v0
spec:

    review.tsv   — Inspector-importable issue list (8 columns)
    report.json  — full evidence ledger (metrics, candidates, thresholds)

Usage::

    python scripts/run_l1l2_qc.py \\
        --input  /path/to/json_dir \\
        --output /path/to/out_dir \\
        [--thresholds anylabeling/configs/quality/l1_l2_threshold_profile_v0.yaml] \\
        [--image-dir /path/to/images]

The run is strictly read-only: no JSON is written back.  See
``docs/阶段一L1_L2质检实现任务文档.md`` section G.
"""

from __future__ import annotations

import argparse
import os
import os.path as osp
import sys

# make the anylabeling package importable when run as a bare script
_PROJECT_ROOT = osp.dirname(osp.dirname(osp.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from anylabeling.views.labeling.widgets.inspector.quality import (  # noqa: E402
    load_threshold_profile,
    run_quality_check,
    write_report_json,
    write_review_tsv,
)

try:
    from tqdm import tqdm  # type: ignore
except ModuleNotFoundError:  # optional progress bar

    def tqdm(iterable=None, *args, **kwargs):  # type: ignore
        return iterable


def collect_json_paths(directory: str) -> list[str]:
    """Collect ``*.json`` files from a single-level directory."""
    paths: list[str] = []
    try:
        with os.scandir(directory) as entries:
            for entry in entries:
                try:
                    is_file = entry.is_file(follow_symlinks=False)
                except OSError:
                    continue
                if is_file and entry.name.lower().endswith(".json"):
                    paths.append(osp.abspath(entry.path))
    except OSError as exc:
        print(f"Error: failed to scan {directory}: {exc}", file=sys.stderr)
        sys.exit(1)
    paths.sort()
    return paths


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Stage-1 L1/L2 quality checker (review.tsv + report.json)",
    )
    parser.add_argument(
        "--input",
        required=True,
        help="directory containing annotation JSON files",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="output directory for review.tsv and report.json",
    )
    parser.add_argument(
        "--thresholds",
        default=None,
        help="path to threshold profile YAML (default: bundled v0 profile)",
    )
    parser.add_argument(
        "--image-dir",
        default=None,
        help="optional image directory (recorded in report source only)",
    )
    parser.add_argument(
        "--no-progress",
        action="store_true",
        help="disable the progress bar",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if not osp.isdir(args.input):
        print(f"Error: input not a directory: {args.input}", file=sys.stderr)
        return 2

    json_paths = collect_json_paths(args.input)
    if not json_paths:
        print(f"No JSON files found in {args.input}", file=sys.stderr)
        return 2

    os.makedirs(args.output, exist_ok=True)

    profile = load_threshold_profile(args.thresholds)
    print(
        f"Loaded threshold profile: {profile.profile_id} "
        f"({len(profile.enabled_rules())} enabled rules)"
    )
    print(f"Scanning {len(json_paths)} JSON files...")

    progress = None
    if not args.no_progress:
        progress = _ProgressAdapter(tqdm(total=len(json_paths)))

    report = run_quality_check(
        json_paths=json_paths,
        profile=profile,
        input_root=osp.abspath(args.input),
        image_dir=args.image_dir,
        progress_callback=progress.callback if progress else None,
    )
    if progress:
        progress.close()

    review_path = osp.join(args.output, "review.tsv")
    report_path = osp.join(args.output, "report.json")
    write_review_tsv(report, review_path)
    write_report_json(report, report_path)

    print()
    print("=" * 60)
    print(f"run_id            : {report.run_id}")
    print(f"files / shapes    : {report.total_files} / {report.total_shapes}")
    print(
        f"issues (e/w/i)    : {report.error_count} / "
        f"{report.warning_count} / {report.info_count}"
    )
    print(f"review.tsv        : {review_path}")
    print(f"report.json       : {report_path}")
    print("=" * 60)
    return 0


class _ProgressAdapter:
    """Wrap tqdm so the report_writer callback can update it."""

    def __init__(self, bar) -> None:
        self.bar = bar

    def callback(self, current: int, total: int, filename: str) -> None:
        if self.bar is not None:
            self.bar.update(1)

    def close(self) -> None:
        if self.bar is not None:
            self.bar.close()


if __name__ == "__main__":
    sys.exit(main())
