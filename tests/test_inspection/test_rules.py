from anylabeling.services.inspection.models import (
    CoverageState,
    FileSnapshot,
    InspectionProfile,
    RuleConfig,
    ShapeSnapshot,
    canonical_relation_key,
)
from anylabeling.services.inspection.profiles import (
    build_default_catalog,
    default_profiles,
    validate_profile,
)
from anylabeling.services.inspection.rules import (
    RuleContext,
    run_classroom_relation,
    run_corner_completeness,
    run_count_constraint,
    run_group_completeness,
    run_group_id_required,
    run_shape_type_binding,
)


def _shape(
    shape_id,
    label,
    points,
    *,
    group_id=None,
    shape_type="rectangle",
):
    return ShapeSnapshot(
        shape_id=shape_id,
        index=0,
        label=label,
        shape_type=shape_type,
        points=tuple(tuple(point) for point in points),
        group_id=group_id,
    )


def _file(shapes):
    return FileSnapshot(
        relative_path="a.jpg",
        image_path="a.jpg",
        annotation_path="a.json",
        annotation_digest="digest",
        shapes=tuple(shapes),
    )


def _context(shapes, profile=None):
    return RuleContext(
        profile=profile or default_profiles()[0],
        file=_file(shapes),
    )


def test_shape_type_binding_reports_mismatch():
    context = _context(
        [
            _shape(
                "id1",
                "person",
                [[0, 0], [1, 1], [2, 0]],
                shape_type="polygon",
            )
        ]
    )
    outcome = run_shape_type_binding(
        context, {"expected_types": {"person": "rectangle"}}
    )
    assert outcome.state is CoverageState.COMPLETED
    assert outcome.issues[0].title == "标签与形状类型不匹配"


def test_group_id_required_reports_missing_group():
    context = _context([_shape("id1", "person", [[0, 0], [10, 10]])])
    outcome = run_group_id_required(context, {"labels": ["person"]})
    assert outcome.state is CoverageState.COMPLETED
    assert outcome.issues


def test_corner_completeness_reports_missing_and_duplicate():
    shapes = [
        _shape("screen", "screen", [[0, 0], [100, 100]], group_id=1),
        _shape("tl", "tl", [[0, 0], [5, 5]], group_id=1),
        _shape("tl2", "tl", [[1, 1], [6, 6]], group_id=1),
        _shape("tr", "tr", [[95, 0], [100, 5]], group_id=1),
        _shape("bl", "bl", [[0, 95], [5, 100]], group_id=1),
    ]
    context = _context(shapes)
    outcome = run_corner_completeness(
        context,
        {
            "screen_label": "screen",
            "corner_labels": {
                "top_left": "tl",
                "top_right": "tr",
                "bottom_left": "bl",
                "bottom_right": "br",
            },
        },
    )
    titles = {issue.title for issue in outcome.issues}
    assert "屏幕缺少角点" in titles
    assert "屏幕存在重复角点" in titles


def test_corner_completeness_uses_explicit_occlusion_exception():
    shapes = [
        _shape(
            "screen",
            "screen",
            [[0, 0], [100, 100]],
            group_id=1,
            shape_type="rectangle",
        ),
        _shape("tl", "tl", [[0, 0], [5, 5]], group_id=1),
        _shape("tr", "tr", [[95, 0], [100, 5]], group_id=1),
        _shape("bl", "bl", [[0, 95], [5, 100]], group_id=1),
    ]
    shapes[0] = ShapeSnapshot(
        shape_id=shapes[0].shape_id,
        index=shapes[0].index,
        label=shapes[0].label,
        shape_type=shapes[0].shape_type,
        points=shapes[0].points,
        group_id=shapes[0].group_id,
        attributes={"occluded": True},
    )
    context = _context(shapes)
    outcome = run_corner_completeness(
        context,
        {
            "screen_label": "screen",
            "corner_labels": {
                "top_left": "tl",
                "top_right": "tr",
                "bottom_left": "bl",
                "bottom_right": "br",
            },
            "exceptions": {"br": "occluded"},
        },
    )
    titles = {issue.title for issue in outcome.issues}
    assert "屏幕缺少角点" not in titles
    assert "角点缺失按配置例外处理" in titles


