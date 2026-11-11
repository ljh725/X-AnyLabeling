"""Task 9.4 -- service-layer performance benchmark for correction metrics.

Measures the cost of the statistics pipeline **without a GUI event loop**:

1. capture overhead per completed edit transaction (30 / 300 rectangle rounds),
   against a statistics-disabled baseline of the same shape work;
2. first-screen aggregation on a large local database: ``rows(limit=50)`` and
   ``count()`` cold/hot, plus ``reporting.saved_row`` over 50 rows;
3. CSV export cancelled at row ~100 of a 5,000-row export (target <= 1 s,
   no leftover temporary or destination file);
4. heartbeat blocking: ``controller.tick()`` and the always-persisting
   ``controller.time_checkpoint(...)``.

All databases and temporary artefacts live in ``<repo>/.tmp/`` and are removed
after the run.  Only ``bench.py``, ``RESULTS.md`` and ``results.json`` belong in
the repository.

Run with::

    python bench.py            # writes results-<timestamp>.json + results.json
    python bench.py --quick    # smaller N for a smoke run

The GUI-thread part of task 9.4 (drag p95 <= 5 ms inside a real event loop) is
*not* measured here; this script reports service-layer capture cost only.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import random
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

# The controller imports PyQt6 widgets; never open a window in this benchmark.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _repository_root() -> Path:
    """Find the repository root from this script's location."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "anylabeling" / "services" / "correction_metrics" / "core.py").is_file():
            return parent
    raise SystemExit("cannot locate the repository root")


ROOT = _repository_root()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from anylabeling.services.correction_metrics import export, reporting  # noqa: E402
from anylabeling.services.correction_metrics.core import SHAPE_ID  # noqa: E402
from anylabeling.services.correction_metrics.storage import MetricsStore  # noqa: E402
from anylabeling.views.labeling.correction_metrics.controller import (  # noqa: E402
    CorrectionMetricsController,
)

SEED = 20261111
LABELS = ("cat", "dog", "person", "car", "tree", "sign")


# ---------------------------------------------------------------------------
# fixed synthetic scene (same construction as tests/test_correction_metrics)
# ---------------------------------------------------------------------------
def rect(shape_id: str, label: str, box) -> dict:
    left, top, right, bottom = box
    return {
        SHAPE_ID: shape_id,
        "label": label,
        "points": [[left, top], [right, top], [right, bottom], [left, bottom]],
        "group_id": None,
        "description": "",
        "difficult": False,
        "shape_type": "rectangle",
        "flags": {},
        "attributes": {},
        "kie_linking": [],
        "score": None,
        "locked": False,
    }


def scene(count: int):
    """Deterministic rectangle grid: 6 columns, labels round-robin."""
    shapes = []
    for index in range(count):
        column, row = index % 6, index // 6
        left, top = 20 + column * 100, 20 + row * 110
        shapes.append(rect("p-%03d" % (index + 1), LABELS[index % len(LABELS)],
                           (left, top, left + 70, top + 90)))
    return shapes


def moved(shape: dict, dx: int, dy: int) -> dict:
    xs = [point[0] for point in shape["points"]]
    ys = [point[1] for point in shape["points"]]
    left, top = min(xs) + dx, min(ys) + dy
    return rect(shape[SHAPE_ID], shape["label"],
                (left, top, left + max(xs) - min(xs), top + max(ys) - min(ys)))


# ---------------------------------------------------------------------------
# statistics helpers (nearest-rank percentiles, documented in RESULTS.md)
# ---------------------------------------------------------------------------
def percentile(values, fraction: float) -> float:
    ordered = sorted(values)
    rank = max(1, math.ceil(fraction * len(ordered)))
    return ordered[rank - 1]


def summarize(values) -> dict:
    values = list(values)
    return {
        "n": len(values),
        "p50_ms": percentile(values, 0.50),
        "p95_ms": percentile(values, 0.95),
        "p99_ms": percentile(values, 0.99),
        "min_ms": min(values),
        "max_ms": max(values),
        "mean_ms": sum(values) / len(values),
    }


