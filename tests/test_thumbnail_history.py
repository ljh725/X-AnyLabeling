"""Durable history, field evidence and real JSON inverse transactions."""

import copy
import json
from dataclasses import replace

import pytest

from anylabeling.views.labeling.widgets.dataset_thumbnail.history_store import (
    document_digest,
    read_document,
)
from anylabeling.views.labeling.widgets.dataset_thumbnail.history_inverse import (
    build_inverse_plan,
)
from anylabeling.views.labeling.widgets.dataset_thumbnail.review_store import (
    ReviewStore,
)
from anylabeling.views.labeling.widgets.object_relabel import (
    MarkedObjectRef,
    ObjectRelabelEngine,
    build_object_relabel_plan,
)
from anylabeling.views.labeling.dataset_index.types import DatasetThumbnailRef


def annotation(tmp_path):
    """Create three distinct labels in one annotation document."""
    path = tmp_path / "image.json"
    data = {
        "shapes": [
            dict(
                label=label,
                points=[[0, 0], [20, 20]],
                shape_type="rectangle",
                xanylabeling_shape_id=f"{i:032x}",
            )
            for i, label in enumerate(("person", "head", "other"))
        ],
        "imagePath": "image.png",
    }
    path.write_text(json.dumps(data), encoding="utf-8")
    return path, data


def forward(tmp_path):
    """Execute a real forward transaction and project its durable history."""
    path, data = annotation(tmp_path)
    store = ReviewStore(str(tmp_path / "history.sqlite"))
    refs = tuple(
        MarkedObjectRef(
            str(tmp_path),
            str(tmp_path / "image.png"),
            f"{i:032x}",
            data["shapes"][i]["label"],
        )
        for i in (0, 1)
    )
    plan = build_object_relabel_plan(
        refs, str(tmp_path), "ignore", str(tmp_path), lambda _image: str(path)
    )
    items = [
        dict(
            image_path=r.image_id,
            json_path=str(path),
            shape_id=r.shape_id,
            before=r.display_summary,
            after="ignore",
            status="pending",
        )
        for r in refs
    ]
    context = store.history.begin("relabel", items, {"label": "person"})
    plan = replace(plan, history_context=context)
    engine = ObjectRelabelEngine(str(tmp_path / "transactions"))
    result = engine.commit(engine.stage(plan), str(tmp_path))
    store.history.finish(copy.deepcopy(result.history_record))
    return store, path, result, store.history.get(context["id"])


def test_forward_persists_exact_values_and_reconciles_once(tmp_path):
    """An on-disk journal can rebuild a missing query row without replaying writes."""
    store, path, result, record = forward(tmp_path)
    assert [i["before"] for i in record["items"]] == ["person", "head"]
    assert all(
        i["after"] == "ignore" and i["status"] == "succeeded"
        for i in record["items"]
    )
    assert result.manifest_path
    assert len(store.history.query()) == 1
    snapshot = path.read_bytes()
    store.history.finish(copy.deepcopy(result.history_record))
    assert path.read_bytes() == snapshot and len(store.history.query()) == 1
    store.close()
    reopened = ReviewStore(str(tmp_path / "history.sqlite"))
    assert len(reopened.history.query("head")) == 1
    assert reopened.history.reconcile() == []
    assert len(reopened.history.query()) == 1
    reopened.close()


def test_inverse_preserves_known_geometry_and_restores_distinct_labels(
    tmp_path,
):
    """Only historical labels are reversed after a verified geometry save."""
    store, path, _result, parent = forward(tmp_path)
    data = read_document(str(path))
    before = document_digest(data)
    data["shapes"][0]["points"] = [[3, 4], [30, 40]]
    data["shapes"][2]["description"] = "later work"
    path.write_text(json.dumps(data), encoding="utf-8")
    with store.connection:
        store.history.observe(str(path), before, data)
    plan = build_inverse_plan(
        store.history, parent, parent["items"], str(tmp_path), {}
    )
    engine = ObjectRelabelEngine(str(tmp_path / "transactions"))
    assert engine.preflight(plan).changeable == 2
    result = engine.commit(engine.stage(plan), str(tmp_path))
    assert result.counts["succeeded"] == 2
    store.history.finish(copy.deepcopy(result.history_record))
    after = read_document(str(path))
    assert [s["label"] for s in after["shapes"]] == ["person", "head", "other"]
    assert after["shapes"][0]["points"] == [[3, 4], [30, 40]]
    assert after["shapes"][2]["description"] == "later work"
    again = build_inverse_plan(
        store.history, parent, parent["items"], str(tmp_path), {}
    )
    assert (
        ObjectRelabelEngine(str(tmp_path / "transactions"))
        .preflight(again)
        .conflict
        == 2
    )
    assert len(store.history.query()) == 3
    store.close()


