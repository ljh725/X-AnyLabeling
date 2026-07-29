"""Stage-1 L1/L2 quality checker (pure-Python, no PyQt dependency).

Public API for the quality-check pipeline:

    from anylabeling.views.labeling.widgets.inspector.quality import (
        run_quality_check,
        write_review_tsv,
        write_report_json,
        generate_threshold_suggestion,
        load_threshold_profile,
    )

See ``docs/qc-040_spec_v0_阶段一l1_l2质检规则阈值与输出规格.md``
for the v0 spec.
"""

# flake8: noqa

from .feedback import (
    FeedbackRow,
    FeedbackParseResult,
    FeedbackTemplateResult,
    aggregate_by_rule,
    read_review_feedback,
    write_review_feedback_template,
)
from .geometry import (
    BBox,
    bbox_area,
    bbox_center,
    bbox_from_points,
    containment_ratio,
    expand_bbox,
    intersection_area,
    iou,
    is_valid_bbox,
    keypoint_y_rel,
    overflow_ratio,
    point_in_bbox,
    shape_bbox,
    x_overlap_ratio,
    y_overlap_ratio,
)
from .l1_rules import run_l1
from .l2_rules import run_l2
from .matching import (
    FaceHeadMatch,
    HeadPersonMatch,
    MatchingCfg,
    match_all_faces,
    match_all_heads,
    match_face_to_heads,
    match_head_to_persons,
    matching_cfg_from_profile,
)
from .quality_issue import (
    MatchCandidate,
    PrimaryMetric,
    QcFile,
    QcShape,
    QcShapeLoader,
    QualityIssue,
    QualityReport,
)
from .report_writer import (
    CHECKER_VERSION,
    REVIEW_TSV_COLUMNS,
    run_quality_check,
    write_report_json,
    write_review_tsv,
)
from .threshold_profile import (
    RuleThreshold,
    ThresholdProfile,
    ThresholdProfileError,
    load_threshold_profile,
    threshold_to_snapshot,
)
from .threshold_suggestion import (
    SCHEMA_VERSION as SUGGESTION_SCHEMA_VERSION,
    SuggestionContext,
    generate_threshold_suggestion,
)
