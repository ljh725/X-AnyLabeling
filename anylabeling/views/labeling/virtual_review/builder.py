"""Cancellable dataset scanning and staging publication for queues.

Construction reads one annotation file at a time in dataset order,
reuses the existing task builder and packer unchanged, and writes a
uniquely named staging sidecar.  A queue becomes active only after the
staging database passes validation and an explicit publish step; a
cancelled or failed build never touches the active queue.
"""

from __future__ import annotations

import math
import os
import os.path as osp
import uuid
from dataclasses import dataclass, field
from typing import Callable, Optional, Sequence

from .locators import (
    build_task_locator,
    scan_annotation_file,
    views_from_annotation,
)
from .models import VirtualPackingOptions, VirtualTaskCriteria
from .packing import pack_virtual_tasks
from .queue_models import (
    AtomicTaskRecord,
    FileAvailability,
    PageRecord,
    SourceFileRecord,
)
from .serialization import (
    canonical_json,
    criteria_to_dict,
    locator_signature,
    normalize_relative_path,
    packing_to_dict,
)
from .store import RevisionContent, ReviewStore, utc_now_iso
from .task_builder import build_virtual_tasks

ProgressCallback = Callable[[int, int, str], None]
CancelCallback = Callable[[], bool]


@dataclass(frozen=True)
class DatasetFileDescriptor:
    """One ordered dataset file with its effective label path."""

    image_path: str
    label_path: str
    dataset_root: str


@dataclass(frozen=True)
class QueueBuildRequest:
    """Frozen input of one deterministic queue build."""

    files: tuple[DatasetFileDescriptor, ...]
    criteria: VirtualTaskCriteria
    packing_options: VirtualPackingOptions
    reference_viewport: tuple[float, float]
    sidecar_path: str
    app_version: str = ""

    def __post_init__(self) -> None:
        """Validate the frozen request, failing closed."""

        if not isinstance(self.criteria, VirtualTaskCriteria):
            raise ValueError("criteria must be VirtualTaskCriteria")
        if not isinstance(self.packing_options, VirtualPackingOptions):
            raise ValueError("packing_options must be VirtualPackingOptions")
        viewport = self.reference_viewport
        try:
            width, height = float(viewport[0]), float(viewport[1])
        except (TypeError, ValueError, IndexError) as exc:
            raise ValueError(
                "reference_viewport must be a finite positive pair"
            ) from exc
        if (
            not math.isfinite(width)
            or not math.isfinite(height)
            or width <= 0
            or height <= 0
        ):
            raise ValueError(
                "reference_viewport must be a finite positive pair"
            )
        object.__setattr__(self, "reference_viewport", (width, height))
        if not str(self.sidecar_path):
            raise ValueError("sidecar_path is required")


@dataclass(frozen=True)
class FileExclusion:
    """One file-level exclusion collected into a draft."""

    image_rel_path: str
    label_rel_path: str
    reason: str  # "missing" | "parse"
    detail: str = ""


@dataclass(frozen=True)
class BuildStats:
    """Deterministic build counters."""

    files_total: int = 0
    files_matched: int = 0
    files_excluded: int = 0
    tasks: int = 0
    pages: int = 0
    singleton_fallback: int = 0


@dataclass
class QueueDraft:
    """Result of one scan: a validated staging database or cancellation."""

    request: QueueBuildRequest
    staging_path: str = ""
    stats: BuildStats = field(default_factory=BuildStats)
    exclusions: tuple[FileExclusion, ...] = ()
    cancelled: bool = False
    diagnostics: tuple[str, ...] = ()

    @property
    def publishable(self) -> bool:
        """Return whether the draft may be published."""

        return not self.cancelled and not self.diagnostics


def _staging_path_for(sidecar_path: str) -> str:
    """Return a unique staging sibling path in the target directory."""

    return f"{sidecar_path}.staging-{uuid.uuid4().hex}" f".xreview.sqlite3"