@pytest.mark.parametrize(
    "change", ["external", "roundtrip", "duplicate", "deleted"]
)
def test_inverse_rejects_unverified_or_changed_targets(tmp_path, change):
    """Equal current strings alone cannot authorize a historical inverse."""
    store, path, _result, parent = forward(tmp_path)
    data = read_document(str(path))
    before = document_digest(data)
    if change == "external":
        data["shapes"][0]["points"] = [[8, 8], [30, 30]]
    elif change == "roundtrip":
        data["shapes"][0]["label"] = "later"
        with store.connection:
            store.history.observe(str(path), before, data)
        before = document_digest(data)
        data["shapes"][0]["label"] = "ignore"
        with store.connection:
            store.history.observe(str(path), before, data)
    elif change == "duplicate":
        data["shapes"].append(copy.deepcopy(data["shapes"][0]))
    else:
        data["shapes"].pop(0)
    path.write_text(json.dumps(data), encoding="utf-8")
    plan = build_inverse_plan(
        store.history, parent, parent["items"], str(tmp_path), {}
    )
    engine = ObjectRelabelEngine(str(tmp_path / "transactions"))
    snapshot = path.read_bytes()
    summary = engine.preflight(plan)
    assert summary.conflict >= 1
    result = engine.commit(engine.stage(plan), str(tmp_path))
    if change != "roundtrip":
        assert path.read_bytes() == snapshot
    else:
        assert (
            result.counts["succeeded"] == 1 and result.counts["conflict"] == 1
        )
    store.close()


def test_inverse_rejects_write_after_preflight(tmp_path):
    """A file changed between inverse confirmation and staging is untouched."""
    store, path, _result, parent = forward(tmp_path)
    plan = build_inverse_plan(
        store.history, parent, parent["items"], str(tmp_path), {}
    )
    engine = ObjectRelabelEngine(str(tmp_path / "transactions"))
    engine.preflight(plan)
    data = read_document(str(path))
    data["new_field"] = "concurrent change"
    path.write_text(json.dumps(data), encoding="utf-8")
    snapshot = path.read_bytes()
    result = engine.commit(engine.stage(plan), str(tmp_path))
    assert result.counts["conflict"] == 2 and path.read_bytes() == snapshot
    store.close()


def test_review_state_history_and_reversal_are_atomic(tmp_path):
    """Review history shares a transaction and refuses later decisions."""
    store = ReviewStore(str(tmp_path / "history.sqlite"))
    ref = DatasetThumbnailRef(
        str(tmp_path / "image.png"),
        str(tmp_path / "image.json"),
        0,
        0,
        "id",
        "person",
        signature="v1",
    )
    record = store.set_status([ref], "confirmed")
    current = replace(ref, review_status="confirmed")
    result = store.revert(record["id"], record["items"], (current,))
    assert result["items"][0]["status"] == "succeeded"
    assert (
        store.connection.execute("SELECT state FROM marks").fetchone()[0]
        == "unreviewed"
    )
    assert len(store.history.query()) == 2
    again = store.revert(record["id"], record["items"], (current,))
    assert again["items"][0]["status"] == "conflict"
    store.close()


def test_pending_without_commit_evidence_is_never_success(tmp_path):
    """An interrupted request stays inspectable and cannot authorize recovery."""
    store = ReviewStore(str(tmp_path / "history.sqlite"))
    record = store.history.begin("relabel", [], {})
    assert store.history.reconcile() == []
    assert store.history.get(record["id"])["state"] == "unverified"
    store.close()


