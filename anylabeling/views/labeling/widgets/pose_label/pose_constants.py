"""COCO 17-keypoint definitions, body-part groups, skeleton, presets.

This module is the authoritative source for COCO keypoint semantics used by
the pose label renderer.  It has **zero** Qt widget dependency so it can be
unit-tested in isolation.

References:
    - HTML prototype ``html-case/0616_code.html`` (P17, SKEL, BCOL)
    - Existing ``keypoint_fill_mode.KEYPOINT_ORDER`` (duplicated shorthand)
"""

from __future__ import annotations

from typing import Dict, List, Tuple

# -- COCO 17 keypoint order (shorthand labels) ---------------------------

COCO_KEYPOINT_ORDER: List[str] = [
    "nose",
    "l_eye",
    "r_eye",
    "l_ear",
    "r_ear",
    "l_sho",
    "r_sho",
    "l_elb",
    "r_elb",
    "l_wri",
    "r_wri",
    "l_hip",
    "r_hip",
    "l_knee",
    "r_knee",
    "l_ank",
    "r_ank",
]

COCO_KEYPOINT_INDEX: Dict[str, int] = {
    name: idx for idx, name in enumerate(COCO_KEYPOINT_ORDER)
}

COCO_KEYPOINT_SET = frozenset(COCO_KEYPOINT_ORDER)

# -- Body-part groups ----------------------------------------------------

BODY_PARTS: Dict[str, List[str]] = {
    "head": ["nose", "l_eye", "r_eye", "l_ear", "r_ear"],
    "la": ["l_sho", "l_elb", "l_wri"],
    "ra": ["r_sho", "r_elb", "r_wri"],
    "ll": ["l_hip", "l_knee", "l_ank"],
    "rl": ["r_hip", "r_knee", "r_ank"],
}

LABEL_TO_BODY_PART: Dict[str, str] = {
    label: part for part, labels in BODY_PARTS.items() for label in labels
}

BODY_PART_ORDER: List[str] = ["head", "la", "ra", "ll", "rl"]

# -- Skeleton edges (index pairs into COCO_KEYPOINT_ORDER) ---------------

SKELETON_EDGES: List[Tuple[int, int]] = [
    (0, 1),
    (0, 2),
    (1, 3),
    (2, 4),
    (5, 6),
    (5, 7),
    (7, 9),
    (6, 8),
    (8, 10),
    (5, 11),
    (6, 12),
    (11, 12),
    (11, 13),
    (13, 15),
    (12, 14),
    (14, 16),
]

# -- Default colors ------------------------------------------------------

DEFAULT_BODY_COLORS: Dict[str, str] = {
    "head": "#e74c3c",
    "la": "#3498db",
    "ra": "#9b59b6",
    "ll": "#2ecc71",
    "rl": "#f39c12",
}

DEFAULT_PERSON_COLORS: List[str] = [
    "#e74c3c",
    "#3498db",
    "#2ecc71",
    "#f39c12",
    "#9b59b6",
]

COLOR_PRESETS: Dict[str, Dict[str, str]] = {
    "default": {
        "head": "#e74c3c",
        "la": "#3498db",
        "ra": "#9b59b6",
        "ll": "#2ecc71",
        "rl": "#f39c12",
    },
    "pastel": {
        "head": "#f5a5a5",
        "la": "#a5c8f5",
        "ra": "#c8a5f5",
        "ll": "#a5f5c8",
        "rl": "#f5d5a5",
    },
    "neon": {
        "head": "#ff0055",
        "la": "#00ccff",
        "ra": "#cc00ff",
        "ll": "#00ff88",
        "rl": "#ffaa00",
    },
    "earth": {
        "head": "#c0755a",
        "la": "#5a8fc0",
        "ra": "#8f5ac0",
        "ll": "#5ac075",
        "rl": "#c09a5a",
    },
}

# -- Direction helpers ---------------------------------------------------

DIRECTION_VECTORS: Dict[str, Tuple[float, float]] = {
    "up": (0.0, -1.0),
    "left-up": (-0.7, -0.7),
    "right-up": (0.7, -0.7),
    "left": (-1.0, 0.0),
    "right": (1.0, 0.0),
    "left-down": (-0.7, 0.7),
    "right-down": (0.7, 0.7),
    "down": (0.0, 1.0),
}

DIRECTION_ARROWS: Dict[str, str] = {
    "up": "\u2191",
    "left-up": "\u2196",
    "right-up": "\u2197",
    "left": "\u2190",
    "right": "\u2192",
    "left-down": "\u2199",
    "right-down": "\u2198",
    "down": "\u2193",
}

# Anti-occlusion priority (limbs first, face last) – from HTML prototype.
LAYOUT_PRIORITY: List[int] = [
    15,
    16,
    9,
    10,
    3,
    4,
    13,
    14,
    7,
    8,
    1,
    2,
    11,
    12,
    5,
    6,
    0,
]
