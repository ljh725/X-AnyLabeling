#!/usr/bin/env python3
"""Generate the synthetic dense-review sample set.

The script draws licence-free "person-like" figures on a plain background
with Pillow, writes one PNG plus one X-AnyLabeling label JSON per scene, and
records the expected review outcome in ``manifest.json`` and ``README.md``.
It uses no network access, no external assets and no real annotation data.

Every scene is built from fixed coordinates and a fixed drawing order, so
rendering the same scene twice yields byte-identical files for one Pillow
version.  No timestamps, EXIF tags or clock-derived seeds are written.

Usage::

    python scripts/generate_dense_review_samples.py
    python scripts/generate_dense_review_samples.py --output DIR --force
    python scripts/generate_dense_review_samples.py --check
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from PIL import Image, ImageDraw

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "samples" / "dense_review"
GENERATOR_PATH = "scripts/generate_dense_review_samples.py"
MANIFEST_SCHEMA = "xanylabeling.dense_review.samples/1"

IMAGE_WIDTH = 1280
IMAGE_HEIGHT = 720
SUPERSAMPLE = 2
BACKGROUND_COLOR = (246, 245, 241)
PROP_COLOR = (150, 148, 142)
LABEL_FORMAT_VERSION = "4.2.1"
COVERAGE = (4, 3, 0.15)
ALL_BATCHES = (
    ("A/B", ("A", "B")),
    ("C/D", ("C", "D")),
    ("E/F", ("E", "F")),
)
LABEL_COLORS = {
    "A": (214, 69, 65),
    "B": (66, 133, 244),
    "C": (52, 168, 83),
    "D": (247, 181, 41),
    "E": (150, 96, 191),
    "F": (240, 133, 60),
}
BOX_RULE_LABELS = {
    "visible": "可见框",
    "full": "完整框",
    "unknown": "未知",
}
SHAPE_TYPE_LABELS = {
    "rectangle": "矩形",
    "polygon": "多边形",
}


class SampleOutputError(RuntimeError):
    """Raised when the output directory cannot be written safely."""


@dataclass(frozen=True)
class SampleObject:
    """One annotated object plus the metadata used for the manifest."""

    shape_id: str
    label: str
    bounds: tuple[int, int, int, int] = ()
    polygon: tuple[tuple[int, int], ...] = ()
    shape_type: str = "rectangle"
    truth_label: str = ""
    difficult: bool = False
    tags: tuple[str, ...] = ()
    note: str = ""

    def points(self) -> list[list[int]]:
        if self.shape_type == "polygon":
            return [[x, y] for x, y in self.polygon]
        left, top, right, bottom = self.bounds
        return [[left, top], [right, top], [right, bottom], [left, bottom]]

    def bbox(self) -> tuple[int, int, int, int]:
        points = self.points()
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        return (min(xs), min(ys), max(xs), max(ys))


def _draw_nothing(
    draw: ImageDraw.ImageDraw,
    scale: float,
    lookup: Mapping[str, SampleObject],
) -> None:
    """Leave the plain background untouched."""


@dataclass(frozen=True)
class Scene:
    """One sample scene: its objects, suggested review config and text."""

    key: str
    title: str
    purpose: str
    objects: tuple[SampleObject, ...]
    batches: tuple[tuple[str, tuple[str, ...]], ...]
    box_rules: Mapping[str, str]
    expected: Mapping[str, Any]
    tasks: Mapping[str, str]
    coverage: tuple[int, int, float] = COVERAGE
    draw: Callable[
        [ImageDraw.ImageDraw, float, Mapping[str, SampleObject]], None
    ] = _draw_nothing


# --------------------------------------------------------------------------
# Drawing primitives
# --------------------------------------------------------------------------


def _scaled(values: Iterable[float], scale: float) -> list[float]:
    return [value * scale for value in values]


def _draw_ellipse(
    draw: ImageDraw.ImageDraw,
    bounds: Sequence[float],
    color: tuple[int, int, int],
    scale: float,
) -> None:
    draw.ellipse(_scaled(bounds, scale), fill=color)


def _draw_rectangle(
    draw: ImageDraw.ImageDraw,
    bounds: Sequence[float],
    color: tuple[int, int, int],
    scale: float,
) -> None:
    draw.rectangle(_scaled(bounds, scale), fill=color)


def _draw_person(
    draw: ImageDraw.ImageDraw,
    bounds: tuple[int, int, int, int],
    color: tuple[int, int, int],
    scale: float,
    arm: tuple[str, int] | None = None,
) -> None:
    """Draw one synthetic standing figure inside ``bounds``.

    ``arm`` optionally adds an outstretched arm that reaches ``length`` pixels
    beyond the annotated box, which is the evidence the clipped-arm scene
    needs outside its boxes.
    """
    left, top, right, bottom = bounds
    width = right - left
    height = bottom - top
    middle = left + width / 2.0

    head_half = width * 0.24
    head_height = height * 0.19
    head_top = top + height * 0.02
    _draw_ellipse(
        draw,
        (
            middle - head_half,
            head_top,
            middle + head_half,
            head_top + head_height,
        ),
        color,
        scale,
    )
    torso_top = head_top + head_height
    torso_bottom = top + height * 0.58
    _draw_rectangle(
        draw,
        (
            middle - width * 0.27,
            torso_top,
            middle + width * 0.27,
            torso_bottom,
        ),
        color,
        scale,
    )
    _draw_rectangle(
        draw,
        (
            middle - width * 0.23,
            torso_bottom - 1,
            middle - width * 0.04,
            bottom,
        ),
        color,
        scale,
    )
    _draw_rectangle(
        draw,
        (
            middle + width * 0.04,
            torso_bottom - 1,
            middle + width * 0.23,
            bottom,
        ),
        color,
        scale,
    )
    shoulder = top + height * 0.25
    thickness = max(2.0, height * 0.045)
    _draw_rectangle(
        draw,
        (left, shoulder, middle - width * 0.26, shoulder + thickness),
        color,
        scale,
    )
    _draw_rectangle(
        draw,
        (middle + width * 0.26, shoulder, right, shoulder + thickness),
        color,
        scale,
    )
    if arm is None:
        return
    side, length = arm
    if side == "right":
        start = middle + width * 0.24
        end = right + length
    else:
        start = middle - width * 0.24
        end = left - length
    _draw_rectangle(
        draw,
        (min(start, end), shoulder, max(start, end), shoulder + thickness),
        color,
        scale,
    )
    radius = thickness * 1.1
    center_y = shoulder + thickness / 2.0
    _draw_ellipse(
        draw,
        (end - radius, center_y - radius, end + radius, center_y + radius),
        color,
        scale,
    )


def _draw_people(
    draw: ImageDraw.ImageDraw,
    scale: float,
    lookup: Mapping[str, SampleObject],
    shape_ids: Iterable[str],
    arms: Mapping[str, tuple[str, int]] | None = None,
) -> None:
    for shape_id in shape_ids:
        item = lookup[shape_id]
        _draw_person(
            draw,
            item.bounds,
            LABEL_COLORS[item.label],
            scale,
            arm=(arms or {}).get(shape_id),
        )


def _draw_polygon(
    draw: ImageDraw.ImageDraw,
    points: Sequence[Sequence[int]],
    color: tuple[int, int, int],
    scale: float,
) -> None:
    flattened: list[float] = []
    for point in points:
        flattened.extend((point[0], point[1]))
    draw.polygon(_scaled(flattened, scale), fill=color)


# --------------------------------------------------------------------------
# Scene definitions
# --------------------------------------------------------------------------


def _scene_dense_30_six_classes() -> Scene:
    labels = ("A", "B", "C", "D", "E", "F")
    objects = []
    for index in range(30):
        row, column = divmod(index, 10)
        left = 20 + column * 124
        top = 20 + row * 232
        objects.append(
            SampleObject(
                shape_id=f"d30-{index + 1:03d}",
                label=labels[index % 6],
                bounds=(left, top, left + 130, top + 210),
                tags=("dense",),
                note="与左右相邻框重叠 6 像素",
            )
        )
    scene_objects = tuple(objects)

    def draw(handle, scale, lookup):
        _draw_people(
            handle,
            scale,
            lookup,
            [item.shape_id for item in scene_objects],
        )

    return Scene(
        key="dense_30_six_classes",
        title="30 个对象 / 6 类密集图",
        purpose="密集相邻对象的类别判读、批次导航与性能对照",
        objects=scene_objects,
        batches=ALL_BATCHES,
        box_rules={label: "visible" for label in labels},
        expected={
            "outcome": "complete",
            "object_complete": True,
            "requires_object_edits": {"category": 0, "geometry": 0},
            "requires_coverage_regions": 12,
            "outcome_when_difficult": "pending",
            "summary": (
                "30 个矩形全部正确；A/B、C/D、E/F 三批各 10 个一次确认，"
                "再完成 4×3 查漏区域后流程完成。"
            ),
            "steps": (
                "配置批次 A/B、C/D、E/F，框规则按“可见框”。",
                "逐批查看卡片与主画布，确认 30 个矩形没有错误类别或错框。",
                "依次点击“完成本批并进入下一批”，每批确认 10 个对象。",
                "进入查漏，按 4×3 网格（重叠 0.15）逐区确认。",
            ),
            "alternatives": [],
        },
        tasks={
            "1.3": "30 对象 6 类密集样本",
            "10.1": "冷/暖缓存 GUI 对照与拖框基线",
            "10.2": "性能门槛的密集图场景",
            "10.3": "卡片缓存峰值与连续切图",
            "10.4": "两人对照的密集难度组",
            "10.5": "质量抽查（本图标注全对）",
        },
        draw=draw,
    )


def _scene_all_correct_12() -> Scene:
    labels = ("A", "B")
    objects = []
    for index in range(12):
        row, column = divmod(index, 4)
        left = 60 + column * 300
        top = 40 + row * 230
        objects.append(
            SampleObject(
                shape_id=f"ok12-{index + 1:03d}",
                label=labels[index % 2],
                bounds=(left, top, left + 220, top + 190),
                note="类别与框均正确",
            )
        )

    def draw(handle, scale, lookup):
        _draw_people(
            handle,
            scale,
            lookup,
            [f"ok12-{index + 1:03d}" for index in range(12)],
        )

    return Scene(
        key="all_correct_12",
        title="12 个对象全部正确的单批图",
        purpose="验证“全正确批次一次确认”的低成本路径",
        objects=tuple(objects),
        batches=(("A/B", ("A", "B")),),
        box_rules={"A": "visible", "B": "visible"},
        expected={
            "outcome": "complete",
            "object_complete": True,
            "requires_object_edits": {"category": 0, "geometry": 0},
            "requires_coverage_regions": 12,
            "outcome_when_difficult": "pending",
            "summary": (
                "12 个矩形全部正确且同批；一次批次确认即可确认全部对象，"
                "无需逐卡点击或逐项打勾。"
            ),
            "steps": (
                "配置批次 A/B（12 个成员），框规则按“可见框”。",
                "不做任何编辑，直接点击"
                "“完成本批并进入下一批（确认 12，保留 0）”。",
                "完成 4×3 查漏区域。",
            ),
            "alternatives": [],
        },
        tasks={
            "1.3": "全正确批次的“一次确认”样本",
            "7.1": "12 对象批次一次确认",
            "7.2": "确认范围与屏外成员提示",
            "10.2": "暖缓存切换与确认操作的耗时对照",
            "10.4": "两人对照的低难度组",
            "10.5": "质量抽查（无错可改时的误操作率）",
        },
        draw=draw,
    )


def _scene_small_and_occluded() -> Scene:
    objects: list[SampleObject] = []
    cluster_one = ("A", "B", "A", "B", "C")
    for index, label in enumerate(cluster_one):
        left = 40 + index * 70
        objects.append(
            SampleObject(
                shape_id=f"soc-{len(objects) + 1:03d}",
                label=label,
                bounds=(left, 60, left + 130, 390),
                difficult=index == 0,
                tags=("dense", "occluded"),
                note="相邻框重叠约 46%，越靠左被遮挡越多",
            )
        )
    cluster_two = ("A", "B", "C", "C", "C")
    for index, label in enumerate(cluster_two):
        left = 500 + index * 46
        objects.append(
            SampleObject(
                shape_id=f"soc-{len(objects) + 1:03d}",
                label=label,
                bounds=(left, 330, left + 150, 710),
                difficult=index < 2,
                tags=("dense", "occluded"),
                note="相邻框重叠约 69%，soc-006/007 仅露出局部",
            )
        )
    small = (
        (900, 80, 26, 60),
        (980, 150, 30, 68),
        (1060, 60, 24, 54),
        (1140, 180, 32, 72),
        (900, 300, 28, 64),
        (60, 480, 30, 70),
        (180, 560, 26, 58),
        (300, 470, 34, 76),
    )
    small_labels = ("A", "A", "B", "B", "A", "B", "A", "B")
    for index, (left, top, width, height) in enumerate(small):
        objects.append(
            SampleObject(
                shape_id=f"soc-{len(objects) + 1:03d}",
                label=small_labels[index],
                bounds=(left, top, left + width, top + height),
                tags=("small",),
                note=f"{width}×{height} 像素小目标",
            )
        )
    scene_objects = tuple(objects)

    def draw(handle, scale, lookup):
        _draw_people(
            handle,
            scale,
            lookup,
            [item.shape_id for item in scene_objects],
        )

    return Scene(
        key="small_and_occluded",
        title="小目标与遮挡",
        purpose="验证小目标放大、上下文裁切与高度遮挡下的证据判断",
        objects=scene_objects,
        batches=(("A/B", ("A", "B")), ("C", ("C",))),
        box_rules={"A": "visible", "B": "visible", "C": "full"},
        expected={
            "outcome": "complete",
            "object_complete": True,
            "requires_object_edits": {"category": 0, "geometry": 0},
            "requires_coverage_regions": 12,
            "outcome_when_difficult": "pending",
            "summary": (
                "18 个矩形标注均正确；难点是证据：8 个小目标与两处密集"
                "遮挡需要放大和上下文。允许把 soc-001、soc-006、soc-007 "
                "标为疑难，标记后流程保持待审。"
            ),
            "steps": (
                "配置批次 A/B（14 个）与 C（4 个）；A/B 按可见框、"
                "C 按完整框。",
                "用卡片上下文与画布放大检查 soc-011…soc-018 这 8 个小目标。",
                "检查 soc-001…soc-010 两处重叠，判断遮挡是否影响类别与框。",
                "确认批次并完成 4×3 查漏区域。",
            ),
            "alternatives": (
                {
                    "when": "把高度遮挡对象标为疑难而不确认",
                    "outcome": "pending",
                    "summary": "流程保持待审，直到解除疑难并重新确认。",
                },
            ),
        },
        tasks={
            "1.3": "小目标与遮挡样本",
            "5.2": "卡片上下文与贴边/遮挡的证据查看",
            "6.1": "小目标与相邻近似尺寸目标的倍率连续性",
            "10.3": "小目标缩略图与缓存开销",
            "10.5": "质量复核：遮挡导致的漏标/错标",
        },
        draw=draw,
    )


def _scene_clipped_arm() -> Scene:
    specs = (
        ("arm-001", "A", (60, 50, 150, 290), ("right", 110)),
        ("arm-002", "B", (480, 50, 570, 290), ("right", 110)),
        ("arm-003", "A", (60, 380, 150, 620), ("right", 110)),
        ("arm-004", "B", (480, 380, 570, 620), ("right", 110)),
        ("arm-005", "A", (900, 50, 990, 290), ("right", 390)),
        ("arm-006", "B", (900, 380, 990, 620), ("left", 160)),
    )
    objects = []
    arms = {}
    for shape_id, label, bounds, arm in specs:
        arms[shape_id] = arm
        tags = ("clipped", "edge") if shape_id == "arm-005" else ("clipped",)
        objects.append(
            SampleObject(
                shape_id=shape_id,
                label=label,
                bounds=bounds,
                tags=tags,
                note=(
                    "手臂伸出图像右边界，完整范围不可知"
                    if shape_id == "arm-005"
                    else "框截断可见手臂，需要拖边扩大"
                ),
            )
        )
    scene_objects = tuple(objects)

    def draw(handle, scale, lookup):
        _draw_people(
            handle,
            scale,
            lookup,
            [item.shape_id for item in scene_objects],
            arms=arms,
        )
        # A foreground prop hides the middle of arm-006's outstretched arm.
        _draw_rectangle(handle, (800, 420, 870, 560), PROP_COLOR, scale)

    return Scene(
        key="clipped_arm",
        title="框截掉手臂（可见框 / 完整框规则）",
        purpose="验证框外肢体证据、拖边扩框与规则差异判定",
        objects=scene_objects,
        batches=(("A/B", ("A", "B")),),
        box_rules={"A": "full", "B": "visible"},
        expected={
            "outcome": "complete",
            "object_complete": True,
            "requires_object_edits": {"category": 0, "geometry": 5},
            "requires_coverage_regions": 12,
            "outcome_when_difficult": "pending",
            "summary": (
                "6 个矩形都截断可见手臂：arm-001…arm-004、arm-006 需要"
                "拖边扩框，扩框后已确认状态失效需重新确认；arm-005 的"
                "手臂伸出图像右边界。"
            ),
            "steps": (
                "配置批次 A/B（6 个）；A 按完整框、B 按可见框。",
                "用卡片上下文查看每个框外手臂，确认手臂像素在框外可见。",
                "拖边扩大 arm-001…arm-004、arm-006 到包含可见手臂；"
                "编辑后类别/框确认失效，在批次确认时重新确认。",
                "arm-005 按可见框扩到图像边界；若按完整框判定完整手臂"
                "不可知，可标记疑难。",
                "确认本批并完成 4×3 查漏区域。",
            ),
            "alternatives": (
                {
                    "when": "arm-005 按完整框规则标记为疑难",
                    "outcome": "pending",
                    "summary": "流程保持待审，直到解除疑难并重新确认。",
                },
            ),
        },
        tasks={
            "1.3": "框截掉手臂样本",
            "5.2": "截断/贴边对象的上下文与倍率",
            "6.3": "拖边扩框与当前对象保持",
            "10.4": "两人对照的中等难度组",
            "10.5": "质量复核：漏扩框与规则差异判定",
        },
        draw=draw,
    )


def _scene_misclassified_third_batch() -> Scene:
    given = (
        "A",
        "B",
        "A",
        "B",
        "A",
        "B",
        "C",
        "D",
        "C",
        "D",
        "C",
        "D",
        "F",
        "F",
        "E",
        "F",
        "E",
        "E",
        "C",
    )
    truth = {
        12: "E",
        13: "E",
        14: "F",
        15: "E",
        16: "F",
        17: "F",
        18: "F",
    }
    prefix = "m3"
    objects = []
    for index, label in enumerate(given):
        row, column = divmod(index, 5)
        left = 20 + column * 250
        top = 15 + row * 172
        actual = truth.get(index, label)
        tags = ("misclassified",)
        note = "第三批系统性错分：真值 %s" % actual
        if index == 18:
            tags = ("misclassified", "cross_batch")
            note = "跨批错分：真值 F，预标注落在 C/D 批"
        objects.append(
            SampleObject(
                shape_id=f"{prefix}-{index + 1:03d}",
                label=label,
                bounds=(left, top, left + 180, top + 140),
                truth_label=actual,
                tags=tags,
                note=note,
            )
        )
    scene_objects = tuple(objects)

    def draw(handle, scale, lookup):
        _draw_people(
            handle,
            scale,
            lookup,
            [item.shape_id for item in scene_objects],
        )

    return Scene(
        key="misclassified_third_batch",
        title="第三批系统性错分",
        purpose="验证批内改类、跨批改类不跳位与错误批次计数",
        objects=scene_objects,
        batches=ALL_BATCHES,
        box_rules={
            "A": "visible",
            "B": "visible",
            "C": "visible",
            "D": "visible",
            "E": "visible",
            "F": "visible",
        },
        expected={
            "outcome": "complete",
            "object_complete": True,
            "requires_object_edits": {"category": 6, "geometry": 0},
            "requires_coverage_regions": 12,
            "outcome_when_difficult": "pending",
            "summary": (
                "19 个矩形；第三批（E/F）6 个对象全部标成同类批次中的"
                "另一类，需要 6 次数字键改类；m3-019 真值 F 却标成 C，"
                "属于跨批错分。"
            ),
            "steps": (
                "配置批次 A/B（6 个）、C/D（7 个）、E/F（6 个）。",
                "确认 A/B 批。",
                "在 C/D 批中把 m3-019 从 C 改为 F：它仍留在 C/D 批"
                "成员中，不会跳回 E/F 批。",
                "在 E/F 批中把 m3-013…m3-018 改成真值类别（E↔F 互换）。",
                "确认剩余批次并完成 4×3 查漏区域。",
            ),
            "alternatives": (),
            "notes": (
                "若未改类就确认第三批，流程仍会显示“完成”——流程只记录"
                "用户声明，不自动判对；独立复核时需比对真值。",
            ),
        },
        tasks={
            "1.3": "错分到第三批的样本",
            "2.3": "改类不跳位、不重复进入另一批",
            "7.3": "批次成员数与当前类别统计的区分",
            "10.4": "两人对照的高难度组",
            "10.5": "质量复核：改类错误与漏改",
        },
        draw=draw,
    )


def _scene_empty() -> Scene:
    return Scene(
        key="empty",
        title="无对象图",
        purpose="验证无标注图片仍必须完成空间查漏",
        objects=(),
        batches=(("A/B", ("A", "B")),),
        box_rules={"A": "visible", "B": "visible"},
        expected={
            "outcome": "complete",
            "object_complete": True,
            "requires_object_edits": {"category": 0, "geometry": 0},
            "requires_coverage_regions": 12,
            "outcome_when_difficult": "pending",
            "summary": (
                "无对象；对象侧立即完成（0/0），但流程完成仍取决于 4×3"
                " 查漏区域是否全部完成，打开时为待审。"
            ),
            "steps": (
                "打开后确认对象计数为 0/0，不需要对象确认。",
                "仍要进入查漏，完成 4×3 个区域，否则流程保持待审。",
            ),
            "alternatives": (
                {
                    "when": "跳过查漏直接看结果",
                    "outcome": "pending",
                    "summary": "流程完成条件不满足，界面必须保持未完成。",
                },
            ),
        },
        tasks={
            "1.3": "无框图样本",
            "8.6": "空标注图片仍需查漏的完成条件",
            "10.4": "两人对照的空图巡查",
            "10.5": "质量复核：空图漏巡",
        },
    )


def _scene_mixed_shapes() -> Scene:
    rect_labels = ("A", "B", "A", "B", "A", "B", "C", "C", "C")
    objects = []
    for index, label in enumerate(rect_labels):
        row, column = divmod(index, 4)
        left = 50 + column * 300
        top = 40 + row * 230
        objects.append(
            SampleObject(
                shape_id=f"mix-{index + 1:03d}",
                label=label,
                bounds=(left, top, left + 220, top + 190),
                note="矩形，可按批次复核",
            )
        )
    objects.append(
        SampleObject(
            shape_id="mix-010",
            label="A",
            shape_type="polygon",
            polygon=((370, 660), (460, 520), (550, 660)),
            tags=("polygon",),
            note="三角形，首版不支持完整复核",
        )
    )
    objects.append(
        SampleObject(
            shape_id="mix-011",
            label="D",
            shape_type="polygon",
            polygon=(
                (760, 520),
                (830, 570),
                (805, 660),
                (715, 660),
                (690, 570),
            ),
            tags=("polygon",),
            note="五边形，首版不支持完整复核",
        )
    )
    scene_objects = tuple(objects)
    rectangles = tuple(
        item for item in scene_objects if item.shape_type == "rectangle"
    )
    polygons = tuple(
        item for item in scene_objects if item.shape_type == "polygon"
    )

    def draw(handle, scale, lookup):
        _draw_people(
            handle,
            scale,
            lookup,
            [item.shape_id for item in rectangles],
        )
        for item in polygons:
            _draw_polygon(
                handle, item.points(), LABEL_COLORS[item.label], scale
            )

    return Scene(
        key="mixed_shapes",
        title="矩形 + 非矩形混合图",
        purpose="验证首版只支持矩形时的“部分复核”路径",
        objects=scene_objects,
        batches=(("A/B", ("A", "B")), ("C/D", ("C", "D"))),
        box_rules={"A": "visible", "B": "visible", "C": "visible"},
        expected={
            "outcome": "partial",
            "object_complete": False,
            "requires_object_edits": {"category": 0, "geometry": 0},
            "requires_coverage_regions": 12,
            "outcome_when_difficult": "pending",
            "summary": (
                "9 个矩形 + 2 个多边形；矩形可按 A/B（6 个）、C/D（3 个）"
                "两批确认，两个多边形进入“其他待处理”，本流程只能部分"
                "复核，不会显示完整完成。"
            ),
            "steps": (
                "配置批次 A/B、C/D，框规则按“可见框”。",
                "确认 A/B 与 C/D 两个矩形批次。",
                "确认 mix-010、mix-011 仍为待处理，流程状态显示为部分/"
                "不支持完整复核。",
                "原有画布编辑与正式验收不受影响，可继续用旧流程处理。",
            ),
            "alternatives": (),
            "notes": (
                "不得用删除多边形换取完成状态；原有编辑与正式验收仍按"
                "旧流程独立可用。",
            ),
        },
        tasks={
            "1.3": "含非矩形的混合图样本",
            "4.5": "部分复核提示与原有编辑入口",
            "8.6": "不支持形状阻止全流程完成",
            "10.5": "质量复核：非矩形对象的处理",
        },
        draw=draw,
    )


SCENES: tuple[Scene, ...] = (
    _scene_dense_30_six_classes(),
    _scene_all_correct_12(),
    _scene_small_and_occluded(),
    _scene_clipped_arm(),
    _scene_misclassified_third_batch(),
    _scene_empty(),
    _scene_mixed_shapes(),
)


# --------------------------------------------------------------------------
# Serialization
# --------------------------------------------------------------------------


def _encode_json(value: Any) -> bytes:
    text = json.dumps(value, ensure_ascii=False, indent=2)
    return (text + "\n").encode("utf-8")


def _shape_payload(item: SampleObject) -> dict[str, Any]:
    return {
        "xanylabeling_shape_id": item.shape_id,
        "label": item.label,
        "score": None,
        "points": item.points(),
        "group_id": None,
        "description": "",
        "difficult": item.difficult,
        "shape_type": item.shape_type,
        "flags": {},
        "attributes": {},
        "kie_linking": [],
    }


def build_label_payload(scene: Scene) -> dict[str, Any]:
    """Return the X-AnyLabeling label JSON for one scene."""
    return {
        "version": LABEL_FORMAT_VERSION,
        "flags": {},
        "checked": False,
        "shapes": [_shape_payload(item) for item in scene.objects],
        "imagePath": f"{scene.key}.png",
        "imageData": None,
        "imageHeight": IMAGE_HEIGHT,
        "imageWidth": IMAGE_WIDTH,
    }


def _render_image(scene: Scene) -> bytes:
    size = (IMAGE_WIDTH * SUPERSAMPLE, IMAGE_HEIGHT * SUPERSAMPLE)
    image = Image.new("RGB", size, BACKGROUND_COLOR)
    handle = ImageDraw.Draw(image)
    lookup = {item.shape_id: item for item in scene.objects}
    scene.draw(handle, float(SUPERSAMPLE), lookup)
    image = image.resize((IMAGE_WIDTH, IMAGE_HEIGHT), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _label_distribution(objects: Iterable[SampleObject]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in objects:
        counts[item.label] = counts.get(item.label, 0) + 1
    return {label: counts[label] for label in sorted(counts)}


def _truth_distribution(objects: Iterable[SampleObject]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in objects:
        label = item.truth_label or item.label
        counts[label] = counts.get(label, 0) + 1
    return {label: counts[label] for label in sorted(counts)}


def _shape_type_distribution(
    objects: Iterable[SampleObject],
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in objects:
        counts[item.shape_type] = counts.get(item.shape_type, 0) + 1
    return {name: counts[name] for name in sorted(counts)}


def _batch_breakdown(scene: Scene) -> tuple[list[dict[str, Any]], int]:
    counts = {name: 0 for name, _labels in scene.batches}
    other = 0
    for item in scene.objects:
        if item.shape_type != "rectangle":
            other += 1
            continue
        name = next(
            (
                batch_name
                for batch_name, batch_labels in scene.batches
                if item.label in batch_labels
            ),
            None,
        )
        if name is None:
            other += 1
        else:
            counts[name] += 1
    batches = [
        {
            "name": name,
            "labels": list(labels),
            "member_count": counts[name],
        }
        for name, labels in scene.batches
    ]
    return batches, other


def _manifest_object(item: SampleObject) -> dict[str, Any]:
    left, top, right, bottom = item.bbox()
    entry: dict[str, Any] = {
        "id": item.shape_id,
        "label": item.label,
        "shape_type": item.shape_type,
        "bbox": [left, top, right, bottom],
    }
    if item.shape_type == "polygon":
        entry["points"] = item.points()
    if item.truth_label and item.truth_label != item.label:
        entry["truth_label"] = item.truth_label
    entry["difficult"] = item.difficult
    entry["tags"] = list(item.tags)
    if item.note:
        entry["note"] = item.note
    return entry


def _manifest_scene(scene: Scene) -> dict[str, Any]:
    batches, other = _batch_breakdown(scene)
    misclassified = [
        {
            "id": item.shape_id,
            "given": item.label,
            "truth": item.truth_label,
        }
        for item in scene.objects
        if item.truth_label and item.truth_label != item.label
    ]
    columns, rows, overlap = scene.coverage
    entry: dict[str, Any] = {
        "key": scene.key,
        "title": scene.title,
        "purpose": scene.purpose,
        "image": f"{scene.key}.png",
        "label": f"{scene.key}.json",
        "image_width": IMAGE_WIDTH,
        "image_height": IMAGE_HEIGHT,
        "object_count": len(scene.objects),
        "class_distribution": _label_distribution(scene.objects),
        "shape_type_distribution": _shape_type_distribution(scene.objects),
        "box_rules": dict(scene.box_rules),
        "coverage": {
            "columns": columns,
            "rows": rows,
            "overlap": overlap,
            "region_count": columns * rows,
        },
        "batches": batches,
        "other_pending_count": other,
        "objects": [_manifest_object(item) for item in scene.objects],
        "misclassified": misclassified,
        "expected": dict(scene.expected),
        "tasks": dict(scene.tasks),
    }
    if misclassified:
        entry["truth_class_distribution"] = _truth_distribution(scene.objects)
    return entry


def build_manifest() -> dict[str, Any]:
    """Return the machine-readable description of every sample scene."""
    return {
        "schema": MANIFEST_SCHEMA,
        "generator": GENERATOR_PATH,
        "label_format_version": LABEL_FORMAT_VERSION,
        "default_image_width": IMAGE_WIDTH,
        "default_image_height": IMAGE_HEIGHT,
        "deterministic": True,
        "license": "自制合成素材，无真人照片、无外部下载，可自由使用。",
        "object_id_scheme": (
            "每个场景固定前缀 + 三位序号，写入 xanylabeling_shape_id"
        ),
        "scenes": [_manifest_scene(scene) for scene in SCENES],
    }


# --------------------------------------------------------------------------
# README rendering
# --------------------------------------------------------------------------


def _format_id_ranges(shape_ids: Sequence[str]) -> str:
    """Compress ``prefix-001`` identifiers into a readable range list."""
    if not shape_ids:
        return "无"
    groups: dict[str, list[int]] = {}
    for shape_id in shape_ids:
        prefix, _, number = shape_id.rpartition("-")
        groups.setdefault(prefix, []).append(int(number))
    parts = []
    for prefix in sorted(groups):
        numbers = sorted(groups[prefix])
        start = previous = numbers[0]
        for number in numbers[1:] + [None]:
            if number is not None and number == previous + 1:
                previous = number
                continue
            if start == previous:
                parts.append(f"{prefix}-{start:03d}")
            else:
                parts.append(f"{prefix}-{start:03d}…{prefix}-{previous:03d}")
            if number is not None:
                start = previous = number
    return "、".join(parts)


def _ids_with_tag(scene: Mapping[str, Any], tag: str) -> list[str]:
    return [item["id"] for item in scene["objects"] if tag in item["tags"]]


def _shape_summary(distribution: Mapping[str, int]) -> str:
    order = sorted(distribution, key=lambda name: (name != "rectangle", name))
    parts = [
        f"{distribution[name]} 个{SHAPE_TYPE_LABELS.get(name, name)}"
        for name in order
    ]
    return "、".join(parts) or "无"


def _scene_readme(scene: Mapping[str, Any]) -> list[str]:
    columns = scene["coverage"]["columns"]
    rows = scene["coverage"]["rows"]
    overlap = scene["coverage"]["overlap"]
    expected = scene["expected"]
    batches = "；".join(
        f"{batch['name']} {batch['member_count']} 个"
        for batch in scene["batches"]
    )
    rules = "、".join(
        f"{label}={BOX_RULE_LABELS.get(rule, rule)}"
        for label, rule in scene["box_rules"].items()
    )
    distribution = "、".join(
        f"{label} {count}"
        for label, count in scene["class_distribution"].items()
    )
    shapes = _shape_summary(scene["shape_type_distribution"])
    object_line = (
        f"标注 `{scene['label']}`，{scene['object_count']} 个对象。"
        if not scene["object_count"]
        else f"标注 `{scene['label']}`，{scene['object_count']} 个对象"
        f"（{shapes}）。"
    )
    lines = [
        f"### `{scene['key']}` — {scene['title']}",
        "",
        f"- 图像：`{scene['image']}`，"
        f"{scene['image_width']}×{scene['image_height']}；{object_line}",
        f"- 类别分布：{distribution or '无'}。",
        f"- 建议批次：{batches}"
        + (
            f"；其他待处理 {scene['other_pending_count']} 个"
            if scene["other_pending_count"]
            else ""
        )
        + "。",
        f"- 框规则：{rules}。",
        f"- 查漏：{columns}×{rows} 网格，重叠 {overlap}。",
        f"- 用途：{scene['purpose']}。",
    ]
    special = []
    misclassified = scene["misclassified"]
    if misclassified:
        detail = "、".join(
            f"{item['id']}（{item['given']}→{item['truth']}）"
            for item in misclassified
        )
        special.append(f"类别错误：{detail}")
    clipped = _ids_with_tag(scene, "clipped")
    if clipped:
        special.append(f"框截断可见手臂 {_format_id_ranges(clipped)}")
    edge = _ids_with_tag(scene, "edge")
    if edge:
        special.append(f"贴图像边界 {_format_id_ranges(edge)}")
    polygons = _ids_with_tag(scene, "polygon")
    if polygons:
        special.append(f"非矩形对象 {_format_id_ranges(polygons)}")
    small = _ids_with_tag(scene, "small")
    if small:
        special.append(f"小目标 {_format_id_ranges(small)}")
    occluded = _ids_with_tag(scene, "occluded")
    if occluded:
        special.append(f"相互遮挡 {_format_id_ranges(occluded)}")
    difficult = [item["id"] for item in scene["objects"] if item["difficult"]]
    if difficult:
        special.append(
            f"旧 `difficult` 标记（仅 JSON 历史字段，不等于复核“疑难”）："
            f"{_format_id_ranges(difficult)}"
        )
    lines.append(
        "- 特殊对象：" + ("；".join(special) + "。" if special else "无。")
    )
    lines.append("- 人工步骤：")
    for index, step in enumerate(expected["steps"], start=1):
        lines.append(f"  {index}. {step}")
    lines.append(
        f"- 预期结果：**{expected['outcome']}** —— {expected['summary']}"
    )
    for alternative in expected.get("alternatives", ()):
        lines.append(
            f"- 例外：若{alternative['when']}，结果为 "
            f"**{alternative['outcome']}**：{alternative['summary']}"
        )
    for note in expected.get("notes", ()):
        lines.append(f"- 注意：{note}")
    lines.append(
        "- 对应任务："
        + "；".join(f"{task}（{use}）" for task, use in scene["tasks"].items())
        + "。"
    )
    lines.append("")
    return lines


def render_readme(manifest: Mapping[str, Any]) -> str:
    """Render the Chinese operator README from the manifest."""
    lines = [
        "# 密集复核人工样本（自制合成，可复现）",
        "",
        "本目录是 X-AnyLabeling 密集复核工作流"
        "（OpenSpec `add-dense-annotation-review-workflow` 任务 1.3）"
        "使用的**自制合成样本**。全部图像由 "
        "`scripts/generate_dense_review_samples.py` 用 Pillow 绘制："
        "纯色背景上的“人形”矩形与椭圆，不含真人照片、网络图片或第三方"
        "素材，可自由复制、修改和分发。",
        "",
        "> 用途：人工复核体验、交互回归与性能对照。不是训练数据，"
        "也不代表真实项目分布。写操作请使用临时副本。",
        "",
        "## 重新生成与校验",
        "",
        "```bash",
        "python scripts/generate_dense_review_samples.py"
        "            # 写入本目录",
        "python scripts/generate_dense_review_samples.py --force"
        "    # 覆盖已有文件",
        "python scripts/generate_dense_review_samples.py --output DIR"
        "   # 输出到其他目录",
        "python scripts/generate_dense_review_samples.py --check"
        "    # 只校验，不写文件",
        "```",
        "",
        "- 确定性：固定坐标与绘制顺序、无随机数、无时间戳与 EXIF；同一 "
        "Pillow 版本下重复运行字节一致。`--check` 重新渲染并逐字节比对，"
        "缺失、不一致或多余文件都会报告并以非零状态退出。",
        "- 自动化测试：`pytest tests/test_dense_review/test_samples.py`"
        "（重新生成到临时目录，校验计数、类别、对象 ID 与标注加载）。",
        "",
        "## 文件",
        "",
        "| 文件 | 说明 |",
        "| --- | --- |",
        "| `<场景>.png` | 合成图像 |",
        "| `<场景>.json` | X-AnyLabeling 标注；`imageData` 为 `null`，"
        "按 `imagePath` 相对路径读取图像 |",
        "| `manifest.json` | 机器可读清单：对象、ID、类别、特殊对象、"
        "预期结果 |",
        "| `README.md` | 本文件（由脚本生成，勿手工修改） |",
        "",
        "## 场景总览",
        "",
        f"共 {len(manifest['scenes'])} 个场景，每个场景 "
        f"{manifest['default_image_width']}×"
        f"{manifest['default_image_height']} 像素。",
        "",
        "| 场景 | 对象数 | 类别 | 形状 | 预期结果 | 主要用途 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for scene in manifest["scenes"]:
        distribution = "、".join(
            f"{label} {count}"
            for label, count in scene["class_distribution"].items()
        )
        shapes = _shape_summary(scene["shape_type_distribution"])
        lines.append(
            f"| `{scene['key']}` | {scene['object_count']} | "
            f"{distribution or '—'} | {shapes} | "
            f"{scene['expected']['outcome']} | {scene['purpose']} |"
        )
    lines.extend(
        [
            "",
            "预期结果的含义：`complete` 表示对象全部可确认，完成查漏后"
            "流程可完成；`partial` 表示首版不支持完整复核；任何对象标为"
            "“疑难”或“暂跳”都会让流程停在待审（`pending`）。",
            "",
            "## 场景详情",
            "",
        ]
    )
    for scene in manifest["scenes"]:
        lines.extend(_scene_readme(scene))
    lines.extend(
        [
            "## 与任务的对应关系",
            "",
            "| 任务 | 使用场景 | 记录内容 |",
            "| --- | --- | --- |",
        ]
    )
    task_rows = [
        (
            "1.3",
            "全部 7 个场景",
            "样本来源、对象数与 ID、可复现性",
        ),
        (
            "10.1",
            "`dense_30_six_classes`",
            "冷/暖缓存对照、卡片后台活动时拖框，至少三轮",
        ),
        (
            "10.2",
            "`dense_30_six_classes`、`all_correct_12`",
            "暖缓存切换 p95、GUI 心跳 p95、拖框回退比例",
        ),
        (
            "10.3",
            "`dense_30_six_classes`、`small_and_occluded`",
            "卡片缓存峰值、连续切图后的内存趋势",
        ),
        (
            "10.4",
            "`dense_30_six_classes`、`all_correct_12`、"
            "`clipped_arm`、`misclassified_third_batch`",
            "两位使用者交叉顺序各两轮：缩放/拖动/确认次数、耗时、疲劳自评",
        ),
        (
            "10.5",
            "`misclassified_third_batch`、`clipped_arm`、"
            "`small_and_occluded`、`empty`",
            "独立复核记录错类、框错误、漏标与分歧",
        ),
    ]
    for task, scenes, content in task_rows:
        lines.append(f"| {task} | {scenes} | {content} |")
    lines.extend(
        [
            "",
            "场景内部的 `tasks` 字段还标注了 2.3、4.5、5.2、6.1、6.3、"
            "7.1、7.2、7.3、8.6 等规格的人工检查点，见 `manifest.json`。",
            "",
            "## 约定与注意",
            "",
            "- 对象 ID 稳定并写入 `xanylabeling_shape_id`；脚本重跑不变，"
            "可直接用于验收记录。",
            "- `manifest.json` 中的 `batches`、`box_rules`、`coverage`、"
            "`expected` 是**建议配置与预期结果**，在应用里按此配置即可"
            "复现；配置不写入标注文件。",
            "- `misclassified` 段给出“预标注 → 真值”，只用于人工核对，"
            "不写入标注 JSON 的 `description`，避免提示泄漏。",
            "- 标注 JSON 保留 `score`、`group_id`、`difficult`、`flags`、"
            "`attributes`、`kie_linking` 等既有字段，未写入任何复核进度"
            "命名空间。",
            "",
        ]
    )
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Writing and verification
# --------------------------------------------------------------------------


def render_samples() -> dict[str, bytes]:
    """Render every generated file in memory, keyed by file name."""
    manifest = build_manifest()
    files: dict[str, bytes] = {}
    for scene in SCENES:
        files[f"{scene.key}.png"] = _render_image(scene)
        files[f"{scene.key}.json"] = _encode_json(build_label_payload(scene))
    files["manifest.json"] = _encode_json(manifest)
    files["README.md"] = render_readme(manifest).encode("utf-8")
    return files


def generate(output_dir: Path | str, *, force: bool = False) -> dict:
    """Write the sample set into ``output_dir`` and return the manifest."""
    target = Path(output_dir)
    files = render_samples()
    if not force:
        existing = [name for name in sorted(files) if (target / name).exists()]
        if existing:
            raise SampleOutputError(
                f"{target} 已存在样本文件（{existing[0]} 等 "
                f"{len(existing)} 个），如需覆盖请加 --force"
            )
    target.mkdir(parents=True, exist_ok=True)
    for name, payload in files.items():
        (target / name).write_bytes(payload)
    return json.loads(files["manifest.json"].decode("utf-8"))


def check(output_dir: Path | str) -> list[str]:
    """Compare the rendered bytes with an existing sample directory."""
    target = Path(output_dir)
    if not target.is_dir():
        return [f"目录不存在：{target}"]
    expected = render_samples()
    problems = []
    for name in sorted(expected):
        path = target / name
        if not path.is_file():
            problems.append(f"缺少文件：{name}")
        elif path.read_bytes() != expected[name]:
            problems.append(f"内容与生成结果不一致：{name}")
    existing = {path.name for path in target.iterdir() if path.is_file()}
    for name in sorted(existing - set(expected)):
        problems.append(f"多出未预期文件：{name}")
    return problems


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "生成密集复核工作流的自制合成样本"
            "（PNG + X-AnyLabeling 标注 + manifest + README）"
        )
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT),
        help="输出目录，默认 samples/dense_review",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="覆盖已存在的样本文件",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="只校验现有样本是否与生成结果逐字节一致，不写文件",
    )
    arguments = parser.parse_args(argv)

    if arguments.check:
        problems = check(Path(arguments.output))
        if problems:
            for problem in problems:
                print(f"[FAIL] {problem}", file=sys.stderr)
            return 1
        print(f"[OK] {arguments.output} 与生成结果一致")
        return 0

    try:
        manifest = generate(Path(arguments.output), force=arguments.force)
    except SampleOutputError as error:
        print(f"[FAIL] {error}", file=sys.stderr)
        return 1
    print(f"[OK] 已写入样本目录 {arguments.output}")
    for scene in manifest["scenes"]:
        classes = ", ".join(
            f"{label}×{count}"
            for label, count in scene["class_distribution"].items()
        )
        print(
            f"  - {scene['key']}: {scene['object_count']} 个对象"
            f"（{classes or '无'}），预期 {scene['expected']['outcome']}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
