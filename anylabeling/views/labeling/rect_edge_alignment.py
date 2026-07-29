"""Rectangle edge editing geometry helper.

This module is a lightweight, QtWidgets-free helper that provides the
geometry primitives used by the rectangle edge editing interaction on the
canvas.

Scope (see ``docs/cls3-010_task_矩形边对齐功能实现任务文档.md``):

- Defines ``RectGeometry`` and ``RectEdgeRef``.
- Provides rectangle point normalization (2-point or 4-point -> bbox/four-point).
- Provides edge enumeration and edge hit-testing.
- Provides edge coordinate update helpers (with anti-flip clamp).
- Does *not* handle mouse events, menu actions, or undo/dirty.

``RectEdgeRef`` holds an in-memory reference to a ``Shape``; it is a purely
temporary editing handle. It is never serialized to JSON and never written
into ``Shape.other_data`` / ``Shape.flags`` / ``Shape.attributes``.
"""

from dataclasses import dataclass
from typing import List, Optional, Tuple

from PyQt6 import QtCore

from . import utils
from .shape import Shape

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RECT_EDGE_LEFT = "left"
RECT_EDGE_RIGHT = "right"
RECT_EDGE_TOP = "top"
RECT_EDGE_BOTTOM = "bottom"

RECT_EDGE_NAMES = (
    RECT_EDGE_LEFT,
    RECT_EDGE_RIGHT,
    RECT_EDGE_TOP,
    RECT_EDGE_BOTTOM,
)

RECT_EDGE_AXIS_X = "x"
RECT_EDGE_AXIS_Y = "y"

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RectGeometry:
    """Normalized axis-aligned rectangle geometry.

    The geometry is always stored as min/max coordinates, regardless of the
    input point ordering. This is the canonical working model for the edge
    edge editing feature.
    """

    x_min: float
    y_min: float
    x_max: float
    y_max: float

    @property
    def width(self) -> float:
        """Return the rectangle width (always >= 0)."""
        return self.x_max - self.x_min

    @property
    def height(self) -> float:
        """Return the rectangle height (always >= 0)."""
        return self.y_max - self.y_min

    def is_valid(
        self, min_width: float = 1.0, min_height: float = 1.0
    ) -> bool:
        """Return whether the geometry is a usable rectangle.

        A rectangle is usable when both dimensions are positive and respect
        the minimum-size bounds (which also guarantees no coordinate flip).

        Args:
            min_width: Minimum allowed width in image coordinates.
            min_height: Minimum allowed height in image coordinates.

        Returns:
            True when the rectangle satisfies the minimum-size contract.
        """
        return (
            self.x_max > self.x_min
            and self.y_max > self.y_min
            and self.width >= min_width
            and self.height >= min_height
        )


@dataclass(frozen=True)
class RectEdgeRef:
    """Temporary reference to one edge of a rectangle shape.

    Holds a live ``Shape`` reference so the Canvas can mutate it in place
    during a drag. It is an editing handle only: it must never be persisted
    to JSON and must never be written into ``Shape.other_data`` /
    ``Shape.flags`` / ``Shape.attributes``.
    """

    shape: Shape
    edge_name: str
    axis: str
    coord: float
    p1: QtCore.QPointF
    p2: QtCore.QPointF
    opposite_coord: float


# ---------------------------------------------------------------------------
# Normalization: Shape -> RectGeometry
# ---------------------------------------------------------------------------


def geometry_from_shape(shape: Shape) -> Optional[RectGeometry]:
    """Build a normalized ``RectGeometry`` from a rectangle shape.

    Rules:

    - Non-rectangle shapes return ``None``.
    - Fewer than 2 points return ``None``.
    - 2 points are treated as diagonal corners (legacy 2-point form).
    - 4 points are reduced via min/max (point ordering is not trusted).
    - Any other point count returns ``None``.

    Args:
        shape: The source shape. Must be a rectangle to produce a geometry.

    Returns:
        The normalized geometry, or ``None`` when the shape is incompatible.
    """
    if shape is None or shape.shape_type != "rectangle":
        return None

    points = shape.points
    count = len(points)
    if count < 2:
        return None

    if count == 2:
        x1, y1 = points[0].x(), points[0].y()
        x2, y2 = points[1].x(), points[1].y()
        xs = (x1, x2)
        ys = (y1, y2)
    elif count == 4:
        xs = tuple(p.x() for p in points)
        ys = tuple(p.y() for p in points)
    else:
        return None

    return RectGeometry(
        x_min=min(xs),
        y_min=min(ys),
        x_max=max(xs),
        y_max=max(ys),
    )


