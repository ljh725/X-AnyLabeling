"""Pure Python tests for marked-object field batch editing."""

import json
import os.path as osp

import pytest

from anylabeling.views.labeling.widgets.object_field_edit import (
    FIELD_CREATED,
    FIELD_UNCHANGED,
    FIELD_UPDATED,
    FieldAssignment,
    ObjectFieldEditPlanError,
    ObjectFieldEditEngine,
    ObjectFieldConflict,
    build_object_field_edit_plan,
    transform_objects_by_fields,
)
from anylabeling.views.labeling.widgets.object_relabel import (
    MarkedObjectRef,
    STATUS_CHANGEABLE,
    STATUS_CONFLICT,
    STATUS_DELETED,
    STATUS_FAILED,
    STATUS_SUCCEEDED,
    STATUS_UNCHANGED,
    ObjectIdentityConflict,
)


def _ref(project_id="proj", image_id="img.png", shape_id="sid-1"):
    """Build a marked object reference."""
    return MarkedObjectRef(project_id, image_id, shape_id)


def _shape(shape_id, **extra):
    """Build a minimal valid Shape dictionary."""
    shape = {
        "xanylabeling_shape_id": shape_id,
        "label": "person",
        "points": [[1, 2], [3, 4]],
        "shape_type": "rectangle",
    }
    shape.update(extra)
    return shape


def _write(path, shapes):
    """Write a small annotation file."""
    path.write_text(
        json.dumps({"version": "5.0.1", "shapes": shapes}, indent=2),
        encoding="utf-8",
    )
    return str(path)


def _resolver(root):
    """Resolve image IDs to JSON files below a root."""

    def resolve(image_id):
        return osp.join(
            str(root), osp.splitext(osp.basename(image_id))[0] + ".json"
        )

    return resolve


def _plan(tmp_path, refs, assignments):
    """Build a field plan for JSON files below ``tmp_path``."""
    return build_object_field_edit_plan(
        refs,
        "proj",
        assignments,
        str(tmp_path),
        _resolver(tmp_path),
    )


def test_assignment_registry_validates_types_and_protected_paths():
    """Supported values are accepted and unsafe paths are rejected."""
    assert FieldAssignment("difficult", False).field_kind == "difficult"
    assert FieldAssignment("group_id", None).field_kind == "group_id"
    assert FieldAssignment("flags.orphan_head", True).field_kind == "flags"
    assert FieldAssignment("attributes.score", 1.5).field_kind == "attributes"
    with pytest.raises(ObjectFieldEditPlanError):
        FieldAssignment("group_id", True)
    with pytest.raises(ObjectFieldEditPlanError):
        FieldAssignment("flags.a.b", True)
    with pytest.raises(ObjectFieldEditPlanError):
        FieldAssignment("points", "bad")
    with pytest.raises(ObjectFieldEditPlanError):
        FieldAssignment("label", "   ")


def test_plan_deduplicates_refs_and_is_immutable(tmp_path):
    """Plans freeze assignments, paths, and duplicate marked keys."""
    plan = _plan(
        tmp_path,
        [_ref(), _ref(), _ref(image_id="other.png", shape_id="sid-2")],
        [FieldAssignment("difficult", False)],
    )
    assert plan.total_objects == 2
    with pytest.raises(TypeError):
        plan.targets_by_annotation_path["new.json"] = ()
    with pytest.raises(AttributeError):
        plan.assignments = ()


def test_transform_missing_field_is_created_and_explicit_default_is_unchanged():
    """Missing and explicit false are not conflated."""
    data = {"shapes": [_shape("sid-1"), _shape("sid-2", difficult=False)]}
    assignment = FieldAssignment("difficult", False)
    first = transform_objects_by_fields(data, {"sid-1"}, [assignment])
    second = transform_objects_by_fields(data, {"sid-2"}, [assignment])
    assert first.changed
    assert first.statuses["sid-1"] == STATUS_CHANGEABLE
    assert first.mutations["sid-1"][0].status == FIELD_CREATED
    assert first.data["shapes"][0]["difficult"] is False
    assert not second.changed
    assert second.statuses["sid-2"] == STATUS_UNCHANGED
    assert second.mutations["sid-2"][0].status == FIELD_UNCHANGED


def test_transform_updates_only_selected_target_fields_and_preserves_input():
    """Multiple assignments change only the marked Shape and paths."""
    data = {
        "root_extension": {"keep": True},
        "shapes": [
            _shape("sid-1", flags={"keep": True}, unknown={"x": 1}),
            _shape("sid-2", difficult=True),
        ],
    }
    original = json.dumps(data, sort_keys=True)
    outcome = transform_objects_by_fields(
        data,
        {"sid-1"},
        [
            FieldAssignment("difficult", False),
            FieldAssignment("flags.orphan_head", True),
            FieldAssignment("description", "reviewed"),
        ],
    )
    assert outcome.changed
    target = outcome.data["shapes"][0]
    assert target["difficult"] is False
    assert target["flags"] == {"keep": True, "orphan_head": True}
    assert target["description"] == "reviewed"
    assert outcome.data["shapes"][1] == data["shapes"][1]
    assert outcome.data["root_extension"] == {"keep": True}
    assert json.dumps(data, sort_keys=True) == original