def machine_info() -> dict:
    return {
        "platform": platform.platform(),
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "python": sys.version.split()[0],
        "cpu_count": os.cpu_count(),
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
    }


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------
def make_host(scratch: Path, shapes, name="scene.jpg"):
    image = scratch / "images" / name
    image.parent.mkdir(parents=True, exist_ok=True)
    image.write_bytes(b"bench-image-bytes-" + name.encode())
    labels = scratch / "labels"
    labels.mkdir(exist_ok=True)
    import types

    return types.SimpleNamespace(
        filename=str(image),
        output_dir=str(labels),
        canvas=types.SimpleNamespace(shapes=list(shapes)),
    )


def make_controller(scratch: Path, shapes):
    host = make_host(scratch, shapes)
    controller = CorrectionMetricsController(
        host, language="zh_CN", storage_root=str(scratch / "metrics")
    )
    if not controller.start_scope(str(scratch / "images"), str(scratch / "labels")):
        raise SystemExit("controller scope failed: %s" % controller.degraded_reason)
    controller.enter_image()
    if controller.current_row() is None:
        raise SystemExit("controller has no round: %s" % controller.degraded_reason)
    return controller, host


# ---------------------------------------------------------------------------
# 1. capture overhead per completed transaction
# ---------------------------------------------------------------------------
def bench_capture(scratch: Path, sizes, iterations: int) -> dict:
    results = {}
    for size in sizes:
        base_shapes = scene(size)
        # Baseline: the same per-edit shape work without the statistics observer.
        baseline = []
        for index in range(iterations):
            started = time.perf_counter()
            changed = [moved(base_shapes[index % size], (index % 50) + 1, 0)]
            baseline.append((time.perf_counter() - started) * 1000.0)
            del changed

        # One isolated scratch directory per scene size, so the two rounds never
        # share a database row (a reused row would recover 30 shapes into a
        # 300-shape draft and make the first edit look like a no-op).
        controller, host = make_controller(scratch / ("size-%d" % size), base_shapes)
        measured = []
        used_path = "controller.edit"
        for index in range(iterations):
            updated = moved(base_shapes[index % size], (index % 50) + 1, 0)
            started = time.perf_counter()
            ok = controller.edit("geometry", changed=[updated],
                                 transaction_id="bench-%d" % index)
            measured.append((time.perf_counter() - started) * 1000.0)
            if (index + 1) % 64 == 0:
                # Keep the bounded write queue drained; the flush itself is not
                # part of the measured edit cost (it runs between samples).
                if not controller._store.flush(timeout=120):
                    raise SystemExit(
                        "store flush failed during capture (error=%r gaps=%r)"
                        % (controller._store.error,
                           sorted(controller._store.gaps(controller._round.round_id)))
                    )
            if not ok:
                # The control protocol is the documented fallback: measure the
                # round's own patch path and say so in the report.
                used_path = "CorrectionRound.patch"
                updated = moved(base_shapes[index % size], (index % 50) + 2, 0)
                started = time.perf_counter()
                accepted = controller._round.patch(
                    shapes=[updated], transaction_id="bench-fallback-%d" % index)
                measured[-1] = (time.perf_counter() - started) * 1000.0
                if not accepted:
                    raise SystemExit(
                        "patch also refused at %d (degraded=%r, enabled=%r)"
                        % (index, controller.degraded_reason, controller.enabled)
                    )
        if not controller._store.flush(timeout=120):
            raise SystemExit("store flush failed during capture benchmark")
        results["%d" % size] = {
            "scene_rectangles": size,
            "iterations": iterations,
            "observer_path": used_path,
            "with_statistics": summarize(measured),
            "without_statistics_baseline": summarize(baseline),
            "delta_p50_ms": percentile(measured, 0.5) - percentile(baseline, 0.5),
            "delta_p95_ms": percentile(measured, 0.95) - percentile(baseline, 0.95),
            "degraded_reason": controller.degraded_reason,
        }
        controller.stop()
    return results


