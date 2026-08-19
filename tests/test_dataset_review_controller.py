"""Controller tests with fake host/load/save adapters.

Covers cross-file success, dirty save/discard/cancel decisions,
destination load failure, completion save failure, complete-and-next
ordering, filtering, persistence blocking, and the local/dataset
mutual exclusion guard.  Self-contained offscreen test file.
"""

import json
import os
import os.path as osp
import sqlite3

import pytest

from PyQt6 import QtCore

from anylabeling.views.labeling import virtual_review as vr
from anylabeling.views.labeling.widgets.inspector import (
    dataset_review_controller as drc_module,
)
from anylabeling.views.labeling.widgets.inspector.dataset_review_controller import (  # noqa: E501
    DatasetReviewController,
    DatasetReviewState,
)

CRITERIA = vr.VirtualTaskCriteria(
    labels=frozenset({"person"}),
    shape_types=frozenset({"rectangle"}),
)
PACKING = vr.VirtualPackingOptions(mode="single")
VIEWPORT = (1200.0, 800.0)


def _rect(gid=None, x=100, y=100, w=60, h=70, label="person"):
    """Return one rectangle shape payload."""

    return {
        "label": label,
        "shape_type": "rectangle",
        "group_id": gid,
        "points": [[x, y], [x + w, y + h]],
    }


def _write(root, name, shapes):
    """Write one annotation pair and return absolute paths."""

    os.makedirs(root, exist_ok=True)
    image_path = osp.join(root, f"{name}.jpg")
    label_path = osp.join(root, f"{name}.json")
    with open(image_path, "wb") as handle:
        handle.write(b"img")
    with open(label_path, "w", encoding="utf-8") as handle:
        json.dump(
            {"imageWidth": 1000, "imageHeight": 800, "shapes": shapes},
            handle,
        )
    return image_path, label_path


class FakeHost(QtCore.QObject):
    """Host double exposing only the dataset-review host API."""

    dataset_review_load_finished = QtCore.pyqtSignal(str, bool, int, bool)

    def __init__(self, root):
        """Initialize scripted host state."""

        super().__init__()
        self.root = str(root)
        self.descriptors = ()
        self.dirty = False
        self.dirty_decision = "save"
        self.save_result = True
        self.edit_guard = False
        self.current_image = None
        self.load_behaviour = {}  # path -> ok
        self.load_calls = []

    def dataset_review_descriptors(self):
        """Return the configured ordered descriptors."""

        return self.descriptors

    def dataset_review_resolve_dirty(self):
        """Resolve dirty state like the real guard, saving on 'save'."""

        if not self.dirty:
            return "save"
        if self.dirty_decision == "save":
            if self.dataset_review_save_current():
                return "save"
            return "save_failed"
        return self.dirty_decision

    def dataset_review_save_current(self):
        """Return the scripted save result and clear dirty on success."""

        if not self.dirty:
            return True
        if self.save_result:
            self.dirty = False
        return self.save_result

    def dataset_review_current_image(self):
        """Return the current image path of the (fake) viewer."""

        return self.current_image

    def dataset_review_edit_guard_active(self):
        """Return the scripted transient-edit state."""

        return self.edit_guard

    def dataset_review_request_load(self, image_path, token):
        """Simulate a guarded asynchronous load of one image."""

        self.load_calls.append((str(image_path), int(token)))
        self.current_image = str(image_path)
        ok = self.load_behaviour.get(str(image_path), True)
        if ok:
            # Populate the fake local controller with the on-disk
            # shapes so rehydration has live content to bind.
            label_path = osp.splitext(str(image_path))[0] + ".json"
            scan = vr.scan_annotation_file(label_path)
            views, points = vr.views_from_annotation(scan)
            self.local.views = views
            self.local.points = points
        self.dataset_review_load_finished.emit(
            str(image_path), bool(ok), int(token), False
        )


class FakeLocal:
    """Image-local controller double for dataset-mode ownership."""

    def __init__(self):
        self.dataset_mode = False
        self.exit_calls = 0
        self.installed = []
        self.views = ()
        self.points = {}

    def enter_dataset_mode(self):
        """Take ownership of the review focus."""

        self.dataset_mode = True

    def exit_dataset_mode(self):
        """Release ownership and count exits."""

        self.dataset_mode = False
        self.exit_calls += 1

    def install_dataset_page(self, page, progress):
        """Record installed pages; fail when nothing is live."""

        self.installed.append((page, progress))
        return len(page.member_ids) > 0

    def dataset_shape_payloads(self):
        """Return current views/points for rehydration."""

        return self.views, self.points, {}


