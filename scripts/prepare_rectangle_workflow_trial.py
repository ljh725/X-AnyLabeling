"""Prepare a read-only dataset inventory and a pending human rectangle trial."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

CONDITIONS = (
    ("create", "two_points"),
    ("create", "four_extremes"),
    ("refine", "edge_drag"),
    ("refine", "edge_nudge"),
    ("refine", "edge_nudge_object_zoom"),
)


def inventory(images: Path, labels: Path) -> tuple[list[dict], dict]:
    """Read annotation geometry and resolve images without writing sources."""
    records: list[dict] = []
    counts: Counter = Counter()
    label_counts: Counter = Counter()
    for path in sorted(labels.glob("*.json")):
        counts["json_files"] += 1
        try:
            raw = path.read_bytes()
            data = json.loads(raw.decode("utf-8-sig"))
        except (OSError, ValueError):
            counts["unreadable_json"] += 1
            continue
        image = images / Path(str(data.get("imagePath", ""))).name
        if not image.is_file():
            candidates = [
                images / (path.stem + ext)
                for ext in (".jpg", ".png", ".jpeg", ".bmp")
            ]
            image = next((p for p in candidates if p.is_file()), image)
        if not image.is_file():
            counts["missing_images"] += 1
            continue
        digest = hashlib.sha256(raw).hexdigest()
        width, height = data.get("imageWidth", 0), data.get("imageHeight", 0)
        for index, shape in enumerate(data.get("shapes", [])):
            if shape.get("shape_type") != "rectangle":
                counts["other_shapes"] += 1
                continue
            try:
                points = shape["points"]
                xs = [float(p[0]) for p in points]
                ys = [float(p[1]) for p in points]
                bbox = (min(xs), min(ys), max(xs), max(ys))
                left, top, right, bottom = bbox
                valid = (
                    len(points) in (2, 4)
                    and all(math.isfinite(v) for v in bbox)
                    and 0 <= left < right <= width - 1
                    and 0 <= top < bottom <= height - 1
                    and min(right - left, bottom - top) >= 1
                )
            except (KeyError, ValueError, TypeError, IndexError):
                valid = False
            if not valid:
                counts["invalid_rectangles"] += 1
                continue
            short_side = min(right - left, bottom - top)
            size = (
                "small"
                if short_side < 100
                else ("medium" if short_side < 200 else "large")
            )
            label = str(shape.get("label", ""))
            counts["valid_rectangles"] += 1
            counts["size_" + size] += 1
            label_counts[label] += 1
            records.append(
                {
                    "image_path": str(image.resolve()),
                    "json_path": str(path.resolve()),
                    "json_sha256": digest,
                    "shape_index": index,
                    "shape_id": shape.get("xanylabeling_shape_id", ""),
                    "label": label,
                    "size_class": size,
                    "baseline_bbox": json.dumps(bbox),
                }
            )
    return records, {"counts": dict(counts), "labels": dict(label_counts)}


def prepare_trial(
    images: Path, labels: Path, output: Path, per_condition: int = 30
) -> dict[str, Any]:
    """Write a deterministic pending trial with distinct source images."""
    output = output.resolve()
    if output == images.resolve() or output == labels.resolve():
        raise ValueError("Output must be separate from source directories")
    if output.is_relative_to(images.resolve()) or output.is_relative_to(
        labels.resolve()
    ):
        raise ValueError("Output cannot be inside the source dataset")
    output.mkdir(parents=True, exist_ok=True)
    manifest = output / "trial.tsv"
    if manifest.exists():
        raise FileExistsError("Refusing to replace an existing trial")
    records, report = inventory(images, labels)
    rng = random.Random(20260908)
    pools: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        pools[record["size_class"]].append(record)
    for pool in pools.values():
        rng.shuffle(pool)
    rows: list[dict] = []
    used_images: set[str] = set()
    for repetition in range(per_condition):
        order = list(CONDITIONS)
        rng.shuffle(order)
        preferred = ("small", "medium", "large")[repetition % 3]
        for task, condition in order:
            chosen = None
            for size in (preferred, "small", "medium", "large"):
                pool = pools[size]
                while pool and pool[-1]["image_path"] in used_images:
                    pool.pop()
                if pool:
                    chosen = pool.pop()
                    break
            if chosen is None:
                continue
            used_images.add(chosen["image_path"])
            rows.append(
                {
                    "trial_id": len(rows) + 1,
                    "task": task,
                    "condition": condition,
                    **chosen,
                    "visual_condition": "",
                    "boundary_policy": "",
                    "tolerance_px": "",
                    "initial_bbox": "",
                    "final_bbox": "",
                    "elapsed_seconds": "",
                    "rework_count": "",
                    "wrong_edge_count": "",
                    "fatigue_1_to_5": "",
                    "independent_quality_pass": "",
                    "status": "pending",
                    "notes": "",
                }
            )
    if rows:
        with manifest.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(
                stream, fieldnames=list(rows[0]), delimiter="\t"
            )
            writer.writeheader()
            writer.writerows(rows)
    report.update(
        image_directory=str(images.resolve()),
        label_directory=str(labels.resolve()),
        trial_count=len(rows),
        per_condition=dict(Counter(r["condition"] for r in rows)),
        boundary_policy="pending_user_confirmation",
        tolerance_px=None,
        human_trial_status="pending",
        source_annotations_modified=False,
        note="Existing annotations are comparison references, not adjudicated truth.",
    )
    (output / "dataset_summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> None:
    """Parse the inventory and output paths and report pending trial counts."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--images", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = prepare_trial(args.images, args.labels, args.output)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
