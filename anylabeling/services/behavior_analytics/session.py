"""Application, project, image and object interaction session state."""

from __future__ import annotations

from dataclasses import dataclass

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


@dataclass(frozen=True)
class ObjectEpisode:
    """One continuous selection/editing round for a shape."""

    object_episode_id: str
    shape_id: str
    image_id: str
    started_at: ClockReading


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
        return self.project_session

    def enter_image(self, image_path: str) -> ImageVisit:
        """Begin an image visit and close the current object episode."""
        if self.project_session is None:
            raise RuntimeError("project session has not started")
        self.object_episode = None
        visit = ImageVisit(
            image_visit_id=new_session_id("image-visit"),
            image_id=self._hasher.image_id(self._project_root, image_path),
            image_path=image_path,
            started_at=self._clock.read(),
        )
        self.image_visit = visit
        return visit

    def select_shape(self, shape_id: str) -> ObjectEpisode:
        """Select a shape, starting a new episode when identity changes."""
        if self.image_visit is None:
            raise RuntimeError("image visit has not started")
        current = self.object_episode
        if current is not None and current.shape_id == shape_id:
            return current
        self._episode_counter += 1
        episode = ObjectEpisode(
            object_episode_id=(f"{shape_id}-episode-{self._episode_counter}"),
            shape_id=shape_id,
            image_id=self.image_visit.image_id,
            started_at=self._clock.read(),
        )
        self.object_episode = episode
        return episode

    def clear_shape(self) -> ObjectEpisode | None:
        """End the current object episode and return its final value."""
        episode = self.object_episode
        self.object_episode = None
        return episode

    def close_project(self) -> ProjectSession | None:
        """Close all nested contexts while returning the project session."""
        project = self.project_session
        self.object_episode = None
        self.image_visit = None
        self.project_session = None
        return project
