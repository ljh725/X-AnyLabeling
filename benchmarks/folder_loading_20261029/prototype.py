"""Independent background/index prototype; does not patch the application."""

import json
import os
from pathlib import Path
import sqlite3
import statistics
import time
import traceback

import benchmark as baseline
from benchmark import QtCore, QtGui, QtWidgets, QtTest, Qt, HERE


class IndexWorker(QtCore.QObject):
    paths_ready = QtCore.pyqtSignal(list)
    metadata_ready = QtCore.pyqtSignal(list)
    done = QtCore.pyqtSignal(dict)
    failed = QtCore.pyqtSignal(str)

    def __init__(self, directory, database):
        super().__init__()
        self.directory = directory
        self.database = database

    @QtCore.pyqtSlot()
    def run(self):
        connection = None
        try:
            started = time.perf_counter()
            paths = baseline.scan_images(str(self.directory))
            self.paths_ready.emit(paths)
            connection = sqlite3.connect(self.database)
            connection.execute("CREATE TABLE IF NOT EXISTS annotations(path TEXT PRIMARY KEY,mtime_ns INTEGER,size INTEGER,checked TEXT,labels TEXT)")
            cached = {row[0]: row[1:] for row in connection.execute("SELECT path,mtime_ns,size,checked,labels FROM annotations")}
            parsed = 0
            hits = 0
            batch = []
            changed_rows = []
            for index, image in enumerate(paths):
                label = str(Path(image).with_suffix(".json"))
                signature = os.stat(label)
                old = cached.get(label)
                if old and old[:2] == (signature.st_mtime_ns, signature.st_size):
                    status, labels = json.loads(old[2]), json.loads(old[3])
                    hits += 1
                else:
                    with open(label, encoding="utf-8") as stream:
                        data = json.load(stream)
                    raw = data.get("checked", False)
                    status = "failed" if raw == "failed" else raw is True
                    labels = sorted({shape.get("label", "").lower() for shape in data.get("shapes", [])})
                    changed_rows.append((label, signature.st_mtime_ns, signature.st_size, json.dumps(status), json.dumps(labels)))
                    parsed += 1
                batch.append((index, status, labels))
                if len(batch) == 250:
                    self.metadata_ready.emit(batch)
                    batch = []
            if batch:
                self.metadata_ready.emit(batch)
            connection.executemany("INSERT OR REPLACE INTO annotations VALUES (?,?,?,?,?)", changed_rows)
            connection.commit()
            self.done.emit({"background_seconds": time.perf_counter() - started, "parsed": parsed, "cache_hits": hits, "count": len(paths)})
        except Exception:
            self.failed.emit(traceback.format_exc())
        finally:
            if connection is not None:
                connection.close()