def scan_dataset(
    request: QueueBuildRequest,
    progress: Optional[ProgressCallback] = None,
    cancel: Optional[CancelCallback] = None,
) -> QueueDraft:
    """Scan the dataset into a validated staging sidecar.

    Files are read sequentially in dataset order; every file either
    contributes image-local pages, is omitted for zero matches, or is
    recorded as an exclusion.  Cancellation deletes the staging
    database and reports it without touching any existing queue.
    """

    staging_path = _staging_path_for(request.sidecar_path)
    root_hint = (
        request.files[0].dataset_root
        if request.files
        else osp.dirname(osp.abspath(request.sidecar_path))
    )
    store: Optional[ReviewStore] = None
    try:
        store = ReviewStore.create(
            staging_path,
            dataset_root_hint=root_hint,
            app_version=request.app_version,
        )
    except Exception:
        _discard_staging(staging_path)
        raise

    files: list[SourceFileRecord] = []
    tasks: list[AtomicTaskRecord] = []
    pages: list[PageRecord] = []
    exclusions: list[FileExclusion] = []
    fallback_count = 0
    task_count = 0
    page_order = 0
    try:
        for index, descriptor in enumerate(request.files):
            if cancel is not None and cancel():
                store.close()
                _discard_staging(staging_path)
                return QueueDraft(
                    request=request,
                    staging_path=staging_path,
                    cancelled=True,
                )
            if progress is not None:
                progress(index + 1, len(request.files), descriptor.label_path)
            image_rel = normalize_relative_path(
                descriptor.dataset_root, descriptor.image_path
            )
            label_rel = normalize_relative_path(
                descriptor.dataset_root, descriptor.label_path
            )
            scan = scan_annotation_file(descriptor.label_path)
            if not scan.ok:
                reason = scan.error or "parse"
                exclusions.append(
                    FileExclusion(
                        image_rel_path=image_rel,
                        label_rel_path=label_rel,
                        reason=reason,
                    )
                )
                files.append(
                    SourceFileRecord(
                        file_id=uuid.uuid4().hex,
                        order=len(files),
                        image_rel_path=image_rel,
                        label_rel_path=label_rel,
                        availability=FileAvailability.EXCLUDED,
                        exclusion_reason=reason,
                        source_signature=scan.source_signature,
                    )
                )
                continue
            views, points_by_id = views_from_annotation(scan)
            local_tasks = build_virtual_tasks(views, request.criteria)
            if not local_tasks:
                # Zero matching tasks: the file is omitted without
                # being an error and without queue membership.
                continue
            packing = pack_virtual_tasks(
                local_tasks,
                request.reference_viewport,
                request.packing_options,
            )
            fallback_count += packing.singleton_fallback_count
            file_id = uuid.uuid4().hex
            files.append(
                SourceFileRecord(
                    file_id=file_id,
                    order=len(files),
                    image_rel_path=image_rel,
                    label_rel_path=label_rel,
                    availability=FileAvailability.AVAILABLE,
                    source_signature=scan.source_signature,
                )
            )
            task_id_by_runtime: dict[str, str] = {}
            for order, task in enumerate(local_tasks):
                task_id = uuid.uuid4().hex
                task_id_by_runtime[task.task_id] = task_id
                locator = build_task_locator(
                    task,
                    views,
                    points_by_id,
                    scan.image_width,
                    scan.image_height,
                )
                tasks.append(
                    AtomicTaskRecord(
                        task_id=task_id,
                        file_id=file_id,
                        source_order=order,
                        locator=locator,
                        current_signature=locator_signature(locator),
                    )
                )
            for page in packing.pages:
                pages.append(
                    PageRecord(
                        page_id=uuid.uuid4().hex,
                        file_id=file_id,
                        order=page_order,
                        bbox=page.bbox,
                        projected_scale=page.projected_scale,
                        fallback=page.fallback,
                        task_ids=tuple(
                            task_id_by_runtime[task_id]
                            for task_id in page.task_ids
                        ),
                    )
                )
                page_order += 1
            task_count += len(local_tasks)

        content = RevisionContent(
            revision=1,
            criteria_json=_canonical(request_criteria(request)),
            packing_json=_canonical(request_packing(request)),
            reference_viewport_json=_canonical(
                list(request.reference_viewport)
            ),
            created_at=utc_now_iso(),
            build_diagnostics={
                "exclusions": len(exclusions),
                "fallback": fallback_count,
            },
            files=files,
            tasks=tasks,
            pages=pages,
        )
        store.insert_revision(content)
        stats = BuildStats(
            files_total=len(request.files),
            files_matched=sum(
                1
                for record in files
                if record.availability is FileAvailability.AVAILABLE
            ),
            files_excluded=len(exclusions),
            tasks=task_count,
            pages=len(pages),
            singleton_fallback=fallback_count,
        )
        store.close()
        store = None
        diagnostics = validate_staging(staging_path, stats)
        return QueueDraft(
            request=request,
            staging_path=staging_path,
            stats=stats,
            exclusions=tuple(exclusions),
            diagnostics=tuple(diagnostics),
        )
    except Exception:
        if store is not None:
            try:
                store.close()
            except Exception:
                pass
        _discard_staging(staging_path)
        raise