def points_from_geometry(
    geometry: RectGeometry,
) -> List[QtCore.QPointF]:
    """Return the canonical four corners of a geometry.

    Output order is always::

        top-left -> top-right -> bottom-right -> bottom-left

    This matches the Canvas rectangle creation convention
    (``canvas.py`` mousePressEvent rectangle finalize).
    """
    return [
        QtCore.QPointF(geometry.x_min, geometry.y_min),  # top-left
        QtCore.QPointF(geometry.x_max, geometry.y_min),  # top-right
        QtCore.QPointF(geometry.x_max, geometry.y_max),  # bottom-right
        QtCore.QPointF(geometry.x_min, geometry.y_max),  # bottom-left
    ]


# ---------------------------------------------------------------------------
# Edges
# ---------------------------------------------------------------------------

# edge_name -> (axis, coord_attr, opposite_attr, p1 corner, p2 corner)
# corner keys reference RectGeometry fields.
_EDGE_TABLE = {
    RECT_EDGE_LEFT: (
        RECT_EDGE_AXIS_X,
        "x_min",
        "x_max",
        ("x_min", "y_min"),  # top-left
        ("x_min", "y_max"),  # bottom-left
    ),
    RECT_EDGE_RIGHT: (
        RECT_EDGE_AXIS_X,
        "x_max",
        "x_min",
        ("x_max", "y_min"),  # top-right
        ("x_max", "y_max"),  # bottom-right
    ),
    RECT_EDGE_TOP: (
        RECT_EDGE_AXIS_Y,
        "y_min",
        "y_max",
        ("x_min", "y_min"),  # top-left
        ("x_max", "y_min"),  # top-right
    ),
    RECT_EDGE_BOTTOM: (
        RECT_EDGE_AXIS_Y,
        "y_max",
        "y_min",
        ("x_min", "y_max"),  # bottom-left
        ("x_max", "y_max"),  # bottom-right
    ),
}


def edge_from_geometry(
    shape: Shape,
    geometry: RectGeometry,
    edge_name: str,
) -> RectEdgeRef:
    """Build a ``RectEdgeRef`` for one edge of a geometry.

    Args:
        shape: The owning shape (kept by reference on the returned object).
        geometry: The normalized geometry the edge is derived from.
        edge_name: One of ``RECT_EDGE_NAMES``.

    Returns:
        The edge reference. Raises ``ValueError`` for an unknown edge name.
    """
    if edge_name not in _EDGE_TABLE:
        raise ValueError(f"Unknown edge name: {edge_name!r}")

    axis, coord_attr, opposite_attr, p1_key, p2_key = _EDGE_TABLE[edge_name]
    coord = float(getattr(geometry, coord_attr))
    opposite_coord = float(getattr(geometry, opposite_attr))

    def _corner(key: Tuple[str, str]) -> QtCore.QPointF:
        return QtCore.QPointF(
            getattr(geometry, key[0]),
            getattr(geometry, key[1]),
        )

    return RectEdgeRef(
        shape=shape,
        edge_name=edge_name,
        axis=axis,
        coord=coord,
        p1=_corner(p1_key),
        p2=_corner(p2_key),
        opposite_coord=opposite_coord,
    )


def iter_edges(shape: Shape) -> List[RectEdgeRef]:
    """Return the four edges of a rectangle shape.

    Non-rectangle shapes or invalid rectangles return an empty list.
    """
    if shape is None or shape.shape_type != "rectangle":
        return []

    geometry = geometry_from_shape(shape)
    if geometry is None or not geometry.is_valid():
        return []

    return [
        edge_from_geometry(shape, geometry, name) for name in RECT_EDGE_NAMES
    ]


