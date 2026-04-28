"""将数据集标签可视化"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path

import cv2
from tqdm import tqdm

SUPPORTED_IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".bmp")


def do_work(dataset_dir, output_dir, split="train,val", label_dir="labels_cls2,labels_cls2_onfiled"):
    """
    dataset_dir: 数据集目录
    output_dir: 输出目录
    split: 数据集划分，逗号分隔
    label_dir: 标签目录名称，逗号分隔
    """

    dataset_dir = Path(dataset_dir)
    output_dir = Path(output_dir)

    # 逐个split处理
    splits = [item.strip() for item in split.split(",") if item.strip()]
    label_dir_names = [item.strip() for item in label_dir.split(",") if item.strip()]
    for split_name in splits:
        split_dir = dataset_dir / split_name
        images_dir = split_dir / "images"
        if not split_dir.exists() or not images_dir.exists():
            continue

        # 逐个标签目录处理
        for label_dir_name in label_dir_names:
            label_dir_path = split_dir / label_dir_name
            if not label_dir_path.exists():
                continue
            # 获取所有标签文件
            label_files = [label_file for label_file in label_dir_path.iterdir() if label_file.is_file() and label_file.suffix == ".txt"]
            if not label_files:
                continue
            output_images_dir = output_dir / dataset_dir.name / split_name / label_dir_name
            output_images_dir.mkdir(parents=True, exist_ok=True)
            # 读取标签和图片并可视化
            for label_file in label_files:
                image_stem = label_file.stem
                image_file = None
                for suffix in SUPPORTED_IMAGE_SUFFIXES:
                    candidate = images_dir / f"{image_stem}{suffix}"
                    if candidate.exists():
                        image_file = candidate
                        break
                if image_file is None:
                    continue
                image = cv2.imread(str(image_file))
                if image is None:
                    continue
                with open(str(label_file), "r") as f:
                    lines = f.readlines()
                for line in lines:
                    parts = line.strip().split()
                    if len(parts) < 5:
                        continue
                    cls_id, x_center, y_center, width, height = map(float, parts[:5])
                    x_center = int(x_center * image.shape[1])
                    y_center = int(y_center * image.shape[0])
                    width = int(width * image.shape[1])
                    height = int(height * image.shape[0])
                    if int(cls_id) == 0:
                        cv2.rectangle(image, (x_center - width // 2, y_center - height // 2), (x_center + width // 2, y_center + height // 2), (255, 0, 0), 2)
                        cv2.putText(image, str(int(cls_id)), (x_center + width//2+3, y_center - height//2-3), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 0, 0), 2)
                    else:
                        cv2.rectangle(image, (x_center - width // 2, y_center - height // 2), (x_center + width // 2, y_center + height // 2), (0, 255, 0), 2)
                        cv2.putText(image, str(int(cls_id)), (x_center + width//2+3, y_center - height//2-3), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
                output_image_file = output_images_dir / f"{image_stem}{image_file.suffix}"
                cv2.imwrite(str(output_image_file), image)
        

def draw_label(datasets_dir, output_dir, split="train,val", label_dir="labels_cls2,labels_cls2_onfiled"):
    """
    datasets_dir: 数据集根目录
    output_dir: 输出目录
    split: 数据集划分，逗号分隔， 如果是 all 则选择目录下所有文件夹
    label_dir: 标签目录名称，逗号分隔
    """
    datasets_path = Path(datasets_dir)
    output_dir = Path(output_dir)
    if split == "all":
        split = [p.name for p in datasets_path.iterdir() if p.is_dir()]
        split = ",".join(split)
        datasets = [datasets_path]
    else:
        if (datasets_path / 'train').exists() or (datasets_path / 'val').exists() or (datasets_path / 'test').exists() or (datasets_path / split.split(',')[0]).exists():
            datasets = [datasets_path]
        else:
            datasets = [dataset for dataset in datasets_path.iterdir() if dataset.is_dir() and ((dataset / 'train').exists() or (dataset / 'val').exists() or (dataset / 'test').exists())]
    if not datasets:
        raise ValueError("No datasets found")
    
    # 多线程处理
    tasks = partial(do_work, output_dir=output_dir, split=split, label_dir=label_dir)
    with ThreadPoolExecutor() as executor:
        list(tqdm(
            executor.map(tasks, datasets),
            total=len(datasets),
            desc="Processing datasets"
        ))

    
if __name__ =="__main__":
    parser = argparse.ArgumentParser(description="Draw labels on images")
    parser.add_argument("--datasets_dir", type=str, required=True, help="Path to datasets directory")
    parser.add_argument("--output_dir", type=str, required=True, help="Path to output directory")
    parser.add_argument("--split", type=str, default="train,val", help="Data splits to process, 'all' select all folder")
    parser.add_argument("--label_dir", type=str, default="labels_cls2,labels_cls2_onfiled", help="Label directories to process")
    args = parser.parse_args()
    draw_label(args.datasets_dir, args.output_dir, args.split, args.label_dir)

"""demo
python tools_py/dataset/dataset_vis.py \
    --datasets_dir /datasets \
    --output_dir /datasets_vis \
    --split train,val \
    --label_dir labels_cls2,labels_cls2_onfiled
"""

    