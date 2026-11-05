# Dense-review workspace performance, 2026-11-03

> **修复前基线 / PRE-FIX BASELINE.** Every number below was measured
> before the follow-up fix described at the end of this file.  It is
> the comparison baseline for that fix, not a post-fix result.  No
> further benchmark was run after the fix was proposed; post-fix
> validation is owned by the parent session.

Scope: OpenSpec change `add-dense-annotation-review-workflow`,
tasks 10.1-10.3.  This is a harness measurement, not a release
claim.  No production code was changed to influence the numbers.

## Verdict

| Item | Result |
| --- | --- |
| 10.1 cold/warm GUI comparison | measured for 30 and 300 objects, 3 repetitions, including drags with card work active |
| 10.2 warm switch p95 <= 150 ms | PASS both sizes |
| 10.2 GUI heartbeat p95 <= 50 ms | PASS both sizes |
| 10.2 drag p95 regression <= 10 % (workspace open, no extra load) | PASS both sizes |
| 10.2 drag p95 regression <= 10 % (cards generating) | **FAIL at 30 objects (2/2 runs); PASS at 300 objects but fragile** |
| 10.3 bounded card cache | PASS: peak 30 of 64 entries (30 objects); peak 64 of 64 (300 objects), plateau, no linear growth |
| 10.3 no per-move re-crop / fingerprint | PASS: one request pass per drag release, 0 fingerprint calls during drag |

Task 10.2 is **not fully met**: the 30-object background drag repeats
at +36.0 % and +23.0 % over baseline.  The 300-object p95 passes
(+7.1 %), but its p50 regression is +19.4 %, so "no regression while
cards generate" is not established at either size.

## Environment

| Fact | Value |
| --- | --- |
| Python | 3.12.12 (CPython, MSC v.1929 64 bit) |
| PyQt6 | 6.10.2 |
| Qt | 6.10.0 |
| Platform | Windows-10-10.0.19041-SP0, AMD64 |
| Processor | Intel64 Family 6 Model 165 Stepping 3, GenuineIntel |
| CPUs | 12 logical |
| QPA | offscreen (`QT_QPA_PLATFORM=offscreen`) |
| Window | 1600x1000, workspace 1280x860 |
| Thumbnail request | 360x240 target, 35 % context, LRU limit 64 |
| Fixture 30 | 1400x1000 PNG, 30 rectangles, 6 classes, 22,512 bytes |
| Fixture 300 | 2400x1800 PNG, 300 rectangles, 6 classes, 116,688 bytes |

All fixtures are synthesized deterministically (seed 11) in a throw-away
directory below `.tmp`; the config and QSettings are redirected there.

## Method

* A real `MainWindow`/`LabelingWidget` is created offscreen and the
  dense-review workspace is opened, copying the fixture pattern from
  `tests/test_dense_review/test_workspace.py`.
* Each condition gets `--samples 30` per repetition and 3 repetitions,
  i.e. 90 samples.  A condition is one navigation, one timer tick or
  one synthetic mouse-move frame.
* Cold switch: the whole `ThumbnailProvider` generation is reset
  (`start_generation`, empty LRU, cleared per-shape maps) before every
  sample.  Warm switch: the target cards are warmed through the
  production navigation path and the LRU is reused.
* Object switch uses `workspace._navigate_to` within the visible batch
  (the card-rebuild path used by "complete and next").
  Batch switch uses `batch_list.setCurrentRow` (the user-visible list
  click).  Cold/warm batch numbers are close because the list-click
  path rebuilds cards with placeholders but does not schedule
  `_request_visible_thumbnails`, so cached icons are not re-applied.
* Heartbeat: a precise 16 ms `QTimer` records event-loop overshoot.
  The "cards" condition keeps direct background crop requests flowing
  while the timer runs.
* Drag: press on the focused box, 5 synthetic moves of 1 screen pixel,
  release.  Each move plus one event-loop turn is one sample.  The
  workspace-open condition uses display mode `all` so the canvas paints
  the same shapes as the closed baseline.  The background condition
  requests one batch of card crops (or three rounds of all objects for
  the small fixture) immediately before the drag.
* Raw reports contain every sample, per-repeat summaries, cache traces
  and environment facts.

## Latency results (ms, p50 / p95 over 90 samples)