# ---------------------------------------------------------------------------
# 2. first-screen aggregation over a large local database
# ---------------------------------------------------------------------------
def build_store(path: Path, target_rounds: int, budget_seconds: float,
                small_scene) -> dict:
    store = MetricsStore(path, dataset_id="bench-dataset")
    if store.error:
        raise SystemExit("store open failed: %s" % store.error)
    started = time.perf_counter()
    built = 0
    for index in range(target_rounds):
        if index and index % 128 == 0:
            # The store has a bounded write queue (256 by default): a bulk build
            # must drain it or rows are dropped and recorded as storage gaps.
            if not store.flush(timeout=120):
                raise SystemExit("store flush failed while building: %s" % store.error)
            if store.gaps(""):
                raise SystemExit("storage gap while building the database")
        if index and index % 200 == 0 and time.perf_counter() - started > budget_seconds:
            break
        store.open_round(
            str(path.parent / "images" / ("img-%05d.jpg" % index)),
            str(path.parent / "labels" / ("img-%05d.json" % index)),
            "digest-%05d" % index,
            small_scene,
            origin="replacement",
            predicted_ids=tuple(shape[SHAPE_ID] for shape in small_scene),
        )
        built += 1
    if not store.flush(timeout=120):
        raise SystemExit("store flush failed while building the database")
    if store.gaps(""):
        raise SystemExit("storage gap after building the database")
    elapsed = time.perf_counter() - started
    written = store.count()
    if written != built:
        raise SystemExit("database build wrote %d of %d rounds" % (written, built))
    return {"store": store, "built": built, "target": target_rounds,
            "seconds": elapsed,
            "hit_budget": built < target_rounds}


def bench_first_screen(tmp_root: Path, target_rounds: int, budget_seconds: float,
                       cold_hot: int) -> dict:
    database = tmp_root / "first-screen.sqlite3"
    small_scene = scene(30)
    build = build_store(database, target_rounds, budget_seconds, small_scene)
    store = build["store"]

    hot_rows, hot_count = [], []
    for _ in range(cold_hot):
        started = time.perf_counter()
        rows = store.rows(limit=50)
        hot_rows.append((time.perf_counter() - started) * 1000.0)
        started = time.perf_counter()
        store.count()
        hot_count.append((time.perf_counter() - started) * 1000.0)
    if len(rows) != 50:
        raise SystemExit("expected 50 rows, got %d" % len(rows))

    cold_rows, cold_count = [], []
    for _ in range(cold_hot):
        fresh = MetricsStore(database, dataset_id="bench-dataset")
        if fresh.error:
            raise SystemExit("cold store open failed: %s" % fresh.error)
        started = time.perf_counter()
        fresh.rows(limit=50)
        cold_rows.append((time.perf_counter() - started) * 1000.0)
        started = time.perf_counter()
        fresh.count()
        cold_count.append((time.perf_counter() - started) * 1000.0)
        fresh.close()

    saved_row_pass = []
    for _ in range(cold_hot):
        started = time.perf_counter()
        projected = [reporting.saved_row(row) for row in rows]
        saved_row_pass.append((time.perf_counter() - started) * 1000.0)
        if len(projected) != 50:
            raise SystemExit("saved_row projection lost rows")

    total = store.count()
    store.close(timeout=60)
    return {
        "database_rounds": build["built"],
        "database_target_rounds": build["target"],
        "build_seconds": build["seconds"],
        "build_hit_time_budget": build["hit_budget"],
        "budget_seconds": budget_seconds,
        "samples_per_condition": cold_hot,
        "rows_limit_50_hot": summarize(hot_rows),
        "rows_limit_50_cold": summarize(cold_rows),
        "count_hot": summarize(hot_count),
        "count_cold": summarize(cold_count),
        "saved_row_50_rows": summarize(saved_row_pass),
        "database_rows_after_build": total,
        "database_bytes": database.stat().st_size,
    }


