"""Build the CUSTOM-003 comparison table from two benchmark runs.

usage: summarize.py [fixed.json baseline.json prefix]
The frozen-config re-run uses: summarize.py results_fixed_r2.json results_baseline_r2.json summary_r2
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
fixed_name = sys.argv[1] if len(sys.argv) > 1 else "results_fixed.json"
baseline_name = sys.argv[2] if len(sys.argv) > 2 else "results_baseline.json"
prefix = sys.argv[3] if len(sys.argv) > 3 else "summary"
fixed = json.loads((HERE / fixed_name).read_text(encoding="utf-8"))
baseline = json.loads((HERE / baseline_name).read_text(encoding="utf-8"))

CONDITIONS = ["none", "exif", "metadata", "both"]


def group(report, key):
    rows = {}
    for case in report["cases"]:
        rows.setdefault(case[key], []).append(case)
    return rows


fixed_cases = group(fixed, "background")
base_cases = group(baseline, "background")

lines = []
lines.append("# CUSTOM-003 benchmark comparison\n")
lines.append(
    f"fixed: {fixed['date']} | baseline: {baseline['date']} | "
    f"config snapshot: {fixed.get('config_snapshot_sha256', 'n/a')[:16]} | "
    f"Qt {fixed['qt']} / PyQt {fixed['pyqt']} | window {fixed['window']} | "
    f"files {fixed['files']} | shapes {fixed['shapes']} | moves {fixed['moves']} | rounds {fixed['rounds']}\n"
)
lines.append("## Background conditions (median / P95 of 100 moves per sample)\n")
lines.append(
    "| condition | fixed median | fixed P95 | baseline median | baseline P95 | median change | paints fixed/baseline | list reads fixed/baseline |"
)
lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")

verdict = {}
for condition in CONDITIONS:
    fixed_rows = fixed_cases[condition]
    base_rows = base_cases[condition]
    f_med = [row["cycle"]["median_ms"] for row in fixed_rows]
    f_p95 = [row["cycle"]["p95_ms"] for row in fixed_rows]
    b_med = [row["cycle"]["median_ms"] for row in base_rows]
    b_p95 = [row["cycle"]["p95_ms"] for row in base_rows]
    change = [round((b - f) / b * 100, 1) for f, b in zip(f_med, b_med)]
    paints = [
        f"{row['paints']}/{base_rows[i]['paints']}"
        for i, row in enumerate(fixed_rows)
    ]
    reads = [
        f"{row['image_list_reads']}/{base_rows[i]['image_list_reads']}"
        for i, row in enumerate(fixed_rows)
    ]
    lines.append(
        f"| {condition} | {' / '.join(f'{v:.2f}' for v in f_med)} | "
        f"{' / '.join(f'{v:.2f}' for v in f_p95)} | "
        f"{' / '.join(f'{v:.2f}' for v in b_med)} | "
        f"{' / '.join(f'{v:.2f}' for v in b_p95)} | "
        f"{' / '.join(f'{v:.1f}%' for v in change)} | "
        f"{' / '.join(paints)} | {' / '.join(reads)} |"
    )
    verdict[condition] = {
        "fixed_median_ms": f_med,
        "fixed_p95_ms": f_p95,
        "baseline_median_ms": b_med,
        "baseline_p95_ms": b_p95,
        "improvement_pct": change,
    }

lines.append("\n## List size sweep (same image, same 54 objects)\n")
lines.append("| list size | fixed median | fixed P95 | baseline median | baseline P95 |")
lines.append("|---:|---:|---:|---:|---:|")
for fixed_row, base_row in zip(fixed["list_size_cases"], baseline["list_size_cases"]):
    lines.append(
        f"| {fixed_row['list_size']} | {fixed_row['cycle']['median_ms']:.2f} | "
        f"{fixed_row['cycle']['p95_ms']:.2f} | {base_row['cycle']['median_ms']:.2f} | "
        f"{base_row['cycle']['p95_ms']:.2f} |"
    )

fixed_sizes = {row["list_size"]: row["cycle"]["median_ms"] for row in fixed["list_size_cases"]}
spread = max(fixed_sizes.values()) - min(fixed_sizes.values())
lines.append(f"\nFixed median spread across list sizes: {spread:.2f} ms (target <= 3 ms)\n")

thresholds = {
    "none_median_le_15": all(v <= 15 for v in verdict["none"]["fixed_median_ms"]),
    "none_p95_le_25": all(v <= 25 for v in verdict["none"]["fixed_p95_ms"]),
    "none_improvement_ge_60": all(v >= 60 for v in verdict["none"]["improvement_pct"]),
    "review_median_le_25": all(
        v <= 25
        for key in ("metadata", "both")
        for v in verdict[key]["fixed_median_ms"]
    ),
    "review_p95_le_40": all(
        v <= 40
        for key in ("metadata", "both")
        for v in verdict[key]["fixed_p95_ms"]
    ),
    "size_spread_le_3": spread <= 3,
    "no_full_list_reads": all(
        case["image_list_reads"] == 0
        for case in fixed["cases"] + fixed["list_size_cases"]
    ),
}
lines.append("## Acceptance\n")
for name, passed in thresholds.items():
    lines.append(f"- {name}: {'PASS' if passed else 'FAIL'}")

(HERE / f"{prefix}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
(HERE / f"{prefix}.json").write_text(
    json.dumps({"verdict": verdict, "thresholds": thresholds, "size_spread_ms": spread}, indent=2),
    encoding="utf-8",
)
print("\n".join(lines))