### 30 objects, run A (`bench-30-objects.json`)

| Condition | p50 | p95 |
| --- | ---: | ---: |
| object switch cold | 28.265 | 42.835 |
| object switch warm | 19.856 | 24.943 |
| batch switch cold | 17.999 | 22.518 |
| batch switch warm | 18.789 | 26.997 |
| heartbeat idle | 0.094 | 2.114 |
| heartbeat with card generation | 0.000 | 3.886 |
| drag baseline (workspace closed) | 5.414 | 8.813 |
| drag workspace open (`all`) | 5.661 | 8.067 |
| drag workspace open (`focus`) | 3.503 | 5.414 |
| drag open + background crops | 7.974 | 11.990 |
| card text refresh | 1.097 | 2.203 |

### 30 objects, run B repeat (`bench-30-objects-rerun.json`)

| Condition | p50 | p95 |
| --- | ---: | ---: |
| object switch cold | 23.302 | 28.992 |
| object switch warm | 16.193 | 25.500 |
| batch switch cold | 15.019 | 21.603 |
| batch switch warm | 14.678 | 17.870 |
| heartbeat idle | 0.000 | 1.899 |
| heartbeat with card generation | 0.000 | 2.768 |
| drag baseline (workspace closed) | 3.819 | 4.949 |
| drag workspace open (`all`) | 3.956 | 4.938 |
| drag workspace open (`focus`) | 2.846 | 3.878 |
| drag open + background crops | 4.860 | 6.089 |
| card text refresh | 1.770 | 2.113 |

### 300 objects (`bench-300-objects.json`)

| Condition | p50 | p95 |
| --- | ---: | ---: |
| object switch cold | 57.388 | 87.238 |
| object switch warm | 36.129 | 56.076 |
| batch switch cold | 39.503 | 60.883 |
| batch switch warm | 34.483 | 48.517 |
| heartbeat idle | 0.000 | 1.959 |
| heartbeat with card generation | 0.016 | 5.939 |
| drag baseline (workspace closed) | 25.449 | 40.846 |
| drag workspace open (`all`) | 25.618 | 33.471 |
| drag workspace open (`focus`) | 11.925 | 15.986 |
| drag open + background crops | 30.373 | 43.754 |
| card text refresh | 2.868 | 5.016 |

Per-repeat p95 spread is in each JSON under `per_repeat`.  The warm
cache reduces object-switch p95 by 41.8 % (30 A), 12.0 % (30 B) and
35.7 % (300); batch-switch p95 by 19.9 %, 17.3 % and 20.3 %
respectively.  `focus` display mode is faster than baseline because it
hides non-selected shapes; it is reported for context, not thresholded.

## Threshold checks

| Check | 30 run A | 30 run B | 300 | Limit |
| --- | --- | --- | --- | --- |
| warm object switch p95 | 24.943 PASS | 25.500 PASS | 56.076 PASS | 150 ms |
| warm batch switch p95 | 26.997 PASS | 17.870 PASS | 48.517 PASS | 150 ms |
| heartbeat cards p95 | 3.886 PASS | 2.768 PASS | 5.939 PASS | 50 ms |
| drag open p95 regression | -8.465 % PASS | -0.222 % PASS | -18.056 % PASS | <= 10 % |
| drag background p95 regression | **+36.049 % FAIL** | **+23.035 % FAIL** | +7.119 % PASS | <= 10 % |
| drag background p50 regression (diagnostic) | +47.3 % | +27.3 % | +19.4 % | not a threshold |

The 30-object background failure repeats in two independent runs with
the same code and fixture.  The absolute deltas are small (3.18 ms in
run A, 1.14 ms in run B) because the 30-object, 1400x1000 fixture has a
cheap baseline frame (4.9-8.8 ms p95).  A fixed GUI-side cost therefore
becomes a large percentage, while the 300-object baseline frame is
already 25-40 ms.

### Cause of the background drag regression

* `ThumbnailProvider._drain()` runs on the GUI thread on a 30 ms timer.
  It calls `QImage.loadFromData` for each completed PNG, and
  `_on_thumbnail_ready` creates `QPixmap.fromImage`, sets the card icon
  and text and calls `_update_action_labels()` for every arrival.
  Those GUI-thread tasks interleave with canvas paint and show up as
  longer move frames when a generation burst is active.
