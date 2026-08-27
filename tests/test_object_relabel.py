"""Pure object-relabel planning, preflight, transform, and store tests."""

import json
import os.path as osp

import pytest

from anylabeling.views.labeling.widgets.label_batch import (
    BatchMigrationEngine,
)
from anylabeling.views.labeling.widgets.object_relabel import (
    KEEP_ON_RESULT,
    MarkedObjectRef,
    MarkedObjectStore,
    ObjectIdentityConflict,
    ObjectRelabelEngine,
    ObjectRelabelPlanError,
    REMOVE_ON_RESULT,
    STATUS_CANCELLED,
    STATUS_CHANGEABLE,
    STATUS_CONFLICT,
    STATUS_DELETED,
    STATUS_FAILED,
    STATUS_SUCCEEDED,
    STATUS_UNCHANGED,
    build_object_relabel_plan,
    classify_file_objects,
    transform_objects_by_id,
)


def _ref(
    project_id="proj",
    image_id="img.png",
    shape_id="sid-1",
    summary="person",
):
    """Build a compact marked reference."""
    return MarkedObjectRef(
        project_id=project_id,
        image_id=image_id,
        shape_id=shape_id,
        display_summary=summary,
    )


def _write_annotation(path, shapes, **extra):
    """Write one annotation JSON file."""
    payload = {"version": "5.0.1", "shapes": shapes}
    payload.update(extra)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return str(path)


def _shape(sid, label="person", points=None, **extra):
    """Build one shape dict with a persistent identity."""
    body = {
        "xanylabeling_shape_id": sid,
        "label": label,
        "points": points if points is not None else [[1, 2], [3, 4]],
        "group_id": None,
        "description": "",
        "shape_type": "rectangle",
        "flags": {},
    }
    body.update(extra)
    return body


def _resolver(root):
    """Resolver mapping image ids next to json files under ``root``."""

    def resolve(image_id):
        path = osp.join(str(root), osp.basename(image_id))
        return osp.splitext(path)[0] + ".json"

    return resolve


# ---------------------------------------------------------------- plan


def test_plan_rejects_empty_snapshot_and_blank_label(tmp_path):
    """No snapshot or empty target label never becomes a plan."""
    resolver = _resolver(tmp_path)
    with pytest.raises(ObjectRelabelPlanError):
        build_object_relabel_plan((), "proj", "new", str(tmp_path), resolver)
    with pytest.raises(ObjectRelabelPlanError):
        build_object_relabel_plan(
            [_ref()], "proj", "   ", str(tmp_path), resolver
        )


def test_plan_rejects_cross_project_and_escape_and_unresolvable(tmp_path):
    """Invalid entries are reported together before any file is touched."""
    outside = tmp_path.parent / "outside.json"
    outside.write_text("{}", encoding="utf-8")

    def resolve(image_id):
        if image_id == "escape.png":
            return str(outside)
        if image_id == "missing.png":
            return None
        path = osp.join(str(tmp_path), osp.basename(image_id))
        return osp.splitext(path)[0] + ".json"

    with pytest.raises(ObjectRelabelPlanError) as excinfo:
        build_object_relabel_plan(
            [
                _ref(image_id="ok.png", shape_id="sid-a"),
                _ref(project_id="other", image_id="ok.png", shape_id="sid-b"),
                _ref(image_id="escape.png", shape_id="sid-c"),
                _ref(image_id="missing.png", shape_id="sid-d"),
            ],
            "proj",
            "new",
            str(tmp_path),
            resolve,
        )
    message = str(excinfo.value)
    assert "another project" in message
    assert "escapes" in message
    assert "cannot resolve" in message


def test_plan_groups_split_directory_dataset_and_dedupes(tmp_path):
    """output_dir-style layouts group by json path; duplicate keys merge."""
    json_dir = tmp_path / "labels"
    json_dir.mkdir()

    def resolver(image_id):
        return osp.join(
            str(json_dir),
            osp.splitext(osp.basename(image_id))[0] + ".json",
        )

    refs = [
        _ref(image_id="a.png", shape_id="sid-1"),
        _ref(image_id="a.png", shape_id="sid-1", summary="dup"),
        _ref(image_id="b.png", shape_id="sid-2"),
    ]
    plan = build_object_relabel_plan(
        refs, "proj", "new", str(json_dir), resolver
    )
    assert plan.total_objects == 2
    assert plan.file_count == 2
    grouped = plan.targets_by_annotation_path
    assert [
        ref.shape_id
        for ref in grouped[osp.join(str(json_dir), "a.json")]
    ] == ["sid-1"]


