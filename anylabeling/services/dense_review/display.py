"""Pure resolution of dense-review display roles and component styles.

This module is the single place that decides *what* a shape looks like while
dense review is active.  It deliberately contains no Qt painting code and no
canvas mutation: callers translate the returned plan into paint calls,
hit-test gates and label text.  Keeping the decision pure is what lets the
canvas, the hit test and the label layout agree by construction
(DP-01, DP-02, DP-15, DP-17, DP-18).

The input is the user's own visibility intent (``shape_filter`` plus manual
hides), the stable batch/current identity from the review session, and the
temporary presentation state owned by the workspace.  The output classifies
each shape into one of three roles and gives that role a full set of
component styles, so "background strength zero" removes the outline, points,
label plate and guide line *and* the mouse target together rather than
leaving orphaned overlays behind.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Optional

ROLE_CURRENT = "current"
ROLE_BATCH = "batch"
ROLE_OTHER = "other"

#: Display roles in paint order; later roles sit above earlier ones.
PAINT_ORDER = (ROLE_OTHER, ROLE_BATCH, ROLE_CURRENT)

#: Roles whose editing handles are shown.  Only the explicit edit target
#: keeps handles, so formal keypoints stay distinguishable from handles
#: (DP-03).
HANDLE_ROLES = (ROLE_CURRENT,)


@dataclass(frozen=True)
class RoleStyle:
    """Component strengths for one display role, all in ``0..1``.

    ``fill`` defaults to zero on purpose: dense review starts with the
    source image readable and only outlines the review scope (DP-01).
    """

    fill: float = 0.0
    outline: float = 1.0
    outline_width: float = 1.4
    points: float = 1.0
    handles: float = 1.0
    text: float = 1.0
    text_plate: float = 1.0
    attributes: float = 1.0
    linking: float = 1.0
    mask: float = 1.0

    def normalized(self) -> "RoleStyle":
        def clamp(value: float) -> float:
            return max(0.0, min(1.0, float(value)))

        return RoleStyle(
            fill=clamp(self.fill),
            outline=clamp(self.outline),
            outline_width=max(0.5, min(6.0, float(self.outline_width))),
            points=clamp(self.points),
            handles=clamp(self.handles),
            text=clamp(self.text),
            text_plate=clamp(self.text_plate),
            attributes=clamp(self.attributes),
            linking=clamp(self.linking),
            mask=clamp(self.mask),
        )

    @property
    def visible(self) -> bool:
        """Return whether any component of this style still paints."""
        return any(
            value > 0.0
            for value in (
                self.fill,
                self.outline,
                self.points,
                self.handles,
                self.text,
                self.attributes,
                self.linking,
                self.mask,
            )
        )

    @property
    def interactive(self) -> bool:
        """Return whether this style leaves a mouse-selectable component.

        Only the geometric components count: text and its plate are drawn
        affordances, so hiding text does not make a visible outline
        unclickable.
        """
        return any(
            value > 0.0
            for value in (self.fill, self.outline, self.points, self.handles)
        )

    def to_dict(self) -> dict[str, float]:
        return {
            "fill": self.fill,
            "outline": self.outline,
            "outline_width": self.outline_width,
            "points": self.points,
            "handles": self.handles,
            "text": self.text,
            "text_plate": self.text_plate,
            "attributes": self.attributes,
            "linking": self.linking,
            "mask": self.mask,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RoleStyle":
        defaults = cls()
        values = {}
        for name in defaults.to_dict():
            raw = data.get(name, getattr(defaults, name))
            try:
                values[name] = float(raw)
            except (TypeError, ValueError):
                values[name] = getattr(defaults, name)
        return cls(**values).normalized()


def default_role_styles() -> dict[str, RoleStyle]:
    """Return the initial review presets described by D3.

    The numbers are trial defaults: the real screen pass tunes brightness,
    so they stay in one place instead of being scattered through paint code.
    """
    return {
        ROLE_CURRENT: RoleStyle(
            fill=0.0,
            outline=1.0,
            outline_width=2.0,
            points=1.0,
            handles=1.0,
            text=1.0,
            text_plate=1.0,
            attributes=1.0,
            linking=1.0,
            mask=1.0,
        ),
        ROLE_BATCH: RoleStyle(
            fill=0.0,
            outline=0.65,
            outline_width=1.4,
            points=0.55,
            handles=0.0,
            text=0.75,
            text_plate=0.6,
            attributes=0.45,
            linking=0.45,
            mask=0.0,
        ),
        ROLE_OTHER: RoleStyle(
            fill=0.0,
            outline=0.2,
            outline_width=0.9,
            points=0.3,
            handles=0.0,
            text=0.0,
            text_plate=0.0,
            attributes=0.0,
            linking=0.0,
            mask=0.0,
        ),
    }


@dataclass(frozen=True)
class ShapeDisplay:
    """The effective display result for one shape.

    ``drawable`` and ``hittable`` are derived from the same inputs, so a
    component that exits painting exits hit testing too (DP-02).  ``reason``
    carries the machine-readable exclusion cause so the panel can explain a
    hidden object instead of silently ignoring a navigation request (DP-11).
    """

    shape_id: str
    role: str
    style: RoleStyle
    drawable: bool
    hittable: bool
    label_visible: bool
    reason: str = ""
    temporary: bool = False
    locked: bool = False

    @property
    def visible(self) -> bool:
        return self.drawable

    def to_dict(self) -> dict[str, Any]:
        return {
            "shape_id": self.shape_id,
            "role": self.role,
            "style": self.style.to_dict(),
            "drawable": self.drawable,
            "hittable": self.hittable,
            "label_visible": self.label_visible,
            "reason": self.reason,
            "temporary": self.temporary,
            "locked": self.locked,
        }


#: Exclusion reasons, ordered by the precedence documented in D2.
REASON_GLOBAL_OFF = "global-off"
REASON_ORIGINAL_ONLY = "original-only"
REASON_MANUAL_HIDDEN = "manual-hidden"
REASON_LABEL_HIDDEN = "label-hidden"
REASON_FILTERED = "filtered"
REASON_MISSING = "missing"
REASON_UNSUPPORTED = "unsupported"

REASON_TEXT = {
    REASON_GLOBAL_OFF: "全局标注显示已关闭",
    REASON_ORIGINAL_ONLY: "正在显示原图对照",
    REASON_MANUAL_HIDDEN: "已手动隐藏",
    REASON_LABEL_HIDDEN: "类别已隐藏",
    REASON_FILTERED: "被类别或分组过滤排除",
    REASON_MISSING: "对象不存在",
    REASON_UNSUPPORTED: "当前不支持复核显示",
}


@dataclass
class DisplayContext:
    """Everything the resolver needs, provided by the workspace/host.

    ``styles`` may be partially overridden; missing roles fall back to the
    trial defaults.  ``temporary_ids`` is the explicit "show anyway" set and
    is *not* a confirmation-eligibility change (PC-06).
    """

    batch_ids: frozenset = frozenset()
    current_id: str = ""
    associated_ids: frozenset = frozenset()
    styles: Mapping[str, RoleStyle] = field(default_factory=dict)
    global_annotations_on: bool = True
    original_only: bool = False
    manual_hidden: frozenset = frozenset()
    label_hidden: frozenset = frozenset()
    filtered: frozenset = frozenset()
    unsupported: frozenset = frozenset()
    temporary_ids: frozenset = frozenset()
    hovering_id: str = ""

    def style_for(self, role: str) -> RoleStyle:
        defaults = default_role_styles()
        override = self.styles.get(role)
        if override is None:
            return defaults[role]
        return override.normalized()


def _exclusion_reason(
    shape_id: str,
    labels: Mapping[str, str],
    context: DisplayContext,
) -> str:
    """Return the first blocking exclusion reason, or "" when visible."""
    if not context.global_annotations_on:
        return REASON_GLOBAL_OFF
    if context.original_only:
        return REASON_ORIGINAL_ONLY
    if shape_id not in labels:
        return REASON_MISSING
    if shape_id in context.manual_hidden:
        return REASON_MANUAL_HIDDEN
    if shape_id in context.label_hidden:
        return REASON_LABEL_HIDDEN
    if shape_id in context.filtered:
        return REASON_FILTERED
    return ""


def _role_for(shape_id: str, context: DisplayContext) -> str:
    if shape_id and shape_id == context.current_id:
        return ROLE_CURRENT
    if shape_id in context.associated_ids:
        # Associated keypoints rise with their current rectangle so the
        # frame-and-keypoint task stays readable (D2 step 5).
        return ROLE_CURRENT
    if shape_id in context.batch_ids:
        return ROLE_BATCH
    return ROLE_OTHER


def resolve_shape(
    shape_id: str,
    label: str,
    context: DisplayContext,
    *,
    locked: bool = False,
) -> ShapeDisplay:
    """Resolve one shape's effective display result."""
    labels = {shape_id: label} if label is not None else {}
    return _resolve(shape_id, labels, context, locked=locked)