@pytest.fixture()
def env(qapp, tmp_path):
    """Create a two-file queue with fake host and controller wiring."""

    root = tmp_path / "ds"
    first = _write(root, "a", [_rect(gid=1)])
    second = _write(root, "b", [_rect(gid=2)])
    descriptors = vr.descriptors_from_lists(
        str(root), [first[0], second[0]], [first[1], second[1]]
    )
    sidecar = tmp_path / "q.xreview.sqlite3"
    request = vr.QueueBuildRequest(
        files=descriptors,
        criteria=CRITERIA,
        packing_options=PACKING,
        reference_viewport=VIEWPORT,
        sidecar_path=str(sidecar),
    )
    draft = vr.scan_dataset(request)
    assert draft.publishable, draft.diagnostics
    vr.publish_new_queue(draft)

    host = FakeHost(root)
    host.descriptors = descriptors
    local = FakeLocal()
    host.local = local
    controller = DatasetReviewController(host, local)
    host.controller = controller
    return controller, host, local, str(root), str(sidecar)


def _wait(controller, predicate, timeout_ms=5000):
    """Process events until a condition holds or time runs out."""

    from PyQt6 import QtCore

    deadline = QtCore.QTime.currentTime().addMSecs(timeout_ms)
    while not predicate():
        if QtCore.QTime.currentTime() > deadline:
            return False
        QtCore.QCoreApplication.processEvents(
            QtCore.QEventLoop.ProcessEventsFlag.AllEvents, 20
        )
    return True


def test_open_and_cross_file_transition_commits_cursor(env):
    controller, host, local, root, sidecar = env
    controller.open_queue(sidecar)
    assert _wait(
        controller,
        lambda: controller.state is DatasetReviewState.ACTIVE,
    )
    assert local.dataset_mode is True
    assert controller.current_page_id is not None

    store = vr.ReviewStore.open(sidecar, editable=False)
    try:
        first_cursor = store.load_cursor()
        assert first_cursor.page_id == controller.current_page_id
    finally:
        store.close()

    controller.next_page()
    assert _wait(
        controller,
        lambda: controller.state is DatasetReviewState.ACTIVE
        and any(call[0].endswith("b.jpg") for call in host.load_calls),
    )
    store = vr.ReviewStore.open(sidecar, editable=False)
    try:
        cursor = store.load_cursor()
        assert cursor.page_id == controller.current_page_id
    finally:
        store.close()
    assert local.installed, "target page was never installed"


def test_dirty_save_proceeds_and_cancel_keeps_cursor(env):
    controller, host, local, root, sidecar = env
    controller.open_queue(sidecar)
    assert _wait(
        controller, lambda: controller.state is DatasetReviewState.ACTIVE
    )
    before = controller.current_page_id
    loads_before_cancel = len(host.load_calls)

    host.dirty = True
    host.dirty_decision = "cancel"
    controller.next_page()
    assert _wait(
        controller, lambda: controller.state is DatasetReviewState.ACTIVE
    )
    assert controller.current_page_id == before
    assert len(host.load_calls) == loads_before_cancel

    host.dirty_decision = "save"
    controller.next_page()
    assert _wait(
        controller,
        lambda: controller.state is DatasetReviewState.ACTIVE
        and bool(host.load_calls),
    )
    assert controller.current_page_id != before
    assert host.dirty is False


def test_destination_load_failure_preserves_cursor(env):
    controller, host, local, root, sidecar = env
    controller.open_queue(sidecar)
    assert _wait(
        controller, lambda: controller.state is DatasetReviewState.ACTIVE
    )
    before = controller.current_page_id
    host.load_behaviour[osp.join(root, "b.jpg")] = False
    controller.next_page()
    assert _wait(
        controller, lambda: controller.state is DatasetReviewState.ACTIVE
    )
    assert controller.current_page_id == before
    store = vr.ReviewStore.open(sidecar, editable=False)
    try:
        cursor = store.load_cursor()
        assert cursor.page_id == before
    finally:
        store.close()