def test_plan_is_immutable_and_stores_no_runtime_shapes(tmp_path):
    """Plans expose frozen mappings and only string identities."""
    json_dir = tmp_path
    resolver = _resolver(json_dir)
    plan = build_object_relabel_plan(
        [_ref()], "proj", "new", str(json_dir), resolver
    )
    with pytest.raises(TypeError):
        plan.targets_by_annotation_path["injected.json"] = ()
    with pytest.raises(AttributeError):
        plan.target_label = "other"
    ref = next(iter(plan.targets_by_annotation_path.values()))[0]
    with pytest.raises(AttributeError):
        ref.shape_id = "mutated"
    for refs in plan.targets_by_annotation_path.values():
        for marked in refs:
            assert isinstance(marked, MarkedObjectRef)
            assert set(vars(marked)) == {
                "project_id",
                "image_id",
                "shape_id",
                "display_summary",
            }


# ---------------------------------------------------------- classification


def test_classification_survives_reorder_and_field_changes():
    """Identity matching ignores order, label, geometry, and group edits."""
    data = {
        "shapes": [
            _shape("other", label="person"),
            _shape(
                "sid-1",
                label="renamed",
                points=[[9, 9]],
                group_id=7,
                attributes={"pose": "stand"},
            ),
        ]
    }
    _file, statuses = classify_file_objects(data, {"sid-1"}, "target")
    assert statuses == {"sid-1": STATUS_CHANGEABLE}


def test_classification_reports_deleted_without_fuzzy_matching():
    """Absent ids are deleted; similar ids never match."""
    data = {"shapes": [_shape("sid-11"), _shape("sid-111")]}
    _file, statuses = classify_file_objects(data, {"sid-1"}, "target")
    assert statuses == {"sid-1": STATUS_DELETED}


def test_classification_marks_duplicates_as_whole_file_conflict():
    """Duplicate target ids poison the file, not just one object."""
    data = {
        "shapes": [
            _shape("sid-1", label="a"),
            _shape("sid-1", label="b"),
            _shape("sid-2"),
        ]
    }
    file_status, statuses = classify_file_objects(
        data, {"sid-1", "sid-2"}, "target"
    )
    assert file_status == STATUS_CONFLICT
    assert statuses["sid-1"] == STATUS_CONFLICT
    assert statuses["sid-2"] == STATUS_CHANGEABLE


def test_classification_treats_illegal_ids_as_conflict():
    """Illegally-typed target ids conflict and keep the file unchanged."""
    data = {
        "shapes": [
            {"label": "person", "xanylabeling_shape_id": 123},
            {"label": "person"},
            _shape(""),
        ]
    }
    file_status, statuses = classify_file_objects(
        data, {"123", ""}, "target"
    )
    assert file_status == STATUS_CONFLICT
    assert statuses == {"123": STATUS_CONFLICT, "": STATUS_CONFLICT}


def test_classification_missing_field_is_file_conflict():
    """A missing persistent id poisons the file instead of guessing."""
    data = {"shapes": [{"label": "person"}]}
    file_status, statuses = classify_file_objects(data, {"123"}, "target")
    assert file_status == STATUS_CONFLICT
    assert statuses == {"123": STATUS_CONFLICT}


def test_classification_reports_already_target_label():
    """Objects already matching the target count as unchanged."""
    data = {"shapes": [_shape("sid-1", label="target")]}
    _file, statuses = classify_file_objects(data, {"sid-1"}, "target")
    assert statuses == {"sid-1": STATUS_UNCHANGED}


# ---------------------------------------------------------------- transform


