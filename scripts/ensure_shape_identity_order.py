#!/usr/bin/env python3
"""Assign Shape IDs and place the identity field first in project JSON.

This migration changes only ``xanylabeling_shape_id``: missing or conflicting
IDs are repaired and the key is moved to position zero.  It does not add any
other default Shape fields or alter geometry values.
"""

from __future__ import annotations

import argparse
import os.path as osp
import sys

_PROJECT_ROOT = osp.dirname(osp.dirname(osp.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from anylabeling.views.labeling.shape_identity_project import (  # noqa: E402
    discover_project_json_files,
    ensure_project_shape_ids,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse the project path supplied on the command line."""
    parser = argparse.ArgumentParser(
        description=(
            "Assign xanylabeling_shape_id and move it to the first key of "
            "every Shape without completing other fields."
        )
    )
    parser.add_argument(
        "--input",
        required=True,
        help="annotation JSON file or project directory to scan recursively",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run the identity-only project migration."""
    args = parse_args(argv)
    input_path = osp.abspath(osp.normpath(args.input))
    if not osp.exists(input_path):
        print(f"Input path does not exist: {input_path}", file=sys.stderr)
        return 2

    json_paths = discover_project_json_files([input_path])
    result = ensure_project_shape_ids(json_paths)
    print(
        "Shape identity migration complete: "
        f"{result.files_scanned} files scanned, "
        f"{result.files_changed} files changed, "
        f"{result.shapes_assigned} IDs assigned, "
        f"{result.files_failed} files failed."
    )
    for file_result in result.file_results:
        if file_result.error:
            print(
                f"FAILED {file_result.path}: {file_result.error}",
                file=sys.stderr,
            )
    return 1 if result.files_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
