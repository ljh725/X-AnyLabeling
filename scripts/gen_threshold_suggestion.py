#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate ``threshold_suggestion.json`` from a report + feedback.

Reads a previously-produced ``report.json`` and a human-reviewed
``review_feedback.tsv``, aggregates review decisions per rule, and emits
a NON-binding ``threshold_suggestion.json``.  The suggestion file is
always ``approval.status = pending`` — it never modifies the threshold
YAML automatically.

Usage::

    python scripts/gen_threshold_suggestion.py \\
        --report   /path/to/report.json \\
        --feedback /path/to/review_feedback.tsv \\
        --output   /path/to/threshold_suggestion.json \\
        [--base-profile v0_default] \\
        [--target-profile v1_after_review]

See ``docs/阶段一L1_L2质检规则阈值与输出规格_v0.md`` section 9.
"""

from __future__ import annotations

import argparse
import os.path as osp
import sys

_PROJECT_ROOT = osp.dirname(osp.dirname(osp.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from anylabeling.views.labeling.widgets.inspector.quality import (  # noqa: E402
    SuggestionContext,
    generate_threshold_suggestion,
)
from anylabeling.views.labeling.widgets.inspector.quality.feedback import (  # noqa: E402
    read_review_feedback,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate threshold_suggestion.json from report + feedback "
            "(non-binding, pending human approval)"
        ),
    )
    parser.add_argument(
        "--report",
        required=True,
        help="path to report.json produced by run_l1l2_qc.py",
    )
    parser.add_argument(
        "--feedback",
        required=True,
        help="path to review_feedback.tsv",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="output path for threshold_suggestion.json",
    )
    parser.add_argument(
        "--base-profile",
        default="v0_default",
        help="base threshold profile name (default: v0_default)",
    )
    parser.add_argument(
        "--target-profile",
        default="v1_after_review",
        help="target threshold profile name (default: v1_after_review)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    for required, label in (
        (args.report, "--report"),
        (args.feedback, "--feedback"),
    ):
        if not osp.isfile(required):
            print(f"Error: {label} not found: {required}", file=sys.stderr)
            return 2

    # validate feedback up front so we surface enum errors early
    fb = read_review_feedback(args.feedback, strict=False)
    if fb.errors:
        print("Feedback warnings/errors:", file=sys.stderr)
        for e in fb.errors:
            print(f"  - {e}", file=sys.stderr)
    print(f"Read {len(fb.rows)} feedback rows.")

    ctx = SuggestionContext(
        report_path=args.report,
        feedback_path=args.feedback,
        base_threshold_profile=args.base_profile,
        target_threshold_profile=args.target_profile,
    )
    out = generate_threshold_suggestion(ctx, args.output)

    print()
    print("=" * 60)
    print(f"threshold_suggestion.json : {out}")
    print("approval.status           : pending (NOT auto-applied)")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
