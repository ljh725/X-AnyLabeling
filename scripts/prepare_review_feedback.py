#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Prepare a semi-automatic ``review_feedback.tsv`` from ``report.json``.

The output table pre-fills issue metadata and review context. Reviewers only
need to fill:

    decision
    final_action
    note

If ``--existing-feedback`` is provided, previously reviewed decisions are
preserved by ``issue_id``.
"""

from __future__ import annotations

import argparse
import os.path as osp
import sys

_PROJECT_ROOT = osp.dirname(osp.dirname(osp.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from anylabeling.views.labeling.widgets.inspector.quality import (  # noqa: E402
    write_review_feedback_template,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Create or refresh review_feedback.tsv from report.json. "
            "Existing decisions can be preserved by issue_id."
        ),
    )
    parser.add_argument(
        "--report",
        required=True,
        help="path to report.json produced by run_l1l2_qc.py",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="output path for review_feedback.tsv",
    )
    parser.add_argument(
        "--existing-feedback",
        default=None,
        help="optional existing review_feedback.tsv to merge/preserve",
    )
    parser.add_argument(
        "--reviewer",
        default="",
        help="optional reviewer name prefilled for blank rows",
    )
    parser.add_argument(
        "--reviewed-at",
        default="",
        help="optional reviewed_at value prefilled for blank rows",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run the feedback-template generator."""
    args = parse_args(argv)
    if not osp.isfile(args.report):
        print(f"Error: --report not found: {args.report}", file=sys.stderr)
        return 2
    if args.existing_feedback and not osp.isfile(args.existing_feedback):
        print(
            f"Error: --existing-feedback not found: {args.existing_feedback}",
            file=sys.stderr,
        )
        return 2

    result = write_review_feedback_template(
        report_path=args.report,
        output_path=args.output,
        existing_feedback_path=args.existing_feedback,
        reviewer=args.reviewer,
        reviewed_at=args.reviewed_at,
    )

    print()
    print("=" * 60)
    print(f"review_feedback.tsv : {result.output_path}")
    print(f"total rows          : {result.total_rows}")
    print(f"preserved rows      : {result.preserved_rows}")
    print(f"blank decision rows : {result.blank_rows}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
