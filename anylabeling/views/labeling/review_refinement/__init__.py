"""Pure-Python helpers for low-fatigue rectangle review refinement."""

from .gain import (
    DEFAULT_TARGET_GAIN,
    effective_gain,
    effective_image_delta,
    image_delta_multiplier,
    resolve_target_gain,
    target_gain_from_legacy_config,
)
from .metrics import (
    DEFAULT_IDLE_TIMEOUT_SECONDS,
    DEFAULT_REVERSAL_CONFIRM_PX,
    DEFAULT_REVERSAL_DEADBAND_PX,
    DEFAULT_ZOOM_BURST_SECONDS,
    EpisodeEndReason,
    FeatureStage,
    JsonlMetricsWriter,
    ReviewEpisodeCollector,
    ReviewEpisodeRecord,
    aggregate_records,
    read_records,
)
from .feedback import ReviewFeedbackSnapshot, make_feedback_snapshot
from .assistance import (
    CandidatePreviewController,
    EdgeCandidate,
    EdgeCandidateService,
    LoupeROI,
    build_loupe_roi,
)
from .nudge import (
    NudgeCommand,
    NudgeBurstTracker,
    WheelAccumulator,
    nudge_delta,
    valid_edge_nudge,
)
from .session import RefinementSessionController, RefinementSessionState

__all__ = [
    "DEFAULT_IDLE_TIMEOUT_SECONDS",
    "DEFAULT_REVERSAL_CONFIRM_PX",
    "DEFAULT_REVERSAL_DEADBAND_PX",
    "DEFAULT_TARGET_GAIN",
    "DEFAULT_ZOOM_BURST_SECONDS",
    "CandidatePreviewController",
    "EdgeCandidate",
    "EdgeCandidateService",
    "EpisodeEndReason",
    "FeatureStage",
    "JsonlMetricsWriter",
    "LoupeROI",
    "NudgeCommand",
    "NudgeBurstTracker",
    "ReviewEpisodeCollector",
    "ReviewEpisodeRecord",
    "ReviewFeedbackSnapshot",
    "RefinementSessionController",
    "RefinementSessionState",
    "WheelAccumulator",
    "aggregate_records",
    "effective_gain",
    "effective_image_delta",
    "image_delta_multiplier",
    "nudge_delta",
    "make_feedback_snapshot",
    "build_loupe_roi",
    "resolve_target_gain",
    "read_records",
    "target_gain_from_legacy_config",
    "valid_edge_nudge",
]
