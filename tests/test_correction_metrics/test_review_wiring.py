"""Ordinary shape undo and redo preserve correction statistics."""


from .test_controller import make_host, rect, started


def test_undo_event_links_the_previous_transaction(tmp_path):
    """canvas 撤销事件自动带上 undo_of = 最近一次事务 id。"""
    controller, _host = started(tmp_path, [rect("r1")])
    controller.enter_image()
    first = [rect("r1", box=(20, 20, 60, 80))]
    second = [rect("r1", box=(30, 30, 70, 90))]
    controller.edit("geometry", changed=first, transaction_id="tx-1")
    controller.edit("geometry", changed=second, transaction_id="tx-2")

    # The canvas restores the snapshot taken before tx-2.
    assert controller.edit("undo", changed=first) is True

    current = controller.current_row()
    assert current["transactions"] == 2
    assert current["undo_count"] == 1
    controller._store.flush()
    events = controller._store.events(current["round_id"])
    undo = [event for event in events if event["kind"] == "undo"]
    assert len(undo) == 1
    assert undo[0]["undo_of"] == "tx-2"
    assert undo[0]["id"] != "tx-2"


def test_redo_is_not_counted_as_a_new_correction(tmp_path):
    controller, _host = started(tmp_path, [rect("r1")])
    controller.enter_image()
    forward = [rect("r1", box=(20, 20, 60, 80))]
    controller.edit("geometry", changed=forward, transaction_id="tx-1")
    controller.edit("undo", changed=[rect("r1")])
    controller.edit("redo", changed=forward, transaction_id="tx-redo")

    assert controller.current_row()["transactions"] == 1  # geometry only
