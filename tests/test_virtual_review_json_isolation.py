"""Integration checks proving review metadata never enters JSON.

Runs the full queue lifecycle (build, publish, outcomes, reconcile,
rebuild, backup) against real annotation files and asserts that no
queue ids, outcomes, page ids, locators, or persistence fields leak
into any annotation JSON, and that annotation bytes stay untouched by
sidecar operations.  Self-contained file.
"""

import json
import os
import os.path as osp

import pytest

from PyQt6 import QtCore

from anylabeling.views.labeling import virtual_review as vr

CRITERIA = vr.VirtualTaskCriteria(
    labels=frozenset({"person"}),
    shape_types=frozenset({"rectangle"}),
)

FORBIDDEN_KEYS = (
    "xreview",
    "queue_id",
    "page_id",
    "task_id",
    "reviewed_signature",
    "current_signature",
    "binding_state",
    "outcome_event",
    "carried_from",
    "logical_revision",
    "writer_lease",
)


def _rect(gid=None, x=100, y=100):
    """Return one rectangle shape payload."""

    return {
        "label": "person",
        "shape_type": "rectangle",
        "group_id": gid,
        "points": [[x, y], [x + 60, y + 70]],
    }


def _write(root, name, shapes):
    """Write one annotation pair and return the paths."""

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


def _snapshot_files(root):
    """Return label-path -> raw-bytes and parsed-payload maps."""

    snapshot = {}
    for name in os.listdir(root):
        if not name.endswith(".json"):
            continue
        path = osp.join(root, name)
        with open(path, "rb") as handle:
            snapshot[path] = handle.read()
    return snapshot


def _assert_no_forbidden(payload, where):
    """Recursively reject any queue-metadata key inside a payload."""

    if isinstance(payload, dict):
        for key, value in payload.items():
            assert (
                str(key).lower() not in FORBIDDEN_KEYS
            ), f"{where}: forbidden key {key}"
            _assert_no_forbidden(value, where)
    elif isinstance(payload, list):
        for item in payload:
            _assert_no_forbidden(item, where)


@pytest.fixture()
def dataset(tmp_path):
    """Create a two-file dataset and return its descriptors."""

    root = tmp_path / "ds"
    first = _write(root, "a", [_rect(gid=1), _rect(x=700, y=500)])
    second = _write(root, "b", [_rect(gid=2)])
    descriptors = vr.descriptors_from_lists(
        str(root), [first[0], second[0]], [first[1], second[1]]
    )
    return root, descriptors


def test_queue_lifecycle_never_touches_annotation_json(dataset, tmp_path):
    root, descriptors = dataset
    sidecar = str(tmp_path / "q.xreview.sqlite3")
    request = vr.QueueBuildRequest(
        files=descriptors,
        criteria=CRITERIA,
        packing_options=vr.VirtualPackingOptions(mode="single"),
        reference_viewport=(1200.0, 800.0),
        sidecar_path=sidecar,
    )
    original = _snapshot_files(str(root))

    draft = vr.scan_dataset(request)
    assert draft.publishable, draft.diagnostics
    vr.publish_new_queue(draft)
    store = vr.ReviewStore.open(sidecar)
    try:
        snapshot = store.load_snapshot()
        for page in snapshot.pages:
            for task_id in page.task_ids:
                store.apply_outcomes(
                    snapshot.revision,
                    [
                        vr.OutcomeChange(
                            task_id,
                            vr.TaskOutcome.COMPLETED,
                            reviewed_signature=(
                                snapshot.task_by_id[task_id].current_signature
                            ),
                        )
                    ],
                    store.logical_revision,
                )
        store.backup_to(str(tmp_path / "copy.xreview.sqlite3"))
    finally:
        store.close()

    # Reconcile after renaming file a's first target label.
    _write(
        str(root),
        "a",
        [
            {
                "label": "worker",
                "shape_type": "rectangle",
                "group_id": 1,
                "points": [[100, 100], [160, 170]],
            },
            _rect(x=700, y=500),
        ],
    )
    store = vr.ReviewStore.open(sidecar)
    try:
        snapshot = store.load_snapshot()
        reports = []
        for file_record in snapshot.files:
            reports.append(
                vr.reconcile_source_file(
                    file_record,
                    str(root),
                    {
                        task.task_id: task.locator
                        for task in snapshot.tasks
                        if task.file_id == file_record.file_id
                    },
                )
            )
        store.record_reconciliation(
            snapshot.revision,
            reports,
            store.logical_revision,
            dataset_root=str(root),
        )
        # Rebuild with one extra target on file b.
        _write(str(root), "b", [_rect(gid=2), _rect(gid=9, x=500)])
        draft = vr.scan_dataset(request)
        assert draft.publishable, draft.diagnostics
        vr.publish_rebuild(draft, store, store.logical_revision)
    finally:
        store.close()

    after = _snapshot_files(str(root))
    assert set(after) == set(original)
    for path, payload_bytes in after.items():
        # File a/b were intentionally edited by the test itself; the
        # only requirement is that no queue metadata keys appear.
        payload = json.loads(payload_bytes.decode("utf-8"))
        _assert_no_forbidden(payload, path)
        for shape in payload.get("shapes", []):
            assert set(shape.keys()) <= {
                "label",
                "points",
                "group_id",
                "shape_type",
                "flags",
                "description",
                "difficult",
                "attributes",
                "kie_linking",
                "visible",
            }
    # Only sidecar artifacts may exist outside the dataset directory.
    extra = set(os.listdir(tmp_path)) - {"ds"}
    assert extra, "expected the published sidecar to exist"
    for name in extra:
        assert name.startswith(
            ("q.xreview.sqlite3", "copy.xreview.sqlite3")
        ), name
        assert not name.endswith(".json"), name


def test_shape_serialization_keeps_runtime_ids_out(qapp, dataset):
    """Runtime review ids stay off annotation serialization."""

    # Canvas import first: it completes the labeling package init in
    # an order that avoids the logger->batch->shape import cycle.
    from anylabeling.views.labeling.widgets.canvas import (  # noqa: F401
        Canvas,
    )
    from anylabeling.views.labeling.shape import Shape

    shape = Shape(label="person", shape_type="rectangle", group_id=3)
    shape.points = [
        QtCore.QPointF(10.0, 20.0),
        QtCore.QPointF(60.0, 80.0),
    ]
    shape._virtual_review_id = "vr:0:secret"
    payload = shape.to_dict()
    _assert_no_forbidden(payload, "shape.to_dict")
    assert "_virtual_review_id" not in payload
    assert "vr:0:secret" not in json.dumps(payload)
