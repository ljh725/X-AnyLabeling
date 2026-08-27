"""Application, project, image and object interaction session state."""

from __future__ import annotations

from dataclasses import dataclass, field

from .clock import ClockReading, SystemClock
from .identifiers import IdentifierHasher, new_session_id


@dataclass(frozen=True)
class ProjectSession:
    """Identity and current local-day slice for an open project."""

    app_session_id: str
    project_session_id: str
    project_id: str
    project_root: str
    started_at: ClockReading

    def day_slice_id(self, reading: ClockReading) -> str:
        """Return the stable day slice key for a clock reading."""
        return f"{self.project_session_id}:{reading.local_date}"


@dataclass(frozen=True)
class ImageVisit:
    """One visit to an image during a project session."""

    image_visit_id: str
    image_id: str
    image_path: str
    started_at: ClockReading
    ended_at: ClockReading | None = None
    end_reason: str | None = None


@dataclass
class ActivitySegment:
    """A focused, non-idle interval within one object episode."""

    segment_id: str
    started_at: ClockReading
    ended_at: ClockReading | None = None
    end_reason: str | None = None

    @property
    def active_ms(self) -> int | None:
        """Return active duration when the segment is closed."""
        if self.ended_at is None:
            return None
        return max(
            0, self.ended_at.monotonic_ms - self.started_at.monotonic_ms
        )


@dataclass
class ObjectEpisode:
    """One continuous selection/editing round for a shape."""

    object_episode_id: str
    shape_id: str
    image_id: str
    started_at: ClockReading
    ended_at: ClockReading | None = None
    end_reason: str | None = None
    changed: bool = False
    saved_after_change: bool = False
    action_count: int = 0
    terminal_integrity: str = "open"
    selection_source: str = "user_canvas_single"
    selection_batch_id: str | None = None
    segments: list[ActivitySegment] = field(default_factory=list)

    @property
    def wall_ms(self) -> int | None:
        """Return wall duration for a closed episode."""
        if self.ended_at is None:
            return None
        return max(
            0, self.ended_at.monotonic_ms - self.started_at.monotonic_ms
        )

    @property
    def focused_ms(self) -> int | None:
        """Return duration spent in focused segments."""
        if self.ended_at is None:
            return None
        return self.wall_ms

    @property
    def active_ms(self) -> int | None:
        """Return the sum of closed active segment durations."""
        if self.ended_at is None:
            return None
        return sum(segment.active_ms or 0 for segment in self.segments)

    def ensure_segment(self, reading: ClockReading) -> ActivitySegment:
        """Start an active segment when none is currently open."""
        if self.segments and self.segments[-1].ended_at is None:
            return self.segments[-1]
        segment = ActivitySegment(
            segment_id=f"{self.object_episode_id}-segment-{len(self.segments) + 1}",
            started_at=reading,
        )
        self.segments.append(segment)
        return segment

    def close(self, reading: ClockReading, reason: str) -> None:
        """Close the current segment and episode exactly once."""
        if self.ended_at is not None:
            return
        if self.segments and self.segments[-1].ended_at is None:
            self.segments[-1].ended_at = reading
            self.segments[-1].end_reason = reason
        self.ended_at = reading
        self.end_reason = reason
        self.terminal_integrity = "complete"


