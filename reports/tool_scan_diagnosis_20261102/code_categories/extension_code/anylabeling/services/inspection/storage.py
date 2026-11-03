"""Atomic, revision-safe storage for inspection reports and feedback."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator, Mapping, Optional

from .models import (
    FEEDBACK_SCHEMA_VERSION,
    REPORT_SCHEMA_VERSION,
    SESSION_SCHEMA_VERSION,
    FeedbackRecord,
    Manifest,
    ReviewSession,
    RunReport,
    utc_now_iso,
)


class StorageError(RuntimeError):
    """Base error for inspection persistence."""


class ReportNotFound(StorageError):
    """Raised when a requested run report does not exist."""


class RevisionConflict(StorageError):
    """Raised when another writer changed feedback or session state."""

    def __init__(self, message: str, conflict_path: str = "") -> None:
        super().__init__(message)
        self.conflict_path = conflict_path


def atomic_write_json(path: str, payload: Mapping[str, Any]) -> str:
    """Write JSON through a temporary file, fsync and atomic replace."""
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=".inspection_", suffix=".tmp", dir=directory
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)
    return path


def read_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


@contextmanager
def _exclusive_lock(path: str) -> Iterator[None]:
    """Best-effort cross-process lock covering compare-and-replace."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    handle = open(path, "a+b")
    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def storage_root(
    dataset_root: str,
    output_root: str = "",
    preferred: str = "",
) -> str:
    """Resolve a writable inspection directory without touching annotations."""
    if preferred:
        os.makedirs(preferred, exist_ok=True)
        return preferred
    base = output_root or dataset_root
    if base:
        candidate = os.path.join(
            os.path.abspath(base), ".xanylabeling", "inspection"
        )
        try:
            os.makedirs(candidate, exist_ok=True)
            probe = os.path.join(candidate, ".write-test")
            with open(probe, "w", encoding="utf-8") as handle:
                handle.write("ok")
            os.remove(probe)
            return candidate
        except OSError:
            pass
    identity = os.path.abspath(base or "unbound")
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
    fallback = os.path.join(
        os.path.expanduser("~"),
        ".xanylabeling",
        "inspection",
        digest,
    )
    os.makedirs(fallback, exist_ok=True)
    return fallback