def test_transform_only_touches_target_label_and_preserves_everything():
    """One field changes; every other byte of every shape survives."""
    data = {
        "version": "x",
        "custom": {"keep": [1, 2]},
        "shapes": [
            _shape(
                "sid-1",
                label="person",
                attributes={"age": 3},
                unknown_extension={"deep": {"value": 1}},
            ),
            _shape("sid-2", label="person"),
        ],
    }
    outcome = transform_objects_by_id(data, {"sid-1"}, "face")
    assert outcome.changed
    assert outcome.statuses == {"sid-1": "changed"}
    shapes = outcome.data["shapes"]
    assert shapes[0]["label"] == "face"
    assert shapes[0]["points"] == [[1, 2], [3, 4]]
    assert shapes[0]["group_id"] is None
    assert shapes[0]["flags"] == {}
    assert shapes[0]["attributes"] == {"age": 3}
    assert shapes[0]["unknown_extension"] == {"deep": {"value": 1}}
    assert shapes[0]["xanylabeling_shape_id"] == "sid-1"
    assert shapes[1] == _shape("sid-2", label="person")
    assert outcome.data["custom"] == {"keep": [1, 2]}
    assert [s["xanylabeling_shape_id"] for s in shapes] == ["sid-1", "sid-2"]


def test_transform_keeps_array_order_and_input_untouched():
    """Shape order is preserved and the input mapping is never mutated."""
    data = {
        "shapes": [_shape("sid-2"), _shape("sid-1"), _shape("sid-3")]
    }
    original = json.dumps(data, sort_keys=True)
    outcome = transform_objects_by_id(data, {"sid-1"}, "face")
    assert [
        s["xanylabeling_shape_id"] for s in outcome.data["shapes"]
    ] == ["sid-2", "sid-1", "sid-3"]
    assert json.dumps(data, sort_keys=True) == original
    assert data["shapes"][1]["label"] == "person"


def test_transform_reports_noop_for_already_target_object():
    """Already-target objects report unchanged without staging a write."""
    data = {"shapes": [_shape("sid-1", label="face")]}
    outcome = transform_objects_by_id(data, {"sid-1"}, "face")
    assert not outcome.changed
    assert outcome.statuses == {"sid-1": STATUS_UNCHANGED}


def test_transform_rejects_duplicate_target_ids():
    """Duplicate identities abort the transform for the whole file."""
    data = {"shapes": [_shape("sid-1"), _shape("sid-1")]}
    with pytest.raises(ObjectIdentityConflict):
        transform_objects_by_id(data, {"sid-1"}, "face")


def test_transform_leaves_same_label_unmarked_siblings_alone():
    """Only snapshot objects change even when labels are identical."""
    data = {"shapes": [_shape("sid-1"), _shape("sid-2"), _shape("sid-3")]}
    outcome = transform_objects_by_id(data, {"sid-2"}, "face")
    assert outcome.data["shapes"][0]["label"] == "person"
    assert outcome.data["shapes"][1]["label"] == "face"
    assert outcome.data["shapes"][2]["label"] == "person"


# -------------------------------------------------------------- transactions


def _engine(tmp_path):
    """Build an object engine over a temp transaction directory."""
    return ObjectRelabelEngine(str(tmp_path / "transactions"))


def _plan_for(tmp_path, refs, label="face", root=None):
    """Build a plan resolving images next to jsons under ``root``."""
    root = str(root if root is not None else tmp_path)
    return build_object_relabel_plan(refs, "proj", label, root, _resolver(root))


def test_object_commit_updates_only_target_objects(tmp_path):
    """Full flow succeeds and only the target label field changes."""
    source = tmp_path / "img.json"
    _write_annotation(
        source,
        [
            _shape("sid-1", label="person", description="keep me"),
            _shape("sid-2", label="person"),
        ],
        imagePath="img.png",
    )
    plan = _plan_for(tmp_path, [_ref(image_id="img.png", shape_id="sid-1")])
    engine = _engine(tmp_path)
    staged = engine.stage(plan)
    assert staged.operation.files[0].status == "staged"
    result = engine.commit(staged, str(tmp_path))
    assert result.counts[STATUS_SUCCEEDED] == 1
    data = json.loads(source.read_text(encoding="utf-8"))
    assert data["shapes"][0]["label"] == "face"
    assert data["shapes"][0]["description"] == "keep me"
    assert data["shapes"][1]["label"] == "person"
    assert data["imagePath"] == "img.png"