def test_projection_failure_is_reconciled_without_repeating_json_write(tmp_path, monkeypatch):
    """Final evidence survives a failed SQLite projection and recovers once."""
    store, path, result, record = forward(tmp_path)
    with store.connection:
        store.connection.execute("DELETE FROM thumbnail_history WHERE id=?", (record['id'],))
        store.connection.execute("DELETE FROM thumbnail_observations")
    put = store.history.put
    monkeypatch.setattr(store.history, 'put', lambda _record: (_ for _ in ()).throw(OSError('disk unavailable')))
    snapshot = path.read_bytes()
    with pytest.raises(OSError):
        store.history.finish(copy.deepcopy(result.history_record))
    monkeypatch.setattr(store.history, 'put', put)
    assert store.history.reconcile() == []
    recovered = store.history.get(record['id'])
    assert recovered['state'] == 'completed'
    assert path.read_bytes() == snapshot
    assert store.history.guard(record['id'], recovered['items'][0], read_document(str(path))) == ''
    store.close()


def test_review_history_failure_rolls_back_state(tmp_path, monkeypatch):
    """No review decision is saved if its history row cannot be committed."""
    store = ReviewStore(str(tmp_path / 'history.sqlite'))
    ref = DatasetThumbnailRef(str(tmp_path / 'a.png'), str(tmp_path / 'a.json'), 0, 0, 'id', 'person', signature='v1')
    monkeypatch.setattr(store.history, 'put', lambda _record: (_ for _ in ()).throw(OSError('write failed')))
    with pytest.raises(OSError):
        store.set_status([ref], 'confirmed')
    assert store.connection.execute('SELECT COUNT(*) FROM marks').fetchone()[0] == 0
    store.close()


def test_file_restore_journal_and_duplicate_consumption(tmp_path):
    """A file recovery has its own durable result and cannot run twice."""
    from anylabeling.views.labeling.widgets.label_batch import JsonTransactionEngine

    store, path, result, parent = forward(tmp_path)
    context = store.history.begin('restore', [dict(i, before=i['after'], after=i['before'], status='pending') for i in parent['items']], {}, parent['id'])
    context['manifest_path'] = result.manifest_path
    engine = JsonTransactionEngine(str(tmp_path / 'transactions'))
    restored = engine.restore(result.manifest_path, str(tmp_path), True, history_context=context)
    assert restored.counts['succeeded'] == 1
    store.history.finish(context)
    assert all(store.history.consumed(parent['id'], i) for i in parent['items'])
    snapshot = path.read_bytes()
    repeated = engine.restore(result.manifest_path, str(tmp_path), True)
    assert repeated.counts.get('succeeded', 0) == 0 and path.read_bytes() == snapshot
    assert len(store.history.query()) == 2
    store.close()


def test_legacy_import_and_dataset_isolation(tmp_path):
    """Existing manifests are searchable without fabricating inverse eligibility."""
    store, _path, _result, _parent = forward(tmp_path)
    other = ReviewStore(str(tmp_path / 'legacy.sqlite'))
    count = other.history.import_backups(str(tmp_path / 'transactions'), lambda path: path.replace('.json', '.png'))
    assert count == 0  # Declared dataset differs from the transaction directory.
    # Use the application's normal transaction root, which is the dataset root.
    source, data = annotation(tmp_path)
    ref = MarkedObjectRef(str(tmp_path), str(tmp_path / 'image.png'), data['shapes'][0]['xanylabeling_shape_id'])
    plan = build_object_relabel_plan([ref], str(tmp_path), 'new', str(tmp_path), lambda _: str(source))
    engine = ObjectRelabelEngine(str(tmp_path))
    engine.commit(engine.stage(plan), str(tmp_path))
    assert other.history.import_backups(str(tmp_path), lambda _: ref.image_id) == 1
    imported = other.history.query()[0]
    assert imported['legacy'] and imported['items'][0]['before'] is None
    assert other.history.import_backups(str(tmp_path), lambda _: ref.image_id) == 0
    assert len(store.history.query()) == 1
    store.close()
    other.close()