class ReportStore:
    """Immutable run reports plus a small cached summary index."""

    def __init__(self, root: str) -> None:
        self.root = root
        self.report_dir = os.path.join(root, "reports")
        self.manifest_dir = os.path.join(root, "manifests")
        self.index_path = os.path.join(root, "reports.json")
        os.makedirs(self.report_dir, exist_ok=True)
        os.makedirs(self.manifest_dir, exist_ok=True)

    def _path(self, run_id: str) -> str:
        safe = "".join(
            character
            for character in str(run_id)
            if character.isalnum() or character in ("-", "_", ".")
        )
        if not safe:
            raise StorageError("invalid run id")
        return os.path.join(self.report_dir, f"{safe}.json")

    def save(
        self, report: RunReport, manifest: Optional[Manifest] = None
    ) -> str:
        payload = report.to_dict()
        payload["saved_at"] = utc_now_iso()
        path = atomic_write_json(self._path(report.run_id), payload)
        if manifest is not None:
            self.save_manifest(report.run_id, manifest)
        self._update_index(report)
        return path

    def save_manifest(self, run_id: str, manifest: Manifest) -> str:
        path = self._manifest_path(run_id)
        atomic_write_json(
            path,
            {
                "schema_version": "inspection-manifest.v1",
                "run_id": run_id,
                "saved_at": utc_now_iso(),
                "manifest": manifest.to_dict(),
            },
        )
        return path

    def load_manifest(self, run_id: str) -> Manifest:
        path = self._manifest_path(run_id)
        if not os.path.isfile(path):
            raise ReportNotFound(f"manifest not found: {run_id}")
        payload = read_json(path)
        if not isinstance(payload, Mapping):
            raise StorageError("manifest root must be an object")
        if str(payload.get("schema_version", "")) != "inspection-manifest.v1":
            raise StorageError("unsupported manifest schema")
        manifest = payload.get("manifest", {})
        if not isinstance(manifest, Mapping):
            raise StorageError("manifest payload must be an object")
        return Manifest.from_dict(manifest)

    def _manifest_path(self, run_id: str) -> str:
        safe = "".join(
            character
            for character in str(run_id)
            if character.isalnum() or character in ("-", "_", ".")
        )
        if not safe:
            raise StorageError("invalid run id")
        return os.path.join(self.manifest_dir, f"{safe}.json")

    def load(self, run_id: str) -> RunReport:
        path = self._path(run_id)
        if not os.path.isfile(path):
            raise ReportNotFound(f"report not found: {run_id}")
        payload = read_json(path)
        if not isinstance(payload, Mapping):
            raise StorageError("report root must be an object")
        schema = str(payload.get("schema_version", ""))
        if schema != REPORT_SCHEMA_VERSION:
            raise StorageError(
                f"unsupported report schema: {schema or 'empty'}"
            )
        return RunReport.from_dict(payload)

    def list_reports(self) -> tuple[Mapping[str, Any], ...]:
        if not os.path.isfile(self.index_path):
            return ()
        try:
            payload = read_json(self.index_path)
        except (OSError, json.JSONDecodeError):
            return ()
        reports = (
            payload.get("reports", []) if isinstance(payload, Mapping) else []
        )
        return tuple(item for item in reports if isinstance(item, Mapping))

    def read_issue_page(
        self, run_id: str, offset: int = 0, limit: int = 100
    ) -> tuple[Mapping[str, Any], ...]:
        report = self.load(run_id)
        start = max(0, int(offset))
        end = start + max(0, int(limit))
        return tuple(issue.to_dict() for issue in report.issues[start:end])

    def _update_index(self, report: RunReport) -> None:
        entries = [
            dict(item)
            for item in self.list_reports()
            if item.get("run_id") != report.run_id
        ]
        entries.insert(
            0,
            {
                "run_id": report.run_id,
                "state": report.state.value,
                "scope": report.scope.value,
                "started_at": report.started_at,
                "finished_at": report.finished_at,
                "issue_count": len(report.issues),
                "summary": report.summary(),
                "profile_id": report.profile_snapshot.get("profile", {}).get(
                    "profile_id", ""
                ),
            },
        )
        atomic_write_json(
            self.index_path,
            {
                "schema_version": REPORT_SCHEMA_VERSION,
                "updated_at": utc_now_iso(),
                "reports": entries[:200],
            },
        )


@dataclass
class FeedbackSnapshot:
    """Feedback entries grouped by stable family key."""

    revision: int
    records: dict[str, FeedbackRecord]


class FeedbackStore:
    """Revision-checked feedback persistence with conflict preservation."""

    def __init__(self, root: str) -> None:
        self.root = root
        self.path = os.path.join(root, "feedback.json")
        self.lock_path = os.path.join(root, "feedback.lock")

    def load(self) -> FeedbackSnapshot:
        if not os.path.isfile(self.path):
            return FeedbackSnapshot(0, {})
        payload = read_json(self.path)
        if not isinstance(payload, Mapping):
            raise StorageError("feedback root must be an object")
        schema = str(payload.get("schema_version", ""))
        if schema != FEEDBACK_SCHEMA_VERSION:
            raise StorageError(
                f"unsupported feedback schema: {schema or 'empty'}"
            )
        records = {}
        for key, item in (payload.get("records", {}) or {}).items():
            if isinstance(item, Mapping):
                records[str(key)] = FeedbackRecord.from_dict(item)
        return FeedbackSnapshot(
            revision=int(payload.get("revision", 0) or 0),
            records=records,
        )

    def save(
        self,
        records: Mapping[str, FeedbackRecord],
        expected_revision: int,
    ) -> int:
        with _exclusive_lock(self.lock_path):
            current = self.load()
            if current.revision != int(expected_revision):
                conflict_path = self._write_conflict(
                    current, records, expected_revision
                )
                raise RevisionConflict(
                    "feedback revision changed; both versions preserved",
                    conflict_path,
                )
            revision = current.revision + 1
            payload = {
                "schema_version": FEEDBACK_SCHEMA_VERSION,
                "revision": revision,
                "updated_at": utc_now_iso(),
                "records": {
                    key: record.to_dict()
                    for key, record in sorted(records.items())
                },
            }
            atomic_write_json(self.path, payload)
            return revision

    def upsert(
        self,
        record: FeedbackRecord,
        expected_revision: int,
    ) -> int:
        snapshot = self.load()
        records = dict(snapshot.records)
        records[record.family_key] = record
        return self.save(records, expected_revision)

    def _write_conflict(
        self,
        current: FeedbackSnapshot,
        attempted: Mapping[str, FeedbackRecord],
        expected_revision: int,
    ) -> str:
        path = os.path.join(
            self.root,
            f"feedback.conflict-{utc_now_iso().replace(':', '')}.json",
        )
        atomic_write_json(
            path,
            {
                "schema_version": FEEDBACK_SCHEMA_VERSION,
                "expected_revision": int(expected_revision),
                "current": {
                    "revision": current.revision,
                    "records": {
                        key: record.to_dict()
                        for key, record in current.records.items()
                    },
                },
                "attempted": {
                    "records": {
                        key: record.to_dict()
                        for key, record in attempted.items()
                    }
                },
                "written_at": utc_now_iso(),
            },
        )
        return path


