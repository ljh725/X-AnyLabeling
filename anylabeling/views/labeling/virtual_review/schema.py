"""SQLite schema definition and migration registry for review sidecars.

The schema is the single authority for table layout.  Repositories in
:mod:`virtual_review.store` never issue DDL of their own; they only run
the statements registered here.  Every foreign key is declared so that
``PRAGMA foreign_keys = ON`` enforces membership integrity at write
time.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Callable, Optional, Sequence

SCHEMA_VERSION = 1
SIDECAR_SUFFIX = ".xreview.sqlite3"

_QUEUE_META_DDL = """
CREATE TABLE IF NOT EXISTS queue_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

_REVISION_DDL = """
CREATE TABLE IF NOT EXISTS queue_revision (
    revision INTEGER PRIMARY KEY,
    state TEXT NOT NULL DEFAULT 'active'
        CHECK (state IN ('active', 'archived')),
    criteria_json TEXT NOT NULL,
    packing_json TEXT NOT NULL,
    reference_viewport_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    build_diagnostics_json TEXT NOT NULL DEFAULT '{}'
);
"""

_SOURCE_FILE_DDL = """
CREATE TABLE IF NOT EXISTS source_file (
    file_id TEXT NOT NULL,
    revision INTEGER NOT NULL REFERENCES queue_revision(revision),
    file_order INTEGER NOT NULL,
    image_rel_path TEXT NOT NULL,
    label_rel_path TEXT NOT NULL,
    availability TEXT NOT NULL DEFAULT 'available'
        CHECK (availability IN ('available', 'missing', 'excluded')),
    exclusion_reason TEXT,
    source_signature TEXT,
    PRIMARY KEY (revision, file_id),
    UNIQUE (revision, file_order)
);
CREATE INDEX IF NOT EXISTS idx_source_file_label_path
    ON source_file(revision, label_rel_path);
"""

_ATOMIC_TASK_DDL = """
CREATE TABLE IF NOT EXISTS atomic_task (
    task_id TEXT NOT NULL,
    revision INTEGER NOT NULL REFERENCES queue_revision(revision),
    file_id TEXT NOT NULL,
    source_order INTEGER NOT NULL,
    locator_json TEXT NOT NULL,
    outcome TEXT NOT NULL DEFAULT 'pending'
        CHECK (outcome IN ('pending', 'completed', 'needs_rework',
                           'skipped')),
    freshness TEXT NOT NULL DEFAULT 'fresh'
        CHECK (freshness IN ('fresh', 'stale', 'unresolved')),
    binding_state TEXT NOT NULL DEFAULT 'ready'
        CHECK (binding_state IN ('ready', 'changed_resolved',
                                 'manually_bound', 'orphaned',
                                 'ambiguous', 'missing')),
    reviewed_signature TEXT,
    current_signature TEXT,
    note TEXT,
    carried_from TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (revision, task_id),
    FOREIGN KEY (revision, file_id)
        REFERENCES source_file(revision, file_id)
);
CREATE INDEX IF NOT EXISTS idx_atomic_task_outcome
    ON atomic_task(revision, outcome, freshness);
CREATE INDEX IF NOT EXISTS idx_atomic_task_file
    ON atomic_task(revision, file_id, source_order);
"""

_REVIEW_PAGE_DDL = """
CREATE TABLE IF NOT EXISTS review_page (
    page_id TEXT NOT NULL,
    revision INTEGER NOT NULL REFERENCES queue_revision(revision),
    file_id TEXT NOT NULL,
    page_order INTEGER NOT NULL,
    bbox_json TEXT,
    projected_scale REAL NOT NULL DEFAULT 0,
    fallback INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (revision, page_id),
    UNIQUE (revision, page_order),
    FOREIGN KEY (revision, file_id)
        REFERENCES source_file(revision, file_id)
);
CREATE INDEX IF NOT EXISTS idx_review_page_file
    ON review_page(revision, file_id, page_order);
"""

_PAGE_TASK_DDL = """
CREATE TABLE IF NOT EXISTS page_task (
    revision INTEGER NOT NULL,
    page_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    slot INTEGER NOT NULL,
    PRIMARY KEY (revision, page_id, task_id),
    UNIQUE (revision, task_id),
    FOREIGN KEY (revision, page_id)
        REFERENCES review_page(revision, page_id),
    FOREIGN KEY (revision, task_id)
        REFERENCES atomic_task(revision, task_id)
);
"""

_CURSOR_DDL = """
CREATE TABLE IF NOT EXISTS cursor_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    active_revision INTEGER NOT NULL,
    page_id TEXT,
    filter_name TEXT NOT NULL DEFAULT 'actionable',
    updated_at TEXT NOT NULL
);
"""

_OUTCOME_EVENT_DDL = """
CREATE TABLE IF NOT EXISTS outcome_event (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    revision INTEGER NOT NULL,
    task_id TEXT NOT NULL,
    outcome TEXT NOT NULL,
    previous_outcome TEXT NOT NULL,
    note TEXT,
    occurred_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_outcome_event_task
    ON outcome_event(revision, task_id, event_id);
"""

