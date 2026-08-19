"""Transactional SQLite store for review-queue sidecars.

The store owns every SQL statement used by the queue.  It enforces the
writer lease, optimistic logical-revision verification, transactional
outcome/cursor commits, reconciliation recording, and transactional
rebuild publication.  The module is pure Python: it must stay free of
Qt imports so the high-risk transaction logic is testable headless.
"""

from __future__ import annotations

import json
import os
import os.path as osp
import platform
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional, Sequence

from .queue_models import (
    DEFAULT_FILTER,
    TRUSTED_BINDINGS,
    VALID_OUTCOMES,
    AtomicTaskRecord,
    BindingState,
    FileAvailability,
    PageRecord,
    QueueFilter,
    QueueSnapshot,
    SourceFileRecord,
    TaskFreshness,
    TaskOutcome,
)
from .schema import (
    MIGRATIONS,
    SCHEMA_VERSION,
    SIDECAR_SUFFIX,
    expected_tables,
    initialize_schema,
    read_schema_version,
)
from .locators import FileReconcileReport, evaluate_task_freshness
from .serialization import locator_signature as _locator_signature

BUSY_TIMEOUT_MS = 5000
LEASE_STALE_AFTER_SECONDS = 300.0
INSERT_BATCH_SIZE = 50


def utc_now_iso() -> str:
    """Return a timezone-aware UTC timestamp string."""

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def process_alive(pid: int) -> bool:
    """Return whether a process id is alive on this host (best effort)."""

    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        return False
    try:
        if os.name == "nt":
            import ctypes

            query_info = 0x1000  # PROCESS_QUERY_LIMITED_INFORMATION
            handle = ctypes.windll.kernel32.OpenProcess(query_info, 0, pid)
            if not handle:
                return False
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        os.kill(pid, 0)
        return True
    except (OSError, ValueError, AttributeError):
        return False


class StoreError(Exception):
    """Base error for sidecar storage failures."""


class InvalidSidecar(StoreError):
    """The file is not a recognizable review sidecar."""


class SchemaVersionTooNew(StoreError):
    """The sidecar schema version is newer than supported."""

    def __init__(self, version: int) -> None:
        """Record the offending version."""

        super().__init__(f"unsupported newer schema version: {version}")
        self.version = version


class IntegrityFailure(StoreError):
    """Schema, foreign-key, or integrity validation failed."""

    def __init__(self, diagnostics: Sequence[str]) -> None:
        """Record validation diagnostics."""

        super().__init__("; ".join(diagnostics))
        self.diagnostics = list(diagnostics)


class MigrationFailure(StoreError):
    """A schema migration could not be applied."""


class ReadOnlyStore(StoreError):
    """A mutation was requested on a read-only connection."""


class LeaseHeld(StoreError):
    """Another instance owns the writer lease."""

    def __init__(self, holder: dict, stale: bool) -> None:
        """Record holder details and staleness."""

        super().__init__(f"writer lease held by {holder.get('instance_id')}")
        self.holder = holder
        self.stale = stale


class LeaseLost(StoreError):
    """The lease no longer belongs to this instance."""


class RevisionConflict(StoreError):
    """The logical revision changed unexpectedly."""

    def __init__(self, expected: int, actual: int) -> None:
        """Record expected and actual logical revisions."""

        super().__init__(
            f"logical revision conflict: expected {expected}, "
            f"found {actual}"
        )
        self.expected = expected
        self.actual = actual


class NotFound(StoreError):
    """A referenced row does not exist in this revision."""


class InvalidOutcomeTarget(StoreError):
    """An outcome change targets an untrusted or unknown task."""

    def __init__(self, message: str, task_ids: Sequence[str] = ()) -> None:
        """Record the rejection reason and offending tasks."""

        super().__init__(message)
        self.task_ids = list(task_ids)


@dataclass(frozen=True)
class MutationResult:
    """Result of one durable sidecar mutation."""

    logical_revision: int
    detail: dict = field(default_factory=dict)


@dataclass(frozen=True)
class CursorRecord:
    """Durable navigation cursor."""

    active_revision: int
    page_id: Optional[str]
    filter_name: QueueFilter
    updated_at: str


@dataclass(frozen=True)
class RevisionMeta:
    """Frozen definition of one queue revision."""

    revision: int
    state: str
    criteria_json: str
    packing_json: str
    reference_viewport_json: str
    created_at: str
    build_diagnostics: dict


@dataclass
class RevisionContent:
    """Insertable rows for one queue revision."""

    revision: int
    criteria_json: str
    packing_json: str
    reference_viewport_json: str
    created_at: str
    build_diagnostics: dict
    files: list
    tasks: list
    pages: list


@dataclass(frozen=True)
class OutcomeChange:
    """One requested atomic-task outcome transition."""

    task_id: str
    outcome: TaskOutcome
    reviewed_signature: Optional[str] = None
    note: Optional[str] = None

    def __post_init__(self) -> None:
        """Validate the outcome value at construction time."""

        outcome = self.outcome
        if isinstance(outcome, str):
            outcome = TaskOutcome(outcome)
        if outcome.value not in VALID_OUTCOMES:
            raise ValueError(f"invalid outcome: {self.outcome}")
        object.__setattr__(self, "outcome", outcome)


def _connect(path: str, readonly: bool = False) -> sqlite3.Connection:
    """Open one sidecar connection with standard pragmas."""

    if readonly:
        from pathlib import Path

        conn = sqlite3.connect(
            Path(osp.abspath(path)).as_uri() + "?mode=ro",
            uri=True,
            timeout=BUSY_TIMEOUT_MS / 1000.0,
            isolation_level=None,
        )
    else:
        conn = sqlite3.connect(
            path,
            timeout=BUSY_TIMEOUT_MS / 1000.0,
            isolation_level=None,
        )
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    return conn