def test_completion_requires_successful_save(env):
    controller, host, local, root, sidecar = env
    controller.open_queue(sidecar)
    assert _wait(
        controller, lambda: controller.state is DatasetReviewState.ACTIVE
    )
    page_id = controller.current_page_id
    snapshot = controller.snapshot
    task_id = snapshot.page_by_id[page_id].task_ids[0]

    host.dirty = True
    host.save_result = False
    controller.apply_outcome("completed", [task_id])
    store = vr.ReviewStore.open(sidecar, editable=False)
    try:
        fresh = store.load_snapshot()
        assert fresh.task_by_id[task_id].outcome is vr.TaskOutcome.PENDING
    finally:
        store.close()

    host.save_result = True
    controller.apply_outcome("completed", [task_id])
    store = vr.ReviewStore.open(sidecar, editable=False)
    try:
        fresh = store.load_snapshot()
        record = fresh.task_by_id[task_id]
        assert record.outcome is vr.TaskOutcome.COMPLETED
        assert record.reviewed_signature
    finally:
        store.close()


def test_complete_and_next_survives_navigation_failure(env):
    controller, host, local, root, sidecar = env
    controller.open_queue(sidecar)
    assert _wait(
        controller, lambda: controller.state is DatasetReviewState.ACTIVE
    )
    page_id = controller.current_page_id
    snapshot = controller.snapshot
    task_id = snapshot.page_by_id[page_id].task_ids[0]
    # The only other page fails to load: completion must survive.
    other = osp.join(root, "b.jpg")
    host.load_behaviour[other] = False

    controller.complete_and_next()
    assert _wait(
        controller, lambda: controller.state is DatasetReviewState.ACTIVE
    )
    store = vr.ReviewStore.open(sidecar, editable=False)
    try:
        fresh = store.load_snapshot()
        assert fresh.task_by_id[task_id].outcome is vr.TaskOutcome.COMPLETED
        cursor = store.load_cursor()
        assert cursor.page_id == page_id
    finally:
        store.close()


def test_actionable_filter_skips_fresh_completed_pages(env):
    controller, host, local, root, sidecar = env
    controller.open_queue(sidecar)
    assert _wait(
        controller, lambda: controller.state is DatasetReviewState.ACTIVE
    )
    controller.apply_outcome("completed")
    assert _wait(
        controller, lambda: controller.state is DatasetReviewState.ACTIVE
    )
    snapshot = controller.snapshot
    assert controller.current_page_id == snapshot.pages[0].page_id
    controller.next_page()
    assert _wait(
        controller,
        lambda: controller.state is DatasetReviewState.ACTIVE
        and len(host.load_calls) >= 1,
    )
    assert controller.current_page_id == snapshot.pages[1].page_id
    controller.apply_outcome("completed")
    controller.next_page()
    assert _wait(
        controller, lambda: controller.state is DatasetReviewState.ACTIVE
    )
    # All pages are freshly completed: no further navigation targets.
    assert controller.current_page_id == snapshot.pages[1].page_id


def test_edit_guard_blocks_navigation_and_outcomes(env):
    controller, host, local, root, sidecar = env
    controller.open_queue(sidecar)
    assert _wait(
        controller, lambda: controller.state is DatasetReviewState.ACTIVE
    )
    before = controller.current_page_id
    host.edit_guard = True
    controller.next_page()
    assert controller.state is DatasetReviewState.ACTIVE
    assert controller.current_page_id == before
    controller.apply_outcome("completed")
    store = vr.ReviewStore.open(sidecar, editable=False)
    try:
        fresh = store.load_snapshot()
        assert all(
            task.outcome is vr.TaskOutcome.PENDING for task in fresh.tasks
        )
    finally:
        store.close()
    host.edit_guard = False


def test_persistence_block_and_recovery(env):
    controller, host, local, root, sidecar = env
    controller.open_queue(sidecar)
    assert _wait(
        controller, lambda: controller.state is DatasetReviewState.ACTIVE
    )
    page_id = controller.current_page_id
    snapshot = controller.snapshot
    task_id = snapshot.page_by_id[page_id].task_ids[0]
    # Simulate an unwritable database by closing the raw handle.
    controller._store.raw_connection().close()

    controller.apply_outcome("completed", [task_id])
    assert controller.state is DatasetReviewState.PERSISTENCE_BLOCKED
    assert controller.blocked_reason

    # Further mutations stay blocked; deliberate close still works.
    controller.apply_outcome("skipped", [task_id])
    assert controller.state is DatasetReviewState.PERSISTENCE_BLOCKED
    controller.close_queue(claim_saved=False)
    assert controller.state is DatasetReviewState.CLOSED
    assert local.dataset_mode is False