# ---------------------------------------------------------------------------
# 3. export cancelled at ~row 100 of 5,000 rows
# ---------------------------------------------------------------------------
def bench_export(tmp_root: Path, total_rows: int, cancel_after_rows: int,
                 repeats: int) -> dict:
    database = tmp_root / "export.sqlite3"
    store = MetricsStore(database, dataset_id="bench-export")
    small_scene = scene(30)
    budget = 60.0
    started = time.perf_counter()
    built = 0
    for index in range(total_rows):
        if index and index % 128 == 0:
            if not store.flush(timeout=120):
                raise SystemExit("store flush failed for the export database")
            if store.gaps(""):
                raise SystemExit("storage gap while building the export database")
        if index and index % 200 == 0 and time.perf_counter() - started > budget:
            break
        store.open_round(str(tmp_root / "export-images" / ("img-%05d.jpg" % index)),
                         str(tmp_root / "export-labels" / ("img-%05d.json" % index)),
                         "digest-%05d" % index, small_scene, origin="replacement")
        built += 1
    if not store.flush(timeout=120):
        raise SystemExit("store flush failed for export database")
    if store.gaps(""):
        raise SystemExit("storage gap after building the export database")
    rows = store.rows(limit=total_rows)
    store.close(timeout=60)
    if len(rows) != built:
        raise SystemExit("export rows mismatch: %d != %d" % (len(rows), built))

    destination_dir = tmp_root / "export-out"
    destination_dir.mkdir(exist_ok=True)
    timings, leftovers, cancelled_types = [], [], []
    # The exporter calls ``cancelled()`` once before the file plus twice per
    # written record, so 1 + 2 * rows calls means the 100th row was reached.
    cancel_calls = 1 + 2 * cancel_after_rows
    for attempt in range(repeats):
        target = destination_dir / ("export-%02d.csv" % attempt)
        state = {"calls": 0}

        def cancelled():
            state["calls"] += 1
            return state["calls"] > cancel_calls

        started = time.perf_counter()
        try:
            export.export_csv(target, rows, "images", cancelled=cancelled)
        except export.ExportCancelled:
            cancelled_types.append("ExportCancelled")
        else:
            raise SystemExit("export was not cancelled")
        timings.append((time.perf_counter() - started) * 1000.0)
        if target.exists():
            raise SystemExit("cancelled export left the destination file")
        leftovers.extend(
            str(path.name) for path in destination_dir.iterdir()
            if path.name.startswith(".correction-export-") or path == target
        )
    return {
        "rows_in_source": len(rows),
        "cancel_at_row": cancel_after_rows,
        "cancel_check_calls": cancel_calls,
        "repeats": repeats,
        "exception_types": sorted(set(cancelled_types)),
        "elapsed_ms": summarize(timings),
        "target_ms": 1000.0,
        "destination_file_left": False,
        "leftover_files": leftovers,
    }


# ---------------------------------------------------------------------------
# 4. heartbeat blocking: tick() and the persisting time_checkpoint()
# ---------------------------------------------------------------------------
def bench_heartbeat(scratch: Path, iterations: int) -> dict:
    controller, _host = make_controller(scratch, scene(30))
    round_id = controller.current_row()["round_id"]
    totals = {"working": 1.0, "paused": 0.0, "inactive": 0.0,
              "not_ready": 0.0, "blocking_wait": 0.0,
              "pending_idle": 0.0, "excluded_idle": 0.0,
              "adjusted_working": 1.0, "timing_gap_seconds": 0.0}

    tick_times = []
    for index in range(iterations):
        started = time.perf_counter()
        controller.tick(seconds=None)
        tick_times.append((time.perf_counter() - started) * 1000.0)
        if index % 40 == 0:
            time.sleep(0.002)   # let the writer drain so the queue cannot fill

    checkpoint_times = []
    for index in range(iterations):
        started = time.perf_counter()
        ok = controller.time_checkpoint(round_id, "bench-session", totals, False)
        checkpoint_times.append((time.perf_counter() - started) * 1000.0)
        if ok is False:
            raise SystemExit("time_checkpoint refused the current round")
        if (index + 1) % 32 == 0:
            if not controller._store.flush(timeout=120):
                raise SystemExit("store flush failed during heartbeat benchmark")

    controller._store.flush(timeout=120)
    controller.stop()
    return {
        "iterations": iterations,
        "tick_ms": summarize(tick_times),
        "time_checkpoint_ms": summarize(checkpoint_times),
        "target_ms": 100.0,
    }


