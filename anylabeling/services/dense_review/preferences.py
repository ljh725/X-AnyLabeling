"""Validated view preferences, separate from annotation review progress."""

import copy

DEFAULTS = {
    "task": "category",
    "image_height": 320,
    "context": 35,
    "batches_visible": True,
    "cards_visible": True,
    "task_display": {
        task: {"mode": mode, "show_points": False, "styles": None}
        for task, mode in (
            ("category", "focus"),
            ("box-points", "focus"),
            ("coverage", "all"),
        )
    },
}


def normalize_preferences(raw):
    """Normalize old/malformed view settings to usable, bounded values."""
    raw = raw if isinstance(raw, dict) else {}
    result = copy.deepcopy({**DEFAULTS, **raw})
    if result["task"] not in ("category", "box-points", "coverage"):
        result["task"] = "category"
    for name, lower, upper in (
        ("image_height", 160, 640),
        ("context", 0, 150),
    ):
        try:
            result[name] = max(lower, min(upper, int(result[name])))
        except (TypeError, ValueError, OverflowError):
            result[name] = DEFAULTS[name]
    for name in ("batches_visible", "cards_visible"):
        if not isinstance(result[name], bool):
            result[name] = DEFAULTS[name]
    if not isinstance(result["task_display"], dict):
        result["task_display"] = {}
    return result
