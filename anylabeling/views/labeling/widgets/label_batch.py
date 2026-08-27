"""Safe, toolkit-neutral label planning and batch JSON migration."""

import copy
import hashlib
import json
import os
import os.path as osp
import shutil
import tempfile
import threading
import uuid
from dataclasses import dataclass, field
from typing import (
    Any,
    Callable,
    Iterable,
    Mapping,
    Optional,
    Protocol,
    Sequence,
)

CancelCheck = Callable[[], bool]
ProgressCallback = Callable[[str, int, int, str], None]


@dataclass(frozen=True)
class LabelMetadataDraft:
    """Immutable snapshot of one editable label row."""

    label: str
    color: tuple[int, int, int] = (0, 114, 178)
    opacity: int = 128
    visible: bool = True
    value: Optional[str] = None
    delete: bool = False


@dataclass(frozen=True)
class LabelChangePlan:
    """Diff between original and confirmed label metadata."""

    visual_changes: Mapping[str, LabelMetadataDraft] = field(
        default_factory=dict
    )
    rename_map: Mapping[str, str] = field(default_factory=dict)
    delete_labels: frozenset[str] = frozenset()
    annotation_paths: tuple[str, ...] = ()

    @property
    def has_visual_changes(self) -> bool:
        """Return whether project display metadata needs an update."""
        return bool(self.visual_changes)

    @property
    def has_dataset_changes(self) -> bool:
        """Return whether JSON migration is required."""
        return bool(self.rename_map or self.delete_labels)

    @property
    def is_noop(self) -> bool:
        """Return whether confirmation produces no side effects."""
        return not self.has_visual_changes and not self.has_dataset_changes


@dataclass(frozen=True)
class MergeConflict:
    """Explicit rename-to-existing-label conflict."""

    source: str
    target: str


@dataclass(frozen=True)
class PreflightSummary:
    """Counts and conflicts shown before a destructive operation."""

    candidate_files: int = 0
    matching_shapes: int = 0
    merge_conflicts: tuple[MergeConflict, ...] = ()
    dirty_current_file: bool = False


@dataclass(frozen=True)
class FileOperationResult:
    """Result for one candidate file."""

    source_path: str
    status: str
    message: str = ""
    matched_shapes: int = 0
    backup_path: Optional[str] = None


@dataclass(frozen=True)
class OperationResult:
    """Structured aggregate result for one migration."""

    transaction_id: str
    phase: str
    files: tuple[FileOperationResult, ...] = ()
    cancelled: bool = False
    manifest_path: Optional[str] = None

    @property
    def counts(self) -> dict[str, int]:
        """Return stable status counters for UI summaries."""
        counts = {"succeeded": 0, "failed": 0, "skipped": 0, "cancelled": 0}
        for item in self.files:
            counts[item.status] = counts.get(item.status, 0) + 1
        if self.cancelled:
            counts["cancelled"] = max(counts["cancelled"], 1)
        return counts


def build_label_change_plan(
    original: Mapping[str, LabelMetadataDraft],
    edited: Mapping[str, LabelMetadataDraft],
    annotation_paths: Iterable[str] = (),
) -> LabelChangePlan:
    """Compute an isolated plan without mutating either metadata mapping."""
    visual: dict[str, LabelMetadataDraft] = {}
    rename: dict[str, str] = {}
    deleted: set[str] = set()
    for label, draft in edited.items():
        before = original.get(label)
        if before is None:
            visual[label] = draft
        elif (
            before.color != draft.color
            or before.opacity != draft.opacity
            or before.visible != draft.visible
        ):
            visual[label] = draft
        if draft.delete:
            deleted.add(label)
        elif draft.value and draft.value != label:
            rename[label] = draft.value
    return LabelChangePlan(
        visual_changes=visual,
        rename_map=rename,
        delete_labels=frozenset(deleted),
        annotation_paths=tuple(annotation_paths),
    )


def find_merge_conflicts(
    rename_map: Mapping[str, str], existing_labels: Iterable[str]
) -> tuple[MergeConflict, ...]:
    """Return renames that would merge into an existing label."""
    existing = set(existing_labels)
    return tuple(
        MergeConflict(source=source, target=target)
        for source, target in rename_map.items()
        if target in existing and target != source
    )


