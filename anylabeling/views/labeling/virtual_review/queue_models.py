"""Queue-level models for the cross-file dataset review queue.

This module stays pure Python: it defines outcomes, freshness, binding
states, page-state derivation, filters, snapshots, and navigation over a
frozen queue snapshot.  It never imports Qt or the database layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Optional, Sequence


class TaskOutcome(StrEnum):
    """Explicit review outcomes for one atomic task."""

    PENDING = "pending"
    COMPLETED = "completed"
    NEEDS_REWORK = "needs_rework"
    SKIPPED = "skipped"


VALID_OUTCOMES = frozenset(
    outcome.value for outcome in TaskOutcome.__members__.values()
)


class TaskFreshness(StrEnum):
    """Freshness of a recorded outcome relative to current content."""

    FRESH = "fresh"
    STALE = "stale"
    UNRESOLVED = "unresolved"


class BindingState(StrEnum):
    """Live-binding classification of a frozen task against its file."""

    READY = "ready"
    CHANGED_RESOLVED = "changed_resolved"
    MANUALLY_BOUND = "manually_bound"
    ORPHANED = "orphaned"
    AMBIGUOUS = "ambiguous"
    MISSING = "missing"


TRUSTED_BINDINGS = frozenset(
    {
        BindingState.READY,
        BindingState.CHANGED_RESOLVED,
        BindingState.MANUALLY_BOUND,
    }
)


class FileAvailability(StrEnum):
    """Availability of a queued source file."""

    AVAILABLE = "available"
    MISSING = "missing"
    EXCLUDED = "excluded"


class PageState(StrEnum):
    """Derived display state of one review page."""

    FRESH_COMPLETED = "fresh_completed"
    SKIPPED = "skipped"
    ACTIONABLE = "actionable"
    MIXED = "mixed"
    UNRESOLVED = "unresolved"


class QueueFilter(StrEnum):
    """Named task/page filters for navigation and counters."""

    ACTIONABLE = "actionable"
    COMPLETED = "completed"
    NEEDS_REWORK = "needs_rework"
    SKIPPED = "skipped"
    STALE = "stale"
    UNRESOLVED = "unresolved"
    ALL = "all"


DEFAULT_FILTER = QueueFilter.ACTIONABLE


@dataclass(frozen=True)
class SourceFileRecord:
    """One ordered source file inside a frozen queue revision."""

    file_id: str
    order: int
    image_rel_path: str
    label_rel_path: str
    availability: FileAvailability = FileAvailability.AVAILABLE
    exclusion_reason: Optional[str] = None
    source_signature: Optional[str] = None


@dataclass(frozen=True)
class AtomicTaskRecord:
    """One frozen atomic task with its durable review state."""

    task_id: str
    file_id: str
    source_order: int
    locator: dict
    outcome: TaskOutcome = TaskOutcome.PENDING
    freshness: TaskFreshness = TaskFreshness.FRESH
    binding_state: BindingState = BindingState.READY
    reviewed_signature: Optional[str] = None
    current_signature: Optional[str] = None
    note: Optional[str] = None
    carried_from: Optional[str] = None
    created_at: str = ""
    updated_at: str = ""

    @property
    def trusted_binding(self) -> bool:
        """Return whether the task currently has a live binding."""

        return self.binding_state in TRUSTED_BINDINGS

    @property
    def stale_completed(self) -> bool:
        """Return whether this task is a stale completion."""

        return (
            self.outcome is TaskOutcome.COMPLETED
            and self.freshness is TaskFreshness.STALE
        )

    @property
    def actionable(self) -> bool:
        """Return whether the task belongs to the default work view."""

        if not self.trusted_binding:
            return False
        if self.outcome in (TaskOutcome.PENDING, TaskOutcome.NEEDS_REWORK):
            return True
        return self.stale_completed


@dataclass(frozen=True)
class PageRecord:
    """One frozen image-local page inside a queue revision."""

    page_id: str
    file_id: str
    order: int
    bbox: Optional[tuple[float, float, float, float]] = None
    projected_scale: float = 0.0
    fallback: bool = False
    task_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class QueueSnapshot:
    """A frozen, fully loaded view of one queue revision."""

    revision: int
    files: tuple[SourceFileRecord, ...]
    pages: tuple[PageRecord, ...]
    tasks: tuple[AtomicTaskRecord, ...]
    filter_name: QueueFilter = DEFAULT_FILTER

    def __post_init__(self) -> None:
        """Index records once for deterministic, cheap lookup."""

        object.__setattr__(
            self,
            "filter_name",
            QueueFilter(self.filter_name),
        )
        task_index = {record.task_id: record for record in self.tasks}
        object.__setattr__(self, "_task_index", task_index)
        object.__setattr__(
            self,
            "_file_index",
            {record.file_id: record for record in self.files},
        )
        object.__setattr__(
            self,
            "_page_index",
            {record.page_id: record for record in self.pages},
        )
        object.__setattr__(
            self,
            "_page_tasks",
            {
                page.page_id: tuple(
                    task_index[task_id]
                    for task_id in page.task_ids
                    if task_id in task_index
                )
                for page in self.pages
            },
        )

    @property
    def file_by_id(self) -> dict[str, SourceFileRecord]:
        """Return source files keyed by id."""

        return self._file_index  # type: ignore[attr-defined]

    @property
    def task_by_id(self) -> dict[str, AtomicTaskRecord]:
        """Return tasks keyed by id."""

        return self._task_index  # type: ignore[attr-defined]

    @property
    def page_by_id(self) -> dict[str, PageRecord]:
        """Return pages keyed by id."""

        return self._page_index  # type: ignore[attr-defined]

    @property
    def tasks_by_page(self) -> dict[str, tuple[AtomicTaskRecord, ...]]:
        """Return ordered member tasks keyed by page id."""

        return self._page_tasks  # type: ignore[attr-defined]


def derive_page_state(tasks: Sequence[AtomicTaskRecord]) -> PageState:
    """Derive the display state of a page from its member tasks.

    The precedence is deterministic: fully skipped pages and freshly
    completed pages are terminal states; pages with any actionable task
    stay actionable even when other members lack a live binding; pages
    whose members are all reviewed but lack bindings report unresolved;
    remaining outcome combinations report mixed.
    """

    members = tuple(tasks)
    if not members:
        return PageState.UNRESOLVED
    if all(
        task.outcome is TaskOutcome.SKIPPED for task in members
    ):  # pragma: no cover - trivial branch
        return PageState.SKIPPED
    if all(
        task.outcome is TaskOutcome.COMPLETED
        and task.freshness is TaskFreshness.FRESH
        for task in members
    ):
        return PageState.FRESH_COMPLETED
    if any(task.actionable for task in members):
        return PageState.ACTIONABLE
    if any(not task.trusted_binding for task in members):
        return PageState.UNRESOLVED
    return PageState.MIXED


def page_has_unresolved(tasks: Sequence[AtomicTaskRecord]) -> bool:
    """Return whether any member task lacks a trustworthy binding."""

    return any(not task.trusted_binding for task in tasks)


def task_matches_filter(
    task: AtomicTaskRecord, filter_name: QueueFilter
) -> bool:
    """Return whether one task belongs to a named filter."""

    flt = QueueFilter(filter_name)
    if flt is QueueFilter.ALL:
        return True
    if flt is QueueFilter.ACTIONABLE:
        return task.actionable
    if flt is QueueFilter.COMPLETED:
        return task.outcome is TaskOutcome.COMPLETED
    if flt is QueueFilter.NEEDS_REWORK:
        return task.outcome is TaskOutcome.NEEDS_REWORK
    if flt is QueueFilter.SKIPPED:
        return task.outcome is TaskOutcome.SKIPPED
    if flt is QueueFilter.STALE:
        return task.stale_completed
    return not task.trusted_binding


def page_matches_filter(
    tasks: Sequence[AtomicTaskRecord], filter_name: QueueFilter
) -> bool:
    """Return whether a page has at least one task in the filter."""

    return any(task_matches_filter(task, filter_name) for task in tasks)


def page_navigable(
    page: PageRecord,
    tasks: Sequence[AtomicTaskRecord],
    availability: FileAvailability,
) -> bool:
    """Return whether automatic navigation may activate this page.

    Hard constraints: the file must exist, and at least one member must
    have a trustworthy live binding so activation can focus something.
    """

    if availability is not FileAvailability.AVAILABLE:
        return False
    return any(task.trusted_binding for task in tasks)


@dataclass(frozen=True)
class QueueSummary:
    """Aggregated counters for one queue revision."""

    total_files: int = 0
    total_pages: int = 0
    total_tasks: int = 0
    tasks_by_outcome: dict[str, int] = field(default_factory=dict)
    tasks_by_freshness: dict[str, int] = field(default_factory=dict)
    tasks_by_binding: dict[str, int] = field(default_factory=dict)
    pages_by_state: dict[str, int] = field(default_factory=dict)
    actionable_tasks: int = 0
    actionable_pages: int = 0
    unresolved_tasks: int = 0
    stale_tasks: int = 0

    @property
    def completion_ratio(self) -> float:
        """Return the fresh-completion ratio over all tasks."""

        if self.total_tasks == 0:
            return 0.0
        fresh_done = (
            self.tasks_by_outcome.get(TaskOutcome.COMPLETED.value, 0)
            - self.stale_tasks
        )
        return max(0, fresh_done) / self.total_tasks


def summarize_snapshot(snapshot: QueueSnapshot) -> QueueSummary:
    """Count tasks and pages by outcome, freshness, and binding."""

    tasks_by_outcome: dict[str, int] = {}
    tasks_by_freshness: dict[str, int] = {}
    tasks_by_binding: dict[str, int] = {}
    for task in snapshot.tasks:
        tasks_by_outcome[task.outcome.value] = (
            tasks_by_outcome.get(task.outcome.value, 0) + 1
        )
        tasks_by_freshness[task.freshness.value] = (
            tasks_by_freshness.get(task.freshness.value, 0) + 1
        )
        tasks_by_binding[task.binding_state.value] = (
            tasks_by_binding.get(task.binding_state.value, 0) + 1
        )
    tasks_by_page = snapshot.tasks_by_page
    file_by_id = snapshot.file_by_id
    pages_by_state: dict[str, int] = {}
    actionable_pages = 0
    for page in snapshot.pages:
        members = tasks_by_page.get(page.page_id, ())
        state = derive_page_state(members)
        pages_by_state[state.value] = pages_by_state.get(state.value, 0) + 1
        availability = file_by_id[page.file_id].availability
        if page_navigable(page, members, availability) and any(
            task.actionable for task in members
        ):
            actionable_pages += 1
    return QueueSummary(
        total_files=len(snapshot.files),
        total_pages=len(snapshot.pages),
        total_tasks=len(snapshot.tasks),
        tasks_by_outcome=tasks_by_outcome,
        tasks_by_freshness=tasks_by_freshness,
        tasks_by_binding=tasks_by_binding,
        pages_by_state=pages_by_state,
        actionable_tasks=sum(1 for task in snapshot.tasks if task.actionable),
        actionable_pages=actionable_pages,
        unresolved_tasks=sum(
            1 for task in snapshot.tasks if not task.trusted_binding
        ),
        stale_tasks=sum(1 for task in snapshot.tasks if task.stale_completed),
    )


@dataclass(frozen=True)
class QueueNavigationPlan:
    """Result of looking for the next eligible page."""

    target: Optional[PageRecord]
    boundary: bool
    skipped_page_ids: tuple[str, ...] = ()
    message: str = ""


def eligible_pages(
    snapshot: QueueSnapshot, filter_name: QueueFilter
) -> tuple[PageRecord, ...]:
    """Return all navigation-eligible pages in frozen order."""

    tasks_by_page = snapshot.tasks_by_page
    file_by_id = snapshot.file_by_id
    selected = []
    for page in snapshot.pages:
        members = tasks_by_page.get(page.page_id, ())
        availability = file_by_id[page.file_id].availability
        if page_navigable(page, members, availability) and page_matches_filter(
            members, filter_name
        ):
            selected.append(page)
    return tuple(selected)


def find_next_eligible(
    snapshot: QueueSnapshot,
    current_page_id: Optional[str],
    filter_name: QueueFilter,
    delta: int,
) -> QueueNavigationPlan:
    """Find the next eligible page in one direction without wrapping.

    ``delta > 0`` searches forward in frozen page order, ``delta < 0``
    searches backward.  Repeated navigation never wraps silently; the
    boundary flag reports the end of the queue.
    """

    if delta == 0:
        raise ValueError("delta must be a non-zero direction")
    ordered = eligible_pages(snapshot, filter_name)
    if not ordered:
        return QueueNavigationPlan(None, True, message="no_eligible_pages")
    ids = [page.page_id for page in ordered]
    start_index = 0
    if current_page_id in ids:
        step = 1 if delta > 0 else -1
        start_index = ids.index(current_page_id) + step
    elif delta < 0:
        start_index = len(ordered)
    if 0 <= start_index < len(ordered):
        return QueueNavigationPlan(ordered[start_index], False)
    boundary = "last_page" if delta > 0 else "first_page"
    return QueueNavigationPlan(None, True, message=boundary)


def find_resume_target(
    snapshot: QueueSnapshot,
    saved_page_id: Optional[str],
    filter_name: QueueFilter,
) -> QueueNavigationPlan:
    """Select the nearest next eligible page for resume.

    The saved page wins when it is still navigation-eligible under the
    active filter; otherwise the first eligible page strictly after it
    in frozen order is chosen, mirroring nearest-next resume semantics.
    """

    ordered = eligible_pages(snapshot, filter_name)
    if not ordered:
        return QueueNavigationPlan(None, True, message="no_eligible_pages")
    if saved_page_id is None:
        return QueueNavigationPlan(ordered[0], False)
    page_by_id = snapshot.page_by_id
    saved = page_by_id.get(saved_page_id)
    eligible_ids = {page.page_id for page in ordered}
    if saved is not None and saved.page_id in eligible_ids:
        return QueueNavigationPlan(saved, False)
    if saved is None:
        return QueueNavigationPlan(ordered[0], False, message="saved_missing")
    saved_order = saved.order
    for page in ordered:
        if page.order > saved_order:
            return QueueNavigationPlan(
                page, False, message="saved_not_eligible"
            )
    return QueueNavigationPlan(None, True, message="no_eligible_after_saved")


__all__ = [
    "DEFAULT_FILTER",
    "FileAvailability",
    "PageRecord",
    "PageState",
    "QueueFilter",
    "QueueNavigationPlan",
    "QueueSnapshot",
    "QueueSummary",
    "SourceFileRecord",
    "TaskFreshness",
    "TaskOutcome",
    "AtomicTaskRecord",
    "BindingState",
    "TRUSTED_BINDINGS",
    "VALID_OUTCOMES",
    "derive_page_state",
    "eligible_pages",
    "find_next_eligible",
    "find_resume_target",
    "page_has_unresolved",
    "page_matches_filter",
    "page_navigable",
    "summarize_snapshot",
    "task_matches_filter",
]