def nearest_edge(
    shape: Shape,
    point: QtCore.QPointF,
    epsilon: float,
) -> Optional[Tuple[RectEdgeRef, float]]:
    """Return the nearest rectangle edge within ``epsilon`` of ``point``.

    Distance is computed in image coordinates using
    :func:`utils.distance_to_line`. ``epsilon`` is supplied by the Canvas,
    which is responsible for converting the screen-pixel hit threshold to
    image space.

    Args:
        shape: The rectangle shape to test.
        point: The query point in image coordinates.
        epsilon: Hit radius in image coordinates.

    Returns:
        A ``(edge_ref, distance)`` tuple for the nearest edge within range,
        or ``None`` when no edge is close enough (or the shape is not a
        usable rectangle).
    """
    edges = iter_edges(shape)
    if not edges:
        return None

    best: Optional[Tuple[RectEdgeRef, float]] = None
    for edge in edges:
        dist = utils.distance_to_line(point, [edge.p1, edge.p2])
        if dist <= epsilon and (best is None or dist < best[1]):
            best = (edge, dist)
    return best


# ---------------------------------------------------------------------------
# Edge coordinate update (with anti-flip clamp)
# ---------------------------------------------------------------------------


def geometry_with_edge_coord(
    geometry: RectGeometry,
    edge_name: str,
    coord: float,
    min_size: float = 1.0,
) -> RectGeometry:
    """Return a new geometry with one edge moved to ``coord``.

    The opposite edge is preserved and the moved edge is clamped so the
    rectangle can never flip (``min`` always stays below ``max``):

    ====================  =========================
    edge                  clamp
    ====================  =========================
    left                  coord <= x_max - min_size
    right                 coord >= x_min + min_size
    top                   coord <= y_max - min_size
    bottom                coord >= y_min + min_size
    ====================  =========================

    Args:
        geometry: The source geometry.
        edge_name: The edge to move.
        coord: The new coordinate for that edge's axis.
        min_size: Minimum retained dimension used for clamping.

    Returns:
        A new clamped ``RectGeometry``. Raises ``ValueError`` for an unknown
        edge name.
    """
    if edge_name not in _EDGE_TABLE:
        raise ValueError(f"Unknown edge name: {edge_name!r}")

    x_min, y_min = geometry.x_min, geometry.y_min
    x_max, y_max = geometry.x_max, geometry.y_max

    if edge_name == RECT_EDGE_LEFT:
        x_min = min(coord, x_max - min_size)
    elif edge_name == RECT_EDGE_RIGHT:
        x_max = max(coord, x_min + min_size)
    elif edge_name == RECT_EDGE_TOP:
        y_min = min(coord, y_max - min_size)
    elif edge_name == RECT_EDGE_BOTTOM:
        y_max = max(coord, y_min + min_size)

    return RectGeometry(
        x_min=float(x_min),
        y_min=float(y_min),
        x_max=float(x_max),
        y_max=float(y_max),
    )


def apply_edge_coord(
    shape: Shape,
    edge_name: str,
    coord: float,
    min_size: float = 1.0,
) -> bool:
    """Apply an edge coordinate change to a rectangle shape in place.

    The shape is rewritten to the canonical four-point form
    (``top-left -> top-right -> bottom-right -> bottom-left``) and its
    geometry caches are invalidated. The label, group_id, attributes,
    selected/hovered flags are never touched.

    Args:
        shape: The rectangle shape to mutate.
        edge_name: The edge to move.
        coord: The new coordinate for that edge's axis.
        min_size: Minimum retained dimension used for clamping.

    Returns:
        True when the change was applied, False when the shape is not a
        usable rectangle (e.g. invalid geometry).
    """
    geometry = geometry_from_shape(shape)
    if geometry is None or not geometry.is_valid(min_size, min_size):
        return False

    new_geometry = geometry_with_edge_coord(
        geometry, edge_name, coord, min_size=min_size
    )
    shape.points = points_from_geometry(new_geometry)
    # ``shape.points`` is a plain list; mutating it does not invalidate the
    # internal bbox/path caches, so invalidate explicitly.
    shape._invalidate_cache()
    return True