class CandidateProvider(Protocol):
    """Read-only provider for label-to-file candidate queries."""

    def candidates(
        self, labels: frozenset[str], paths: Sequence[str]
    ) -> Sequence[str]:
        """Return a conservative candidate subset."""


class FilesystemCandidateProvider:
    """Index-aware candidate provider with safe filesystem fallback."""

    def __init__(
        self,
        index_query: Optional[
            Callable[[frozenset[str]], Sequence[str]]
        ] = None,
    ) -> None:
        """Initialize with an optional read-only index query callback."""
        self._index_query = index_query

    def candidates(
        self, labels: frozenset[str], paths: Sequence[str]
    ) -> Sequence[str]:
        """Use the index only when it returns paths contained in the request."""
        requested_by_absolute = {osp.abspath(path): path for path in paths}
        requested = set(requested_by_absolute)
        if self._index_query is not None:
            try:
                indexed = {
                    osp.abspath(path) for path in self._index_query(labels)
                }
                if indexed and indexed.issubset(requested):
                    return tuple(
                        sorted(requested_by_absolute[path] for path in indexed)
                    )
            except Exception:
                pass
        return tuple(paths)


def _json_path_for_image(image_file: str, output_dir: Optional[str]) -> str:
    """Resolve an annotation path from an image path."""
    path = osp.splitext(image_file)[0] + ".json"
    return osp.join(output_dir, osp.basename(path)) if output_dir else path


def collect_candidate_json_paths(
    image_paths: Sequence[str],
    labels: frozenset[str],
    output_dir: Optional[str] = None,
    provider: Optional[CandidateProvider] = None,
    cancel_check: Optional[CancelCheck] = None,
    progress: Optional[ProgressCallback] = None,
) -> tuple[str, ...]:
    """Resolve candidate JSON files while remaining cancellable."""
    provider = provider or FilesystemCandidateProvider()
    candidate_images = provider.candidates(labels, image_paths)
    result: list[str] = []
    total = len(candidate_images)
    for index, image_path in enumerate(candidate_images, 1):
        if cancel_check and cancel_check():
            break
        json_path = _json_path_for_image(image_path, output_dir)
        if osp.isfile(json_path):
            result.append(json_path)
        if progress:
            progress("preflight", index, total, json_path)
    return tuple(result)


@dataclass(frozen=True)
class Transformation:
    """Pure JSON transformation output."""

    data: Mapping[str, Any]
    matched_shapes: int
    changed: bool


def transform_annotation_data(
    data: Mapping[str, Any],
    rename_map: Mapping[str, str],
    delete_labels: Iterable[str],
) -> Transformation:
    """Rename/delete labels while preserving every unrelated JSON field."""
    result = copy.deepcopy(dict(data))
    deleted = set(delete_labels)
    shapes = result.get("shapes", [])
    if not isinstance(shapes, list):
        raise ValueError("annotation JSON shapes must be a list")
    output_shapes: list[Any] = []
    matched = 0
    for shape in shapes:
        if not isinstance(shape, dict):
            output_shapes.append(shape)
            continue
        label = shape.get("label")
        if label in deleted:
            matched += 1
            continue
        target = rename_map.get(label)
        if target and target != label:
            shape["label"] = target
            matched += 1
        output_shapes.append(shape)
    result["shapes"] = output_shapes
    return Transformation(result, matched, result != data)