* Each drag release emits `shape_moved`, which runs
  `_dense_review_sync_from_canvas()` -> `session.sync_shapes()` ->
  `workspace.refresh_all()`.  That refreshes up to 50 card texts,
  tooltips and roles on the 300-object fixture and schedules one
  `_request_visible_thumbnails()` pass.  Instrumentation counted 6
  request passes for 6 drags (one per release), not one per mouse move.
* No per-move re-crop and no fingerprint work was observed:
  `crop_thumbnail` started 164-211 crops while the drag flag was set,
  but those are queued worker crops from the pre-drag burst and from
  the release-triggered pass.  `image_fingerprint` was called 2 times
  in a whole run and 0 times during drag frames.

## Follow-up fix under test (not measured in this report)

These numbers are the pre-fix baseline.  After this run the parent
session proposed two production changes and will run the post-fix
validation itself:

1. `anylabeling/views/labeling/dense_review/thumbnails.py`,
   `ThumbnailProvider._drain`: reduce the per-tick batch from 32 to 8
   so one event-loop turn cannot decode and emit dozens of finished
   cards at once.
2. `anylabeling/views/labeling/dense_review/workspace.py`: coalesce
   the per-card `_update_action_labels()` calls into one update per
   event-loop turn instead of one call per thumbnail arrival.

Those changes target exactly the GUI-thread work identified below.  No
post-fix numbers are claimed here; re-run the same command after the
fix to obtain a like-for-like comparison against this baseline.

## Cache boundedness (10.3)

| Metric | 30 objects | 300 objects |
| --- | ---: | ---: |
| Provider limit | 64 | 64 |
| Entries before probe | 5 | 20 |
| Entries after probe | 30 | 64 |
| Peak entries | 30 | 64 |
| Peak QImage bytes | 6,606,460 | 6,202,856 |
| Plateau at switch | 26 / 90 | 51 / 300 |
| Late maximum entries | 30 | 64 |
| Bounded | yes | yes |
| `latest_requests` after probe | 30 | 300 |
| `card_request_keys` after probe | 30 | 300 |
| `shape_items` (cards in view) | 5 | 50 |

* The LRU never exceeds 64 entries.  The 300-object trace reaches 64 at
  switch 51 and stays exactly 64 through switch 300 while the image
  bytes fluctuate around 5.7-6.2 MB; there is no linear growth.
* For 30 objects the cache is bounded by the object count (30), not by
  the navigation count; 90 switches still end at 30 entries.
* `latest_requests` and `card_request_keys` are one small key tuple per
  object, not per navigation and not image pixels; they reset with the
  provider generation.  They are O(objects), not an unbounded image
  cache.
* `start_generation` reset: cached entries 0, pending 0, failed 0,
  latest requests 0, and card request keys 0 after the refreshed
  snapshot (run B); the image-entry reset is 0 in all runs.
* `bench-30-objects.json` and `bench-300-objects.json` were written by
  the immediately preceding harness revision, which sampled
  `image_switch_reset` before clearing the workspace-side key map;
  their `card_request_keys` field still shows 5/20 there.  The rerun
  JSON and the current script clear it first (0).  Image entries,
  pending and latest requests are 0 in every reset snapshot.
* There is no source-pixel cache.  `crop_thumbnail` re-opens the PNG for
  every request: 1,063-1,079 worker crops for 30 objects (p50 10-13 ms,
  p95 18-27 ms) and 3,013 crops for 300 objects (p50 27 ms, p95 61 ms).
* Card text refresh (50 cards on 300 objects) costs p50 2.9 ms,
  p95 5.0 ms per pass; on 5 cards it is p50 1.1-1.8 ms.

## Limitations

* Offscreen Qt uses software rasterization.  Absolute drag numbers are
  not comparable with a GPU desktop session; only the relative
  open/closed comparison is meaningful.
* The offscreen `QFontDatabase` has no font directory, so card text
  rasterization may be cheaper than on a desktop session.
* The host was shared with other work.  The 30-object baseline p95
  moved from 8.813 ms to 4.949 ms between runs, which is why the
  percentage threshold was re-run; the background direction repeated.
* The 300-object background p95 pass is fragile: p95 is 43.754 ms
  against a noisy 40.846 ms baseline, while p50 rises from 25.449 to
  30.373 ms (+19.4 %).  It should not be read as "no drag cost".
