"""Tests for virtual review page session navigation."""

from anylabeling.views.labeling.virtual_review import (
    VirtualReviewPage,
    VirtualReviewSession,
)


def _page(page_id, anchors):
    return VirtualReviewPage(
        page_id=page_id,
        task_ids=tuple(f"task:{anchor}" for anchor in anchors),
        member_ids=tuple(f"member:{anchor}" for anchor in anchors),
        anchor_ids=tuple(anchors),
    )


def test_start_and_navigation_are_frozen():
    session = VirtualReviewSession()
    pages = (_page("p1", ("s1",)), _page("p2", ("s2",)))

    started = session.start(pages)
    assert started.page == pages[0]
    assert started.total == 2

    moved = session.move(1, {"s1", "s2"})
    assert moved.page == pages[1]
    assert session.pages == pages


def test_boundaries_keep_current_page():
    session = VirtualReviewSession()
    pages = (_page("p1", ("s1",)), _page("p2", ("s2",)))
    session.start(pages)

    previous = session.move(-1)
    assert previous.boundary is True
    assert previous.message == "first_page"
    assert previous.page == pages[0]
    session.move(1)
    following = session.move(1)
    assert following.boundary is True
    assert following.message == "last_page"
    assert following.page == pages[1]


def test_fully_deleted_page_is_skipped_and_reported():
    session = VirtualReviewSession()
    pages = (
        _page("p1", ("gone",)),
        _page("p2", ("s2",)),
    )
    session.start(pages)

    result = session.move(1, {"s2"})

    assert result.page == pages[1]
    assert result.skipped_page_ids == ("p1",)


def test_partially_deleted_page_survives():
    session = VirtualReviewSession()
    combined = VirtualReviewPage(
        page_id="p1",
        task_ids=("task:a", "task:b"),
        member_ids=("member:a", "member:b"),
        anchor_ids=("a", "b"),
    )
    following = _page("p2", ("s2",))
    session.start((combined, following))

    result = session.move(1, {"b", "s2"})

    assert result.page == following
    moved_back = session.move(-1, {"b"})
    assert moved_back.page == combined
    assert moved_back.skipped_page_ids == ("p2",)


def test_inactive_session_reports_inactive():
    result = VirtualReviewSession().move(1)

    assert result.page is None
    assert result.message == "inactive"


def test_empty_session_reports_no_pages():
    result = VirtualReviewSession().start(())

    assert result.page is None
    assert result.message == "no_pages"


def test_explicit_rebuild_replaces_frozen_membership():
    session = VirtualReviewSession()
    session.start((_page("p1", ("s1",)),))
    rebuilt = (_page("new1", ("n1", "n2")), _page("new2", ("n3",)))

    result = session.start(rebuilt)

    assert session.pages == rebuilt
    assert result.page == rebuilt[0]
    assert session.index == 0