def _fingerprint(path: str) -> dict[str, Any]:
    """Return a source fingerprint used to detect concurrent edits."""
    stat = os.stat(path)
    return {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


@dataclass(frozen=True)
class StagedTransform:
    """Outcome of one pure per-file transformation.

    ``metadata`` carries serializable domain data (for example per-object
    stage statuses) that is persisted into the transaction manifest.
    """

    data: Mapping[str, Any]
    changed: bool
    matched_shapes: int = 0
    metadata: Mapping[str, Any] = field(default_factory=dict)
    skip_reason: str = "no matching change"


class DatasetWriteCoordinator:
    """Process-local coordinator preventing concurrent dataset commits."""

    _locks: dict[str, threading.Lock] = {}
    _guard = threading.Lock()

    @classmethod
    def lock_for(cls, root: str) -> threading.Lock:
        """Return the stable lock for one annotation root."""
        key = osp.normcase(osp.abspath(root))
        with cls._guard:
            return cls._locks.setdefault(key, threading.Lock())


class BatchWriteGate:
    """Process-local registry preventing overlapping batch writers.

    Any feature that starts a dataset-wide batch write (label migration,
    object relabeling) must acquire the gate for its annotation root
    before staging and release it after its terminal signal.
    """

    _active: dict[str, str] = {}
    _guard = threading.Lock()

    @classmethod
    def try_acquire(cls, root: str, owner: str) -> bool:
        """Claim the root for one owner; False if already claimed."""
        key = osp.normcase(osp.abspath(root))
        with cls._guard:
            if key in cls._active:
                return False
            cls._active[key] = owner
            return True

    @classmethod
    def release(cls, root: str, owner: str) -> None:
        """Release the root only when still owned by ``owner``."""
        key = osp.normcase(osp.abspath(root))
        with cls._guard:
            if cls._active.get(key) == owner:
                del cls._active[key]


class JsonTransactionEngine:
    """Generic staged JSON transactions shared by every batch writer.

    The engine owns transaction directories, same-volume temporary files,
    JSON re-parsing, backups, source fingerprints, the dataset write lock,
    atomic replacement, manifest persistence, and restore. Domain flows
    supply a pure per-file transform and serializable metadata.
    """

    def __init__(self, transaction_root: str) -> None:
        """Initialize a transaction engine under a project-owned directory."""
        self.transaction_root = osp.abspath(transaction_root)

    def stage_files(
        self,
        sources: Sequence[str],
        transform: Callable[[str, Mapping[str, Any]], StagedTransform],
        cancel_check: Optional[CancelCheck] = None,
        progress: Optional[ProgressCallback] = None,
        domain: Optional[Mapping[str, Any]] = None,
    ) -> OperationResult:
        """Stage and validate transformed JSON without replacing sources."""
        transaction_id = uuid.uuid4().hex
        transaction_dir = osp.join(self.transaction_root, transaction_id)
        staged_dir = osp.join(transaction_dir, "staged")
        backups_dir = osp.join(transaction_dir, "backups")
        os.makedirs(staged_dir, exist_ok=True)
        os.makedirs(backups_dir, exist_ok=True)
        entries: list[dict[str, Any]] = []
        results: list[FileOperationResult] = []
        for index, source in enumerate(sources, 1):
            if cancel_check and cancel_check():
                manifest_path = self._write_manifest(
                    transaction_dir, transaction_id, entries, domain
                )
                return OperationResult(
                    transaction_id,
                    "staged",
                    tuple(results),
                    True,
                    manifest_path,
                )
            try:
                with open(source, "r", encoding="utf-8") as stream:
                    original = json.load(stream)
                outcome = transform(source, original)
                if not outcome.changed:
                    results.append(
                        FileOperationResult(
                            source, "skipped", outcome.skip_reason
                        )
                    )
                    continue
                token = hashlib.sha256(
                    osp.abspath(source).encode("utf-8")
                ).hexdigest()[:20]
                staged = osp.join(staged_dir, f"{token}.json")
                backup = osp.join(backups_dir, f"{token}.json")
                fd, temporary = tempfile.mkstemp(
                    prefix="stage-", suffix=".json", dir=staged_dir
                )
                os.close(fd)
                try:
                    with open(temporary, "w", encoding="utf-8") as stream:
                        json.dump(
                            outcome.data,
                            stream,
                            indent=2,
                            ensure_ascii=False,
                        )
                        stream.write("\n")
                    with open(temporary, "r", encoding="utf-8") as stream:
                        json.load(stream)
                    os.replace(temporary, staged)
                finally:
                    if osp.exists(temporary):
                        os.remove(temporary)
                shutil.copy2(source, backup)
                entry = {
                    "source_path": osp.abspath(source),
                    "staged_path": staged,
                    "backup_path": backup,
                    "original_fingerprint": _fingerprint(source),
                    "status": "staged",
                    "matched_shapes": outcome.matched_shapes,
                    "domain_metadata": dict(outcome.metadata),
                }
                entries.append(entry)
                results.append(
                    FileOperationResult(
                        source,
                        "staged",
                        matched_shapes=outcome.matched_shapes,
                        backup_path=backup,
                    )
                )
            except (OSError, ValueError, TypeError) as exc:
                results.append(FileOperationResult(source, "failed", str(exc)))
            if progress:
                progress("staging", index, len(sources), source)
        manifest_path = self._write_manifest(
            transaction_dir, transaction_id, entries, domain
        )
        return OperationResult(
            transaction_id, "staged", tuple(results), False, manifest_path
        )

    def commit(self, staged: OperationResult, root: str) -> OperationResult:
        """Atomically replace staged files; this phase deliberately ignores cancel."""
        lock = DatasetWriteCoordinator.lock_for(root)
        results: list[FileOperationResult] = []
        manifest_path = staged.manifest_path
        payload = self._read_manifest_payload(manifest_path)
        domain = payload.get("domain")
        entries = self._entries_from_payload(payload)
        with lock:
            for entry in entries:
                source = entry["source_path"]
                try:
                    if _fingerprint(source) != entry["original_fingerprint"]:
                        raise RuntimeError("source changed after preflight")
                    os.replace(entry["staged_path"], source)
                    entry["status"] = "succeeded"
                    results.append(
                        FileOperationResult(
                            source,
                            "succeeded",
                            matched_shapes=entry.get("matched_shapes", 0),
                            backup_path=entry.get("backup_path"),
                        )
                    )
                except (OSError, RuntimeError) as exc:
                    entry["status"] = "failed"
                    entry["message"] = str(exc)
                    results.append(
                        FileOperationResult(
                            source,
                            "failed",
                            str(exc),
                            backup_path=entry.get("backup_path"),
                        )
                    )
            if manifest_path:
                self._write_manifest(
                    osp.dirname(manifest_path),
                    staged.transaction_id,
                    entries,
                    domain,
                )
        for item in staged.files:
            if item.status == "skipped" or item.status == "failed":
                results.append(item)
        return OperationResult(
            staged.transaction_id,
            "committed",
            tuple(results),
            False,
            manifest_path,
        )

    def restore(
        self, manifest_path: str, root: Optional[str] = None
    ) -> OperationResult:
        """Restore every committed source under the dataset write lock."""
        payload = self._read_manifest_payload(manifest_path)
        domain = payload.get("domain")
        entries = self._entries_from_payload(payload)
        results: list[FileOperationResult] = []
        lock_root = osp.abspath(root) if root else self._restore_root(entries)
        lock = DatasetWriteCoordinator.lock_for(lock_root)
        with lock:
            for entry in entries:
                try:
                    fd, temporary = tempfile.mkstemp(
                        prefix="restore-",
                        suffix=".json",
                        dir=osp.dirname(entry["source_path"]),
                    )
                    os.close(fd)
                    shutil.copy2(entry["backup_path"], temporary)
                    with open(temporary, "r", encoding="utf-8") as stream:
                        json.load(stream)
                    os.replace(temporary, entry["source_path"])
                    entry["status"] = "restored"
                    results.append(
                        FileOperationResult(entry["source_path"], "succeeded")
                    )
                except (OSError, ValueError) as exc:
                    results.append(
                        FileOperationResult(
                            entry["source_path"], "failed", str(exc)
                        )
                    )
            transaction_id = (
                payload.get("transaction_id")
                or (
                    entries[0].get("transaction_id", "restore")
                    if entries
                    else ""
                )
                or "restore"
            )
            self._write_manifest(
                osp.dirname(manifest_path), transaction_id, entries, domain
            )
        return OperationResult(
            osp.basename(osp.dirname(manifest_path)),
            "restored",
            tuple(results),
            False,
            manifest_path,
        )

    @staticmethod
    def _restore_root(entries: Sequence[Mapping[str, Any]]) -> str:
        """Return a stable dataset root for a manifest restore lock."""
        directories = [
            osp.dirname(osp.abspath(str(entry["source_path"])))
            for entry in entries
            if entry.get("source_path")
        ]
        if not directories:
            return "."
        try:
            return osp.commonpath(directories)
        except ValueError:
            return directories[0]

    @staticmethod
    def _write_manifest(
        transaction_dir: str,
        transaction_id: str,
        entries: list[dict[str, Any]],
        domain: Optional[Mapping[str, Any]] = None,
    ) -> str:
        """Write a versioned transaction manifest atomically."""
        path = osp.join(transaction_dir, "manifest.json")
        payload: dict[str, Any] = {
            "schema_version": 2,
            "transaction_id": transaction_id,
            "entries": entries,
        }
        if domain is not None:
            payload["domain"] = dict(domain)
        temporary = f"{path}.tmp"
        with open(temporary, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, ensure_ascii=False)
        os.replace(temporary, path)
        return path

    @staticmethod
    def _read_manifest_payload(
        path: Optional[str],
    ) -> dict[str, Any]:
        """Read the full manifest payload defensively."""
        if not path:
            return {"transaction_id": "", "entries": []}
        with open(path, "r", encoding="utf-8") as stream:
            payload = json.load(stream)
        if not isinstance(payload, dict):
            raise ValueError("manifest payload must be an object")
        return payload

    @staticmethod
    def _entries_from_payload(payload: Mapping[str, Any]) -> list:
        """Return manifest entries with per-entry transaction ids filled."""
        entries = payload.get("entries", [])
        transaction_id = payload.get("transaction_id", "")
        for entry in entries:
            entry.setdefault("transaction_id", transaction_id)
        return entries


class BatchMigrationEngine:
    """Preflight, stage, atomically commit, and restore label migrations.

    Compatibility facade over :class:`JsonTransactionEngine`; the public
    preflight/stage/commit/restore API and the global rename/delete
    semantics are preserved for existing callers.
    """

    def __init__(self, transaction_root: str) -> None:
        """Initialize a transaction engine under a project-owned directory."""
        self._engine = JsonTransactionEngine(transaction_root)

    def preflight(
        self,
        paths: Sequence[str],
        plan: LabelChangePlan,
        cancel_check: Optional[CancelCheck] = None,
        progress: Optional[ProgressCallback] = None,
    ) -> PreflightSummary:
        """Count actual matching shapes without writing files."""
        matching = 0
        files = 0
        labels = set(plan.rename_map) | set(plan.delete_labels)
        for index, path in enumerate(paths, 1):
            if cancel_check and cancel_check():
                break
            try:
                with open(path, "r", encoding="utf-8") as stream:
                    data = json.load(stream)
                count = sum(
                    1
                    for shape in data.get("shapes", [])
                    if isinstance(shape, dict) and shape.get("label") in labels
                )
                if count:
                    files += 1
                    matching += count
            except (OSError, ValueError):
                continue
            if progress:
                progress("preflight", index, len(paths), path)
        return PreflightSummary(
            candidate_files=files, matching_shapes=matching
        )

    def stage(
        self,
        paths: Sequence[str],
        plan: LabelChangePlan,
        cancel_check: Optional[CancelCheck] = None,
        progress: Optional[ProgressCallback] = None,
    ) -> OperationResult:
        """Stage and validate changed JSON files without replacing sources."""

        def transform(
            _source: str, original: Mapping[str, Any]
        ) -> StagedTransform:
            outcome = transform_annotation_data(
                original, plan.rename_map, plan.delete_labels
            )
            return StagedTransform(
                data=outcome.data,
                changed=outcome.changed,
                matched_shapes=outcome.matched_shapes,
            )

        return self._engine.stage_files(
            paths, transform, cancel_check, progress
        )

    def commit(self, staged: OperationResult, root: str) -> OperationResult:
        """Atomically replace staged files; this phase deliberately ignores cancel."""
        return self._engine.commit(staged, root)

    def restore(self, manifest_path: str) -> OperationResult:
        """Restore every committed source from its retained backup atomically."""
        return self._engine.restore(manifest_path)