def test_create_queue_publishes_after_worker_scan(qapp, tmp_path):
    from PyQt6 import QtCore

    root = tmp_path / "ds"
    first = _write(root, "a", [_rect(gid=1)])
    second = _write(root, "b", [_rect(gid=2)])
    descriptors = vr.descriptors_from_lists(
        str(root), [first[0], second[0]], [first[1], second[1]]
    )
    host = FakeHost(root)
    host.descriptors = descriptors
    local = FakeLocal()
    host.local = local
    controller = DatasetReviewController(host, local)
    sidecar = tmp_path / "created.xreview.sqlite3"
    controller.create_queue(str(sidecar), CRITERIA, PACKING, VIEWPORT)
    assert _wait(
        controller,
        lambda: controller.state is DatasetReviewState.ACTIVE,
    ), controller.state
    assert osp.exists(str(sidecar))
    assert local.installed
    controller.close_queue()
    assert _wait(
        controller,
        lambda: controller.state is DatasetReviewState.CLOSED,
    )
    QtCore.QCoreApplication.processEvents()


def test_cancel_scan_without_worker_is_safe(env):
    controller, host, local, root, sidecar = env
    controller.cancel_scan()
    assert controller.state is DatasetReviewState.IDLE


def test_reconcile_updates_without_changing_membership(env):
    controller, host, local, root, sidecar = env
    controller.open_queue(sidecar)
    assert _wait(
        controller, lambda: controller.state is DatasetReviewState.ACTIVE
    )
    snapshot = controller.snapshot
    page_ids = [page.page_id for page in snapshot.pages]
    # Rename file b's target so reconcile reports a changed binding.
    _write(root, "b", [_rect(gid=2, label="worker")])
    controller.reconcile()
    assert controller.state is DatasetReviewState.ACTIVE
    fresh = controller.snapshot
    assert [page.page_id for page in fresh.pages] == page_ids
    changed = [
        task
        for task in fresh.tasks
        if task.binding_state is vr.BindingState.CHANGED_RESOLVED
    ]
    assert changed


def test_stale_lease_takeover_flow(env):
    controller, host, local, root, sidecar = env
    # Simulate a crashed holder before opening.
    controller.shutdown()
    conn = sqlite3.connect(sidecar)
    old = "2000-01-01T00:00:00+00:00"
    conn.execute("DELETE FROM writer_lease")
    conn.execute(
        "INSERT INTO writer_lease (id, instance_id, pid, host, "
        "acquired_at, heartbeat_at) VALUES (1, 'ghost', 999999999, "
        "'ghost-host', ?, ?)",
        (old, old),
    )
    conn.commit()
    conn.close()

    prompts = []
    controller.takeover_prompt.connect(prompts.append)
    controller.open_queue(sidecar)
    assert controller.state is DatasetReviewState.IDLE
    assert prompts and prompts[0]["instance_id"] == "ghost"

    controller.open_queue(sidecar, takeover=True)
    assert _wait(
        controller, lambda: controller.state is DatasetReviewState.ACTIVE
    )
    store = vr.ReviewStore.open(sidecar, editable=False)
    try:
        events = (
            store.raw_connection()
            .execute("SELECT kind FROM reconciliation_event")
            .fetchall()
        )
        assert ("lease_takeover",) in events
    finally:
        store.close()
    controller.close_queue()


def test_local_start_blocked_while_dataset_session_active(qapp, env):
    """Local single-image review refuses to start under a dataset session."""

    controller, host, local, root, sidecar = env
    controller.open_queue(sidecar)
    assert _wait(
        controller, lambda: controller.state is DatasetReviewState.ACTIVE
    )

    from types import SimpleNamespace

    from PyQt6 import QtWidgets

    from anylabeling.views.labeling.widgets.inspector import (
        virtual_review_controller as vrc_module,
    )
    from anylabeling.views.labeling.widgets.inspector import (
        virtual_review_widget as vrw_module,
    )

    class _Canvas:
        def __init__(self):
            self.shapes = []

        def drawing(self):
            return False

    label_host = QtWidgets.QWidget()
    label_host.canvas = _Canvas()
    label_host._virtual_review_active = False
    label_host.status_messages = []
    label_host.status = label_host.status_messages.append
    label_host.dataset_review_controller = controller
    review = vrw_module.VirtualReviewWidget()
    local_controller = vrc_module.VirtualReviewController(label_host, review)
    local_controller.start(
        {
            "criteria": {
                "labels": frozenset({"person"}),
                "shape_types": frozenset({"rectangle"}),
            },
            "packing": {},
        }
    )
    assert local_controller.active is False
    assert any(
        "数据集复核队列" in message for message in label_host.status_messages
    )
    review.deleteLater()
    label_host.deleteLater()
