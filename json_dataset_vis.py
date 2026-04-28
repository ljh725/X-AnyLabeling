"""可视化 X-AnyLabeling JSON 格式标注"""
import argparse
import json
import random
from pathlib import Path

import cv2
import numpy as np
from tqdm import tqdm

SUPPORTED_IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".bmp", ".webp")


def get_color(label: str, color_map: dict) -> tuple:
    """为每个标签分配固定颜色。"""
    if label not in color_map:
        color_map[label] = (
            random.randint(50, 255),
            random.randint(50, 255),
            random.randint(50, 255),
        )
    return color_map[label]


def draw_shape(image, shape, color_map):
    """在图上绘制单个 shape。"""
    label = shape.get("label", "")
    shape_type = shape.get("shape_type", "")
    points = shape.get("points", [])
    color = get_color(label, color_map)

    if not points:
        return image

    pts = np.array(points, dtype=np.int32)

    if shape_type == "rectangle":
        if len(pts) == 4:
            # 四点矩形（X-AnyLabeling 标准格式）
            x_min, y_min = pts[:, 0].min(), pts[:, 1].min()
            x_max, y_max = pts[:, 0].max(), pts[:, 1].max()
            cv2.rectangle(image, (x_min, y_min), (x_max, y_max), color, 2)
            text_pos = (x_min, max(y_min - 5, 10))
        elif len(pts) == 2:
            # 对角线矩形（兼容旧格式）
            pt1 = tuple(pts[0])
            pt2 = tuple(pts[1])
            cv2.rectangle(image, pt1, pt2, color, 2)
            text_pos = (pt1[0], max(pt1[1] - 5, 10))
        else:
            return image
        cv2.putText(
            image, label, text_pos, cv2.FONT_HERSHEY_SIMPLEX,
            0.8, color, 2, lineType=cv2.LINE_AA
        )

    elif shape_type == "polygon":
        if len(pts) >= 3:
            cv2.polylines(image, [pts], isClosed=True, color=color, thickness=2)
            text_pos = tuple(pts[0])
            cv2.putText(
                image, label, text_pos, cv2.FONT_HERSHEY_SIMPLEX,
                0.8, color, 2, lineType=cv2.LINE_AA
            )

    elif shape_type in ("point", "line"):
        for pt in pts:
            cv2.circle(image, tuple(pt), 5, color, -1)
        if label:
            cv2.putText(
                image, label, tuple(pts[0]), cv2.FONT_HERSHEY_SIMPLEX,
                0.8, color, 2, lineType=cv2.LINE_AA
            )

    elif shape_type == "linestrip":
        if len(pts) >= 2:
            for i in range(len(pts) - 1):
                cv2.line(image, tuple(pts[i]), tuple(pts[i + 1]), color, 2)

    elif shape_type == "circle":
        if len(pts) == 2:
            center = tuple(pts[0])
            edge = tuple(pts[1])
            radius = int(np.linalg.norm(np.array(center) - np.array(edge)))
            cv2.circle(image, center, radius, color, 2)
            cv2.putText(
                image, label, (center[0], center[1] - radius - 5),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2, lineType=cv2.LINE_AA
            )

    return image


def find_image(json_path: Path, image_path_hint: str) -> Path:
    """根据 JSON 路径和图片名提示查找对应图片。"""
    dir_path = json_path.parent

    # 优先使用 JSON 中记录的 imagePath
    if image_path_hint:
        candidate = dir_path / image_path_hint
        if candidate.exists():
            return candidate

    # 否则按同名查找
    stem = json_path.stem
    for suffix in SUPPORTED_IMAGE_SUFFIXES:
        candidate = dir_path / f"{stem}{suffix}"
        if candidate.exists():
            return candidate
    return None


def process_json(json_file: Path, output_dir: Path, color_map: dict):
    """处理单个 JSON 文件。"""
    with open(json_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    image_path_hint = data.get("imagePath", "")
    image_file = find_image(json_file, image_path_hint)
    if image_file is None:
        return False, f"Image not found for {json_file.name}"

    image = cv2.imread(str(image_file))
    if image is None:
        return False, f"Failed to read image: {image_file}"

    shapes = data.get("shapes", [])
    for shape in shapes:
        image = draw_shape(image, shape, color_map)

    output_path = output_dir / image_file.name
    cv2.imwrite(str(output_path), image)
    return True, None


def main(datasets_dir: str, output_dir: str):
    datasets_path = Path(datasets_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    json_files = sorted(datasets_path.glob("*.json"))
    if not json_files:
        raise ValueError(f"No JSON files found in {datasets_path}")

    color_map = {}
    success_count = 0
    errors = []

    for json_file in tqdm(json_files, desc="Visualizing"):
        ok, err = process_json(json_file, output_path, color_map)
        if ok:
            success_count += 1
        else:
            errors.append(err)

    print(f"Done: {success_count}/{len(json_files)} images saved to {output_path}")
    if errors:
        print(f"Errors ({len(errors)}):")
        for e in errors[:10]:
            print("  -", e)
        if len(errors) > 10:
            print(f"  ... and {len(errors) - 10} more")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Visualize X-AnyLabeling JSON annotations")
    parser.add_argument("--datasets_dir", type=str, required=True, help="Directory containing .jpg and .json files")
    parser.add_argument("--output_dir", type=str, required=True, help="Directory to save visualized images")
    args = parser.parse_args()
    main(args.datasets_dir, args.output_dir)
