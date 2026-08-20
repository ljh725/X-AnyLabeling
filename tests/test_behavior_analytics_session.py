"""Tests for behavior analytics identity and session boundaries."""

from dataclasses import dataclass

import pytest

from anylabeling.services.behavior_analytics import (
    IdentifierHasher,
    SessionTracker,
)


@dataclass
class FakeReading:
    """Deterministic reading returned by the fake clock."""

    occurred_at_utc: str
    local_date: str
    timezone_offset: str
    monotonic_ms: int


class FakeClock:
    """Clock that advances through a supplied sequence."""

    def __init__(self):
        self.readings = iter(
            [
                FakeReading("2026-08-20T15:59:00Z", "2026-08-20", "+08:00", 0),
                FakeReading(
                    "2026-08-20T15:59:01Z", "2026-08-20", "+08:00", 1000
                ),
                FakeReading(
                    "2026-08-20T16:00:01Z", "2026-08-21", "+08:00", 61000
                ),
                FakeReading(
                    "2026-08-20T16:00:02Z", "2026-08-21", "+08:00", 62000
                ),
                FakeReading(
                    "2026-08-20T16:00:03Z", "2026-08-21", "+08:00", 63000
                ),
            ]
        )

    def read(self):
        """Return the next deterministic reading."""
        return next(self.readings)


def test_project_id_is_stable_with_same_private_salt(tmp_path):
    """The same project and salt produce the same anonymous ID."""
    hasher = IdentifierHasher(salt=b"test-salt")
    assert hasher.project_id(str(tmp_path)) == hasher.project_id(str(tmp_path))
    assert hasher.project_id(str(tmp_path)) != IdentifierHasher(
        salt=b"other-salt"
    ).project_id(str(tmp_path))


def test_session_tracker_keeps_project_across_midnight(tmp_path):
    """A project session spans midnight while day slices change."""
    tracker = SessionTracker(
        str(tmp_path),
        hasher=IdentifierHasher(salt=b"test-salt"),
        clock=FakeClock(),
        app_session_id="app-fixed",
    )
    project = tracker.start_project()
    visit = tracker.enter_image(str(tmp_path / "image-a.jpg"))
    assert project.project_session_id.startswith("project-session-")
    assert project.day_slice_id(project.started_at).endswith("2026-08-20")
    midnight = FakeReading("", "2026-08-21", "+08:00", 61000)
    assert project.day_slice_id(midnight).endswith("2026-08-21")
    assert visit.image_id.startswith("image-")


def test_object_episodes_distinguish_a_b_a(tmp_path):
    """Returning to A keeps identity but opens a new interaction episode."""
    tracker = SessionTracker(
        str(tmp_path),
        clock=FakeClock(),
        app_session_id="app-fixed",
    )
    tracker.start_project()
    tracker.enter_image(str(tmp_path / "image-a.jpg"))
    first_a = tracker.select_shape("shape-a")
    shape_b = tracker.select_shape("shape-b")
    second_a = tracker.select_shape("shape-a")
    assert first_a.shape_id == second_a.shape_id == "shape-a"
    assert first_a.object_episode_id != second_a.object_episode_id
    assert shape_b.shape_id == "shape-b"
    assert tracker.clear_shape() == second_a


def test_tracker_requires_project_and_image_context(tmp_path):
    """Nested identities cannot be created without their parent context."""
    tracker = SessionTracker(str(tmp_path))
    with pytest.raises(RuntimeError, match="project session"):
        tracker.enter_image("image.jpg")
    tracker.start_project()
    with pytest.raises(RuntimeError, match="image visit"):
        tracker.select_shape("shape-a")
