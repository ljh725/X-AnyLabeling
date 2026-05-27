#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
按 train/val/test 划分 YOLOv8 Pose 数据集。

默认读取：
    datasets/cls3pose-yolov8pose/images
    datasets/cls3pose-yolov8pose/labels

默认输出结构：
    datasets/cls3pose-yolov8pose-split/train/images
    datasets/cls3pose-yolov8pose-split/train/labels
    datasets/cls3pose-yolov8pose-split/val/images
    datasets/cls3pose-yolov8pose-split/val/labels
    datasets/cls3pose-yolov8pose-split/test/images
    datasets/cls3pose-yolov8pose-split/test/labels
"""

from __future__ import annotations

import argparse
import random
import shutil
from pathlib import Path
from typing import Dict, List, Sequence, Tuple


IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp")
SPLIT_NAMES = ("train", "val", "test")
DEFAULT_DATASET_DIR = Path("datasets") / "cls3pose-yolov8pose"
DEFAULT_OUTPUT_DIR = Path("datasets") / "cls3pose-yolov8pose-split"


def parse_ratio(text: str) -> Tuple[float, float, float]:
    """解析 7:2:1 或 0.7:0.2:0.1 形式的比例。"""
    parts = text.replace(",", ":").split(":")
    if len(parts) != 3:
        raise ValueError("--ratio 必须包含三个数字，例如 7:2:1 或 8:2:0")

    ratio = tuple(float(part) for part in parts)
    if any(value < 0 for value in ratio):
        raise ValueError("--ratio 不能包含负数")
    if sum(ratio) <= 0:
        raise ValueError("--ratio 三项之和必须大于 0")
    return ratio  # type: ignore[return-value]


def collect_images(images_dir: Path) -> List[Path]:
    """收集图片文件。"""
    images = [
        path
        for path in images_dir.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    ]
    if not images:
        raise FileNotFoundError(f"未在 {images_dir} 找到图片文件")
    return sorted(images)


def find_label(image_path: Path, labels_dir: Path) -> Path:
    """根据图片文件名查找同名 txt 标签。"""
    return labels_dir / f"{image_path.stem}.txt"


def split_counts(total: int, ratio: Sequence[float]) -> Tuple[int, int, int]:
    """根据样本总数和比例计算 train/val/test 数量。"""
    train_ratio, val_ratio, test_ratio = ratio
    ratio_sum = sum(ratio)

    train_count = int(round(total * train_ratio / ratio_sum))
    val_count = int(round(total * val_ratio / ratio_sum))
    if train_count + val_count > total:
        val_count = max(0, total - train_count)

    test_count = total - train_count - val_count
    if test_ratio == 0:
        train_count += test_count
        test_count = 0
    return train_count, val_count, test_count


def make_split_map(images: List[Path], ratio: Sequence[float], seed: int) -> Dict[str, List[Path]]:
    """随机打乱图片并划分到 train/val/test。"""
    shuffled = images[:]
    random.Random(seed).shuffle(shuffled)

    train_count, val_count, test_count = split_counts(len(shuffled), ratio)
    train_end = train_count
    val_end = train_count + val_count
    return {
        "train": shuffled[:train_end],
        "val": shuffled[train_end:val_end],
        "test": shuffled[val_end : val_end + test_count],
    }


def prepare_output_dirs(output_dir: Path, split_map: Dict[str, List[Path]]) -> None:
    """创建 train/images、train/labels 这类输出目录。"""
    for split, images in split_map.items():
        if not images:
            continue
        (output_dir / split / "images").mkdir(parents=True, exist_ok=True)
        (output_dir / split / "labels").mkdir(parents=True, exist_ok=True)


def transfer_file(src: Path, dst: Path, mode: str) -> None:
    """按 copy 或 move 处理文件。"""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if mode == "copy":
        shutil.copy2(src, dst)
    else:
        shutil.move(str(src), str(dst))


def check_labels(images: Sequence[Path], labels_dir: Path, allow_empty_label: bool) -> None:
    """提前检查标签是否缺失，避免移动到一半才失败。"""
    missing_labels = [find_label(image, labels_dir) for image in images if not find_label(image, labels_dir).exists()]
    if missing_labels and not allow_empty_label:
        examples = "\n".join(str(path) for path in missing_labels[:10])
        raise FileNotFoundError(
            f"发现 {len(missing_labels)} 个图片缺少同名标签。可修复标签，或添加 --allow-empty-label。\n{examples}"
        )


def split_dataset(args: argparse.Namespace) -> None:
    """执行数据集划分。"""
    images_dir = args.images or args.dataset / "images"
    labels_dir = args.labels or args.dataset / "labels"
    ratio = parse_ratio(args.ratio)

    images = collect_images(images_dir)
    check_labels(images, labels_dir, args.allow_empty_label)

    split_map = make_split_map(images, ratio, args.seed)
    prepare_output_dirs(args.output, split_map)

    for split, split_images in split_map.items():
        if not split_images:
            continue
        for image_path in split_images:
            label_path = find_label(image_path, labels_dir)
            image_dst = args.output / split / "images" / image_path.name
            label_dst = args.output / split / "labels" / f"{image_path.stem}.txt"

            transfer_file(image_path, image_dst, args.mode)
            if label_path.exists():
                transfer_file(label_path, label_dst, args.mode)
            elif args.allow_empty_label:
                label_dst.write_text("", encoding="utf-8")

        print(f"[{split}] {len(split_images)} 张图片")

    print(f"完成：mode={args.mode}，ratio={args.ratio}，输出目录={args.output}")


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(description="划分 YOLOv8 Pose 数据集")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=DEFAULT_DATASET_DIR,
        help=f"待划分的数据集根目录，默认：{DEFAULT_DATASET_DIR}",
    )
    parser.add_argument(
        "--images",
        type=Path,
        default=None,
        help="图片目录；不传时使用 dataset/images",
    )
    parser.add_argument(
        "--labels",
        type=Path,
        default=None,
        help="标签目录；不传时使用 dataset/labels",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"划分后的输出目录，默认：{DEFAULT_OUTPUT_DIR}",
    )
    parser.add_argument(
        "--ratio",
        type=str,
        default="7:2:1",
        help="train:val:test 比例，默认 7:2:1；例如 8:2:0 表示不生成 test",
    )
    parser.add_argument(
        "--mode",
        choices=("copy", "move"),
        default="copy",
        help="划分方式：copy 复制，move 移动；默认 copy",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="随机种子，默认：42，用于保证划分结果可复现",
    )
    parser.add_argument(
        "--allow-empty-label",
        action="store_true",
        help="允许图片没有同名 txt 标签；缺失时会生成空标签",
    )
    return parser.parse_args()


def main() -> None:
    """命令行入口。"""
    args = parse_args()
    split_dataset(args)


if __name__ == "__main__":
    main()


"""demo
python .\split_yolov8pose_dataset.py `
  --dataset datasets\cls3pose-tmp `
  --output .\datasets\cls3pose-yolov8pose-split `
  --ratio 8:2:0 `
  --mode copy

python .\split_yolov8pose_dataset.py `
  --dataset .\datasets\cls3pose-yolov8pose `
  --output .\datasets\cls3pose-yolov8pose-split `
  --ratio 7:2:1 `
  --mode copy

使用注意事项：
1. --dataset 目录下默认需要存在 images 和 labels 两个子目录。
2. --images 和 --labels 可分别指定图片目录和标签目录；不传时使用 --dataset 下的 images/labels。
3. 输出目录格式为 train/images、train/labels、val/images、val/labels、test/images、test/labels。
4. --ratio 使用 train:val:test 格式，默认 7:2:1；例如 8:2:0 表示不生成 test。
5. --mode copy 会保留原始数据，--mode move 会移动原始图片和标签。
6. 默认要求每张图片都有同名 txt 标签；如需允许空标签，可添加 --allow-empty-label。
"""
