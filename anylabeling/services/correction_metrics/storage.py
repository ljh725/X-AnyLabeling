"""Local correction history with a bounded single writer and snapshot readers."""

from __future__ import annotations

import ctypes
import json
import os
import queue
import sqlite3
import threading
import time
import weakref
from pathlib import Path

from .core import (
    SCHEMA_VERSION, CorrectionRound, dataset_identity, digest, encode,
    initialise_state, path_identity, report_row, safe_provenance, snapshot, uid,
)


_DDL = """
CREATE TABLE rounds(
 id TEXT PRIMARY KEY, image_path TEXT NOT NULL, label_path TEXT NOT NULL,
 phase TEXT NOT NULL, active INTEGER NOT NULL, current INTEGER NOT NULL,
 state TEXT NOT NULL, report TEXT NOT NULL
);
CREATE INDEX round_target ON rounds(image_path,label_path,phase,active);
CREATE TABLE events(
 round_id TEXT NOT NULL, tx TEXT NOT NULL, seq INTEGER NOT NULL,
 outcome TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY(round_id,tx)
);
CREATE INDEX event_order ON events(round_id,seq);
CREATE TABLE revisions(
 round_id TEXT NOT NULL, revision TEXT NOT NULL, through_seq INTEGER NOT NULL,
 snapshot TEXT NOT NULL, PRIMARY KEY(round_id,revision)
);
CREATE TABLE completions(
 id TEXT PRIMARY KEY, round_id TEXT NOT NULL, revision TEXT NOT NULL, data TEXT NOT NULL
);
CREATE TABLE predictions(
 run_id TEXT NOT NULL, image_path TEXT NOT NULL, label_path TEXT NOT NULL,
 status TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY(run_id,image_path,label_path)
);
"""


def _local_path(path):
    raw = os.fspath(path)
    if raw.startswith(("//", "\\\\")):
        return False
    if os.name == "nt":
        drive = Path(raw).resolve().anchor
        return ctypes.windll.kernel32.GetDriveTypeW(drive) != 4
    return True


