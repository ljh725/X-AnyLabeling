from dataclasses import dataclass, field
from typing import Optional

from anylabeling.services.dense_review.models import (
    BatchDefinition,
    CoverageSettings,
    LabelRule,
    ReviewConfig,
    ReviewRules,
)


@dataclass
class FakePoint:
    x_value: float
    y_value: float

    def x(self) -> float:
        return self.x_value

    def y(self) -> float:
        return self.y_value


@dataclass
class FakeShape:
    xanylabeling_shape_id: str
    label: str
    bounds: tuple[float, float, float, float]
    shape_type: str = "rectangle"
    attributes: dict = field(default_factory=dict)
    flags: dict = field(default_factory=dict)
    group_id: Optional[int] = None
    difficult: bool = False
    description: str = ""
    locked: bool = False

    def __post_init__(self):
        self.set_bounds(self.bounds)

    def set_bounds(self, bounds):
        x0, y0, x1, y1 = bounds
        self.bounds = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
        self.points = [
            FakePoint(self.bounds[0], self.bounds[1]),
            FakePoint(self.bounds[2], self.bounds[1]),
            FakePoint(self.bounds[2], self.bounds[3]),
            FakePoint(self.bounds[0], self.bounds[3]),
        ]

    def move_by(self, dx, dy):
        x0, y0, x1, y1 = self.bounds
        self.set_bounds((x0 + dx, y0 + dy, x1 + dx, y1 + dy))

    def set_points_raw(self, points):
        self.points = [FakePoint(x, y) for x, y in points]


def make_shape(
    shape_id,
    label="A",
    bounds=(0, 0, 10, 10),
    shape_type="rectangle",
):
    return FakeShape(
        xanylabeling_shape_id=shape_id,
        label=label,
        bounds=bounds,
        shape_type=shape_type,
    )


def make_config(
    batches=(("A/B", ("A", "B")),),
    rules=None,
    columns=2,
    rows=2,
    overlap=0.2,
):
    rule_map = {}
    for label, box_rule, note in rules or ():
        rule_map[label] = LabelRule(
            label=label, box_rule=box_rule, note=note
        )
    return ReviewConfig(
        batches=tuple(
            BatchDefinition(name=name, labels=tuple(labels))
            for name, labels in batches
        ),
        rules=ReviewRules(rules=rule_map),
        coverage=CoverageSettings(
            columns=columns, rows=rows, overlap=overlap
        ),
    )
