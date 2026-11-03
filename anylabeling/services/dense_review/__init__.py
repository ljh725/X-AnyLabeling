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
    "AnnotationFileState",
    "BatchConfirmation",
    "CandidateScope",
    "CompletionStatus",
    "ConfigIssue",
    "CoveragePlan",
    "CoverageRegion",
    "CoverageSettings",
    "DenseReviewSession",
    "IncompatibleReviewState",
    "ObjectReviewState",
    "ReviewConfig",
    "ReviewConfigError",
    "ReviewConfigFileError",
    "ReviewRules",
    "ReviewState",
    "annotation_state",
    "config_path",
    "image_fingerprint",
    "load_config",
    "load_payload",
    "resolve_config",
    "save_config",
]