class MetricsStore:
    def __init__(self, db_path, dataset_id=None, queue_size=256):
        self.path = Path(db_path)
        self.dataset_id = dataset_id or self.path.stem
        self.session_id = uid()
        self._queue = queue.Queue(maxsize=max(1, queue_size))
        self._state_lock = threading.RLock()
        self._fault_lock = threading.Lock()
        self._faults = {}
        self._target_faults = {}
        self._live = weakref.WeakValueDictionary()
        self._closed = False
        self._thread = None
        self.error = None
        try:
            if not _local_path(db_path):
                raise ValueError("correction history needs a local database")
            self.path.parent.mkdir(parents=True, exist_ok=True)
            db = sqlite3.connect(self.path, timeout=0.25)
            try:
                version = db.execute("PRAGMA user_version").fetchone()[0]
                existing = db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' LIMIT 1"
                ).fetchone()
                if version == 0 and not existing:
                    db.execute("PRAGMA journal_mode=WAL")
                    db.executescript(
                        "BEGIN;" + _DDL + f"PRAGMA user_version={SCHEMA_VERSION};COMMIT;"
                    )
                elif version != SCHEMA_VERSION:
                    raise ValueError(f"unsupported correction database version {version}")
                else:
                    db.execute("SELECT id FROM rounds LIMIT 0")
            finally:
                db.close()
        except (OSError, sqlite3.Error, ValueError) as exc:
            self.error = str(exc)
            return
        self._thread = threading.Thread(
            target=self._writer, name="Correction metrics writer", daemon=True
        )
        self._thread.start()

    def _reader(self):
        if self._thread is None:
            raise sqlite3.OperationalError(self.error or "database unavailable")
        return sqlite3.connect(
            self.path.resolve().as_uri() + "?mode=ro", uri=True, timeout=0.25,
            check_same_thread=False,
        )

    def _fault(self, round_id, error, *, target=None, kind="storage-gap"):
        with self._fault_lock:
            self.error = str(error)
            self._faults.setdefault(round_id, set()).add(kind)
            if target:
                key = (path_identity(target[0]), path_identity(target[1]))
                self._target_faults.setdefault(key, set()).add(kind)

    def gaps(self, round_id):
        with self._fault_lock:
            return set(self._faults.get(round_id, ()))

    def gaps_for(self, image_path, label_path):
        """Gaps recorded for one image/label pair, whatever the round."""
        key = (path_identity(image_path), path_identity(label_path))
        with self._fault_lock:
            return set(self._target_faults.get(key, ()))

    def _enqueue(self, state, operations):
        key = state["round_id"]
        if self._closed or self._thread is None or not self._thread.is_alive():
            self._fault(key, self.error or "database closed")
            return False
        state["issues"] = sorted(set(state["issues"]) | self.gaps(key))
        try:
            self._queue.put_nowait(("write", state, operations))
        except queue.Full:
            self._fault(key, "correction metrics queue full")
            return False
        return True

    @staticmethod
    def _write(db, state, ops):
        round_id = state["round_id"]
        if ops.get("new_round"):
            target = (state["image_path"], state["label_path"])
            if state["phase"] == "review":
                db.execute(
                    "UPDATE rounds SET active=0,current=0 WHERE image_path=? AND "
                    "label_path=? AND phase='review' AND active=1", target)
            else:
                db.execute(
                    "UPDATE rounds SET active=0,current=0 WHERE image_path=? AND "
                    "label_path=? AND (active=1 OR current=1)", target)
        event = ops.get("event")
        if event:
            db.execute(
                "INSERT OR IGNORE INTO events VALUES(?,?,?,'draft',?)",
                (round_id, event["id"], event["seq"], encode(event)),
            )
        if ops.get("discard_through") is not None:
            db.execute(
                "UPDATE events SET outcome='discarded' WHERE round_id=? "
                "AND seq<=? AND outcome='draft'", (round_id, ops["discard_through"]),
            )
        revision = ops.get("revision")
        if revision or (ops.get("new_round") and state["saved"] is not None):
            db.execute(
                "INSERT OR REPLACE INTO revisions VALUES(?,?,?,?)",
                (round_id, state["revision"], state["saved_seq"], encode(state["saved"])),
            )
            db.execute(
                "UPDATE events SET outcome='saved' WHERE round_id=? "
                "AND seq<=? AND outcome='draft'", (round_id, state["saved_seq"]),
            )
        if ops.get("completion"):
            comp = ops["completion"]
            db.execute("INSERT OR IGNORE INTO completions VALUES(?,?,?,?)",
                       (comp["id"], round_id, comp["revision"], encode(comp)))
        db.execute(
            "INSERT INTO rounds VALUES(?,?,?,?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET active=excluded.active,"
            "current=excluded.current,state=excluded.state,report=excluded.report",
            (round_id, state["image_path"], state["label_path"], state["phase"],
             int(state["active"]), int(state["current"]), encode(state), encode(report_row(state))),
        )

    def _writer(self):
        db = None
        failed = False
        try:
            db = sqlite3.connect(self.path, timeout=0.12)
            while True:
                item = self._queue.get()
                if item is None:
                    return
                kind, arg, ops = item
                if kind == "barrier":
                    ops.append(not failed)
                    failed = False
                    arg.set()
                    continue
                try:
                    with db:
                        if kind == "prediction":
                            db.execute("INSERT OR REPLACE INTO predictions VALUES(?,?,?,?,?)", arg)
                        else:
                            self._write(db, arg, ops)
                except (sqlite3.Error, ValueError, TypeError, OSError) as exc:
                    failed = True
                    self._fault(arg["round_id"] if kind == "write" else "", exc)
        except sqlite3.Error as exc:
            self._fault("", exc)
        finally:
            if db is not None:
                db.close()

    def flush(self, timeout=2):
        if self._closed or self._thread is None or not self._thread.is_alive():
            return False
        deadline = time.monotonic() + timeout
        barrier, ok = threading.Event(), []
        try:
            self._queue.put(("barrier", barrier, ok), timeout=timeout)
        except queue.Full:
            return False
        return barrier.wait(max(0, deadline - time.monotonic())) and ok == [True]

    def close(self, timeout=2):
        if self._closed:
            return
        if self._thread and self._thread.is_alive():
            self.flush(timeout)
            try:
                self._queue.put(None, timeout=timeout)
            except queue.Full:
                self._fault("", "database writer still draining")
                return
            self._thread.join(timeout)
        self._closed = True

    def open_existing(self, round_id):
        with self._state_lock:
            found = self._live.get(round_id)
            if found is not None:
                return found
            try:
                db = self._reader()
                try:
                    row = db.execute(
                        "SELECT state,active,current FROM rounds WHERE id=?", (round_id,)
                    ).fetchone()
                    if row is None:
                        return None
                    state = json.loads(row[0])
                    state.update(active=bool(row[1]), current=bool(row[2]))
                    seen = [r[0] for r in db.execute(
                        "SELECT tx FROM events WHERE round_id=?", (round_id,))]
                finally:
                    db.close()
            except (sqlite3.Error, ValueError) as exc:
                self._fault(round_id, exc)
                return None
            obj = CorrectionRound(self, state, seen)
            self._live[round_id] = obj
            return obj

    def latest(self, image_path, label_path, phase=None):
        image, label = path_identity(image_path), path_identity(label_path)
        with self._state_lock:
            for obj in reversed(list(self._live.values())):
                s = obj._state
                if (s["image_path"] == image and s["label_path"] == label
                    and s["active"] and (phase is None or s["phase"] == phase)):
                    return obj
            if self._thread is None:
                return None
            query = "SELECT id FROM rounds WHERE image_path=? AND label_path=? AND active=1"
            args = [image, label]
            if phase:
                query += " AND phase=?"
                args.append(phase)
            try:
                db = self._reader()
                try:
                    row = db.execute(query + " ORDER BY rowid DESC LIMIT 1", args).fetchone()
                finally:
                    db.close()
            except sqlite3.Error as exc:
                self._fault("", exc)
                return None
            return self.open_existing(row[0]) if row else None

    def open_round(self, image_path, label_path, image_digest, shapes, *,
                   origin="unknown-existing", provenance=None, predicted_ids=(),
                   saved=True, force_new=False, phase="correction"):
        data = snapshot(shapes)
        with self._state_lock:
            prev = self.latest(image_path, label_path, phase)
            if prev and not force_new and prev._state["image_digest"] == image_digest:
                self._recover(prev, data, saved)
                return prev
            s = initialise_state(self.dataset_id, image_path, label_path, image_digest,
                                 data, origin, provenance, predicted_ids, saved, phase)
            if prev and prev._state["image_digest"] != image_digest:
                s["issues"] = sorted({*s["issues"], "image-content-changed"})
            for obj in list(self._live.values()):
                prior = obj._state
                if (obj.image_path == s["image_path"] and obj.label_path == s["label_path"]
                    and (phase != "review" or prior["phase"] == "review")):
                    prior.update(active=False, current=False)
            current = CorrectionRound(self, s)
            self._live[current.round_id] = current
            current._persist(new_round=True)
            return current

    def _recover(self, obj, disk, saved):
        s = obj._state
        pending = s["pending"]
        if saved and pending and pending["target"] == obj.label_path:
            if disk == pending["snapshot"]:
                obj.saved(pending)
            else:
                obj.save_failed(pending)
        if saved and disk == s["saved"] and s["draft"] != disk:
            obj.discard()
            obj.mark_gap("interrupted-draft")
        elif saved and disk != s["saved"]:
            s["draft"] = disk
            s["completed"] = False
            obj.mark_gap("external-annotation-change")
        orphan = {key for key, rec in s["sessions"].items()
                  if not rec.get("closed") and key != self.session_id}
        if orphan:
            s["sessions"] = {k: ({**v, "closed": True} if k in orphan else v)
                             for k, v in s["sessions"].items()}
            obj.mark_gap("interrupted-time")
        obj._persist()

    def record_prediction(self, image_path, label_path, provenance, status):
        source = safe_provenance(provenance)
        run = source.get("run_id") or uid()
        args = (run, path_identity(image_path), path_identity(label_path), status, encode(source))
        if not self._closed and self._thread and self._thread.is_alive():
            try:
                self._queue.put_nowait(("prediction", args, None))
                return run
            except queue.Full:
                pass
        # A lost prediction record must stay visible on the affected image:
        # an unattributed gap would never be shown to the user.
        self._fault("", "prediction record unavailable",
                    target=(image_path, label_path), kind="prediction-gap")
        return None

    def iter_rows(self, limit=None, offset=0):
        """Take one read snapshot now. Use and close the iterator in the reader worker."""
        if self._thread is None:
            return iter(())
        db = self._reader()
        try:
            db.execute("BEGIN")
            cursor = db.execute(
                "SELECT report,current FROM rounds ORDER BY rowid DESC LIMIT ? OFFSET ?",
                (max(0, int(limit)) if limit is not None else -1, max(0, int(offset))),
            )
        except BaseException:
            db.close()
            raise

        def read():
            try:
                for payload, current in cursor:
                    row = json.loads(payload)
                    row["current"] = bool(current)
                    faults = (self.gaps(row["round_id"])
                              | self.gaps_for(row["image_path"], row["label_path"]))
                    if faults:
                        row["issues"] = sorted(set(row["issues"]) | faults)
                        row["comparable"] = False
                    yield row
            finally:
                db.close()

        return read()

    def rows(self, limit=None, offset=0):
        return list(self.iter_rows(limit, offset))

    def count(self):
        if self._thread is None:
            return 0
        db = self._reader()
        try:
            return db.execute("SELECT count(*) FROM rounds").fetchone()[0]
        finally:
            db.close()

    def events(self, round_id):
        db = self._reader()
        try:
            return [
                {**json.loads(data), "outcome": outcome} for data, outcome in
                db.execute("SELECT data,outcome FROM events WHERE round_id=? ORDER BY seq",
                           (round_id,))
            ]
        finally:
            db.close()
