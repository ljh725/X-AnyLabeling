"""Generate deterministic local behavior analytics benchmark fixtures."""

from __future__ import annotations

import argparse
from pathlib import Path

from anylabeling.services.behavior_analytics import write_fixture


def main() -> int:
    """Write the requested benchmark fixture and return a process status."""
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--count",
        type=int,
        required=True,
        choices=(1_000, 100_000, 1_000_000),
    )
    parser.add_argument("--sessions", type=int, default=4)
    args = parser.parse_args()
    write_fixture(args.output, args.count, sessions=args.sessions)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
