"""Capture real offscreen screenshots of the dense-review workspace.

The images are produced by rendering the actual widgets of this checkout with
the Qt ``offscreen`` platform, so they are runtime screenshots rather than
design mockups. They feed the user guide in ``docs/zh_cn/dense_review.md``.

Usage::

    QT_QPA_PLATFORM=offscreen python scripts/capture_dense_review_screenshots.py
"""

from __future__ import annotations

import json
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
for _path in (REPO_ROOT, SCRIPT_DIR):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from PIL import Image  # noqa: E402
from PyQt6 import QtWidgets  # noqa: E402

from anylabeling.resources import resources  # noqa: E402,F401
from anylabeling.views.mainwindow import MainWindow  # noqa: E402
from dev_isolation import IsolatedConfig  # noqa: E402

OUTPUT_DIR = os.path.join(REPO_ROOT, "images", "dense_review")
WORK_DIR = os.path.join(REPO_ROOT, ".tmp", "screenshots")

CLASSES = (
    "行人",
    "骑行者",
    "施工人员",
    "儿童",
    "工作人员",
    "运动人员",
)
LONG_CLASSES = (
    "画面左侧正在搬运货物的成年男性工作人员",
    "画面右侧骑行电动车的配送人员",
    "道路中央指挥交通的执勤人员",
    "画面后方等待过街的成年女性行人",
    "画面近处正在打电话的青年男性行人",
    "远处站立观察的儿童",
)


def _scene(objects=30, long_labels=False):
    """Build one deterministic dense scene and write image + annotation."""
    os.makedirs(WORK_DIR, exist_ok=True)
    width, height = 1280, 800
    image = Image.new("RGB", (width, height), (236, 238, 241))
    from PIL import ImageDraw

    draw = ImageDraw.Draw(image)
    draw.rectangle([0, 560, width, 800], fill=(214, 218, 222))
    labels = LONG_CLASSES if long_labels else CLASSES
    shapes = []
    columns = 6
    for index in range(objects):
        column = index % columns
        row = index // columns
        left = 40 + column * 200 + (row % 2) * 30
        top = 60 + row * 150
        box = [left, top, left + 120, top + 130]
        color = (
            90 + (index * 37) % 120,
            90 + (index * 53) % 120,
            90 + (index * 71) % 120,
        )
        draw.rounded_rectangle(box, radius=12, fill=color)
        draw.ellipse(
            [left + 35, top + 12, left + 85, top + 62],
            fill=(245, 220, 200),
        )
        shapes.append(
            {
                "label": labels[index % len(labels)],
                "shape_type": "rectangle",
                "points": [
                    [box[0], box[1]],
                    [box[2], box[1]],
                    [box[2], box[3]],
                    [box[0], box[3]],
                ],
                "xanylabeling_shape_id": f"shot-{index + 1:03d}",
            }
        )
    image_path = os.path.join(WORK_DIR, "scene.png")
    image.save(image_path)
    annotation = {
        "version": "4.2.1",
        "imageWidth": width,
        "imageHeight": height,
        "imagePath": "scene.png",
        "imageData": None,
        "shapes": shapes,
    }
    label_path = os.path.join(WORK_DIR, "scene.json")
    with open(label_path, "w", encoding="utf-8") as handle:
        json.dump(annotation, handle, ensure_ascii=False)
    return image_path


def _build_window(app, isolated):
    """Build the real main window on top of an isolated configuration."""
    config = isolated.config
    config.update(auto_save=False)
    window = MainWindow(app, config=config)
    window.resize(1680, 1020)
    window.show()
    app.processEvents()
    return window


def _grab(widget, name):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    path = os.path.join(OUTPUT_DIR, name)
    pixmap = widget.grab()
    pixmap.save(path)
    print(f"wrote {path} ({pixmap.width()}x{pixmap.height()})")


def main():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    app.setQuitOnLastWindowClosed(False)
    image_path = _scene(objects=30)
    isolated = IsolatedConfig(os.path.join(WORK_DIR, "config"))
    with isolated:
        window = _build_window(app, isolated)
        try:
            _capture(app, image_path, window)
        finally:
            _shutdown(app, window)


def _shutdown(app, window):
    """Close the window and review workspace even when a capture fails."""
    view = window.labeling_widget.view
    workspace = view.dense_review_workspace
    view.dirty = False
    if workspace is not None:
        try:
            workspace.close()
            workspace.shutdown()
        except Exception:  # noqa: BLE001 - best-effort teardown
            pass
    window.close()
    app.processEvents()


def _capture(app, image_path, window):
    view = window.labeling_widget.view
    if not view.load_file(image_path):
        raise SystemExit("failed to load the synthetic scene")
    view.open_dense_review()
    app.processEvents()
    workspace = view.dense_review_workspace

    _grab(workspace, "01-workspace.png")
    _grab(window, "02-main-window.png")

    workspace._complete_batch()
    app.processEvents()
    _grab(workspace, "03-after-batch-confirmation.png")

    workspace.tabs.setCurrentIndex(1)
    app.processEvents()
    # The button may open a confirmation dialog; build the plan through the
    # session API so the capture script stays non-interactive.
    session = view.dense_review_session
    if session is not None:
        session.ensure_coverage()
    workspace.refresh_all()
    app.processEvents()
    _grab(workspace, "04-spatial-review.png")
    workspace.tabs.setCurrentIndex(0)
    app.processEvents()

    # The button opens a reason dialog, so mark through the session API to keep
    # the capture script non-interactive.
    session = view.dense_review_session
    current = session.current_object() if session is not None else None
    if current is not None:
        session.mark_difficult(current.shape_id, ("category",), "看不清")
    workspace.refresh_all()
    app.processEvents()
    _grab(workspace, "05-difficult-state.png")

    # A narrow window with long Chinese class names is the layout stress case.
    for index, shape in enumerate(view.canvas.shapes):
        shape.label = LONG_CLASSES[index % len(LONG_CLASSES)]
    workspace.refresh_all()
    workspace.resize(900, 620)
    app.processEvents()
    _grab(workspace, "06-narrow-window.png")


if __name__ == "__main__":
    main()