def trial(app, directory, database, expected_parsed):
    window = baseline.Harness()
    # These filename rows have the same height; avoid repeatedly measuring
    # every earlier row when a later batch arrives.
    window.file_list_widget.setUniformItemSizes(True)
    window.file_list_widget.setLayoutMode(QtWidgets.QListView.LayoutMode.Batched)
    window.file_list_widget.setBatchSize(250)
    window.show()
    QtTest.QTest.qWait(30)
    loop = QtCore.QEventLoop()
    state = {"paths": None, "position": 0, "metadata": {}, "worker": None, "first_batch": None, "all_names": None, "error": None}
    labels_index = {}
    started = time.perf_counter()
    beats = [started]
    heartbeat = QtCore.QTimer()
    heartbeat.setInterval(10)
    heartbeat.timeout.connect(lambda: beats.append(time.perf_counter()))
    heartbeat.start()
    thread = QtCore.QThread()
    worker = IndexWorker(directory, str(database))
    worker.moveToThread(thread)

    def check_finished():
        paths = state["paths"]
        if paths is not None and state["position"] == len(paths) and state["worker"] is not None and len(state["metadata"]) == len(paths):
            loop.quit()

    def apply_metadata(index, metadata):
        status, labels = metadata
        item = window.file_list_widget.item(index)
        window._set_file_item_checked(item, status)

    def add_batch():
        before = state["position"]
        end = min(before + 250, len(state["paths"]))
        window.file_list_widget.setUpdatesEnabled(False)
        try:
            window.file_list_widget.addItems(state["paths"][before:end])
            for index in range(before, end):
                item = window.file_list_widget.item(index)
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                item.setToolTip(state["paths"][index])
                item.setCheckState(Qt.CheckState.Checked)
                if index in state["metadata"]:
                    apply_metadata(index, state["metadata"][index])
        finally:
            window.file_list_widget.setUpdatesEnabled(True)
        state["position"] = end
        if state["first_batch"] is None:
            app.processEvents()
            state["first_batch"] = time.perf_counter() - started
        if end < len(state["paths"]):
            QtCore.QTimer.singleShot(0, add_batch)
        else:
            state["all_names"] = time.perf_counter() - started
            check_finished()

    def paths_ready(paths):
        state["paths"] = paths
        QtCore.QTimer.singleShot(0, add_batch)

    def metadata_ready(batch):
        window.file_list_widget.setUpdatesEnabled(False)
        try:
            for index, status, labels in batch:
                state["metadata"][index] = status, labels
                for label in labels:
                    labels_index.setdefault(label, set()).add(index)
                if index < state["position"]:
                    apply_metadata(index, (status, labels))
        finally:
            window.file_list_widget.setUpdatesEnabled(True)
        check_finished()

    def done(result):
        state["worker"] = result
        check_finished()

    def failed(message):
        state["error"] = message
        loop.quit()

    worker.paths_ready.connect(paths_ready)
    worker.metadata_ready.connect(metadata_ready)
    worker.done.connect(done)
    worker.failed.connect(failed)
    worker.done.connect(thread.quit)
    worker.failed.connect(thread.quit)
    thread.started.connect(worker.run)
    thread.start()
    loop.exec()
    finished = time.perf_counter()
    app.processEvents()
    QtTest.QTest.qWait(30)
    heartbeat.stop()
    thread.quit()
    assert thread.wait(5000)
    if state["error"]:
        raise RuntimeError(state["error"])
    assert state["worker"]["parsed"] == expected_parsed
    assert len(state["metadata"]) == 10000
    assert window.file_list_widget.count() == 10000
    assert sorted(labels_index["person"]) == list(range(0, 10000, 2))
    for index in range(10000):
        expected_status = (False, True, "failed")[index % 3]
        assert window.file_list_widget.item(index).data(Qt.ItemDataRole.UserRole) == expected_status
    search_times = []
    for _ in range(3):
        search_started = time.perf_counter()
        matching = sorted(labels_index.get("person", ()))
        window.file_list_widget.setUpdatesEnabled(False)
        window.file_list_widget.clear()
        window.file_list_widget.addItems([state["paths"][index] for index in matching])
        for row, index in enumerate(matching):
            item = window.file_list_widget.item(row)
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            item.setCheckState(Qt.CheckState.Checked)
            window._set_file_item_checked(item, state["metadata"][index][0])
        window.file_list_widget.setUpdatesEnabled(True)
        app.processEvents()
        search_times.append(time.perf_counter() - search_started)
        assert window.file_list_widget.count() == 5000
        for row in (0, 1234, 4999):
            assert window.file_list_widget.item(row).data(Qt.ItemDataRole.UserRole) == state["metadata"][matching[row]][0]
    result = dict(state["worker"], first_250_rows_seconds=state["first_batch"], all_names_seconds=state["all_names"],
                  complete_seconds=finished-started, largest_heartbeat_gap_seconds=max(b-a for a,b in zip(beats, beats[1:])),
                  indexed_search_with_5000_row_rebuild_seconds=statistics.median(search_times))
    window.close()
    window.deleteLater()
    app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
    app.processEvents()
    return result


def main():
    app = QtWidgets.QApplication([])
    app.setQuitOnLastWindowClosed(False)
    directory = HERE / "data/multi_10000"
    assert (directory / "complete.json").exists()
    database = HERE / f"prototype_index_{time.time_ns()}.sqlite"
    report = {"scope": "Separate proof of concept with real QThread, timed batches of 250 real Qt list rows, uniform row size and batched Qt layout, SQLite index, mtime_ns+size invalidation. No production integration. Excludes canvas and app startup. OS cache not flushed.", "trials": []}
    for run in range(4):
        result = trial(app, directory, database, 10000 if run == 0 else 0)
        result["mode"] = "build_index" if run == 0 else "reuse_index"
        report["trials"].append(result)
        (HERE / "prototype_results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(result), flush=True)
    # Verify that external edits invalidate exactly one record and update labels.
    edited = directory / "image_00000.json"
    original = edited.read_bytes()
    try:
        data = json.loads(original)
        data["description"] = "cache invalidation benchmark"
        edited.write_text(json.dumps(data, indent=2), encoding="utf-8")
        result = trial(app, directory, database, 1)
        report["external_edit_validation"] = {"passed": True, "parsed": result["parsed"], "cache_hits": result["cache_hits"]}
    finally:
        edited.write_bytes(original)
    (HERE / "prototype_results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