class SessionStore:
    """Single review-session cursor with revision checks."""

    def __init__(self, root: str) -> None:
        self.root = root
        self.path = os.path.join(root, "session.json")
        self.lock_path = os.path.join(root, "session.lock")

    def load(self) -> Optional[ReviewSession]:
        if not os.path.isfile(self.path):
            return None
        payload = read_json(self.path)
        if not isinstance(payload, Mapping):
            raise StorageError("session root must be an object")
        schema = str(payload.get("schema_version", ""))
        if schema != SESSION_SCHEMA_VERSION:
            raise StorageError(
                f"unsupported session schema: {schema or 'empty'}"
            )
        return ReviewSession.from_dict(payload)

    def save(
        self, session: ReviewSession, expected_revision: int
    ) -> ReviewSession:
        with _exclusive_lock(self.lock_path):
            current = self.load()
            current_revision = current.revision if current else 0
            if current_revision != int(expected_revision):
                raise RevisionConflict(
                    "session revision changed; reload before saving"
                )
            next_session = ReviewSession(
                report_id=session.report_id,
                dataset_root=session.dataset_root,
                output_root=session.output_root,
                filters=session.filters,
                cursor=session.cursor,
                updated_at=utc_now_iso(),
                revision=current_revision + 1,
                schema_version=SESSION_SCHEMA_VERSION,
            )
            atomic_write_json(self.path, next_session.to_dict())
            return next_session


class ProjectBindingStore:
    """Remember the selected profile for one dataset/output identity."""

    def __init__(self, root: str) -> None:
        self.root = root
        self.path = os.path.join(root, "binding.json")

    def _key(self, dataset_root: str, output_root: str) -> str:
        raw = f"{os.path.abspath(dataset_root)}|{os.path.abspath(output_root or dataset_root)}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

    def load(
        self, dataset_root: str, output_root: str = ""
    ) -> Optional[Mapping[str, Any]]:
        if not os.path.isfile(self.path):
            return None
        payload = read_json(self.path)
        if not isinstance(payload, Mapping):
            return None
        return payload.get(self._key(dataset_root, output_root))

    def save(
        self,
        dataset_root: str,
        output_root: str,
        profile_id: str,
        profile_version: int,
        profile_fingerprint: str,
    ) -> str:
        payload = {}
        if os.path.isfile(self.path):
            existing = read_json(self.path)
            if isinstance(existing, Mapping):
                payload = dict(existing)
        payload[self._key(dataset_root, output_root)] = {
            "dataset_root": os.path.abspath(dataset_root),
            "output_root": os.path.abspath(output_root or dataset_root),
            "profile_id": profile_id,
            "profile_version": int(profile_version),
            "profile_fingerprint": profile_fingerprint,
            "updated_at": utc_now_iso(),
        }
        return atomic_write_json(self.path, payload)


@dataclass
class InspectionStorage:
    """Facade combining report, feedback, session and binding stores."""

    root: str
    reports: ReportStore
    feedback: FeedbackStore
    sessions: SessionStore
    bindings: ProjectBindingStore

    @classmethod
    def open(
        cls,
        dataset_root: str,
        output_root: str = "",
        preferred: str = "",
    ) -> "InspectionStorage":
        root = storage_root(dataset_root, output_root, preferred)
        return cls(
            root=root,
            reports=ReportStore(root),
            feedback=FeedbackStore(root),
            sessions=SessionStore(root),
            bindings=ProjectBindingStore(root),
        )
