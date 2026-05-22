#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
可视化 YOLO detection / YOLO pose 数据集标签。

支持的数据集目录格式：
    dataset/train/images
    dataset/train/labels
    dataset/val/images
    dataset/val/labels
"""

from __future__ import annotations

import argparse
import concurrent.futures
import threading
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError as exc:
    raise ImportError("请先安装 Pillow：pip install pillow") from exc


IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp")
DEFAULT_DATASET_DIR = Path("datasets") / "cls3pose-yolov8pose-split"
DEFAULT_OUTPUT_DIR = Path("vis-cls3")
DEFAULT_SPLITS = ("train", "val")
BOX_COLORS = (
    (255, 64, 64),
    (64, 160, 255),
    (80, 210, 120),
    (255, 190, 64),
    (220, 100, 255),
    (64, 220, 220),
)
_WARN_LOCK = threading.Lock()


def warn(message: str) -> None:
    """统一输出警告，方便批量检查问题标签。"""
    with _WARN_LOCK:
        print(f"[WARN] {message}")


def find_image(images_dir: Path, stem: str) -> Optional[Path]:
    """根据标签文件名查找同名图片。"""
    for suffix in IMAGE_SUFFIXES:
        image_path = images_dir / f"{stem}{suffix}"
        if image_path.exists():
            return image_path
    return None


def parse_label_line(line: str, label_path: Path, line_number: int) -> Optional[List[float]]:
    """解析一行 YOLO 标签，格式异常时返回 None。"""
    parts = line.strip().split()
    if not parts:
        return None
    try:
        values = [float(part) for part in parts]
    except ValueError:
        warn(f"{label_path}:{line_number} 存在非数字字段，已跳过")
        return None
    if len(values) < 5:
        warn(f"{label_path}:{line_number} 字段数量少于 5，已跳过")
        return None
    return values


def label_kind(values: Sequence[float], task: str) -> str:
    """判断当前标签行按 detection 还是 pose 绘制。"""
    if task in {"detect", "pose"}:
        return task
    return "pose" if len(values) > 5 and (len(values) - 5) % 3 == 0 else "detect"


def yolo_box_to_xyxy(values: Sequence[float], image_w: int, image_h: int) -> Tuple[int, int, int, int]:
    """将 YOLO 归一化框转换为像素坐标。"""
    cx, cy, box_w, box_h = values[1:5]
    x1 = int(round((cx - box_w / 2) * image_w))
    y1 = int(round((cy - box_h / 2) * image_h))
    x2 = int(round((cx + box_w / 2) * image_w))
    y2 = int(round((cy + box_h / 2) * image_h))
    x1 = max(0, min(image_w - 1, x1))
    y1 = max(0, min(image_h - 1, y1))
    x2 = max(0, min(image_w - 1, x2))
    y2 = max(0, min(image_h - 1, y2))
    return x1, y1, x2, y2


def draw_box(
    draw: ImageDraw.ImageDraw,
    xyxy: Tuple[int, int, int, int],
    class_id: int,
    color: Tuple[int, int, int],
    line_width: int,
) -> None:
    """绘制检测框和类别 ID。"""
    x1, y1, x2, y2 = xyxy
    for offset in range(line_width):
        draw.rectangle((x1 - offset, y1 - offset, x2 + offset, y2 + offset), outline=color)
    label = str(class_id)
    text_x = x1
    text_y = max(0, y1 - 14)
    draw.rectangle((text_x, text_y, text_x + 8 + len(label) * 7, text_y + 13), fill=color)
    draw.text((text_x + 3, text_y), label, fill=(255, 255, 255), font=ImageFont.load_default())


def draw_keypoints(
    draw: ImageDraw.ImageDraw,
    values: Sequence[float],
    image_w: int,
    image_h: int,
    color: Tuple[int, int, int],
    radius: int,
) -> None:
    """绘制 YOLO pose 关键点；v=0 的点不绘制。"""
    keypoint_values = values[5:]
    for index in range(0, len(keypoint_values), 3):
        x, y, visibility = keypoint_values[index : index + 3]
        if int(visibility) <= 0:
            continue
        px = int(round(x * image_w))
        py = int(round(y * image_h))
        point_color = color if int(visibility) == 2 else (255, 255, 255)
        draw.ellipse((px - radius, py - radius, px + radius, py + radius), fill=point_color, outline=(0, 0, 0))


def visualize_one_image(
    image_path: Path,
    label_path: Path,
    output_path: Path,
    task: str,
    line_width: int,
    point_radius: int,
) -> bool:
    """可视化单张图片，返回是否成功导出。"""
    with Image.open(image_path) as image:
        canvas = image.convert("RGB")
    draw = ImageDraw.Draw(canvas)
    image_w, image_h = canvas.size

    if not label_path.exists():
        warn(f"{image_path.name} 缺少同名标签：{label_path}")
        return False

    lines = label_path.read_text(encoding="utf-8").splitlines()
    for line_number, line in enumerate(lines, start=1):
        values = parse_label_line(line, label_path, line_number)
        if values is None:
            continue
        class_id = int(values[0])
        color = BOX_COLORS[class_id % len(BOX_COLORS)]
        draw_box(draw, yolo_box_to_xyxy(values, image_w, image_h), class_id, color, line_width)
        if label_kind(values, task) == "pose":
            draw_keypoints(draw, values, image_w, image_h, color, point_radius)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path)
    return True


def visualize_split(args: argparse.Namespace, split: str) -> int:
    """可视化一个 split，返回成功导出的图片数量。"""
    images_dir = args.dataset / split / "images"
    labels_dir = args.dataset / split / "labels"
    if not images_dir.exists() or not labels_dir.exists():
        warn(f"{split} 缺少 images 或 labels 目录，已跳过")
        return 0

    image_paths = sorted(path for path in images_dir.iterdir() if path.suffix.lower() in IMAGE_SUFFIXES)
    if not image_paths:
        print(f"[{split}] 目录下无可视化图片")
        return 0

    tasks = []
    for image_path in image_paths:
        label_path = labels_dir / f"{image_path.stem}.txt"
        output_path = args.output / split / image_path.name
        tasks.append((image_path, label_path, output_path))

    count = 0
    workers = min(args.workers, len(tasks))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [
            executor.submit(
                visualize_one_image,
                image_path,
                label_path,
                output_path,
                args.task,
                args.line_width,
                args.point_radius,
            )
            for image_path, label_path, output_path in tasks
        ]
        for future in concurrent.futures.as_completed(futures):
            if future.result():
                count += 1

    print(f"[{split}] 导出 {count} 张可视化图片")
    return count


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(description="可视化 YOLO detection / YOLO pose 数据集")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=DEFAULT_DATASET_DIR,
        help=f"数据集根目录，默认：{DEFAULT_DATASET_DIR}",
    )
    parser.add_argument(
        "--splits",
        nargs="+",
        default=list(DEFAULT_SPLITS),
        help="需要可视化的 split，例如：--splits train val",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"可视化图片输出目录，默认：{DEFAULT_OUTPUT_DIR}",
    )
    parser.add_argument(
        "--task",
        choices=("auto", "detect", "pose"),
        default="auto",
        help="标签类型；auto 会根据每行字段数自动判断，默认：auto",
    )
    parser.add_argument(
        "--line-width",
        type=int,
        default=3,
        help="检测框线宽，默认：3",
    )
    parser.add_argument(
        "--point-radius",
        type=int,
        default=4,
        help="pose 关键点半径，默认：4",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="并行线程数，默认：4",
    )
    return parser.parse_args()


def main() -> None:
    """命令行入口。"""
    args = parse_args()
    total = 0
    for split in args.splits:
        total += visualize_split(args, split)
    print(f"完成：共导出 {total} 张图片，输出目录：{args.output}")


if __name__ == "__main__":
    main()


"""
demo
python .\visualize_yolo_dataset.py `
  --dataset .\datasets\cls3pose-yolov8pose-split `
  --splits train val `
  --output .\vis-cls3

python .\visualize_yolo_dataset.py `
  --dataset .\datasets\cls3pose-yolov8pose-split `
  --splits train val `
  --output .\vis-cls3 `
  --task pose

使用注意事项：
1. --dataset 目录下需要存在 train/images、train/labels 这类 split 子目录。
2. --splits 后面可传入一个或多个 split，例如 train val test。
3. --output 会按 split 创建子目录，例如 .\vis-cls3\train 和 .\vis-cls3\val。
4. --task auto 会自动判断 detection 或 pose；YOLO detection 每行 5 个字段，YOLO pose 每行大于 5 个字段且关键点部分按 x y v 三元组排列。
5. pose 可见性 v=0 的关键点不会绘制，v=1 会画白色点，v=2 会画彩色点。
"""
