"""Report three-box grouping coverage on captured real annotation samples."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from anylabeling.views.labeling.rect_refine_grouping import infer  # noqa: E402
from anylabeling.views.labeling.rect_refine_types import (  # noqa: E402
    ShapeRefineView,
)

LEGACY_SCORING_BASELINE = {
    "anchors": 45,
    "associations": 61,
    "expected_hits": 36,
    "expected_total": 46,
    "expected_recall": 36 / 46,
}


def _build_views(
    sample: Dict[str, Any],
) -> Tuple[List[ShapeRefineView], Dict[Tuple[str, int], str]]:
    """Convert one captured sample into immutable grouping views."""
    views = []
    names = {}
    token = sample["name"]
    for index, raw in enumerate(sample["shapes"]):
        (x1, y1), (x2, y2) = raw["points"]
        shape_id = (token, index)
        names[shape_id] = raw["id"]
        views.append(
            ShapeRefineView(
                shape_id=shape_id,
                shape_index=index,
                label=raw["label"],
                bbox=(x1, y1, x2, y2),
            )
        )
    return views, names


def compare_samples(samples: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Return candidate counts and expected-link directional recall."""
    report: Dict[str, Any] = {"samples": []}
    total_hits = 0
    total_expected = 0
    total_associations = 0
    total_anchors = 0
    total_unfiltered_members = 0
    maximum_members = 0

    for sample in samples:
        views, names = _build_views(sample)
        outcomes = {}
        for anchor in views:
            result = infer(anchor, views)
            outcomes[names[anchor.shape_id]] = {
                names[member.shape_id] for member in result.members
            }

        expected = 0
        hits = 0
        missing = []
        for left, right in sample["expected_links"]:
            for anchor_name, target_name in ((left, right), (right, left)):
                expected += 1
                if target_name in outcomes[anchor_name]:
                    hits += 1
                else:
                    missing.append([anchor_name, target_name])

        associations = sum(len(members) - 1 for members in outcomes.values())
        maximum_members = max(
            maximum_members,
            max((len(members) for members in outcomes.values()), default=0),
        )
        total_hits += hits
        total_expected += expected
        total_associations += associations
        total_anchors += len(views)
        total_unfiltered_members += len(views) * len(views)
        report["samples"].append(
            {
                "name": sample["name"],
                "anchors": len(views),
                "associations": associations,
                "expected_hits": hits,
                "expected_total": expected,
                "missing": missing,
            }
        )

    report["summary"] = {
        "anchors": total_anchors,
        "associations": total_associations,
        "average_members_per_anchor": (
            (total_associations + total_anchors) / total_anchors
            if total_anchors
            else 0.0
        ),
        "maximum_members": maximum_members,
        "visibility_reduction": (
            1.0
            - (total_associations + total_anchors) / total_unfiltered_members
            if total_unfiltered_members
            else 0.0
        ),
        "expected_hits": total_hits,
        "expected_total": total_expected,
        "expected_recall": (
            total_hits / total_expected if total_expected else 1.0
        ),
    }
    report["legacy_scoring_baseline"] = dict(LEGACY_SCORING_BASELINE)
    report["comparison"] = {
        "association_delta": (
            total_associations - LEGACY_SCORING_BASELINE["associations"]
        ),
        "expected_hit_delta": (
            total_hits - LEGACY_SCORING_BASELINE["expected_hits"]
        ),
        "expected_recall_delta": (
            report["summary"]["expected_recall"]
            - LEGACY_SCORING_BASELINE["expected_recall"]
        ),
    }
    return report


def main() -> None:
    """Load the fixture and print a machine-readable comparison report."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "fixture",
        nargs="?",
        type=Path,
        default=Path("tests/fixtures/rect_refine_real_samples.json"),
    )
    args = parser.parse_args()
    samples = json.loads(args.fixture.read_text(encoding="utf-8"))
    print(json.dumps(compare_samples(samples), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