def _resolve(
    shape_id: str,
    labels: Mapping[str, str],
    context: DisplayContext,
    *,
    locked: bool = False,
) -> ShapeDisplay:
    reason = _exclusion_reason(shape_id, labels, context)
    temporary = False
    if reason in (REASON_MANUAL_HIDDEN, REASON_LABEL_HIDDEN, REASON_FILTERED):
        # Only an explicit "show anyway" action lifts a user exclusion, and
        # only the exact object set.  Global-off and original-only still win
        # because they are checked first (DP-12).
        if shape_id in context.temporary_ids:
            reason = ""
            temporary = True
    if not reason and shape_id in context.unsupported:
        reason = REASON_UNSUPPORTED

    role = _role_for(shape_id, context)
    style = context.style_for(role)
    drawable = not reason and style.visible
    label_visible = bool(drawable and style.text > 0.0)
    return ShapeDisplay(
        shape_id=shape_id,
        role=role,
        style=style,
        drawable=drawable,
        hittable=bool(drawable and style.interactive),
        label_visible=label_visible,
        reason=reason,
        temporary=temporary,
        locked=bool(locked),
    )


def resolve_all(
    shapes: Iterable[Any],
    context: DisplayContext,
    shape_id_of=None,
    label_of=None,
) -> dict[str, ShapeDisplay]:
    """Resolve every shape into an id-keyed display map.

    ``shape_id_of``/``label_of`` let callers pass canvas shapes without this
    module importing the canvas type.
    """
    if shape_id_of is None:
        shape_id_of = lambda item: getattr(  # noqa: E731
            item, "xanylabeling_shape_id", ""
        )
    if label_of is None:
        label_of = lambda item: getattr(item, "label", "")  # noqa: E731
    resolved: dict[str, ShapeDisplay] = {}
    for shape in shapes:
        shape_id = str(shape_id_of(shape) or "")
        if not shape_id:
            continue
        resolved[shape_id] = resolve_shape(
            shape_id,
            label_of(shape),
            context,
            locked=bool(getattr(shape, "locked", False)),
        )
    return resolved


def paint_groups(
    displays: Mapping[str, ShapeDisplay],
) -> list[tuple[str, list[str]]]:
    """Group drawable shape ids by role in bottom-to-top paint order."""
    groups: list[tuple[str, list[str]]] = []
    for role in PAINT_ORDER:
        ids = [
            shape_id
            for shape_id, display in displays.items()
            if display.drawable and display.role == role
        ]
        if ids:
            groups.append((role, sorted(ids)))
    return groups


def dominant_reason(
    displays: Mapping[str, ShapeDisplay],
) -> Optional[str]:
    """Return the most common exclusion reason, for the panel summary."""
    counts: dict[str, int] = {}
    for display in displays.values():
        if display.reason:
            counts[display.reason] = counts.get(display.reason, 0) + 1
    if not counts:
        return None
    return max(counts.items(), key=lambda item: (item[1], item[0]))[0]


def exclusion_summary(
    displays: Mapping[str, ShapeDisplay],
) -> dict[str, int]:
    """Count excluded objects per reason for the batch confirmation panel."""
    summary: dict[str, int] = {}
    for display in displays.values():
        if display.reason:
            summary[display.reason] = summary.get(display.reason, 0) + 1
    return summary