def test_object_stage_skips_unchanged_and_conflict_files(tmp_path):
    """Unchanged files never stage; conflict files stay untouched."""
    unchanged = tmp_path / "same.json"
    _write_annotation(unchanged, [_shape("sid-1", label="face")])
    conflict = tmp_path / "dup.json"
    _write_annotation(conflict, [_shape("sid-1"), _shape("sid-1")])
    before = conflict.read_text(encoding="utf-8")
    plan = _plan_for(
        tmp_path,
        [
            _ref(image_id="same.json", shape_id="sid-1"),
            _ref(image_id="dup.json", shape_id="sid-1"),
        ],
    )
    engine = _engine(tmp_path)
    staged = engine.stage(plan)
    statuses = staged.file_object_statuses
    assert statuses[str(unchanged)]["sid-1"] == STATUS_UNCHANGED
    assert statuses[str(conflict)]["sid-1"] == STATUS_CONFLICT
    assert staged.operation.counts["skipped"] == 2
    assert conflict.read_text(encoding="utf-8") == before


def test_object_stage_marks_unreadable_file_objects_failed(tmp_path):
    """Files that cannot be read turn their objects into failures."""
    broken = tmp_path / "broken.json"
    broken.write_text("{not-json", encoding="utf-8")
    plan = _plan_for(tmp_path, [_ref(image_id="broken.json")])
    engine = _engine(tmp_path)
    staged = engine.stage(plan)
    assert staged.operation.counts["failed"] == 1
    assert staged.file_object_statuses[str(broken)]["sid-1"] == STATUS_FAILED


def test_object_stage_preserves_illegal_identity_conflict_from_preflight(
    tmp_path,
):
    """An illegal id remains conflict through stage and commit."""
    source = tmp_path / "illegal.json"
    _write_annotation(source, [_shape(7)])
    plan = _plan_for(
        tmp_path, [_ref(image_id="illegal.json", shape_id="7")]
    )
    engine = _engine(tmp_path)
    assert engine.preflight(plan).conflict == 1
    staged = engine.stage(plan)
    assert (
        staged.file_object_statuses[str(source)]["7"] == STATUS_CONFLICT
    )
    result = engine.commit(staged, str(tmp_path))
    assert result.counts[STATUS_CONFLICT] == 1
    assert result.counts[STATUS_DELETED] == 0


def test_object_cancel_during_stage_keeps_marks_and_files(tmp_path):
    """Cancelling staging writes nothing and reports all objects cancelled."""
    source = tmp_path / "img.json"
    _write_annotation(source, [_shape("sid-1")])
    before = source.read_text(encoding="utf-8")
    plan = _plan_for(tmp_path, [_ref(image_id="img.json")])
    engine = _engine(tmp_path)
    staged = engine.stage(plan, cancel_check=lambda: True)
    result = engine.cancelled_result(staged)
    assert result.cancelled
    assert result.counts[STATUS_CANCELLED] == 1
    assert source.read_text(encoding="utf-8") == before


def test_object_commit_detects_external_change_as_failure(tmp_path):
    """Fingerprint changes turn committed changeable objects into failures."""
    source = tmp_path / "img.json"
    _write_annotation(source, [_shape("sid-1")])
    plan = _plan_for(tmp_path, [_ref(image_id="img.json")])
    engine = _engine(tmp_path)
    staged = engine.stage(plan)
    _write_annotation(source, [_shape("sid-1", label="edited")])
    result = engine.commit(staged, str(tmp_path))
    assert result.counts[STATUS_FAILED] == 1
    assert (
        json.loads(source.read_text(encoding="utf-8"))["shapes"][0]["label"]
        == "edited"
    )


