"""Coordinate-gain helpers for rectangle edge refinement."""

from __future__ import annotations

import math
from typing import Any

DEFAULT_TARGET_GAIN = 0.5
_MIN_SCALE = 1e-6
_MIN_TARGET_GAIN = 1e-6


def _finite_positive(value: Any, fallback: float) -> float:
    """Return a finite positive float or ``fallback``."""
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return fallback
    if not math.isfinite(numeric) or numeric <= 0:
        return fallback
    return numeric


def effective_gain(
    canvas_scale: float,
    target_gain: float = DEFAULT_TARGET_GAIN,
) -> float:
    """Calculate the maximum image-pixel movement per screen pixel.

    Args:
        canvas_scale: Current image-to-screen scale.
        target_gain: Maximum image-pixel movement allowed in refinement mode.

    Returns:
        The natural canvas gain capped by ``target_gain``.
    """
    scale = _finite_positive(canvas_scale, 1.0)
    target = _finite_positive(target_gain, DEFAULT_TARGET_GAIN)
    return min(1.0 / max(scale, _MIN_SCALE), max(target, _MIN_TARGET_GAIN))


def effective_image_delta(
    screen_delta: tuple[float, float],
    canvas_scale: float,
    target_gain: float = DEFAULT_TARGET_GAIN,
) -> tuple[float, float]:
    """Convert a screen-space delta to a refinement image-space delta."""
    gain = effective_gain(canvas_scale, target_gain)
    return float(screen_delta[0]) * gain, float(screen_delta[1]) * gain


def image_delta_multiplier(
    canvas_scale: float,
    target_gain: float = DEFAULT_TARGET_GAIN,
) -> float:
    """Return the multiplier for an already image-space drag delta.

    Canvas mouse coordinates are transformed into image space before the
    rectangle edge handler receives them. This converts the desired
    screen-space gain into the equivalent multiplier for that delta.
    """
    scale = _finite_positive(canvas_scale, 1.0)
    return effective_gain(scale, target_gain) * scale


def target_gain_from_legacy_config(
    config: dict[str, Any] | None,
    default: float = DEFAULT_TARGET_GAIN,
) -> float:
    """Map the historical precision settings to a target gain.

    New callers should pass the leaf values from the new configuration tree
    through ``target_gain`` directly. This helper is deliberately pure so
    migration behavior can be tested without Qt or a settings dialog.

    Args:
        config: A mapping containing legacy ``canvas_precision_*`` keys.
        default: Fallback target gain.

    Returns:
        A finite positive target gain.
    """
    if not isinstance(config, dict):
        return _finite_positive(default, DEFAULT_TARGET_GAIN)

    new_value = config.get("target_gain")
    if new_value is not None:
        return _finite_positive(new_value, default)

    mode = config.get("canvas_precision_mode")
    if mode == "fixed":
        factor = _finite_positive(config.get("canvas_precision_factor"), 2.0)
        return 1.0 / factor
    if mode == "zoom":
        factor = _finite_positive(
            config.get("canvas_precision_max_factor"), 2.0
        )
        return 1.0 / factor
    return _finite_positive(default, DEFAULT_TARGET_GAIN)


def resolve_target_gain(
    refinement_config: dict[str, Any] | None,
    legacy_config: dict[str, Any] | None = None,
) -> tuple[float, bool]:
    """Resolve the new target gain and report whether legacy keys were used.

    Args:
        refinement_config: The nested ``rectangle_review_refinement`` mapping.
        legacy_config: The root configuration containing historical precision
            keys. It is consulted only when the new mapping has no valid
            ``target_gain`` value.

    Returns:
        A ``(target_gain, migrated)`` tuple. ``migrated`` is true when the
        value came from a legacy setting and can be used for a one-time UI
        migration hint.
    """
    nested = refinement_config if isinstance(refinement_config, dict) else {}
    raw = nested.get("target_gain")
    if raw is not None:
        try:
            value = float(raw)
        except (TypeError, ValueError):
            value = float("nan")
        if math.isfinite(value) and value > 0:
            return value, False

    root = legacy_config if isinstance(legacy_config, dict) else {}
    return target_gain_from_legacy_config(root), True
