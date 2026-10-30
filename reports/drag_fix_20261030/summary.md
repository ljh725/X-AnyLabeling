# CUSTOM-003 benchmark comparison

fixed: 2026-10-30 09:09:32 | baseline: 2026-10-30 09:11:30 | Qt 6.10.0 / PyQt 6.10.2 | window [2560, 1377] | files 11792 | shapes 54 | moves 100 | rounds 2

## Background conditions (median / P95 of 100 moves per sample)

| condition | fixed median | fixed P95 | baseline median | baseline P95 | median change | paints fixed/baseline | list reads fixed/baseline |
|---|---:|---:|---:|---:|---:|---:|---:|
| none | 10.38 / 10.86 | 11.61 / 15.29 | 42.34 / 42.14 | 44.00 / 44.44 | 75.5% / 74.2% | 100/200 / 100/200 | 0/200 / 0/200 |
| exif | 10.83 / 11.03 | 13.68 / 14.76 | 43.16 / 44.26 | 46.84 / 50.69 | 74.9% / 75.1% | 100/200 / 100/200 | 0/200 / 0/200 |
| metadata | 11.09 / 12.20 | 17.12 / 20.91 | 43.31 / 42.84 | 49.87 / 48.59 | 74.4% / 71.5% | 100/200 / 100/200 | 0/200 / 0/200 |
| both | 11.86 / 14.37 | 19.36 / 24.59 | 43.94 / 43.71 | 54.38 / 52.38 | 73.0% / 67.1% | 100/200 / 100/200 | 0/200 / 0/200 |

## List size sweep (same image, same 54 objects)

| list size | fixed median | fixed P95 | baseline median | baseline P95 |
|---:|---:|---:|---:|---:|
| 1 | 10.66 | 13.38 | 20.92 | 24.83 |
| 1000 | 10.92 | 16.36 | 22.58 | 26.30 |
| 11792 | 10.74 | 13.00 | 47.21 | 54.86 |

Fixed median spread across list sizes: 0.27 ms (target <= 3 ms)

## Acceptance

- none_median_le_15: PASS
- none_p95_le_25: PASS
- none_improvement_ge_60: PASS
- review_median_le_25: PASS
- review_p95_le_40: PASS
- size_spread_le_3: PASS
- no_full_list_reads: PASS