def test_transform_nested_parent_is_created_or_conflicts():
    """Missing nested parents are created; wrong parents abort safely."""
    outcome = transform_objects_by_fields(
        {"shapes": [_shape("sid-1")]},
        {"sid-1"},
        [FieldAssignment("attributes.reviewed", True)],
    )
    assert outcome.data["shapes"][0]["attributes"] == {"reviewed": True}
    with pytest.raises(ObjectFieldConflict):
        transform_objects_by_fields(
            {"shapes": [_shape("sid-1", flags="bad")]},
            {"sid-1"},
            [FieldAssignment("flags.reviewed", True)],
        )


def test_transform_rejects_identity_conflicts_and_reports_deleted():
    """Identity errors remain strict and absent IDs never fuzzy-match."""
    with pytest.raises(ObjectIdentityConflict):
        transform_objects_by_fields(
            {"shapes": [_shape("sid-1"), _shape("sid-1")]},
            {"sid-1"},
            [FieldAssignment("difficult", False)],
        )
    outcome = transform_objects_by_fields(
        {"shapes": [_shape("sid-11")]},
        {"sid-1"},
        [FieldAssignment("difficult", False)],
    )
    assert outcome.statuses == {"sid-1": STATUS_DELETED}


def test_transform_warns_about_legacy_difficult_without_migrating_it():
    """Top-level edits do not silently rewrite the legacy flags alias."""
    outcome = transform_objects_by_fields(
        {
            "shapes": [
                _shape("sid-1", flags={"difficult": True}),
            ]
        },
        {"sid-1"},
        [FieldAssignment("difficult", False)],
    )
    target = outcome.data["shapes"][0]
    assert target["difficult"] is False
    assert target["flags"]["difficult"] is True
    assert "legacy flags.difficult is present" in outcome.warnings["sid-1"]
    assert (
        "top-level difficult conflicts with flags.difficult"
        in outcome.warnings["sid-1"]
    )


def test_transform_warns_about_preexisting_difficult_mismatch_before_edit():
    """An edit cannot hide a legacy mismatch that existed on disk."""
    outcome = transform_objects_by_fields(
        {
            "shapes": [
                _shape("sid-1", difficult=True, flags={"difficult": False})
            ]
        },
        {"sid-1"},
        [FieldAssignment("difficult", False)],
    )
    assert (
        "top-level difficult conflicts with flags.difficult"
        in outcome.warnings["sid-1"]
    )


def test_engine_preflight_counts_field_states_and_alias_warnings(tmp_path):
    """Preflight separates created/updated/unchanged field counts."""
    source = tmp_path / "img.json"
    _write(
        source,
        [
            _shape("sid-1", flags={"difficult": True}),
            _shape("sid-2", difficult=True),
            _shape("sid-3", difficult=False),
        ],
    )
    plan = _plan(
        tmp_path,
        [
            _ref(shape_id="sid-1"),
            _ref(shape_id="sid-2"),
            _ref(shape_id="sid-3"),
        ],
        [FieldAssignment("difficult", False)],
    )
    summary = ObjectFieldEditEngine(str(tmp_path / "transactions")).preflight(
        plan
    )
    assert summary.created == 1
    assert summary.updated == 1
    assert summary.unchanged == 1
    assert summary.conflict == 0
    assert "legacy flags.difficult is present" in summary.warnings


def test_engine_preflight_mixes_multiple_field_states_and_skips_conflict_file(
    tmp_path,
):
    """Field counters remain precise while one conflicting file is skipped."""
    good = tmp_path / "img.json"
    bad = tmp_path / "bad.json"
    _write(good, [_shape("sid-1"), _shape("sid-2", score=1.0)])
    _write(bad, [_shape("sid-3", flags="wrong")])
    plan = build_object_field_edit_plan(
        [
            _ref(shape_id="sid-1"),
            _ref(shape_id="sid-2"),
            _ref(image_id="bad.png", shape_id="sid-3"),
        ],
        "proj",
        [
            FieldAssignment("difficult", False),
            FieldAssignment("score", 1.0),
            FieldAssignment("flags.reviewed", True),
        ],
        str(tmp_path),
        _resolver(tmp_path),
    )
    summary = ObjectFieldEditEngine(str(tmp_path / "transactions")).preflight(
        plan
    )
    assert summary.created == 5
    assert summary.updated == 0
    assert summary.unchanged == 1
    assert summary.conflict == 1
    assert summary.file_details[1].file_status == STATUS_CONFLICT


