"""Dense annotation review services.

This package is Qt-free: the workspace and the canvas host it from the GUI
layer, while all state transitions, signatures, coverage invalidation and
persistence contracts are testable in isolation.
"""

from .config import (
    ReviewConfigFileError,
    config_path,
    load_config,
    resolve_config,
    save_config,
)
from .display import (
    ROLE_BATCH,
    ROLE_CURRENT,
    ROLE_OTHER,
    DisplayContext,
    PaintStyle,
    RoleStyle,
    ShapeDisplay,
    default_role_styles,
    exclusion_summary,
    paint_groups,
    resolve_all,
    resolve_shape,
)
from .models import (
    BOX_RULE_LABELS,
    DIMENSION_LABELS,
    NEW_PENDING_BATCH_ID,
    OTHER_BATCH_ID,
    REVIEW_VERSION,
    BatchConfirmation,
    CandidateScope,
    CompletionStatus,
    ConfigIssue,
    CoveragePlan,
    CoverageRegion,
    CoverageSettings,
    IncompatibleReviewState,
    ObjectReviewState,
    ReviewConfig,
    ReviewState,
    ReviewRules,
)
from .session import DenseReviewSession, ReviewConfigError
from .storage import (
    DENSE_REVIEW_FIELD,
    AnnotationFileState,
    annotation_state,
    image_fingerprint,
    load_payload,
)

__all__ = [
    "BOX_RULE_LABELS",
    "DENSE_REVIEW_FIELD",
    "DIMENSION_LABELS",
    "NEW_PENDING_BATCH_ID",
    "OTHER_BATCH_ID",
    "REVIEW_VERSION",
    "ROLE_BATCH",
    "ROLE_CURRENT",
    "ROLE_OTHER",
    "AnnotationFileState",
    "BatchConfirmation",
    "CandidateScope",
    "CompletionStatus",
    "ConfigIssue",
    "CoveragePlan",
    "CoverageRegion",
    "CoverageSettings",
    "DenseReviewSession",
    "DisplayContext",
    "IncompatibleReviewState",
    "ObjectReviewState",
    "PaintStyle",
    "ReviewConfig",
    "ReviewConfigError",
    "ReviewConfigFileError",
    "ReviewRules",
    "ReviewState",
    "RoleStyle",
    "ShapeDisplay",
    "annotation_state",
    "config_path",
    "default_role_styles",
    "exclusion_summary",
    "image_fingerprint",
    "load_config",
    "load_payload",
    "paint_groups",
    "resolve_all",
    "resolve_config",
    "resolve_shape",
    "save_config",
]