class ReviewStore:
    """Own the sidecar connection, lease, and transactional mutations."""

    def __init__(
        self,
        path: str,
        conn: sqlite3.Connection,
        editable: bool,
        instance_id: Optional[str] = None,
    ) -> None:
        """Wrap an open connection; prefer the class factory methods."""

        self._path = str(path)
        self._conn = conn
        self._editable = editable
        self._instance_id = instance_id or uuid.uuid4().hex
        self._closed = False

    # ── lifecycle ─────────────────────────────────────────────

    @classmethod
    def create(
        cls,
        path: str,
        dataset_root_hint: str = "",
        app_version: str = "",
    ) -> "ReviewStore":
        """Create a new empty sidecar with the current schema."""

        if osp.exists(path):
            raise InvalidSidecar(f"sidecar already exists: {path}")
        parent = osp.dirname(osp.abspath(path))
        if not osp.isdir(parent):
            raise InvalidSidecar(f"sidecar directory missing: {parent}")
        conn = _connect(path)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=FULL")
            initialize_schema(conn, app_version)
            stamp = utc_now_iso()
            for key, value in (
                ("queue_id", uuid.uuid4().hex),
                ("created_at", stamp),
                ("updated_at", stamp),
                ("active_revision", "0"),
                ("logical_revision", "1"),
                ("dataset_root_hint", str(dataset_root_hint)),
            ):
                conn.execute(
                    "INSERT OR REPLACE INTO queue_meta(key, value) "
                    "VALUES (?, ?)",
                    (key, value),
                )
        except sqlite3.Error:
            conn.close()
            raise
        store = cls(path, conn, editable=True)
        store.acquire_lease()
        return store

    @classmethod
    def open(
        cls,
        path: str,
        editable: bool = True,
        takeover: bool = False,
    ) -> "ReviewStore":
        """Open an existing sidecar with full validation.

        Newer schema versions are rejected without modifying the file;
        read-only opens still succeed so diagnostics can be produced.
        Older versions migrate transactionally after a backup when
        editable, and refuse migration when read-only.
        """

        if not osp.isfile(path):
            raise InvalidSidecar(f"not a sidecar file: {path}")
        conn = _connect(path, readonly=not editable)
        try:
            version = read_schema_version(conn)
            if version is None:
                raise InvalidSidecar("missing schema version")
            if version > SCHEMA_VERSION:
                # Newer sidecars are never modified by this build; a
                # read-only diagnostic open stays available.
                if editable:
                    raise SchemaVersionTooNew(version)
            store = cls(path, conn, editable=editable)
            if version < SCHEMA_VERSION:
                if not editable:
                    raise MigrationFailure(
                        "older schema requires an editable migration"
                    )
                store._migrate(version)
            diagnostics = store.validate()
            if diagnostics:
                raise IntegrityFailure(diagnostics)
            if editable:
                store.acquire_lease(force=takeover)
            return store
        except Exception:
            try:
                conn.close()
            except sqlite3.Error:
                pass
            raise

    def close(self) -> None:
        """Release the lease, checkpoint WAL, and close the handle."""

        if self._closed:
            return
        try:
            if self._editable:
                try:
                    self.release_lease()
                except StoreError:
                    pass
                try:
                    self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                except sqlite3.Error:
                    pass
        finally:
            self._closed = True
            try:
                self._conn.close()
            except sqlite3.Error:
                pass

    # ── meta and validation ───────────────────────────────────

    def meta(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """Read one queue_meta value."""

        row = self._conn.execute(
            "SELECT value FROM queue_meta WHERE key = ?", (key,)
        ).fetchone()
        return default if row is None else str(row[0])

    def set_meta(self, key: str, value: str) -> None:
        """Write one queue_meta value (idempotent maintenance helper)."""

        self._require_editable()
        self._conn.execute(
            "INSERT OR REPLACE INTO queue_meta(key, value) VALUES (?, ?)",
            (key, str(value)),
        )

    @property
    def path(self) -> str:
        """Return the sidecar filesystem path."""

        return self._path

    @property
    def editable(self) -> bool:
        """Return whether mutations are allowed."""

        return self._editable

    @property
    def instance_id(self) -> str:
        """Return this connection's lease instance id."""

        return self._instance_id

    def raw_connection(self) -> sqlite3.Connection:
        """Return the underlying connection for read-only validation."""

        return self._conn

    @property
    def logical_revision(self) -> int:
        """Return the current logical revision counter."""

        value = self.meta("logical_revision", "1")
        try:
            return int(str(value))
        except (TypeError, ValueError):
            return 1

    @property
    def active_revision(self) -> int:
        """Return the active frozen revision number."""

        value = self.meta("active_revision", "0")
        try:
            return int(str(value))
        except (TypeError, ValueError):
            return 0

    def validate(self) -> list:
        """Return integrity and schema diagnostics; empty means valid."""

        diagnostics: list = []
        try:
            row = self._conn.execute("PRAGMA integrity_check").fetchone()
            if row is None or str(row[0]).lower() != "ok":
                diagnostics.append(f"integrity_check: {row}")
            violations = self._conn.execute(
                "PRAGMA foreign_key_check"
            ).fetchall()
            for violation in violations:
                diagnostics.append(f"foreign_key_check: {violation}")
            present = {
                str(row[0])
                for row in self._conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            missing = sorted(expected_tables() - present)
            if missing:
                diagnostics.append(f"missing tables: {missing}")
        except sqlite3.Error as exc:
            diagnostics.append(f"sqlite error: {exc}")
        return diagnostics

    # ── writer lease ──────────────────────────────────────────

    def lease_info(self) -> Optional[dict]:
        """Return the current lease row as a dict, if any."""

        row = self._conn.execute(
            "SELECT instance_id, pid, host, acquired_at, heartbeat_at "
            "FROM writer_lease WHERE id = 1"
        ).fetchone()
        if row is None:
            return None
        return {
            "instance_id": str(row[0]),
            "pid": int(row[1]),
            "host": str(row[2]),
            "acquired_at": str(row[3]),
            "heartbeat_at": str(row[4]),
        }

    @staticmethod
    def _holder_is_stale(holder: dict) -> bool:
        """Return whether a lease holder looks dead or far expired."""

        try:
            heartbeat = datetime.fromisoformat(holder["heartbeat_at"])
            age = (datetime.now(timezone.utc) - heartbeat).total_seconds()
        except (KeyError, ValueError):
            return True
        if age <= LEASE_STALE_AFTER_SECONDS:
            return False
        same_host = holder.get("host") == platform.node()
        if not same_host:
            return True
        return not process_alive(int(holder.get("pid", 0)))

    def acquire_lease(self, force: bool = False) -> None:
        """Claim the single-writer lease in one immediate transaction.

        A live foreign holder always rejects acquisition.  A stale
        holder only loses the lease when ``force`` carries the
        reviewer's explicit takeover confirmation; the takeover is then
        recorded as a reconciliation event.
        """

        self._require_editable()
        now = utc_now_iso()
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            holder = self.lease_info()
            if holder is None:
                self._conn.execute(
                    "INSERT INTO writer_lease "
                    "(id, instance_id, pid, host, acquired_at, "
                    "heartbeat_at) VALUES (1, ?, ?, ?, ?, ?)",
                    (
                        self._instance_id,
                        os.getpid(),
                        platform.node(),
                        now,
                        now,
                    ),
                )
            elif holder["instance_id"] == self._instance_id:
                self._conn.execute(
                    "UPDATE writer_lease SET heartbeat_at = ? " "WHERE id = 1",
                    (now,),
                )
            else:
                stale = self._holder_is_stale(holder)
                if not stale or not force:
                    self._conn.execute("ROLLBACK")
                    raise LeaseHeld(holder, stale)
                self._conn.execute(
                    "INSERT OR REPLACE INTO writer_lease "
                    "(id, instance_id, pid, host, acquired_at, "
                    "heartbeat_at) VALUES (1, ?, ?, ?, ?, ?)",
                    (
                        self._instance_id,
                        os.getpid(),
                        platform.node(),
                        now,
                        now,
                    ),
                )
                self._append_reconciliation_event(
                    self.active_revision,
                    kind="lease_takeover",
                    detail={
                        "previous_holder": holder,
                        "new_instance": self._instance_id,
                    },
                    occurred_at=now,
                    commit=False,
                )
            self._conn.execute("COMMIT")
        except Exception:
            self._safe_rollback()
            raise

    def heartbeat(self) -> None:
        """Refresh the lease heartbeat after verifying ownership."""

        self._require_editable()
        now = utc_now_iso()
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            holder = self.lease_info()
            if holder is None or holder["instance_id"] != (self._instance_id):
                raise LeaseLost("lease not owned by this instance")
            self._conn.execute(
                "UPDATE writer_lease SET heartbeat_at = ? WHERE id = 1",
                (now,),
            )
            self._conn.execute("COMMIT")
        except Exception:
            self._safe_rollback()
            raise

    def release_lease(self) -> None:
        """Delete the lease row when this instance owns it."""

        self._require_editable()
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            holder = self.lease_info()
            if holder is not None and holder["instance_id"] != (
                self._instance_id
            ):
                raise LeaseLost("lease not owned by this instance")
            self._conn.execute("DELETE FROM writer_lease WHERE id = 1")
            self._conn.execute("COMMIT")
        except Exception:
            self._safe_rollback()
            raise

    # ── revision content ──────────────────────────────────────

    def insert_revision(
        self,
        content: RevisionContent,
        make_active: bool = True,
        batch_size: int = INSERT_BATCH_SIZE,
    ) -> None:
        """Insert one revision's rows in batched transactions.

        Rows are inserted parents-first so foreign keys hold at every
        commit boundary; a failure leaves previously committed batches
        in place (staging databases are discarded on failure).
        """

        self._require_editable()
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            self._conn.execute(
                "INSERT INTO queue_revision "
                "(revision, state, criteria_json, packing_json, "
                "reference_viewport_json, created_at, "
                "build_diagnostics_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    content.revision,
                    "active" if make_active else "archived",
                    content.criteria_json,
                    content.packing_json,
                    content.reference_viewport_json,
                    content.created_at,
                    json.dumps(
                        content.build_diagnostics,
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                ),
            )
            self._conn.execute("COMMIT")
        except Exception:
            self._safe_rollback()
            raise
        self._insert_files(content, batch_size)
        self._insert_tasks(content, batch_size)
        self._insert_pages(content, batch_size)
        if make_active:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                self._conn.execute(
                    "INSERT OR REPLACE INTO queue_meta(key, value) "
                    "VALUES ('active_revision', ?)",
                    (str(content.revision),),
                )
                self._conn.execute(
                    "INSERT OR REPLACE INTO queue_meta(key, value) "
                    "VALUES ('updated_at', ?)",
                    (utc_now_iso(),),
                )
                self._conn.execute("COMMIT")
            except Exception:
                self._safe_rollback()
                raise

    def _insert_files(self, content: RevisionContent, batch_size: int) -> None:
        """Insert source files in batches."""

        rows = [
            (
                content.revision,
                record.file_id,
                record.order,
                record.image_rel_path,
                record.label_rel_path,
                record.availability.value,
                record.exclusion_reason,
                record.source_signature,
            )
            for record in content.files
        ]
        self._batch_insert(
            "INSERT INTO source_file (revision, file_id, file_order, "
            "image_rel_path, label_rel_path, availability, "
            "exclusion_reason, source_signature) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
            batch_size,
        )

    def _insert_tasks(self, content: RevisionContent, batch_size: int) -> None:
        """Insert atomic tasks in batches."""

        rows = [
            (
                content.revision,
                record.task_id,
                record.file_id,
                record.source_order,
                json.dumps(
                    record.locator,
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                record.outcome.value,
                record.freshness.value,
                record.binding_state.value,
                record.reviewed_signature,
                record.current_signature,
                record.note,
                record.carried_from,
                record.created_at,
                record.updated_at,
            )
            for record in content.tasks
        ]
        self._batch_insert(
            "INSERT INTO atomic_task (revision, task_id, file_id, "
            "source_order, locator_json, outcome, freshness, "
            "binding_state, reviewed_signature, current_signature, "
            "note, carried_from, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
            batch_size,
        )

    def _insert_pages(self, content: RevisionContent, batch_size: int) -> None:
        """Insert pages and page-task membership in batches."""

        page_rows = []
        membership_rows = []
        for record in content.pages:
            page_rows.append(
                (
                    content.revision,
                    record.page_id,
                    record.file_id,
                    record.order,
                    (
                        json.dumps(list(record.bbox))
                        if record.bbox is not None
                        else None
                    ),
                    float(record.projected_scale),
                    int(bool(record.fallback)),
                )
            )
            for slot, task_id in enumerate(record.task_ids):
                membership_rows.append(
                    (content.revision, record.page_id, task_id, slot)
                )
        self._batch_insert(
            "INSERT INTO review_page (revision, page_id, file_id, "
            "page_order, bbox_json, projected_scale, fallback) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            page_rows,
            batch_size,
        )
        self._batch_insert(
            "INSERT INTO page_task (revision, page_id, task_id, slot) "
            "VALUES (?, ?, ?, ?)",
            membership_rows,
            batch_size,
        )

    def _batch_insert(
        self, statement: str, rows: Sequence[tuple], batch_size: int
    ) -> None:
        """Insert rows in bounded transactions."""

        for start in range(0, len(rows), max(1, batch_size)):
            batch = rows[start : start + max(1, batch_size)]
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                self._conn.executemany(statement, batch)
                self._conn.execute("COMMIT")
            except Exception:
                self._safe_rollback()
                raise

    def load_revision_meta(
        self, revision: Optional[int] = None
    ) -> RevisionMeta:
        """Load one revision's frozen definition."""

        rev = self.active_revision if revision is None else revision
        row = self._conn.execute(
            "SELECT revision, state, criteria_json, packing_json, "
            "reference_viewport_json, created_at, "
            "build_diagnostics_json FROM queue_revision "
            "WHERE revision = ?",
            (rev,),
        ).fetchone()
        if row is None:
            raise NotFound(f"revision {rev} not found")
        try:
            diagnostics = json.loads(str(row[6]) or "{}")
        except json.JSONDecodeError:
            diagnostics = {}
        return RevisionMeta(
            revision=int(row[0]),
            state=str(row[1]),
            criteria_json=str(row[2]),
            packing_json=str(row[3]),
            reference_viewport_json=str(row[4]),
            created_at=str(row[5]),
            build_diagnostics=diagnostics,
        )

    def load_snapshot(self, revision: Optional[int] = None) -> QueueSnapshot:
        """Load one revision into a frozen snapshot."""

        rev = self.active_revision if revision is None else revision
        files = tuple(
            SourceFileRecord(
                file_id=str(row[0]),
                order=int(row[1]),
                image_rel_path=str(row[2]),
                label_rel_path=str(row[3]),
                availability=FileAvailability(str(row[4])),
                exclusion_reason=row[5],
                source_signature=row[6],
            )
            for row in self._conn.execute(
                "SELECT file_id, file_order, image_rel_path, "
                "label_rel_path, availability, exclusion_reason, "
                "source_signature FROM source_file WHERE revision = ? "
                "ORDER BY file_order",
                (rev,),
            )
        )
        membership: dict[str, list[str]] = {}
        for page_id, task_id in self._conn.execute(
            "SELECT page_id, task_id FROM page_task "
            "WHERE revision = ? ORDER BY page_id, slot",
            (rev,),
        ):
            membership.setdefault(str(page_id), []).append(str(task_id))
        pages = tuple(
            PageRecord(
                page_id=str(row[0]),
                file_id=str(row[1]),
                order=int(row[2]),
                bbox=_decode_bbox(row[3]),
                projected_scale=float(row[4] or 0.0),
                fallback=bool(row[5]),
                task_ids=tuple(membership.get(str(row[0]), ())),
            )
            for row in self._conn.execute(
                "SELECT page_id, file_id, page_order, bbox_json, "
                "projected_scale, fallback FROM review_page "
                "WHERE revision = ? ORDER BY page_order",
                (rev,),
            )
        )
        tasks = tuple(
            AtomicTaskRecord(
                task_id=str(row[0]),
                file_id=str(row[1]),
                source_order=int(row[2]),
                locator=_decode_locator(row[3]),
                outcome=TaskOutcome(str(row[4])),
                freshness=TaskFreshness(str(row[5])),
                binding_state=BindingState(str(row[6])),
                reviewed_signature=row[7],
                current_signature=row[8],
                note=row[9],
                carried_from=row[10],
                created_at=str(row[11]),
                updated_at=str(row[12]),
            )
            for row in self._conn.execute(
                "SELECT task_id, file_id, source_order, locator_json, "
                "outcome, freshness, binding_state, reviewed_signature, "
                "current_signature, note, carried_from, created_at, "
                "updated_at FROM atomic_task WHERE revision = ? "
                "ORDER BY file_id, source_order",
                (rev,),
            )
        )
        cursor = self.load_cursor()
        filter_name = (
            cursor.filter_name if cursor is not None else DEFAULT_FILTER
        )
        return QueueSnapshot(
            revision=rev,
            files=files,
            pages=pages,
            tasks=tasks,
            filter_name=filter_name,
        )

    def load_cursor(self) -> Optional[CursorRecord]:
        """Load the durable cursor, if one exists."""

        row = self._conn.execute(
            "SELECT active_revision, page_id, filter_name, updated_at "
            "FROM cursor_state WHERE id = 1"
        ).fetchone()
        if row is None:
            return None
        return CursorRecord(
            active_revision=int(row[0]),
            page_id=None if row[1] is None else str(row[1]),
            filter_name=_safe_filter(row[2]),
            updated_at=str(row[3]),
        )

    # ── outcome and cursor mutations ──────────────────────────

    def apply_outcomes(
        self,
        revision: int,
        changes: Sequence[OutcomeChange],
        expected_logical_revision: int,
    ) -> MutationResult:
        """Commit outcome transitions atomically in one transaction.

        The transaction verifies lease ownership and the expected
        logical revision, rejects untrusted or unknown targets, appends
        one outcome event per task, and increments the logical revision.
        Any failure rolls the whole batch back.
        """

        self._require_editable()
        if not changes:
            return MutationResult(self.logical_revision)
        now = utc_now_iso()
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            self._verify_lease()
            self._verify_logical_revision(expected_logical_revision)
            updated: list[str] = []
            for change in changes:
                row = self._conn.execute(
                    "SELECT outcome, binding_state, current_signature "
                    "FROM atomic_task WHERE revision = ? AND task_id = ?",
                    (revision, change.task_id),
                ).fetchone()
                if row is None:
                    raise NotFound(
                        f"task {change.task_id} not in revision {revision}"
                    )
                if BindingState(str(row[1])) not in TRUSTED_BINDINGS:
                    raise InvalidOutcomeTarget(
                        f"task {change.task_id} has no trustworthy "
                        "live binding",
                        [change.task_id],
                    )
                reviewed = change.reviewed_signature
                if change.outcome is TaskOutcome.COMPLETED:
                    reviewed = reviewed or row[2]
                    if not reviewed:
                        raise InvalidOutcomeTarget(
                            f"task {change.task_id} has no reviewed "
                            "signature",
                            [change.task_id],
                        )
                    self._conn.execute(
                        "UPDATE atomic_task SET outcome = ?, "
                        "freshness = 'fresh', reviewed_signature = ?, "
                        "note = COALESCE(?, note), updated_at = ? "
                        "WHERE revision = ? AND task_id = ?",
                        (
                            change.outcome.value,
                            reviewed,
                            change.note,
                            now,
                            revision,
                            change.task_id,
                        ),
                    )
                else:
                    self._conn.execute(
                        "UPDATE atomic_task SET outcome = ?, "
                        "freshness = 'fresh', "
                        "note = COALESCE(?, note), updated_at = ? "
                        "WHERE revision = ? AND task_id = ?",
                        (
                            change.outcome.value,
                            change.note,
                            now,
                            revision,
                            change.task_id,
                        ),
                    )
                self._conn.execute(
                    "INSERT INTO outcome_event (revision, task_id, "
                    "outcome, previous_outcome, note, occurred_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        revision,
                        change.task_id,
                        change.outcome.value,
                        str(row[0]),
                        change.note,
                        now,
                    ),
                )
                updated.append(change.task_id)
            new_revision = self._bump_logical_revision(now)
            self._conn.execute("COMMIT")
            return MutationResult(new_revision, {"tasks": updated})
        except Exception:
            self._safe_rollback()
            raise

    def commit_cursor(
        self,
        revision: int,
        page_id: Optional[str],
        filter_name: QueueFilter,
        expected_logical_revision: int,
    ) -> MutationResult:
        """Persist the durable cursor after a successful activation."""

        self._require_editable()
        flt = _safe_filter(filter_name)
        now = utc_now_iso()
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            self._verify_lease()
            self._verify_logical_revision(expected_logical_revision)
            if page_id is not None:
                row = self._conn.execute(
                    "SELECT page_id FROM review_page "
                    "WHERE revision = ? AND page_id = ?",
                    (revision, page_id),
                ).fetchone()
                if row is None:
                    raise NotFound(
                        f"page {page_id} not in revision {revision}"
                    )
            self._conn.execute(
                "INSERT OR REPLACE INTO cursor_state "
                "(id, active_revision, page_id, filter_name, updated_at) "
                "VALUES (1, ?, ?, ?, ?)",
                (revision, page_id, flt.value, now),
            )
            new_revision = self._bump_logical_revision(now)
            self._conn.execute("COMMIT")
            return MutationResult(new_revision)
        except Exception:
            self._safe_rollback()
            raise

    # ── reconciliation ────────────────────────────────────────

    def record_reconciliation(
        self,
        revision: int,
        reports: Sequence[FileReconcileReport],
        expected_logical_revision: int,
        dataset_root: Optional[str] = None,
    ) -> MutationResult:
        """Apply reconcile results without touching frozen membership.

        Only availability, source signatures, binding states, current
        signatures, and derived freshness change.  Outcomes, order, and
        page membership stay frozen; the whole update commits in one
        transaction with an appended reconciliation event.
        """

        self._require_editable()
        now = utc_now_iso()
        counts = {"missing_files": 0, "rebound_tasks": 0, "stale": 0}
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            self._verify_lease()
            self._verify_logical_revision(expected_logical_revision)
            for report in reports:
                file_row = self._conn.execute(
                    "SELECT file_id FROM source_file "
                    "WHERE revision = ? AND file_id = ?",
                    (revision, report.file_id),
                ).fetchone()
                if file_row is None:
                    raise NotFound(
                        f"file {report.file_id} not in revision {revision}"
                    )
                availability = _safe_availability(report.availability)
                image_rel = report.image_rel_path
                label_rel = report.label_rel_path
                self._conn.execute(
                    "UPDATE source_file SET availability = ?, "
                    "source_signature = COALESCE(?, source_signature), "
                    "image_rel_path = COALESCE(?, image_rel_path), "
                    "label_rel_path = COALESCE(?, label_rel_path) "
                    "WHERE revision = ? AND file_id = ?",
                    (
                        availability.value,
                        report.source_signature,
                        image_rel,
                        label_rel,
                        revision,
                        report.file_id,
                    ),
                )
                if availability is FileAvailability.MISSING:
                    counts["missing_files"] += 1
                for task_id, binding in report.task_bindings.items():
                    row = self._conn.execute(
                        "SELECT outcome, reviewed_signature, "
                        "binding_state FROM atomic_task "
                        "WHERE revision = ? AND task_id = ?",
                        (revision, task_id),
                    ).fetchone()
                    if row is None:
                        raise NotFound(
                            f"task {task_id} not in revision {revision}"
                        )
                    trusted = binding.state in TRUSTED_BINDINGS
                    freshness = evaluate_task_freshness(
                        TaskOutcome(str(row[0])),
                        row[1],
                        binding.current_signature,
                        trusted,
                    )
                    if freshness is TaskFreshness.STALE:
                        counts["stale"] += 1
                    if trusted and str(row[2]) != binding.state.value:
                        counts["rebound_tasks"] += 1
                    self._conn.execute(
                        "UPDATE atomic_task SET binding_state = ?, "
                        "current_signature = ?, freshness = ? "
                        "WHERE revision = ? AND task_id = ?",
                        (
                            binding.state.value,
                            binding.current_signature,
                            freshness.value,
                            revision,
                            task_id,
                        ),
                    )
            self._append_reconciliation_event(
                revision,
                kind="reconcile",
                detail={
                    "counts": counts,
                    "new_candidates": sum(
                        report.new_candidate_count for report in reports
                    ),
                },
                occurred_at=now,
                commit=False,
            )
            if dataset_root is not None:
                self._conn.execute(
                    "INSERT OR REPLACE INTO queue_meta(key, value) "
                    "VALUES ('dataset_root_hint', ?)",
                    (str(dataset_root),),
                )
            new_revision = self._bump_logical_revision(now)
            self._conn.execute("COMMIT")
            return MutationResult(new_revision, dict(counts))
        except Exception:
            self._safe_rollback()
            raise

    def record_manual_binding(
        self,
        revision: int,
        task_id: str,
        current_signature: Optional[str],
        expected_logical_revision: int,
    ) -> MutationResult:
        """Record an explicit reviewer binding resolution."""

        self._require_editable()
        now = utc_now_iso()
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            self._verify_lease()
            self._verify_logical_revision(expected_logical_revision)
            row = self._conn.execute(
                "SELECT outcome, reviewed_signature FROM atomic_task "
                "WHERE revision = ? AND task_id = ?",
                (revision, task_id),
            ).fetchone()
            if row is None:
                raise NotFound(f"task {task_id} not in revision {revision}")
            freshness = evaluate_task_freshness(
                TaskOutcome(str(row[0])),
                row[1],
                current_signature,
                True,
            )
            self._conn.execute(
                "UPDATE atomic_task SET binding_state = 'manually_bound',"
                " current_signature = ?, freshness = ?, updated_at = ? "
                "WHERE revision = ? AND task_id = ?",
                (current_signature, freshness.value, now, revision, task_id),
            )
            self._append_reconciliation_event(
                revision,
                task_id=task_id,
                kind="manual_binding",
                detail={"signature": current_signature},
                occurred_at=now,
                commit=False,
            )
            new_revision = self._bump_logical_revision(now)
            self._conn.execute("COMMIT")
            return MutationResult(new_revision)
        except Exception:
            self._safe_rollback()
            raise

    # ── rebuild publication ───────────────────────────────────

    def import_revision_from_staging(
        self,
        staging_path: str,
        expected_logical_revision: int,
        confirmed_pairs: Optional[dict] = None,
    ) -> MutationResult:
        """Import a validated staging revision and flip activation.

        The candidate revision is inserted under a new revision number,
        prior outcomes are carried forward only for exact or explicitly
        confirmed task matches, old revision rows are archived but
        retained, and ``active_revision`` flips in the same transaction.
        """

        self._require_editable()
        confirmed_pairs = confirmed_pairs or {}
        staging = _connect(staging_path, readonly=True)
        try:
            candidate = _read_staging_revision(staging)
        finally:
            staging.close()
        now = utc_now_iso()
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            self._verify_lease()
            self._verify_logical_revision(expected_logical_revision)
            old_revision = self.active_revision
            new_revision = old_revision + 1
            carry = _build_carry_index(self._conn, old_revision)
            self._conn.execute(
                "INSERT INTO queue_revision (revision, state, "
                "criteria_json, packing_json, reference_viewport_json, "
                "created_at, build_diagnostics_json) "
                "VALUES (?, 'active', ?, ?, ?, ?, ?)",
                (
                    new_revision,
                    candidate["criteria_json"],
                    candidate["packing_json"],
                    candidate["reference_viewport_json"],
                    candidate["created_at"],
                    candidate["build_diagnostics_json"],
                ),
            )
            if old_revision > 0:
                self._conn.execute(
                    "UPDATE queue_revision SET state = 'archived' "
                    "WHERE revision = ?",
                    (old_revision,),
                )
            carried = 0
            for file_row in candidate["files"]:
                self._conn.execute(
                    "INSERT INTO source_file (revision, file_id, "
                    "file_order, image_rel_path, label_rel_path, "
                    "availability, exclusion_reason, source_signature) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (new_revision,) + tuple(file_row),
                )
            for task in candidate["tasks"]:
                task_id = str(task["task_id"])
                label_rel = str(task["label_rel_path"])
                signature = str(task["signature"])
                old_task = carry.get((label_rel, signature))
                if old_task is None and task_id in confirmed_pairs:
                    old_task = carry.get(
                        ("__by_id__", confirmed_pairs[task_id])
                    )
                outcome = "pending"
                reviewed = None
                carried_from = None
                freshness = "fresh"
                if old_task is not None:
                    outcome = str(old_task["outcome"])
                    reviewed = old_task["reviewed_signature"]
                    carried_from = str(old_task["task_id"])
                    freshness = evaluate_task_freshness(
                        TaskOutcome(outcome),
                        reviewed,
                        signature,
                        True,
                    ).value
                    if outcome != "pending":
                        carried += 1
                self._conn.execute(
                    "INSERT INTO atomic_task (revision, task_id, "
                    "file_id, source_order, locator_json, outcome, "
                    "freshness, binding_state, reviewed_signature, "
                    "current_signature, note, carried_from, created_at, "
                    "updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'ready', "
                    "?, ?, NULL, ?, ?, ?)",
                    (
                        new_revision,
                        task_id,
                        str(task["file_id"]),
                        int(task["source_order"]),
                        str(task["locator_json"]),
                        outcome,
                        freshness,
                        reviewed,
                        signature,
                        carried_from,
                        now,
                        now,
                    ),
                )
            for page in candidate["pages"]:
                self._conn.execute(
                    "INSERT INTO review_page (revision, page_id, "
                    "file_id, page_order, bbox_json, projected_scale, "
                    "fallback) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (new_revision,) + tuple(page),
                )
            for member in candidate["page_task"]:
                self._conn.execute(
                    "INSERT INTO page_task (revision, page_id, task_id, "
                    "slot) VALUES (?, ?, ?, ?)",
                    (new_revision,) + tuple(member),
                )
            self._conn.execute(
                "INSERT OR REPLACE INTO queue_meta(key, value) "
                "VALUES ('active_revision', ?)",
                (str(new_revision),),
            )
            self._conn.execute(
                "UPDATE cursor_state SET page_id = NULL, "
                "active_revision = ?, updated_at = ? WHERE id = 1",
                (new_revision, now),
            )
            self._append_reconciliation_event(
                new_revision,
                kind="rebuild",
                detail={
                    "new_revision": new_revision,
                    "carried": carried,
                    "confirmed": len(confirmed_pairs),
                },
                occurred_at=now,
                commit=False,
            )
            new_logical = self._bump_logical_revision(now)
            self._conn.execute("COMMIT")
            return MutationResult(
                new_logical, {"revision": new_revision, "carried": carried}
            )
        except Exception:
            self._safe_rollback()
            raise

    # ── backup and migration ──────────────────────────────────

    def backup_to(self, destination: str) -> None:
        """Write a consistent backup using the SQLite backup API."""

        parent = osp.dirname(osp.abspath(destination))
        if not osp.isdir(parent):
            raise InvalidSidecar(f"backup directory missing: {parent}")
        if osp.exists(destination):
            os.replace(destination, destination + ".old")
        target = sqlite3.connect(destination, isolation_level=None)
        try:
            self._conn.backup(target)
        finally:
            target.close()
        check = _connect(destination, readonly=True)
        try:
            row = check.execute("PRAGMA integrity_check").fetchone()
            if row is None or str(row[0]).lower() != "ok":
                raise IntegrityFailure(
                    [f"backup integrity_check failed: {row}"]
                )
        finally:
            check.close()

    def _migrate(self, current_version: int) -> None:
        """Migrate an older sidecar inside one transaction after backup."""

        try:
            path = list(MIGRATIONS.path_to_current(current_version))
        except LookupError as exc:
            raise MigrationFailure(str(exc)) from exc
        backup_path = (
            f"{self._path}.pre-v{SCHEMA_VERSION}."
            f"{utc_now_iso().replace(':', '')}.bak"
        )
        self.backup_to(backup_path)
        now = utc_now_iso()
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            for migration in path:
                migration.upgrade(self._conn)
            self._conn.execute(
                "INSERT OR REPLACE INTO queue_meta(key, value) "
                "VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            self._conn.execute(
                "INSERT INTO migration_history (from_version, "
                "to_version, backup_path, applied_at) "
                "VALUES (?, ?, ?, ?)",
                (current_version, SCHEMA_VERSION, backup_path, now),
            )
            diagnostics = self.validate()
            if diagnostics:
                raise IntegrityFailure(diagnostics)
            self._conn.execute("COMMIT")
        except Exception:
            self._safe_rollback()
            raise

    # ── internals ─────────────────────────────────────────────

    def _require_editable(self) -> None:
        """Reject mutations on read-only connections."""

        if self._closed:
            raise StoreError("store is closed")
        if not self._editable:
            raise ReadOnlyStore("store opened read-only")

    def _verify_lease(self) -> None:
        """Verify lease ownership inside an open transaction."""

        holder = self.lease_info()
        if holder is None or holder["instance_id"] != self._instance_id:
            raise LeaseLost("lease not owned by this instance")

    def _verify_logical_revision(self, expected: int) -> None:
        """Verify the logical revision inside an open transaction."""

        row = self._conn.execute(
            "SELECT value FROM queue_meta " "WHERE key = 'logical_revision'"
        ).fetchone()
        try:
            actual = int(str(row[0])) if row is not None else 1
        except (TypeError, ValueError):
            actual = 1
        if actual != expected:
            raise RevisionConflict(expected, actual)

    def _bump_logical_revision(self, now: str) -> int:
        """Increment and return the logical revision (in transaction)."""

        row = self._conn.execute(
            "SELECT value FROM queue_meta " "WHERE key = 'logical_revision'"
        ).fetchone()
        try:
            current = int(str(row[0])) if row is not None else 1
        except (TypeError, ValueError):
            current = 1
        current += 1
        self._conn.execute(
            "INSERT OR REPLACE INTO queue_meta(key, value) "
            "VALUES ('logical_revision', ?)",
            (str(current),),
        )
        self._conn.execute(
            "INSERT OR REPLACE INTO queue_meta(key, value) "
            "VALUES ('updated_at', ?)",
            (now,),
        )
        return current

    def _append_reconciliation_event(
        self,
        revision: int,
        kind: str,
        detail: dict,
        occurred_at: str,
        task_id: Optional[str] = None,
        commit: bool = True,
    ) -> None:
        """Append one reconciliation event row."""

        statement = (
            "INSERT INTO reconciliation_event (revision, task_id, "
            "file_id, kind, detail_json, occurred_at) "
            "VALUES (?, ?, NULL, ?, ?, ?)"
        )
        params = (
            revision,
            task_id,
            kind,
            json.dumps(detail, ensure_ascii=False, sort_keys=True),
            occurred_at,
        )
        if commit:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                self._conn.execute(statement, params)
                self._conn.execute("COMMIT")
            except Exception:
                self._safe_rollback()
                raise
        else:
            self._conn.execute(statement, params)

    def _safe_rollback(self) -> None:
        """Roll back without masking the original exception."""

        try:
            self._conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass


def _decode_bbox(payload: Any) -> Optional[tuple]:
    """Decode a stored bbox payload, failing closed to ``None``."""

    if payload is None:
        return None
    try:
        values = json.loads(str(payload))
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(values, list) or len(values) != 4:
        return None
    try:
        box = tuple(float(value) for value in values)
    except (TypeError, ValueError):
        return None
    return box


def _decode_locator(payload: Any) -> dict:
    """Decode a stored locator payload, failing closed to empty dict."""

    if payload is None:
        return {}
    try:
        locator = json.loads(str(payload))
    except (json.JSONDecodeError, TypeError):
        return {}
    return locator if isinstance(locator, dict) else {}


def _safe_filter(value: Any) -> QueueFilter:
    """Coerce a stored filter name to a valid enum, failing closed."""

    try:
        return QueueFilter(str(value))
    except ValueError:
        return DEFAULT_FILTER


def _safe_availability(value: Any) -> FileAvailability:
    """Coerce an availability string to its enum, failing closed."""

    try:
        return FileAvailability(str(value))
    except ValueError:
        return FileAvailability.MISSING


def _read_staging_revision(conn: sqlite3.Connection) -> dict:
    """Read the single candidate revision from a staging database."""

    row = conn.execute("SELECT MIN(revision) FROM queue_revision").fetchone()
    revision = int(row[0]) if row is not None and row[0] is not None else 1
    meta = conn.execute(
        "SELECT criteria_json, packing_json, reference_viewport_json, "
        "created_at, build_diagnostics_json FROM queue_revision "
        "WHERE revision = ?",
        (revision,),
    ).fetchone()
    if meta is None:
        raise InvalidSidecar("staging database has no revision")
    files = [
        (
            str(row[0]),
            int(row[1]),
            str(row[2]),
            str(row[3]),
            str(row[4]),
            row[5],
            row[6],
        )
        for row in conn.execute(
            "SELECT file_id, file_order, image_rel_path, label_rel_path, "
            "availability, exclusion_reason, source_signature "
            "FROM source_file WHERE revision = ? ORDER BY file_order",
            (revision,),
        )
    ]
    locator_by_task = {}
    tasks = []
    for row in conn.execute(
        "SELECT task_id, file_id, source_order, locator_json "
        "FROM atomic_task WHERE revision = ? ORDER BY file_id, "
        "source_order",
        (revision,),
    ):
        task_id = str(row[0])
        locator_by_task[task_id] = str(row[3])
        tasks.append(
            {
                "task_id": task_id,
                "file_id": str(row[1]),
                "source_order": int(row[2]),
                "locator_json": str(row[3]),
                "signature": _staging_signature(str(row[3])),
            }
        )
    label_by_file = {file_row[0]: file_row[3] for file_row in files}
    for task in tasks:
        task["label_rel_path"] = label_by_file.get(task["file_id"], "")
    pages = [
        (
            str(row[0]),
            str(row[1]),
            int(row[2]),
            row[3],
            float(row[4] or 0.0),
            int(row[5] or 0),
        )
        for row in conn.execute(
            "SELECT page_id, file_id, page_order, bbox_json, "
            "projected_scale, fallback FROM review_page "
            "WHERE revision = ? ORDER BY page_order",
            (revision,),
        )
    ]
    page_task = [
        (str(row[0]), str(row[1]), int(row[2]))
        for row in conn.execute(
            "SELECT page_id, task_id, slot FROM page_task "
            "WHERE revision = ? ORDER BY page_id, slot",
            (revision,),
        )
    ]
    return {
        "criteria_json": str(meta[0]),
        "packing_json": str(meta[1]),
        "reference_viewport_json": str(meta[2]),
        "created_at": str(meta[3]),
        "build_diagnostics_json": str(meta[4] or "{}"),
        "files": files,
        "tasks": tasks,
        "pages": pages,
        "page_task": page_task,
    }


def _staging_signature(locator_json: str) -> str:
    """Return the content signature of a staging locator row."""

    locator = _decode_locator(locator_json)
    return _locator_signature(locator) or ""


def _build_carry_index(conn: sqlite3.Connection, revision: int) -> dict:
    """Index prior tasks by content identity and id for carry-forward."""

    index: dict = {}
    for row in conn.execute(
        "SELECT task_id, outcome, reviewed_signature, locator_json "
        "FROM atomic_task WHERE revision = ?",
        (revision,),
    ):
        task_id = str(row[0])
        locator = _decode_locator(row[3])
        signature = _locator_signature(locator) or ""
        index[("__by_id__", task_id)] = {
            "task_id": task_id,
            "outcome": str(row[1]),
            "reviewed_signature": row[2],
            "signature": signature,
        }
    label_by_file = {
        str(file_row[0]): str(file_row[1])
        for file_row in conn.execute(
            "SELECT file_id, label_rel_path FROM source_file "
            "WHERE revision = ?",
            (revision,),
        )
    }
    for (kind, task_id), entry in list(index.items()):
        if kind != "__by_id__":
            continue
        task_row = conn.execute(
            "SELECT file_id FROM atomic_task "
            "WHERE revision = ? AND task_id = ?",
            (revision, task_id),
        ).fetchone()
        label_rel = (
            label_by_file.get(str(task_row[0]), "")
            if task_row is not None
            else ""
        )
        index[(label_rel, entry["signature"])] = entry
    return index


__all__ = [
    "BUSY_TIMEOUT_MS",
    "CursorRecord",
    "IntegrityFailure",
    "InvalidOutcomeTarget",
    "InvalidSidecar",
    "LEASE_STALE_AFTER_SECONDS",
    "LeaseHeld",
    "LeaseLost",
    "MigrationFailure",
    "MutationResult",
    "NotFound",
    "OutcomeChange",
    "ReadOnlyStore",
    "RevisionConflict",
    "RevisionContent",
    "RevisionMeta",
    "ReviewStore",
    "SCHEMA_VERSION",
    "SchemaVersionTooNew",
    "SIDECAR_SUFFIX",
    "StoreError",
    "process_alive",
    "utc_now_iso",
]