class SessionTracker:
    """Track orthogonal session identities without emitting UI events."""

    def __init__(
        self,
        project_root: str,
        *,
        hasher: IdentifierHasher | None = None,
        clock: SystemClock | None = None,
        app_session_id: str | None = None,
    ) -> None:
        """Initialize a tracker for one application process."""
        self._project_root = project_root
        self._hasher = hasher or IdentifierHasher()
        self._clock = clock or SystemClock()
        self.app_session_id = app_session_id or new_session_id("app")
        self.project_session: ProjectSession | None = None
        self.image_visit: ImageVisit | None = None
        self.object_episode: ObjectEpisode | None = None
        self.closed_episodes: list[ObjectEpisode] = []
        self._episode_counter = 0

    @property
    def clock(self) -> SystemClock:
        """Return the clock used by this tracker."""
        return self._clock

    def start_project(self) -> ProjectSession:
        """Start a new project-open session."""
        reading = self._clock.read()
        self.project_session = ProjectSession(
            app_session_id=self.app_session_id,
            project_session_id=new_session_id("project-session"),
            project_id=self._hasher.project_id(self._project_root),
            project_root=self._project_root,
            started_at=reading,
        )
        self.image_visit = None
        self.object_episode = None
        self.closed_episodes = []
        return self.project_session

    def enter_image(self, image_path: str) -> ImageVisit:
        """Begin an image visit and close the current object episode."""
        if self.project_session is None:
            raise RuntimeError("project session has not started")
        self.end_episode("image_changed")
        visit = ImageVisit(
            image_visit_id=new_session_id("image-visit"),
            image_id=self._hasher.image_id(self._project_root, image_path),
            image_path=image_path,
            started_at=self._clock.read(),
        )
        self.image_visit = visit
        return visit

    def select_shape(
        self,
        shape_id: str,
        *,
        selection_source: str = "user_canvas_single",
        selection_batch_id: str | None = None,
        reading: ClockReading | None = None,
    ) -> ObjectEpisode:
        """Select a shape, starting a new episode when identity changes."""
        return self.select_shape_with_source(
            shape_id,
            selection_source=selection_source,
            selection_batch_id=selection_batch_id,
            reading=reading,
        )

    def select_shape_with_source(
        self,
        shape_id: str,
        *,
        selection_source: str = "user_canvas_single",
        selection_batch_id: str | None = None,
        reading: ClockReading | None = None,
    ) -> ObjectEpisode:
        """Select a shape and retain the source/batch audit metadata."""
        if self.image_visit is None:
            raise RuntimeError("image visit has not started")
        current = self.object_episode
        if current is not None and current.shape_id == shape_id:
            return current
        reading = reading or self._clock.read()
        if current is not None:
            current.close(reading, "selection_changed")
            self.closed_episodes.append(current)
        self._episode_counter += 1
        episode = ObjectEpisode(
            object_episode_id=(f"{shape_id}-episode-{self._episode_counter}"),
            shape_id=shape_id,
            image_id=self.image_visit.image_id,
            started_at=reading,
            selection_source=selection_source,
            selection_batch_id=selection_batch_id,
        )
        episode.ensure_segment(episode.started_at)
        self.object_episode = episode
        return episode

    def clear_shape(self) -> ObjectEpisode | None:
        """End the current object episode and return its final value."""
        return self.end_episode("selection_cleared")

    def end_episode(
        self, reason: str, reading: ClockReading | None = None
    ) -> ObjectEpisode | None:
        """Close the active episode idempotently and retain its audit facts."""
        episode = self.object_episode
        if episode is None:
            return None
        if reading is None:
            try:
                reading = self._clock.read()
            except StopIteration:
                reading = episode.started_at
        episode.close(reading, reason)
        self.closed_episodes.append(episode)
        self.object_episode = None
        return episode

    def mark_changed(self) -> None:
        """Record a proven effective edit for the selected object."""
        if self.object_episode is not None:
            self.object_episode.changed = True

    def mark_saved(self) -> bool:
        """Record one save after a change and avoid duplicate notifications."""
        episode = self.object_episode
        if (
            episode is None
            or not episode.changed
            or episode.saved_after_change
        ):
            return False
        episode.saved_after_change = True
        return True

    def record_action(self, changed: bool = False) -> None:
        """Count a semantic action and optionally mark the episode changed."""
        if self.object_episode is None:
            return
        self.object_episode.action_count += 1
        self.object_episode.ensure_segment(self._clock.read())
        if changed:
            self.mark_changed()

    def pause_activity(self, reason: str) -> None:
        """Close the current active segment while retaining the episode."""
        episode = self.object_episode
        if episode is None or not episode.segments:
            return
        segment = episode.segments[-1]
        if segment.ended_at is None:
            reading = self._clock.read()
            segment.ended_at = reading
            segment.end_reason = reason

    def resume_activity(self) -> None:
        """Start a new active segment in the same selected episode."""
        if self.object_episode is not None:
            self.object_episode.ensure_segment(self._clock.read())

    def close_project(self) -> ProjectSession | None:
        """Close all nested contexts while returning the project session."""
        project = self.project_session
        self.end_episode("project_closed")
        self.image_visit = None
        self.project_session = None
        return project