def test_engine_preflight_reports_nested_parent_type_as_conflict(tmp_path):
    """A wrong nested parent is a conflict, not a read failure."""
    source = tmp_path / "img.json"
    _write(source, [_shape("sid-1", flags="wrong")])
    plan = _plan(
        tmp_path,
        [_ref()],
        [FieldAssignment("flags.reviewed", True)],
    )
    summary = ObjectFieldEditEngine(str(tmp_path / "transactions")).preflight(
        plan
    )
    assert summary.conflict == 1
    assert summary.failed == 0
    assert summary.file_details[0].file_status == "conflict"


def test_engine_stage_commit_and_manifest(tmp_path):
    """A changed field commits atomically and records object metadata."""
    source = tmp_path / "img.json"
    _write(source, [_shape("sid-1")])
    plan = _plan(
        tmp_path,
        [_ref()],
        [
            FieldAssignment("difficult", False),
            FieldAssignment("flags.reviewed", True),
        ],
    )
    engine = ObjectFieldEditEngine(str(tmp_path / "transactions"))
    staged = engine.stage(plan)
    assert staged.operation.files[0].status == "staged"
    result = engine.commit(staged, str(tmp_path))
    assert result.counts[STATUS_SUCCEEDED] == 1
    assert result.field_counts[FIELD_CREATED] == 2
    assert result.manifest_path
    data = json.loads(source.read_text(encoding="utf-8"))
    assert data["shapes"][0]["difficult"] is False
    assert data["shapes"][0]["flags"]["reviewed"] is True


def test_engine_conflict_file_is_not_staged(tmp_path):
    """A wrong nested parent leaves the source file untouched."""
    source = tmp_path / "img.json"
    _write(source, [_shape("sid-1", flags="wrong")])
    before = source.read_text(encoding="utf-8")
    plan = _plan(
        tmp_path,
        [_ref()],
        [FieldAssignment("flags.reviewed", True)],
    )
    engine = ObjectFieldEditEngine(str(tmp_path / "transactions"))
    staged = engine.stage(plan)
    result = engine.commit(staged, str(tmp_path))
    assert result.counts[STATUS_CONFLICT] == 1
    assert source.read_text(encoding="utf-8") == before


def test_engine_cancelled_result_keeps_all_objects(tmp_path):
    """Cancellation reports all snapshot objects as cancelled."""
    source = tmp_path / "img.json"
    _write(source, [_shape("sid-1")])
    plan = _plan(
        tmp_path,
        [_ref()],
        [FieldAssignment("difficult", False)],
    )
    engine = ObjectFieldEditEngine(str(tmp_path / "transactions"))
    staged = engine.stage(plan, cancel_check=lambda: True)
    result = engine.cancelled_result(staged)
    assert result.cancelled
    assert result.counts["cancelled"] == 1
    assert not source.read_text(encoding="utf-8").__contains__('"difficult"')


def test_engine_detects_source_change_and_restores_from_manifest(tmp_path):
    """Fingerprint protection and generic manifest recovery stay intact."""
    source = tmp_path / "img.json"
    _write(source, [_shape("sid-1")])
    plan = _plan(tmp_path, [_ref()], [FieldAssignment("difficult", False)])
    engine = ObjectFieldEditEngine(str(tmp_path / "transactions"))
    staged = engine.stage(plan)
    source.write_text(
        json.dumps({"shapes": [_shape("sid-1", label="concurrent")]}),
        encoding="utf-8",
    )
    failed = engine.commit(staged, str(tmp_path))
    assert failed.counts[STATUS_FAILED] == 1
    assert (
        json.loads(source.read_text(encoding="utf-8"))["shapes"][0]["label"]
        == "concurrent"
    )

    source.write_text(
        json.dumps({"shapes": [_shape("sid-1")]}), encoding="utf-8"
    )
    staged = engine.stage(plan)
    committed = engine.commit(staged, str(tmp_path))
    assert committed.counts[STATUS_SUCCEEDED] == 1
    restored = engine.restore(committed.manifest_path)
    assert restored.counts["succeeded"] == 1
    assert (
        "difficult"
        not in json.loads(source.read_text(encoding="utf-8"))["shapes"][0]
    )


def test_engine_manifest_contains_field_plan_and_object_statuses(tmp_path):
    """Field assignments and per-object status metadata are persisted."""
    source = tmp_path / "img.json"
    _write(source, [_shape("sid-1")])
    plan = _plan(
        tmp_path,
        [_ref()],
        [FieldAssignment("difficult", False), FieldAssignment("score", 0.5)],
    )
    engine = ObjectFieldEditEngine(str(tmp_path / "transactions"))
    result = engine.commit(engine.stage(plan), str(tmp_path))
    manifest = json.loads(
        (
            tmp_path / "transactions" / result.transaction_id / "manifest.json"
        ).read_text(encoding="utf-8")
    )
    assert manifest["domain"]["kind"] == "object-field-edit"
    assert {item["path"] for item in manifest["domain"]["assignments"]} == {
        "difficult",
        "score",
    }
    entry = manifest["entries"][0]["domain_metadata"]
    assert entry["object_statuses"]["sid-1"] == STATUS_CHANGEABLE
