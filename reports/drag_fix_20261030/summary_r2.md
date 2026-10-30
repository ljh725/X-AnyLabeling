# CUSTOM-003 benchmark comparison

fixed: 2026-10-30 10:00:28 | baseline: 2026-10-30 10:01:39 | config snapshot: facd7cfe7dce50bc | Qt 6.10.0 / PyQt 6.10.2 | window [2560, 1377] | files 11792 | shapes 54 | moves 100 | rounds 2

## Background conditions (median / P95 of 100 moves per sample)

| condition | fixed median | fixed P95 | baseline median | baseline P95 | median change | paints fixed/baseline | list reads fixed/baseline |
|---|---:|---:|---:|---:|---:|---:|---:|
| none | 11.27 / 11.27 | 13.83 / 14.31 | 44.53 / 44.56 | 55.39 / 56.23 | 74.7% / 74.7% | 100/200 / 100/200 | 0/200 / 0/200 |
| exif | 11.32 / 13.16 | 17.04 / 17.46 | 43.87 / 48.46 | 58.49 / 60.76 | 74.2% / 72.8% | 100/200 / 100/200 | 0/200 / 0/200 |
| metadata | 12.07 / 11.82 | 19.76 / 21.16 | 48.07 / 45.60 | 60.55 / 61.24 | 74.9% / 74.1% | 100/200 / 100/200 | 0/200 / 0/200 |
| both | 14.14 / 14.20 | 21.05 / 21.50 | 48.15 / 49.35 | 58.64 / 59.70 | 70.6% / 71.2% | 100/200 / 100/200 | 0/200 / 0/200 |

## List size sweep (same image, same 54 objects)

| list size | fixed median | fixed P95 | baseline median | baseline P95 |
|---:|---:|---:|---:|---:|
| 1 | 11.87 | 14.29 | 21.57 | 25.64 |
| 1000 | 9.92 | 11.94 | 23.15 | 29.18 |
| 11792 | 10.04 | 13.78 | 51.22 | 58.45 |

Fixed median spread across list sizes: 1.95 ms (target <= 3 ms)

## Acceptance

- none_median_le_15: PASS
- none_p95_le_25: PASS
- none_improvement_ge_60: PASS
- review_median_le_25: PASS
- review_p95_le_40: PASS
- size_spread_le_3: PASS
- no_full_list_reads: PASS
