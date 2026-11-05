"""Atomic, dataset-isolated storage for inspection reports and feedback."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from typing import Any, Iterator, Mapping, Optional
from .models import (
    FEEDBACK_SCHEMA_VERSION,
    REPORT_SCHEMA_VERSION,
    SESSION_SCHEMA_VERSION,
    FeedbackRecord,
    Manifest,
    ReviewSession,
    RunReport,
    dataset_identity,
    normalize_path,
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


def _usable_root(candidate: str) -> bool:
    try:
        os.makedirs(candidate, exist_ok=True)
        probe = os.path.join(candidate, ".write-test")
        with open(probe, "w", encoding="utf-8") as handle:
            handle.write("ok")
        os.remove(probe)
    except OSError:
        return False
    return True


def _base_root(
    dataset_root: str, output_root: str = "", preferred: str = ""
) -> str:
    if preferred:
        return os.path.abspath(preferred)
    base = output_root or dataset_root
    if base:
        return os.path.join(
            os.path.abspath(base), ".xanylabeling", "inspection"
        )
    return ""


def storage_root(
    dataset_root: str,
    output_root: str = "",
    preferred: str = "",
) -> str:
    """Resolve a per-dataset writable inspection directory.

    Two datasets that share one annotation output directory must never
    share feedback, sessions, candidates or reports, so the dataset
    identity is part of the directory name.
    """
    identity = dataset_identity(dataset_root)
    base = _base_root(dataset_root, output_root, preferred)
    if base:
        candidate = os.path.join(base, identity)
        if _usable_root(candidate):
            return candidate
    fallback = os.path.join(
        os.path.expanduser("~"),
        ".xanylabeling",
        "inspection",
        identity,
    )
    os.makedirs(fallback, exist_ok=True)
    return fallback


def legacy_storage_root(
    dataset_root: str, output_root: str = "", preferred: str = ""
) -> str:
    """Return the pre-isolation shared root, used only for migration."""
    return _base_root(dataset_root, output_root, preferred)


class ReportStore:
    """Immutable run reports, batched writes and bounded pagination."""

    def __init__(
        self,
        root: str,
        *,
        cache_size: int = 8,
        max_page_size: int = 500,
        max_report_issues: int = 200000,
        batch_size: int = 500,
    ) -> None:
        self.root = root
        self.report_dir = os.path.join(root, "reports")
        self.manifest_dir = os.path.join(root, "manifests")
        self.index_path = os.path.join(root, "reports.json")
        self.cache_size = max(1, int(cache_size))
        self.max_page_size = max(1, int(max_page_size))
        self.max_report_issues = max(1, int(max_report_issues))
        self.batch_size = max(1, int(batch_size))
        self._cache: "OrderedDict[str, RunReport]" = OrderedDict()
        os.makedirs(self.report_dir, exist_ok=True)
        os.makedirs(self.manifest_dir, exist_ok=True)

    def _cache_get(self, run_id: str) -> Optional[RunReport]:
        report = self._cache.get(run_id)
        if report is not None:
            self._cache.move_to_end(run_id)
        return report

    def _cache_put(self, run_id: str, report: RunReport) -> None:
        self._cache[run_id] = report
        self._cache.move_to_end(run_id)
        while len(self._cache) > self.cache_size:
            self._cache.popitem(last=False)

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
        if len(report.issues) > self.max_report_issues:
            raise StorageError(
                "报告问题数 {} 超过存储上限 {}；请先缩小范围或调高上限，"
                "不会静默截断".format(
                    len(report.issues), self.max_report_issues
                )
            )
        path = self._path(report.run_id)
        with _exclusive_lock(os.path.join(self.root, "reports.lock")):
            if os.path.isfile(path):
                original = self.load_from(path)
                if original.to_dict() != report.to_dict():
                    raise StorageError(
                        "运行报告不可覆盖；请使用新的运行 ID 保存变更后的结果"
                    )
            else:
                self._write_batched(path, report)
            if manifest is not None:
                self.save_manifest(report.run_id, manifest)
            self._update_index(report)
            self._cache_put(report.run_id, report)
        return path

    def _write_batched(self, path: str, report: RunReport) -> str:
        """Write the report in issue batches instead of one huge string."""
        directory = os.path.dirname(os.path.abspath(path))
        os.makedirs(directory, exist_ok=True)
        payload = replace(report, issues=()).to_dict()
        payload.pop("issues", None)
        payload["summary"] = report.summary()
        payload["saved_at"] = utc_now_iso()
        head = json.dumps(payload, ensure_ascii=False, indent=2)
        descriptor, temporary = tempfile.mkstemp(
            prefix=".inspection_", suffix=".tmp", dir=directory
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(head[:-1].rstrip())
                handle.write(',\n  "issues": [')
                for start in range(0, len(report.issues), self.batch_size):
                    batch = report.issues[start : start + self.batch_size]
                    chunk = ",\n".join(
                        json.dumps(item.to_dict(), ensure_ascii=False)
                        for item in batch
                    )
                    handle.write(("\n    " if start == 0 else ",\n    "))
                    handle.write(chunk.replace("\n", "\n    "))
                handle.write("\n  ]\n}")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.remove(temporary)
        return path

    def save_to(self, path: str, report: RunReport) -> str:
        """Write an immutable copy to a user-selected location."""
        return self._write_batched(path, report)

    def load_from(self, path: str) -> RunReport:
        """Load a report exported by ``save_to``."""
        try:
            payload = read_json(path)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise StorageError(
                f"报告文件损坏或不是有效 JSON: {path}"
            ) from error
        if not isinstance(payload, Mapping):
            raise StorageError("report root must be an object")
        schema = str(payload.get("schema_version", ""))
        if schema != REPORT_SCHEMA_VERSION:
            raise StorageError(f"unsupported report schema: {schema}")
        try:
            return RunReport.from_dict(payload)
        except (TypeError, ValueError) as error:
            raise StorageError(f"报告字段无效: {error}") from error

    def save_manifest(self, run_id: str, manifest: Manifest) -> str:
        path = self._manifest_path(run_id)
        if os.path.isfile(path):
            if self.load_manifest(run_id).to_dict() != manifest.to_dict():
                raise StorageError("运行输入清单不可覆盖；请创建新的运行")
            return path
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
        try:
            payload = read_json(path)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise StorageError(f"manifest 无法读取: {error}") from error
        if not isinstance(payload, Mapping):
            raise StorageError("manifest root must be an object")
        if str(payload.get("schema_version", "")) != "inspection-manifest.v1":
            raise StorageError("unsupported manifest schema")
        manifest = payload.get("manifest", {})
        if not isinstance(manifest, Mapping):
            raise StorageError("manifest payload must be an object")
        try:
            return Manifest.from_dict(manifest)
        except (TypeError, ValueError) as error:
            raise StorageError(f"manifest 字段无效: {error}") from error

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
        cached = self._cache_get(run_id)
        if cached is not None:
            return cached
        path = self._path(run_id)
        if not os.path.isfile(path):
            raise ReportNotFound(f"report not found: {run_id}")
        try:
            payload = read_json(path)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise StorageError(
                f"报告文件损坏或不是有效 JSON: {path} ({error})"
            ) from error
        if not isinstance(payload, Mapping):
            raise StorageError("report root must be an object")
        schema = str(payload.get("schema_version", ""))
        if schema != REPORT_SCHEMA_VERSION:
            raise StorageError(
                f"unsupported report schema: {schema or 'empty'}"
            )
        try:
            report = RunReport.from_dict(payload)
        except (TypeError, ValueError) as error:
            raise StorageError(f"报告字段无效: {error}") from error
        self._cache_put(run_id, report)
        return report

    def list_reports(self) -> tuple[Mapping[str, Any], ...]:
        if not os.path.isfile(self.index_path):
            return ()
        try:
            payload = read_json(self.index_path)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return ()
        reports = (
            payload.get("reports", []) if isinstance(payload, Mapping) else []
        )
        return tuple(item for item in reports if isinstance(item, Mapping))

    def read_issue_page(
        self, run_id: str, offset: int = 0, limit: int = 100
    ) -> tuple[Mapping[str, Any], ...]:
        requested = int(limit if limit is not None else 0)
        if requested < 0 or requested > self.max_page_size:
            raise StorageError(
                "分页大小必须在 0..{} 之间，当前为 {}；不会静默扩大读取量".format(
                    self.max_page_size, requested
                )
            )
        start = max(0, int(offset))
        if requested == 0:
            return ()
        path = self._path(run_id)
        if not os.path.isfile(path):
            raise ReportNotFound(f"report not found: {run_id}")
        # The writer puts one issue on each line: decode only this page.
        try:
            with open(path, "r", encoding="utf-8") as handle:
                for line in handle:
                    if line.startswith('  "issues": ['):
                        break
                else:
                    # Older pretty JSON may use a different layout.
                    report = self.load(run_id)
                    return tuple(
                        issue.to_dict()
                        for issue in report.issues[start : start + requested]
                    )
                page = []
                index = 0
                for line in handle:
                    text = line.strip()
                    if text.startswith("]"):
                        break
                    if not text:
                        continue
                    if index >= start:
                        item = json.loads(text.rstrip(","))
                        if not isinstance(item, Mapping):
                            raise StorageError("报告问题记录必须为对象")
                        page.append(item)
                        if len(page) == requested:
                            break
                    index += 1
                return tuple(page)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise StorageError(f"报告分页记录无效: {error}") from error

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
                "dataset_root": report.dataset_root,
                "output_root": report.output_root,
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
    foreign_records: int = 0


class FeedbackStore:
    """Revision-checked, dataset-aware feedback persistence."""

    def __init__(
        self,
        root: str,
        dataset_key: str = "",
        dataset_root: str = "",
        output_root: str = "",
    ) -> None:
        self.root = root
        self.dataset_key = str(dataset_key)
        self.dataset_root = str(dataset_root)
        self.output_root = str(output_root)
        self.path = os.path.join(root, "feedback.json")
        self.lock_path = os.path.join(root, "feedback.lock")

    def load(self) -> FeedbackSnapshot:
        if not os.path.isfile(self.path):
            return FeedbackSnapshot(0, {}, 0)
        try:
            payload = read_json(self.path)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise StorageError(f"反馈文件损坏: {error}") from error
        if not isinstance(payload, Mapping):
            raise StorageError("feedback root must be an object")
        schema = str(payload.get("schema_version", ""))
        if schema != FEEDBACK_SCHEMA_VERSION:
            raise StorageError(
                f"unsupported feedback schema: {schema or 'empty'}"
            )
        records = {}
        foreign = 0
        for key, item in (payload.get("records", {}) or {}).items():
            if not isinstance(item, Mapping):
                continue
            record = FeedbackRecord.from_dict(item)
            if (
                record.dataset_key
                and self.dataset_key
                and record.dataset_key != self.dataset_key
            ):
                # Never reuse another dataset's human decision even when the
                # relative path and object ids happen to be identical.
                foreign += 1
                continue
            records[str(key)] = record
        return FeedbackSnapshot(
            revision=int(payload.get("revision", 0) or 0),
            records=records,
            foreign_records=foreign,
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
                "dataset_key": self.dataset_key,
                "dataset_root": self.dataset_root,
                "output_root": self.output_root,
                "records": {
                    key: self._stamp(record).to_dict()
                    for key, record in sorted(records.items())
                },
            }
            atomic_write_json(self.path, payload)
            return revision

    def _stamp(self, record: FeedbackRecord) -> FeedbackRecord:
        return replace(
            record,
            dataset_key=self.dataset_key or record.dataset_key,
            dataset_root=self.dataset_root or record.dataset_root,
            output_root=self.output_root or record.output_root,
        )

    def upsert(
        self,
        record: FeedbackRecord,
        expected_revision: int,
    ) -> int:
        snapshot = self.load()
        records = dict(snapshot.records)
        records[record.family_key] = self._stamp(record)
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
                        key: self._stamp(record).to_dict()
                        for key, record in attempted.items()
                    }
                },
                "written_at": utc_now_iso(),
            },
        )
        return path


class SessionStore:
    """Single review-session cursor with revision checks and conflict files."""

    def __init__(self, root: str, dataset_key: str = "") -> None:
        self.root = root
        self.dataset_key = str(dataset_key)
        self.path = os.path.join(root, "session.json")
        self.lock_path = os.path.join(root, "session.lock")

    def load(self) -> Optional[ReviewSession]:
        if not os.path.isfile(self.path):
            return None
        try:
            payload = read_json(self.path)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise StorageError(f"会话文件损坏: {error}") from error
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
                conflict_path = self._write_conflict(
                    current, session, expected_revision
                )
                raise RevisionConflict(
                    "session revision changed; both versions preserved",
                    conflict_path,
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
                dataset_key=self.dataset_key or session.dataset_key,
            )
            atomic_write_json(self.path, next_session.to_dict())
            return next_session

    def _write_conflict(
        self,
        current: Optional[ReviewSession],
        attempted: ReviewSession,
        expected_revision: int,
    ) -> str:
        path = os.path.join(
            self.root,
            f"session.conflict-{utc_now_iso().replace(':', '')}.json",
        )
        atomic_write_json(
            path,
            {
                "schema_version": SESSION_SCHEMA_VERSION,
                "expected_revision": int(expected_revision),
                "current": current.to_dict() if current else None,
                "attempted": attempted.to_dict(),
                "written_at": utc_now_iso(),
            },
        )
        return path


class ProjectBindingStore:
    """Remember the selected profile for one dataset/output identity."""

    def __init__(self, root: str) -> None:
        self.root = root
        self.path = os.path.join(root, "binding.json")

    def _key(self, dataset_root: str, output_root: str) -> str:
        raw = (
            f"{normalize_path(dataset_root)}|"
            f"{normalize_path(output_root or dataset_root)}"
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

    def load(
        self, dataset_root: str, output_root: str = ""
    ) -> Optional[Mapping[str, Any]]:
        if not os.path.isfile(self.path):
            return None
        try:
            payload = read_json(self.path)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        if not isinstance(payload, Mapping):
            return None
        entry = payload.get(self._key(dataset_root, output_root))
        if isinstance(entry, Mapping):
            return entry
        return None

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
            try:
                existing = read_json(self.path)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                existing = None
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


def _copy_file(source: str, target: str) -> bool:
    try:
        os.makedirs(os.path.dirname(os.path.abspath(target)), exist_ok=True)
        shutil.copy2(source, target)
    except OSError:
        return False
    return True


def _merge_report_index(
    source: str, target: str, allowed_run_ids: Optional[set[str]] = None
) -> int:
    """Merge a legacy report index into the dataset-scoped index."""
    try:
        legacy = read_json(source)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return 0
    if not isinstance(legacy, Mapping):
        return 0
    entries = [
        dict(item)
        for item in legacy.get("reports", []) or []
        if isinstance(item, Mapping)
    ]
    if allowed_run_ids is not None:
        entries = [
            item for item in entries if item.get("run_id") in allowed_run_ids
        ]
    if not entries:
        return 0
    existing = []
    if os.path.isfile(target):
        try:
            current = read_json(target)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            current = None
        if isinstance(current, Mapping):
            existing = [
                dict(item)
                for item in current.get("reports", []) or []
                if isinstance(item, Mapping)
            ]
    known = {item.get("run_id") for item in existing}
    merged = existing + [
        item for item in entries if item.get("run_id") not in known
    ]
    atomic_write_json(
        target,
        {
            "schema_version": REPORT_SCHEMA_VERSION,
            "updated_at": utc_now_iso(),
            "reports": merged[:200],
        },
    )
    return len(merged) - len(existing)


class ProfileStateStore:
    """Remember disabled profiles and the last edit revision per profile.

    Built-in templates stay read-only: disabling one only records a local
    preference and never rewrites the template file.
    """

    def __init__(self, root: str) -> None:
        self.root = root
        self.path = os.path.join(root, "profile_state.json")

    def load(self) -> dict[str, Any]:
        if not os.path.isfile(self.path):
            return {"disabled": [], "revisions": {}}
        try:
            payload = read_json(self.path)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return {"disabled": [], "revisions": {}}
        if not isinstance(payload, Mapping):
            return {"disabled": [], "revisions": {}}
        disabled = [str(item) for item in payload.get("disabled", []) or []]
        revisions = {
            str(key): int(value)
            for key, value in (payload.get("revisions", {}) or {}).items()
            if isinstance(value, int)
        }
        return {"disabled": disabled, "revisions": revisions}

    def disabled(self) -> tuple[str, ...]:
        return tuple(sorted(self.load()["disabled"]))

    def set_disabled(self, profile_id: str, disabled: bool) -> None:
        state = self.load()
        ids = set(state["disabled"])
        if disabled:
            ids.add(profile_id)
        else:
            ids.discard(profile_id)
        atomic_write_json(
            self.path,
            {
                "updated_at": utc_now_iso(),
                "disabled": sorted(ids),
                "revisions": state["revisions"],
            },
        )

    def bump_revision(self, profile_id: str) -> int:
        state = self.load()
        revisions = dict(state["revisions"])
        revisions[profile_id] = int(revisions.get(profile_id, 0)) + 1
        atomic_write_json(
            self.path,
            {
                "updated_at": utc_now_iso(),
                "disabled": state["disabled"],
                "revisions": revisions,
            },
        )
        return revisions[profile_id]


@dataclass
class InspectionStorage:
    """Facade combining dataset-scoped report, feedback and session stores."""

    root: str
    reports: ReportStore
    feedback: FeedbackStore
    sessions: SessionStore
    bindings: ProjectBindingStore
    profile_state: ProfileStateStore
    dataset_root: str = ""
    output_root: str = ""
    dataset_key: str = ""
    shared_root: str = ""
    profiles_dir: str = ""
    migration_notes: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def open(
        cls,
        dataset_root: str,
        output_root: str = "",
        preferred: str = "",
    ) -> "InspectionStorage":
        identity = dataset_identity(dataset_root)
        root = storage_root(dataset_root, output_root, preferred)
        legacy = legacy_storage_root(dataset_root, output_root, preferred)
        notes = _migrate_legacy(
            legacy, root, dataset_root, output_root, identity
        )
        shared = legacy if legacy and os.path.isdir(legacy) else root
        profiles_dir = os.path.join(shared, "profiles")
        os.makedirs(profiles_dir, exist_ok=True)
        return cls(
            root=root,
            reports=ReportStore(root),
            feedback=FeedbackStore(
                root,
                dataset_key=identity,
                dataset_root=(
                    os.path.abspath(dataset_root) if dataset_root else ""
                ),
                output_root=(
                    os.path.abspath(output_root) if output_root else ""
                ),
            ),
            sessions=SessionStore(root, dataset_key=identity),
            bindings=ProjectBindingStore(root),
            profile_state=ProfileStateStore(shared),
            dataset_root=os.path.abspath(dataset_root) if dataset_root else "",
            output_root=os.path.abspath(output_root) if output_root else "",
            dataset_key=identity,
            shared_root=shared,
            profiles_dir=profiles_dir,
            migration_notes=tuple(notes),
        )


def _legacy_reports_by_dataset(
    legacy: str, dataset_root: str
) -> tuple[set[str], int]:
    """Return run ids whose legacy report proves it belongs to this dataset."""
    allowed: set[str] = set()
    skipped = 0
    source_dir = os.path.join(legacy, "reports")
    if not os.path.isdir(source_dir):
        return allowed, skipped
    for entry in sorted(os.listdir(source_dir)):
        if not entry.lower().endswith(".json"):
            continue
        source = os.path.join(source_dir, entry)
        try:
            payload = read_json(source)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            skipped += 1
            continue
        if not isinstance(payload, Mapping):
            skipped += 1
            continue
        recorded = normalize_path(str(payload.get("dataset_root", "")))
        if recorded and recorded != normalize_path(dataset_root):
            skipped += 1
            continue
        allowed.add(
            str(payload.get("run_id", "") or os.path.splitext(entry)[0])
        )
    return allowed, skipped


def _migrate_legacy(
    legacy: str,
    root: str,
    dataset_root: str,
    output_root: str,
    identity: str,
) -> list[str]:
    """Copy legacy shared-root records into the dataset-scoped root.

    Legacy records that cannot prove they belong to ``dataset_root`` are
    copied to ``*.legacy-unverified.json`` side files instead of being
    activated, so one dataset never inherits another dataset's human
    decisions.  The legacy files are kept in place as the original source.
    """
    notes: list[str] = []
    if not legacy or normalize_path(legacy) == normalize_path(root):
        return notes
    if not os.path.isdir(legacy):
        return notes
    legacy_entries = set(os.listdir(legacy))
    if not legacy_entries:
        return notes
    current_dataset = normalize_path(dataset_root)
    owner_matches = False
    owner_reason = ""
    legacy_session = os.path.join(legacy, "session.json")
    if os.path.isfile(legacy_session):
        try:
            payload = read_json(legacy_session)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            payload = None
        if isinstance(payload, Mapping):
            recorded = normalize_path(str(payload.get("dataset_root", "")))
            if recorded and recorded == current_dataset:
                owner_matches = True
                owner_reason = "session"
    if not owner_matches and os.path.isfile(
        os.path.join(legacy, "binding.json")
    ):
        try:
            binding = read_json(os.path.join(legacy, "binding.json"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            binding = None
        if isinstance(binding, Mapping):
            key = ProjectBindingStore(legacy)._key(dataset_root, output_root)
            if key in binding:
                owner_matches = True
                owner_reason = "binding"

    def _copy_sidecar(name: str, allow_unverified: bool) -> None:
        source = os.path.join(legacy, name)
        if not os.path.isfile(source):
            return
        target = os.path.join(root, name)
        if os.path.exists(target):
            notes.append(f"旧版 {name} 未迁移：当前数据集已有同名文件")
            return
        if allow_unverified and not owner_matches:
            unverified = os.path.join(
                root, name.replace(".json", ".legacy-unverified.json")
            )
            if _copy_file(source, unverified):
                notes.append(
                    f"旧版 {name} 无法证明属于当前数据集，已保存在 "
                    f"{os.path.basename(unverified)}，未自动应用"
                )
            return
        if _copy_file(source, target):
            notes.append(f"已迁移旧版 {name}（数据集身份匹配）")

    _copy_sidecar("feedback.json", allow_unverified=True)
    _copy_sidecar("candidate_state.json", allow_unverified=True)
    _copy_sidecar("candidate_intents.json", allow_unverified=True)
    if os.path.isfile(legacy_session):
        try:
            payload = read_json(legacy_session)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            payload = None
        recorded = ""
        if isinstance(payload, Mapping):
            recorded = normalize_path(str(payload.get("dataset_root", "")))
        if recorded == current_dataset:
            _copy_sidecar("session.json", allow_unverified=False)
        elif recorded:
            notes.append("旧版复查会话属于其他数据集，未迁移")

    allowed_runs, skipped_reports = _legacy_reports_by_dataset(
        legacy, dataset_root
    )
    copied_runs = 0
    if allowed_runs:
        source_dir = os.path.join(legacy, "reports")
        for run_id in sorted(allowed_runs):
            source = os.path.join(source_dir, f"{run_id}.json")
            if not os.path.isfile(source):
                continue
            if _copy_file(
                source, os.path.join(root, "reports", f"{run_id}.json")
            ):
                copied_runs += 1
            manifest = os.path.join(legacy, "manifests", f"{run_id}.json")
            if os.path.isfile(manifest):
                _copy_file(
                    manifest,
                    os.path.join(root, "manifests", f"{run_id}.json"),
                )
    if copied_runs:
        notes.append(f"已迁移旧版报告 {copied_runs} 份")
    if skipped_reports:
        notes.append(
            f"旧版报告 {skipped_reports} 份无法证明属于当前数据集，未迁移"
        )
    index_path = os.path.join(legacy, "reports.json")
    if os.path.isfile(index_path) and allowed_runs:
        added = _merge_report_index(
            index_path,
            os.path.join(root, "reports.json"),
            allowed_run_ids=allowed_runs,
        )
        if added:
            notes.append(f"已合并旧版运行记录索引 {added} 条")

    legacy_binding = os.path.join(legacy, "binding.json")
    if os.path.isfile(legacy_binding):
        try:
            payload = read_json(legacy_binding)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            payload = None
        if isinstance(payload, Mapping):
            key = ProjectBindingStore(legacy)._key(dataset_root, output_root)
            if isinstance(payload.get(key), Mapping):
                target = os.path.join(root, "binding.json")
                current: dict[str, Any] = {}
                if os.path.isfile(target):
                    try:
                        existing = read_json(target)
                    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                        existing = None
                    if isinstance(existing, Mapping):
                        current = dict(existing)
                if key not in current:
                    current[key] = payload[key]
                    atomic_write_json(target, current)
                    notes.append("已迁移旧版方案绑定（数据集与输出目录匹配）")

    legacy_profiles = os.path.join(legacy, "profiles")
    if os.path.isdir(legacy_profiles):
        copied = 0
        for entry in os.listdir(legacy_profiles):
            if not entry.lower().endswith(".json"):
                continue
            if _copy_file(
                os.path.join(legacy_profiles, entry),
                os.path.join(root, "profiles", entry),
            ):
                copied += 1
        if copied:
            notes.append(f"已迁移自定义方案 {copied} 个")
    if notes:
        notes.insert(
            0,
            "检查存储已按数据集隔离（dataset_key={}）；旧版共享目录保留未删{}。".format(
                identity,
                f"；归属依据 {owner_reason}" if owner_reason else "",
            ),
        )
    return notes