def test_object_partial_commit_reports_per_object_statuses(tmp_path):
    """One replaced file succeeds while a denied replacement fails alone."""
    good = tmp_path / "good.json"
    bad = tmp_path / "bad.json"
    _write_annotation(good, [_shape("sid-1")])
    _write_annotation(bad, [_shape("sid-2")])
    plan = _plan_for(
        tmp_path,
        [
            _ref(image_id="good.json", shape_id="sid-1"),
            _ref(image_id="bad.json", shape_id="sid-2"),
        ],
    )
    engine = _engine(tmp_path)
    staged = engine.stage(plan)
    import anylabeling.views.labeling.widgets.label_batch as lb

    original_replace = lb.os.replace

    def deny(staged_path, target_path):
        if osp.abspath(target_path) == osp.abspath(str(bad)):
            raise PermissionError("denied")
        return original_replace(staged_path, target_path)

    lb.os.replace = deny
    try:
        result = engine.commit(staged, str(tmp_path))
    finally:
        lb.os.replace = original_replace
    assert result.counts[STATUS_SUCCEEDED] == 1
    assert result.counts[STATUS_FAILED] == 1
    assert (
        json.loads(good.read_text(encoding="utf-8"))["shapes"][0]["label"]
        == "face"
    )
    assert (
        json.loads(bad.read_text(encoding="utf-8"))["shapes"][0]["label"]
        == "person"
    )


def test_object_manifest_roundtrips_domain_metadata_and_restores(tmp_path):
    """Manifest keeps the object plan and per-object statuses; restore works."""
    source = tmp_path / "img.json"
    _write_annotation(source, [_shape("sid-1")])
    plan = _plan_for(tmp_path, [_ref(image_id="img.json")])
    engine = _engine(tmp_path)
    staged = engine.stage(plan)
    result = engine.commit(staged, str(tmp_path))
    payload = json.loads(
        open(result.manifest_path, "r", encoding="utf-8").read()
    )
    assert payload["schema_version"] == 2
    assert payload["domain"]["kind"] == "object-relabel"
    assert payload["domain"]["target_label"] == "face"
    assert payload["domain"]["paths"][osp.abspath(str(source))] == ["sid-1"]
    entry = payload["entries"][0]
    assert entry["domain_metadata"]["object_statuses"] == {
        "sid-1": STATUS_CHANGEABLE
    }
    restored = engine._engine.restore(result.manifest_path)
    assert restored.counts["succeeded"] == 1
    assert (
        json.loads(source.read_text(encoding="utf-8"))["shapes"][0]["label"]
        == "person"
    )