* `_on_batch_selected` does not call `_request_visible_thumbnails`, so a
  batch-list click rebuilds cards with placeholders and does not apply
  warm cached icons; cold and warm batch numbers are therefore close.
  This is a production behaviour observation, not a harness choice.
* Cross-batch `workspace._navigate_to` was observed to leave the card
  list on the previous batch (`_refresh_batches` prefers the stale
  `batch_list.currentItem()`), so it is not used for batch switching in
  this harness.
* Each drag frame includes the benchmark's 1 ms event-loop pump; this
  floor is present in baseline and open conditions alike.

## Reproduce

```text
cd D:\X-AnyLabeling-4.2.1
LOCALAPPDATA=...\.tmp\appdataok TEMP=...\.tmp\tempok TMP=...\.tmp\tempok \
QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 \
python -B scripts/benchmark_dense_review.py --objects 30 \
  --samples 30 --repeats 3 --json bench-30-objects.json
python -B scripts/benchmark_dense_review.py --objects 300 \
  --samples 30 --repeats 3 --json bench-300-objects.json
```

Smoke test (no latency assertions, about 6.5 s):

```text
python -B .tmp/run_pytest.py \
  tests/test_dense_review/test_performance_smoke.py -p no:cacheprovider
```

## Files

* `scripts/benchmark_dense_review.py`
* `tests/test_dense_review/test_performance_smoke.py`
* `bench-30-objects.json`, `bench-30-objects-rerun.json`,
  `bench-300-objects.json`
* matching `*.stderr.log` run logs

Note: the originally requested `reports/dense_review_workflow_20261102/`
tree is not writable in this sandbox, so these artifacts live under
`perf_reports/dense_review/performance-20261103/`.

---

# 修复后复测（POST-FIX, 2026-11-03 17:4x-17:5x）

修复针对上文定位的 GUI 线程成本，共四处，均在 `anylabeling/views/labeling/dense_review/` 内：

1. `thumbnails.py::_completed` 在 worker 线程解码 PNG（`QImage.loadFromData` 移出 GUI），队列传递 `QImage`，测试仍可投递 PNG 字节。
2. `thumbnails.py::_drain` 每 tick 最多处理 8 条结果（原 32），并在画布指针按下期间完全让路。
3. `workspace.py` 把每张卡片的 `_update_action_labels()` 合并为每事件循环一次。
4. `thumbnails.py::_crop_yielding`：worker 在指针按下期间休眠，避免 GIL/CPU 与拖框争用；画布新增 `is_pointer_down` 供判定。

复测仍使用同一 harness、同一环境，样本量提高到 300（`--samples 100 --repeats 3`），结果文件：

* `bench-30-objects-100.json`（修复后，30 对象）
* `bench-300-objects-100.json`（修复后，300 对象）

| 条件（p95，ms） | 30 对象 | 300 对象 |
| --- | ---: | ---: |
| warm object switch | 16.479 | 31.680 |
| warm batch switch | 15.342 | 32.161 |
| heartbeat + cards | 2.487 | 3.243 |
| drag baseline（关闭工作区） | 4.646 | 26.045 |
| drag open (`all`) | 5.525 (+18.9%) | 28.310 (+8.7%) |
| drag open (`focus`) | 3.784 | 17.125 |
| drag open + cards generating | 5.797 (+24.8%) | 28.170 (+8.2%) |

结论：

* 10.2 的暖缓存 p95 ≤150 ms 与心跳 p95 ≤50 ms：**两种规模均通过**。
* 拖框回退 ≤10%：**300 对象通过**（+8.7% / +8.2%）；**30 对象不通过**（+18.9% / +24.8%），但绝对 p95 仅 5.5–5.8 ms、p50 相对基线 +0.08 ms，属亚帧开销（30 对象基线本身只有 4.6 ms，10% 即 0.46 ms）。
* 因此 10.2 仍按“部分达标”记录，不写成目标已实现；30 对象小基线下按百分比判定无意义，需在真实屏幕与更高样本上复核。
* 10.3 缓存行为不变：30 对象峰值 30/64、300 对象峰值 64/64，平台期后不线性增长；本次修复未引入新的缓存。
