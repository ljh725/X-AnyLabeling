"""State restoration and bounded-history probes for round two."""
from tests.test_dense_review.conftest import make_shape
from tests.test_dense_review.test_session import build_session


def test_undo_both_moves_restores_original_confirmation():
    shape = make_shape("a", bounds=(5, 5, 15, 15))
    session = build_session([shape])
    session.confirm_object("a", ("category", "geometry"))
    assert session.object("a").confirmed_both()
    shape.move_by(10, 0)
    session.sync_shapes([shape])
    shape.move_by(-10, 0)
    session.sync_shapes([shape])
    shape.move_by(10, 0)
    session.undo_after_canvas([shape])
    shape.move_by(-10, 0)
    session.undo_after_canvas([shape])
    assert session.object("a").confirmed_both(), (
        "Undoing both edits must restore the confirmation that existed before those edits"
    )


def test_progress_history_limit_does_not_expose_missing_snapshot():
    session = build_session([make_shape("a")])
    for index in range(51):
        if index % 2 == 0:
            session.mark_difficult("a")
        else:
            session.clear_difficult("a")
    for _ in range(50):
        assert session.can_undo_progress()
        assert session.undo_progress()
    if session.can_undo_progress():
        # A retained transaction must have a matching snapshot to restore.
        assert session.undo_progress()