def request_criteria(request: QueueBuildRequest) -> dict:
    """Return the canonical criteria payload of a request."""

    return criteria_to_dict(request.criteria)


def request_packing(request: QueueBuildRequest) -> dict:
    """Return the canonical packing payload of a request."""

    return packing_to_dict(request.packing_options)


def _canonical(payload) -> str:
    """Serialize a payload canonically for revision storage."""

    return canonical_json(payload)


def validate_staging(
    staging_path: str, expected: Optional[BuildStats] = None
) -> list:
    """Validate a staging database before publication.

    Checks cover schema version, integrity, foreign keys, expected
    counts, the one-file-per-page invariant, unique page membership,
    and contiguous deterministic ordering.  An empty result means the
    staging database may be published.
    """

    diagnostics: list = []
    store: Optional[ReviewStore] = None
    try:
        store = ReviewStore.open(staging_path, editable=False)
        diagnostics.extend(store.validate())
        conn = store.raw_connection()
        revision = store.active_revision
        if revision < 1:
            diagnostics.append("staging has no active revision")
        counts = conn.execute(
            "SELECT (SELECT COUNT(*) FROM source_file "
            "WHERE revision = ?), (SELECT COUNT(*) FROM atomic_task "
            "WHERE revision = ?), (SELECT COUNT(*) FROM review_page "
            "WHERE revision = ?), (SELECT COUNT(*) FROM page_task "
            "WHERE revision = ?)",
            (revision, revision, revision, revision),
        ).fetchone()
        file_count, task_count, page_count, member_count = (
            int(value or 0) for value in counts
        )
        if member_count != task_count:
            diagnostics.append(
                f"page membership {member_count} != tasks {task_count}"
            )
        mixed = conn.execute(
            "SELECT COUNT(*) FROM page_task pt "
            "JOIN review_page pg ON pg.revision = pt.revision "
            "AND pg.page_id = pt.page_id "
            "JOIN atomic_task at ON at.revision = pt.revision "
            "AND at.task_id = pt.task_id "
            "WHERE pt.revision = ? AND at.file_id != pg.file_id",
            (revision,),
        ).fetchone()
        if int(mixed[0] or 0):
            diagnostics.append(
                f"{int(mixed[0])} page tasks cross source files"
            )
        order_gaps = conn.execute(
            "SELECT COUNT(*) FROM review_page WHERE revision = ? "
            "AND page_order >= (SELECT COUNT(*) FROM review_page "
            "WHERE revision = ?)",
            (revision, revision),
        ).fetchone()
        if int(order_gaps[0] or 0):
            diagnostics.append("page_order is not contiguous")
        file_gaps = conn.execute(
            "SELECT COUNT(*) FROM source_file WHERE revision = ? "
            "AND file_order >= (SELECT COUNT(*) FROM source_file "
            "WHERE revision = ?)",
            (revision, revision),
        ).fetchone()
        if int(file_gaps[0] or 0):
            diagnostics.append("file_order is not contiguous")
        if expected is not None:
            if file_count != expected.files_matched + (
                expected.files_excluded
            ):
                diagnostics.append(f"file count {file_count} != expected")
            if task_count != expected.tasks:
                diagnostics.append(f"task count {task_count} != expected")
            if page_count != expected.pages:
                diagnostics.append(f"page count {page_count} != expected")
    except Exception as exc:  # noqa: BLE001 - diagnostics path
        diagnostics.append(f"staging validation failed: {exc}")
    finally:
        if store is not None:
            try:
                store.close()
            except Exception:
                pass
    return diagnostics