_RECONCILIATION_EVENT_DDL = """
CREATE TABLE IF NOT EXISTS reconciliation_event (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    revision INTEGER NOT NULL,
    task_id TEXT,
    file_id TEXT,
    kind TEXT NOT NULL,
    detail_json TEXT NOT NULL DEFAULT '{}',
    occurred_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reconciliation_event
    ON reconciliation_event(revision, kind, event_id);
"""

_LEASE_DDL = """
CREATE TABLE IF NOT EXISTS writer_lease (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    instance_id TEXT NOT NULL,
    pid INTEGER NOT NULL,
    host TEXT NOT NULL,
    acquired_at TEXT NOT NULL,
    heartbeat_at TEXT NOT NULL
);
"""

_MIGRATION_DDL = """
CREATE TABLE IF NOT EXISTS migration_history (
    migration_id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_version INTEGER NOT NULL,
    to_version INTEGER NOT NULL,
    backup_path TEXT,
    applied_at TEXT NOT NULL
);
"""

_DDL_BLOCKS: tuple[str, ...] = (
    _QUEUE_META_DDL,
    _REVISION_DDL,
    _SOURCE_FILE_DDL,
    _ATOMIC_TASK_DDL,
    _REVIEW_PAGE_DDL,
    _PAGE_TASK_DDL,
    _CURSOR_DDL,
    _OUTCOME_EVENT_DDL,
    _RECONCILIATION_EVENT_DDL,
    _LEASE_DDL,
    _MIGRATION_DDL,
)


def _split_statements(block: str) -> list:
    """Split one DDL block into single statements.

    The blocks contain only plain SQL (no embedded semicolons inside
    string literals), so a plain split is safe and keeps every
    statement runnable through ``execute`` inside a caller-owned
    transaction, unlike ``executescript`` which implicitly commits.
    """

    return [
        statement.strip()
        for statement in block.split(";")
        if statement.strip()
    ]


_DDL_STATEMENTS: tuple[str, ...] = tuple(
    statement
    for block in _DDL_BLOCKS
    for statement in _split_statements(block)
)


@dataclass(frozen=True)
class Migration:
    """One registered schema migration between adjacent versions."""

    from_version: int
    to_version: int
    name: str
    upgrade: Callable[[sqlite3.Connection], None]


class MigrationRegistry:
    """Ordered registry of schema migrations.

    Migrations are applied sequentially inside one transaction; a failed
    migration rolls the database back to its previous version.
    """

    def __init__(self) -> None:
        """Initialize an empty registry."""

        self._migrations: list[Migration] = []

    def register(self, migration: Migration) -> None:
        """Append one migration, rejecting duplicate version steps."""

        for existing in self._migrations:
            if existing.from_version == migration.from_version:
                raise ValueError(
                    "duplicate migration source version: "
                    f"{migration.from_version}"
                )
        self._migrations.append(migration)

    def path_to_current(self, current_version: int) -> Sequence[Migration]:
        """Return the ordered migrations from ``current_version`` upward."""

        path: list[Migration] = []
        version = current_version
        while version < SCHEMA_VERSION:
            step = next(
                (
                    migration
                    for migration in self._migrations
                    if migration.from_version == version
                ),
                None,
            )
            if step is None:
                raise LookupError(
                    f"no migration registered from version {version}"
                )
            path.append(step)
            version = step.to_version
        return path

    def __len__(self) -> int:
        """Return the number of registered migrations."""

        return len(self._migrations)


# The registry for released migrations.  Version 1 is the initial
# schema, so it starts empty; tests may push and pop synthetic
# migrations to exercise the transactional migration path.
MIGRATIONS = MigrationRegistry()


def initialize_schema(conn: sqlite3.Connection, app_version: str) -> None:
    """Create the initial schema and stamp version metadata.

    Statements run individually so the caller may own the transaction
    (migrations execute inside one); every statement is idempotent
    (``IF NOT EXISTS`` / ``OR REPLACE``), which keeps an interrupted
    initialization safe to retry.
    """

    for statement in _DDL_STATEMENTS:
        conn.execute(statement)
    for key, value in (
        ("schema_version", str(SCHEMA_VERSION)),
        ("app_version", str(app_version)),
    ):
        conn.execute(
            "INSERT OR REPLACE INTO queue_meta(key, value) VALUES (?, ?)",
            (key, value),
        )


def read_schema_version(conn: sqlite3.Connection) -> Optional[int]:
    """Return the stored schema version, or ``None`` for a foreign file."""

    try:
        row = conn.execute(
            "SELECT value FROM queue_meta WHERE key = 'schema_version'"
        ).fetchone()
    except sqlite3.Error:
        return None
    if row is None:
        return None
    try:
        return int(row[0])
    except (TypeError, ValueError):
        return None


def expected_tables() -> frozenset[str]:
    """Return the table names required by the current schema version."""

    return frozenset(
        {
            "queue_meta",
            "queue_revision",
            "source_file",
            "atomic_task",
            "review_page",
            "page_task",
            "cursor_state",
            "outcome_event",
            "reconciliation_event",
            "writer_lease",
            "migration_history",
        }
    )


__all__ = [
    "MIGRATIONS",
    "Migration",
    "MigrationRegistry",
    "SCHEMA_VERSION",
    "SIDECAR_SUFFIX",
    "expected_tables",
    "initialize_schema",
    "read_schema_version",
]