def test_corner_completeness_does_not_cancel_missing_and_extra_across_groups():
    shapes = [
        _shape("screen1", "screen", [[0, 0], [50, 50]], group_id=1),
        _shape("screen2", "screen", [[60, 0], [100, 50]], group_id=2),
        _shape("tr1", "tr", [[45, 0], [50, 5]], group_id=1),
        _shape("bl1", "bl", [[0, 45], [5, 50]], group_id=1),
        _shape("br1", "br", [[45, 45], [50, 50]], group_id=1),
        _shape("tl2", "tl", [[60, 0], [65, 5]], group_id=2),
        _shape("tl2b", "tl", [[61, 1], [66, 6]], group_id=2),
        _shape("tr2", "tr", [[95, 0], [100, 5]], group_id=2),
        _shape("bl2", "bl", [[60, 45], [65, 50]], group_id=2),
        _shape("br2", "br", [[95, 45], [100, 50]], group_id=2),
    ]
    context = _context(shapes)
    outcome = run_corner_completeness(
        context,
        {
            "screen_label": "screen",
            "corner_labels": {
                "top_left": "tl",
                "top_right": "tr",
                "bottom_left": "bl",
                "bottom_right": "br",
            },
        },
    )
    titles = [issue.title for issue in outcome.issues]
    assert titles.count("屏幕存在重复角点") == 1
    assert titles.count("屏幕缺少角点") == 1


def test_corner_completeness_without_mapping_is_not_applicable():
    context = _context([])
    outcome = run_corner_completeness(context, {})
    assert outcome.state is CoverageState.NOT_APPLICABLE


def test_classroom_relation_respects_mutual_exclusion():
    shapes = [
        _shape("a", "raise_hand", [[0, 0], [10, 10]]),
        _shape("b", "write", [[2, 2], [12, 12]]),
    ]
    context = _context(shapes)
    outcome = run_classroom_relation(
        context,
        {
            "relations": {
                canonical_relation_key("raise_hand", "write"): (
                    "mutually_exclusive"
                )
            },
            "min_overlap": 0.2,
        },
    )
    assert outcome.state is CoverageState.COMPLETED
    assert outcome.issues[0].title == "互斥动作类别重叠"


def test_classroom_relation_allows_configured_coexistence():
    shapes = [
        _shape("a", "raise_hand", [[0, 0], [10, 10]]),
        _shape("b", "write", [[2, 2], [12, 12]]),
    ]
    context = _context(shapes)
    outcome = run_classroom_relation(
        context,
        {
            "relations": {
                canonical_relation_key("raise_hand", "write"): (
                    "allowed_coexist"
                )
            }
        },
    )
    assert outcome.state is CoverageState.COMPLETED
    assert outcome.issues == ()


def test_count_and_group_completeness_report_quantity_errors():
    shapes = [
        _shape("a", "person", [[0, 0], [10, 10]], group_id=1),
        _shape("screen", "screen", [[0, 0], [50, 50]], group_id=1),
    ]
    context = _context(shapes)
    count = run_count_constraint(
        context, {"counts": {"person": {"min": 2}}}
    )
    assert count.issues
    group = run_group_completeness(
        context, {"groups": {"screen": ["person", "head"]}}
    )
    assert group.issues


def test_profile_validation_detects_relation_conflict():
    profile = InspectionProfile(
        profile_id="test",
        name="test",
        description="",
        stage="post_label",
        rules=(RuleConfig("label_required"),),
        relations={
            "a|b": "mutually_exclusive",
            "b|a": "allowed_coexist",
        },
    )
    validation = validate_profile(profile, build_default_catalog())
    assert validation.valid is False
    assert any("冲突" in error for error in validation.errors)


def test_profile_validation_reports_missing_rule():
    profile = InspectionProfile(
        profile_id="test",
        name="test",
        description="",
        stage="post_label",
        rules=(RuleConfig("not_registered"),),
    )
    validation = validate_profile(profile, build_default_catalog())
    assert validation.valid is True
    assert validation.runnable_subset is False
    assert validation.missing_rule_ids == ("not_registered",)