def publish_new_queue(draft: QueueDraft) -> str:
    """Install a validated staging database as a new sidecar.

    The staging store must already be closed and validated; publication
    is an atomic rename so an interrupted publish never leaves a
    half-written sidecar.  Returns the installed sidecar path.
    """

    if draft.cancelled:
        raise ValueError("cannot publish a cancelled draft")
    if draft.diagnostics:
        raise ValueError(
            "cannot publish an invalid staging database: "
            + "; ".join(draft.diagnostics)
        )
    if not draft.staging_path:
        raise ValueError("draft has no staging database")
    sidecar = draft.request.sidecar_path
    if osp.exists(sidecar):
        raise ValueError(f"sidecar already exists: {sidecar}")
    os.replace(draft.staging_path, sidecar)
    _discard_staging(draft.staging_path)
    return sidecar


def publish_rebuild(
    draft: QueueDraft,
    target_store: ReviewStore,
    expected_logical_revision: int,
    confirmed_pairs: Optional[dict] = None,
):
    """Import a validated staging revision into an open queue."""

    if draft.cancelled:
        raise ValueError("cannot publish a cancelled draft")
    if draft.diagnostics:
        raise ValueError(
            "cannot publish an invalid staging database: "
            + "; ".join(draft.diagnostics)
        )
    try:
        result = target_store.import_revision_from_staging(
            draft.staging_path,
            expected_logical_revision,
            confirmed_pairs=confirmed_pairs,
        )
    finally:
        _discard_staging(draft.staging_path)
    return result


def _discard_staging(staging_path: str) -> None:
    """Delete a staging database and its SQLite siblings."""

    if not staging_path:
        return
    for suffix in ("", "-wal", "-shm"):
        candidate = staging_path + suffix
        if osp.exists(candidate):
            try:
                os.remove(candidate)
            except OSError:
                pass


def descriptors_from_lists(
    dataset_root: str,
    image_paths: Sequence[str],
    label_paths: Sequence[str],
) -> tuple[DatasetFileDescriptor, ...]:
    """Build ordered descriptors from parallel path lists.

    Fails closed when the lists disagree in length or contain empty
    entries so a mismatched host mapping can never reach the scanner.
    """

    if len(image_paths) != len(label_paths):
        raise ValueError(
            f"image/label path count mismatch: "
            f"{len(image_paths)} != {len(label_paths)}"
        )
    descriptors = []
    for image_path, label_path in zip(image_paths, label_paths):
        if not image_path or not label_path:
            raise ValueError("empty dataset path entry")
        descriptors.append(
            DatasetFileDescriptor(
                image_path=str(image_path),
                label_path=str(label_path),
                dataset_root=str(dataset_root),
            )
        )
    return tuple(descriptors)


__all__ = [
    "BuildStats",
    "CancelCallback",
    "DatasetFileDescriptor",
    "FileExclusion",
    "ProgressCallback",
    "QueueBuildRequest",
    "QueueDraft",
    "descriptors_from_lists",
    "publish_new_queue",
    "publish_rebuild",
    "request_criteria",
    "request_packing",
    "scan_dataset",
    "validate_staging",
]