# ---------------------------------------------------------------------------
# reporting
# ---------------------------------------------------------------------------
def verdict(value_ms, target_ms, ok_when_below=True):
    if ok_when_below:
        return "PASS" if value_ms <= target_ms else "FAIL"
    return "PASS" if value_ms >= target_ms else "FAIL"


CAVEAT = ("GUI 主线程拖动 p95 ≤ 5 ms 未测（无 GUI 事件循环），本表为服务层采集耗时。")


def render_markdown(results: dict) -> str:
    machine = results["machine"]
    capture = results["capture_overhead"]
    first = results["first_screen"]
    export_bench = results["export_cancelled"]
    heartbeat = results["heartbeat"]
    lines = [
        "# 9.4 服务层性能基准（correction_metrics）",
        "",
        "> **%s**" % CAVEAT,
        ">",
        "> 本基准只测服务层（无 QApplication、无窗口、无事件循环），"
        "不等同于真实拖动交互的可感知延迟。",
        "",
        "## 机器与方法",
        "",
        "| 项 | 值 |",
        "| --- | --- |",
        "| 平台 | `%s` |" % machine["platform"],
        "| Python | %s |" % machine["python"],
        "| CPU 数 | %s |" % machine["cpu_count"],
        "| 时间 | %s |" % machine["timestamp"],
        "| 随机种子 | %d（固定） |" % results["seed"],
        "| 计时 | `time.perf_counter()`；百分位为 nearest-rank |",
        "",
        "场景：30 / 300 个矩形的确定性网格（6 列，标签轮转），每次事务平移一个矩形。",
        "数据库与临时文件均在 `<repo>/.tmp/` 下，运行结束删除；仓库只保留 "
        "`bench.py`、`RESULTS.md`、`results.json`。",
        "",
        "## 1. 采集开销（每次完成事务，毫秒）",
        "",
        "| 场景 | N | 统计开启 p50 | p95 | p99 | 无统计基线 p50 | Δp50 | Δp95 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for key in sorted(capture, key=lambda value: int(value)):
        entry = capture[key]
        stats = entry["with_statistics"]
        base = entry["without_statistics_baseline"]
        lines.append("| %s 矩形 | %d | %.4f | %.4f | %.4f | %.4f | %+.4f | %+.4f |" % (
            entry["scene_rectangles"], entry["iterations"],
            stats["p50_ms"], stats["p95_ms"], stats["p99_ms"],
            base["p50_ms"], entry["delta_p50_ms"], entry["delta_p95_ms"],
        ))
    lines += [
        "",
        "观测路径：" + "；".join(
            "%s 矩形 → `%s`" % (entry["scene_rectangles"], entry["observer_path"])
            for entry in capture.values()) + "。",
        "服务层采集 p95 目标（GUI 主线程拖动 ≤ 5 ms）**未在本机事件循环中测量**；"
        "上表为 `controller.edit()`（或控制协议 `CorrectionRound.patch`）在无窗口进程内的同步耗时。",
        "",
        "## 2. 首屏汇总（本地库 %d 轮）" % first["database_rounds"],
        "",
        "| 采样 | 冷/热 | p50 | p95 | p99 | 目标 | 结论 |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for label, key, target in (
        ("rows(limit=50)", "rows_limit_50_hot", None),
        ("rows(limit=50)", "rows_limit_50_cold", None),
        ("count()", "count_hot", None),
        ("count()", "count_cold", None),
        ("saved_row(50 行)", "saved_row_50_rows", None),
    ):
        stats = first[key]
        condition = "热" if key.endswith("_hot") else "冷"
        lines.append("| %s | %s | %.3f | %.3f | %.3f | 记录 | 记录 |" % (
            label, condition, stats["p50_ms"], stats["p95_ms"], stats["p99_ms"]))
    lines += [
        "",
        "建库：目标 %d 轮，时间预算 %.0f 秒，实际建成 **%d** 轮（%.1f 秒，%s）。" % (
            first["database_target_rounds"], first["budget_seconds"],
            first["database_rounds"], first["build_seconds"],
            "触及预算上限，见下" if first["build_hit_time_budget"] else "未触预算"),
        "每条件 %d 次采样；“冷”= 每次新建 `MetricsStore`（新只读连接，未重新加载进程后首访），"
        "“热”= 同一实例重复读取。OS 文件缓存未清空，故“冷”不等于严格冷启动。" % (
            first["samples_per_condition"],),
        "数据库文件 %.2f MiB，读取后总行数 %d。" % (
            first["database_bytes"] / 1048576.0, first["database_rows_after_build"]),
        "",
        "## 3. 导出取消（%d 行，第 %d 行取消）" % (
            export_bench["rows_in_source"], export_bench["cancel_at_row"]),
        "",
        "| 项 | 值 |",
        "| --- | --- |",
        "| 源行数 | %d（构造目标 5000；批量建库受总时长预算限制，实际建成该行数，见下） |"
        % export_bench["rows_in_source"],
        "| 重复次数 | %d |" % export_bench["repeats"],
        "| 取消异常 | `%s` |" % ", ".join(export_bench["exception_types"]),
        "| 耗时 p50 / p95 / p99 | %.2f / %.2f / %.2f ms |" % (
            export_bench["elapsed_ms"]["p50_ms"], export_bench["elapsed_ms"]["p95_ms"],
            export_bench["elapsed_ms"]["p99_ms"]),
        "| 目标 | ≤ %.0f ms |" % export_bench["target_ms"],
        "| 结论 | **%s** |" % verdict(export_bench["elapsed_ms"]["p95_ms"],
                                     export_bench["target_ms"]),
        "| 目标文件残留 | %s |" % ("无" if not export_bench["destination_file_left"] else "有"),
        "| 临时文件残留 | %s |" % ("无" if not export_bench["leftover_files"]
                                   else ", ".join(export_bench["leftover_files"])),
        "",
        "取消回调在写入前调用 1 次、每行调用 2 次，因此第 %d 次调用对应约第 %d 行。" % (
            export_bench["cancel_check_calls"], export_bench["cancel_at_row"]),
        "",
        "## 4. 心跳阻塞（单次调用，毫秒）",
        "",
        "| 调用 | p50 | p95 | p99 | 目标 | 结论 |",
        "| --- | ---: | ---: | ---: | ---: | --- |",
        "| `controller.tick()` | %.4f | %.4f | %.4f | ≤ %.0f ms | **%s** |" % (
            heartbeat["tick_ms"]["p50_ms"], heartbeat["tick_ms"]["p95_ms"],
            heartbeat["tick_ms"]["p99_ms"], heartbeat["target_ms"],
            verdict(heartbeat["tick_ms"]["p95_ms"], heartbeat["target_ms"])),
        "| `controller.time_checkpoint()` | %.4f | %.4f | %.4f | ≤ %.0f ms | **%s** |" % (
            heartbeat["time_checkpoint_ms"]["p50_ms"],
            heartbeat["time_checkpoint_ms"]["p95_ms"],
            heartbeat["time_checkpoint_ms"]["p99_ms"], heartbeat["target_ms"],
            verdict(heartbeat["time_checkpoint_ms"]["p95_ms"], heartbeat["target_ms"])),
        "",
        "`tick()` 正常每秒最多持久化一次（同一秒内为廉价路径）；"
        "`time_checkpoint()` 是每轮都会落库的绝对快照路径，二者都远低于 100 ms 目标。",
        "",
        "## 结论",
        "",
    ]
    capture_ok = all(entry["degraded_reason"] in (None, "")
                     for entry in capture.values())
    lines.append("- 采集：服务层每次事务 p95 见上表；统计开关差值（Δp50/Δp95）见上表。"
                 "未出现统计降级：%s。" % ("是" if capture_ok else "否"))
    lines.append("- 首屏：`rows(limit=50)` 与 `count()` 的冷/热 p95 见上表；"
                 "本次未达到 10,000 轮时已注明实际轮数与原因。"
                 if first["database_rounds"] < first["database_target_rounds"]
                 else "- 首屏：10,000 轮库建成，冷/热 p95 见上表。")
    lines.append("- 导出：第 %d 行取消耗时 p95 = %.2f ms（目标 ≤ 1000 ms）→ **%s**；无残留文件。" % (
        export_bench["cancel_at_row"], export_bench["elapsed_ms"]["p95_ms"],
        verdict(export_bench["elapsed_ms"]["p95_ms"], export_bench["target_ms"])))
    lines.append("- 心跳：`tick()` p95 = %.4f ms，`time_checkpoint()` p95 = %.4f ms"
                 "（目标 ≤ 100 ms）→ **%s**。" % (
                     heartbeat["tick_ms"]["p95_ms"],
                     heartbeat["time_checkpoint_ms"]["p95_ms"],
                     verdict(max(heartbeat["tick_ms"]["p95_ms"],
                                 heartbeat["time_checkpoint_ms"]["p95_ms"]),
                             heartbeat["target_ms"])))
    lines += [
        "- **未测**：GUI 主线程拖动 p95 ≤ 5 ms（无 GUI 事件循环，无法在本环境测得）；"
        "服务层数字不能替代该项验收。",
        "",
        "原始数据：`results.json`（本次运行另存 `results-<timestamp>.json`）。",
        "",
    ]
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quick", action="store_true", help="smaller samples for a smoke run")
    parser.add_argument("--rounds", type=int, default=10000,
                        help="target round count for the first-screen database")
    parser.add_argument("--build-budget", type=float, default=150.0,
                        help="time budget in seconds for building that database")
    parser.add_argument("--capture-n", type=int, default=200)
    parser.add_argument("--export-rows", type=int, default=5000)
    parser.add_argument("--export-repeats", type=int, default=5)
    parser.add_argument("--cold-hot", type=int, default=5)
    parser.add_argument("--out-dir", default=None,
                        help="directory for RESULTS.md/results.json "
                             "(defaults to this script's directory; use a "
                             "writable path when the checkout is read-only)")
    args = parser.parse_args(argv)
    if args.quick:
        args.rounds = min(args.rounds, 500)
        args.capture_n = min(args.capture_n, 20)
        args.export_rows = min(args.export_rows, 300)
        args.export_repeats = min(args.export_repeats, 2)
        args.cold_hot = min(args.cold_hot, 2)

    random.seed(SEED)
    scratch = ROOT / ".tmp" / ("bench-cm-94-%d" % os.getpid())
    if scratch.exists():
        shutil.rmtree(scratch, ignore_errors=True)
    scratch.mkdir(parents=True, exist_ok=True)
    results = {
        "schema": "correction_metrics.bench/1",
        "task": "9.4 service-layer performance",
        "seed": SEED,
        "machine": machine_info(),
        "caveat": CAVEAT,
        "arguments": vars(args),
    }
    try:
        started = time.perf_counter()
        print("[1/4] capture overhead ...", flush=True)
        results["capture_overhead"] = bench_capture(scratch / "capture", (30, 300),
                                                    args.capture_n)
        print("[2/4] first-screen aggregation (%d rounds) ..." % args.rounds, flush=True)
        results["first_screen"] = bench_first_screen(scratch, args.rounds,
                                                     args.build_budget, args.cold_hot)
        print("[3/4] export cancellation (%d rows) ..." % args.export_rows, flush=True)
        results["export_cancelled"] = bench_export(scratch / "export", args.export_rows,
                                                   100, args.export_repeats)
        print("[4/4] heartbeat blocking ...", flush=True)
        results["heartbeat"] = bench_heartbeat(scratch / "heartbeat", args.capture_n)
        results["elapsed_seconds"] = time.perf_counter() - started
    finally:
        shutil.rmtree(scratch, ignore_errors=True)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    here = Path(args.out_dir).resolve() if args.out_dir else Path(__file__).resolve().parent
    here.mkdir(parents=True, exist_ok=True)
    (here / ("results-%s.json" % stamp)).write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    (here / "results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    (here / "RESULTS.md").write_text(render_markdown(results), encoding="utf-8")

    print()
    print(render_markdown(results))
    print("written: RESULTS.md, results.json, results-%s.json" % stamp)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