def test_restore_still_supports_legacy_v1_manifests(tmp_path):
    """Old schema-1 manifests written by the label flow still restore."""
    source = tmp_path / "img.json"
    _write_annotation(source, [_shape("sid-1", label="face")])
    backup = tmp_path / "backup.json"
    backup.write_text(
        json.dumps({"shapes": [_shape("sid-1", label="person")]}),
        encoding="utf-8",
    )
    manifest_dir = tmp_path / "transactions" / "legacy"
    manifest_dir.mkdir(parents=True)
    manifest = manifest_dir / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "transaction_id": "legacy-1",
                "entries": [
                    {
                        "source_path": str(source),
                        "backup_path": str(backup),
                        "status": "succeeded",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    engine = BatchMigrationEngine(str(tmp_path / "transactions"))
    result = engine.restore(str(manifest))
    assert result.counts["succeeded"] == 1
    assert (
        json.loads(source.read_text(encoding="utf-8"))["shapes"][0]["label"]
        == "person"
    )


def test_object_preflight_summarizes_all_outcome_kinds(tmp_path):
    """Preflight counts changeable/unchanged/deleted/conflict/failed."""
    ok = tmp_path / "ok.json"
    _write_annotation(
        ok,
        [_shape("sid-1"), _shape("sid-2", label="face"), _shape("x")],
    )
    deleted = tmp_path / "gone.json"
    _write_annotation(deleted, [_shape("other")])
    conflict = tmp_path / "dup.json"
    _write_annotation(conflict, [_shape("sid-3"), _shape("sid-3")])
    broken = tmp_path / "broken.json"
    broken.write_text("{", encoding="utf-8")
    plan = _plan_for(
        tmp_path,
        [
            _ref(image_id="ok.json", shape_id="sid-1"),
            _ref(image_id="ok.json", shape_id="sid-2"),
            _ref(image_id="gone.json", shape_id="sid-9"),
            _ref(image_id="dup.json", shape_id="sid-3"),
            _ref(image_id="broken.json", shape_id="sid-4"),
        ],
    )
    engine = _engine(tmp_path)
    summary = engine.preflight(plan)
    assert summary.snapshot_objects == 5
    assert summary.candidate_files == 4
    assert summary.changeable == 1
    assert summary.unchanged == 1
    assert summary.deleted == 1
    assert summary.conflict == 1
    assert summary.failed == 1
    assert not summary.cancelled


def test_object_preflight_is_cancellable(tmp_path):
    """A cancel request stops preflight early."""
    source = tmp_path / "img.json"
    _write_annotation(source, [_shape("sid-1")])
    plan = _plan_for(tmp_path, [_ref(image_id="img.json")])
    engine = _engine(tmp_path)
    summary = engine.preflight(plan, cancel_check=lambda: True)
    assert summary.cancelled
    assert summary.candidate_files == 0


def test_preflight_counts_whole_conflict_file_as_conflict(tmp_path):
    """Mixed conflict files never promise submittable objects."""
    mixed = tmp_path / "mixed.json"
    _write_annotation(
        mixed, [_shape("sid-1"), _shape("sid-1"), _shape("sid-2")]
    )
    plan = _plan_for(
        tmp_path,
        [
            _ref(image_id="mixed.json", shape_id="sid-1"),
            _ref(image_id="mixed.json", shape_id="sid-2"),
        ],
    )
    engine = _engine(tmp_path)
    summary = engine.preflight(plan)
    assert summary.conflict == 2
    assert summary.changeable == 0


def test_failed_file_turns_unchanged_objects_into_failures(tmp_path):
    """Unchanged objects in a failed commit keep their marks for retry."""
    source = tmp_path / "img.json"
    _write_annotation(
        source,
        [_shape("sid-1", label="person"), _shape("sid-2", label="face")],
    )
    plan = _plan_for(
        tmp_path,
        [
            _ref(image_id="img.json", shape_id="sid-1"),
            _ref(image_id="img.json", shape_id="sid-2"),
        ],
    )
    engine = _engine(tmp_path)
    staged = engine.stage(plan)
    _write_annotation(
        source,
        [_shape("sid-1", label="person"), _shape("sid-2", label="edited")],
    )
    result = engine.commit(staged, str(tmp_path))
    counts = result.counts
    assert counts[STATUS_FAILED] == 2
    assert counts[STATUS_SUCCEEDED] == 0

    unchanged_only = tmp_path / "same.json"
    _write_annotation(unchanged_only, [_shape("sid-3", label="face")])
    plan2 = _plan_for(tmp_path, [_ref(image_id="same.json", shape_id="sid-3")])
    staged2 = engine.stage(plan2)
    result2 = engine.commit(staged2, str(tmp_path))
    assert result2.counts[STATUS_UNCHANGED] == 1


# -------------------------------------------------------------------- store


def test_store_toggle_counts_and_cross_image_query():
    """Toggling, counting, and per-image queries stay consistent."""
    store = MarkedObjectStore()
    a1 = _ref(image_id="a.png", shape_id="s1")
    a2 = _ref(image_id="a.png", shape_id="s2")
    b1 = _ref(image_id="b.png", shape_id="s1")
    assert store.toggle(a1)
    assert store.toggle(a2)
    assert store.toggle(b1)
    assert not store.toggle(a1)
    assert store.counts() == {"objects": 2, "files": 2}
    assert [r.shape_id for r in store.refs_for_image("proj", "a.png")] == [
        "s2"
    ]
    assert store.contains(b1.object_key)
    assert not store.contains(a1.object_key)


def test_store_snapshot_is_frozen_against_later_changes():
    """Store mutation after snapshot never alters the frozen batch."""
    store = MarkedObjectStore()
    store.toggle(_ref(image_id="a.png", shape_id="s1"))
    snapshot = store.snapshot()
    store.toggle(_ref(image_id="b.png", shape_id="s9"))
    store.clear()
    assert [ref.shape_id for ref in snapshot] == ["s1"]


def test_store_project_scoped_snapshot_and_counts():
    """Project-scoped views hide foreign-project marks."""
    store = MarkedObjectStore()
    store.toggle(_ref(project_id="proj", image_id="a.png", shape_id="s1"))
    store.toggle(_ref(project_id="other", image_id="b.png", shape_id="s2"))
    assert store.counts() == {"objects": 2, "files": 2}
    assert store.counts_for_project("proj") == {
        "objects": 1,
        "files": 1,
    }
    scoped = store.snapshot_for_project("proj")
    assert [ref.shape_id for ref in scoped] == ["s1"]
    assert [ref.shape_id for ref in store.snapshot_for_project("none")] == []


def test_store_apply_result_full_success_and_full_cancel():
    """Success removes marks; cancelled keeps everything."""
    store = MarkedObjectStore()
    key = _ref().object_key
    store.toggle(_ref())
    result = _result_for(key, STATUS_SUCCEEDED)
    report = store.apply_relabel_result(result)
    assert report.removed_keys == (key,)
    assert store.counts() == {"objects": 0, "files": 0}

    store.toggle(_ref())
    report = store.apply_relabel_result(_result_for(key, STATUS_CANCELLED))
    assert report.kept_keys == (key,)
    assert store.counts()["objects"] == 1


def test_store_partial_failure_keeps_failed_marks_only():
    """Same-file partial failure keeps failed marks and clears the rest."""
    store = MarkedObjectStore()
    ok = _ref(image_id="a.png", shape_id="ok").object_key
    bad = _ref(image_id="a.png", shape_id="bad").object_key
    gone = _ref(image_id="a.png", shape_id="gone").object_key
    for key in (ok, bad, gone):
        store.toggle(_ref(image_id="a.png", shape_id=key[2]))
    result = _result_for_pairs(
        (ok, STATUS_SUCCEEDED),
        (bad, STATUS_FAILED),
        (gone, STATUS_DELETED),
    )
    report = store.apply_relabel_result(result)
    assert report.removed_keys == (ok, gone)
    assert report.kept_keys == (bad,)
    assert store.contains(bad)


def test_store_apply_never_clears_new_marks_outside_batch():
    """Marks added after the snapshot survive result synchronization."""
    store = MarkedObjectStore()
    store.toggle(_ref(image_id="a.png", shape_id="s1"))
    store.toggle(_ref(image_id="b.png", shape_id="new"))
    report = store.apply_relabel_result(
        _result_for(
            _ref(image_id="a.png", shape_id="s1").object_key,
            STATUS_SUCCEEDED,
        )
    )
    assert report.objects_before == 2
    assert report.objects_after == 1
    assert store.contains(_ref(image_id="b.png", shape_id="new").object_key)


def test_status_partition_covers_every_outcome():
    """Remove/keep partitions are disjoint and cover all final statuses."""
    assert not REMOVE_ON_RESULT & KEEP_ON_RESULT
    assert REMOVE_ON_RESULT | KEEP_ON_RESULT == {
        STATUS_SUCCEEDED,
        STATUS_UNCHANGED,
        STATUS_DELETED,
        STATUS_CONFLICT,
        STATUS_FAILED,
        STATUS_CANCELLED,
    }


def _result_for(key, status, other_key=None, other_status=None):
    """Build a tiny result carrying one or two object outcomes."""
    from anylabeling.views.labeling.widgets.object_relabel import (
        ObjectMutationResult,
        ObjectRelabelResult,
    )

    objects = [ObjectMutationResult(key=key, status=status)]
    if other_key is not None:
        objects.append(
            ObjectMutationResult(key=other_key, status=other_status)
        )
    return ObjectRelabelResult(
        transaction_id="t",
        phase="committed",
        cancelled=False,
        objects=tuple(objects),
    )


def _result_for_pairs(*pairs):
    """Build a result from ``(key, status)`` pairs."""
    from anylabeling.views.labeling.widgets.object_relabel import (
        ObjectMutationResult,
        ObjectRelabelResult,
    )

    return ObjectRelabelResult(
        transaction_id="t",
        phase="committed",
        cancelled=False,
        objects=tuple(
            ObjectMutationResult(key=key, status=status)
            for key, status in pairs
        ),
    )
