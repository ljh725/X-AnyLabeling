#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
将 cls3pose JSON 标注转换为 YOLOv8 Pose 标签。

输出标签格式：
    class_id cx cy w h x1 y1 v1 x2 y2 v2 ...

可见性 v 的含义：
    0：关键点未标注或没有坐标
    1：关键点已标注但不可见/被遮挡
    2：关键点已标注且可见
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

try:
    from PIL import Image
except ImportError:
    Image = None


# =========================== 手动配置区开始 ===========================
# 类别和关键点在这里手动维护：
# 1. 字典键的顺序就是 YOLO 的 class_id 顺序；
# 2. 每个类别下面的列表是该类别允许出现的 pose 名称；
# 3. 目前 YOLOv8 Pose 要求同一数据集使用固定关键点数量，所以脚本会使用所有类别
#    pose 的并集作为全局关键点顺序；没有 pose 的类别会输出全 0 关键点。

CLASSES_POSE: Dict[str, List[str]] = {
    "person": [
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
    ],
    "head": [],
    "face": [],
}
# =========================== 手动配置区结束 ===========================


IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp")
BOX_TYPES = {"rectangle", "bbox", "box"}
DEFAULT_JSON_DIR = Path("datasets") / "cls3pose-tmp" / "jsons"
DEFAULT_IMAGE_DIR = Path("datasets") / "cls3pose-tmp" / "images"
DEFAULT_OUTPUT_LABEL_DIR = Path("datasets") / "cls3pose-yolov8pose" / "labels"


def load_classes_pose(config_yaml: Optional[Path]) -> Dict[str, List[str]]:
    """读取类别和 pose 配置。

    默认使用脚本顶部的 CLASSES_POSE；只有显式传入 --config-yaml 时才读取 yaml。
    yaml 支持当前数据集中的格式：
        classes:
          person:
            - nose
          head: []
    """
    if config_yaml is None:
        return {class_name: list(pose_names) for class_name, pose_names in CLASSES_POSE.items()}
    if not config_yaml.exists():
        raise FileNotFoundError(f"指定的 yaml 不存在：{config_yaml}")

    try:
        import yaml  # type: ignore
    except ImportError:
        yaml = None

    if yaml is not None:
        with config_yaml.open("r", encoding="utf-8") as file:
            data = yaml.safe_load(file) or {}
        classes = data.get("classes", data)
        if not isinstance(classes, dict):
            raise ValueError(f"{config_yaml} 中没有有效的 classes 配置")
        return normalize_classes_pose(classes)

    warn("未安装 PyYAML，使用内置简易解析器读取 yaml")
    return parse_simple_classes_yaml(config_yaml)


def normalize_classes_pose(classes: Dict[str, Any]) -> Dict[str, List[str]]:
    """把 yaml 读取出的 classes 配置标准化为 Dict[str, List[str]]。"""
    result: Dict[str, List[str]] = {}
    for class_name, pose_names in classes.items():
        class_name = str(class_name).strip()
        if pose_names is None:
            result[class_name] = []
        elif isinstance(pose_names, list):
            result[class_name] = [str(name).strip() for name in pose_names if str(name).strip()]
        else:
            raise ValueError(f"类别 {class_name} 的 pose 配置必须是列表或空值")
    return result


def parse_simple_classes_yaml(config_yaml: Path) -> Dict[str, List[str]]:
    """在没有 PyYAML 时解析当前项目使用的简单 classes yaml 格式。"""
    result: Dict[str, List[str]] = {}
    in_classes = False
    current_class: Optional[str] = None

    for raw_line in config_yaml.read_text(encoding="utf-8").splitlines():
        line_without_comment = raw_line.split("#", 1)[0].rstrip()
        if not line_without_comment.strip():
            continue

        stripped = line_without_comment.strip()
        indent = len(line_without_comment) - len(line_without_comment.lstrip(" "))
        if indent == 0:
            in_classes = stripped == "classes:"
            current_class = None
            continue
        if not in_classes:
            continue

        if indent == 2 and stripped.endswith(":"):
            current_class = stripped[:-1].strip().strip("'\"")
            result[current_class] = []
            continue
        if indent == 2 and ":" in stripped:
            class_name, value = stripped.split(":", 1)
            current_class = class_name.strip().strip("'\"")
            result[current_class] = [] if value.strip() in {"", "[]"} else [value.strip().strip("'\"")]
            continue
        if indent >= 4 and stripped.startswith("-") and current_class:
            pose_name = stripped[1:].strip().strip("'\"")
            if pose_name:
                result[current_class].append(pose_name)

    if not result:
        raise ValueError(f"{config_yaml} 中没有解析到 classes 配置")
    return result


def class_names(classes_pose: Dict[str, List[str]]) -> List[str]:
    """返回类别名称列表，顺序即 class_id。"""
    return list(classes_pose.keys())


def class_to_id(classes_pose: Dict[str, List[str]]) -> Dict[str, int]:
    """生成类别名到 class_id 的映射。"""
    return {name: index for index, name in enumerate(class_names(classes_pose))}


def global_pose_names(classes_pose: Dict[str, List[str]]) -> List[str]:
    """生成全局 pose 顺序，保持配置中首次出现的顺序。"""
    names: List[str] = []
    for pose_names in classes_pose.values():
        for pose_name in pose_names:
            if pose_name not in names:
                names.append(pose_name)
    return names


def warn(message: str) -> None:
    """统一输出警告信息，便于在批量转换时搜索。"""
    print(f"[WARN] {message}")


def clamp(value: float, low: float, high: float) -> float:
    """限制数值范围，避免归一化坐标越界。"""
    return max(low, min(high, value))


def yolo_float(value: float) -> str:
    """按固定精度输出浮点数，并去掉无意义的末尾 0。"""
    return f"{value:.6f}".rstrip("0").rstrip(".") or "0"


def normalize_xy(x: float, y: float, image_w: int, image_h: int) -> Tuple[float, float]:
    """将像素坐标归一化为 YOLO 坐标。"""
    return clamp(x / image_w, 0.0, 1.0), clamp(y / image_h, 0.0, 1.0)


def normalize_box(
    x_min: float, y_min: float, x_max: float, y_max: float, image_w: int, image_h: int
) -> Tuple[float, float, float, float]:
    """将左上右下格式的框转换为 YOLO 的 cx、cy、w、h。"""
    x_min, x_max = sorted((clamp(x_min, 0.0, image_w), clamp(x_max, 0.0, image_w)))
    y_min, y_max = sorted((clamp(y_min, 0.0, image_h), clamp(y_max, 0.0, image_h)))
    box_w = x_max - x_min
    box_h = y_max - y_min
    cx = x_min + box_w / 2
    cy = y_min + box_h / 2
    return cx / image_w, cy / image_h, box_w / image_w, box_h / image_h


def shape_label(shape: Dict[str, Any]) -> str:
    """读取 shape 的 label。"""
    return str(shape.get("label", "")).strip()


def shape_group_id(shape: Dict[str, Any]) -> Any:
    """读取 shape 的 group_id，用于把同一目标的框和 pose 关联起来。"""
    return shape.get("group_id")


def shape_points(shape: Dict[str, Any]) -> List[Tuple[float, float]]:
    """提取 shape.points 中的坐标。"""
    points: List[Tuple[float, float]] = []
    for point in shape.get("points", []) or []:
        if isinstance(point, Sequence) and len(point) >= 2:
            points.append((float(point[0]), float(point[1])))
    return points


def box_from_shape(shape: Dict[str, Any]) -> Optional[Tuple[float, float, float, float]]:
    """从 rectangle/bbox/box shape 中提取外接框。"""
    points = shape_points(shape)
    shape_type = str(shape.get("shape_type", "")).strip().lower()
    if len(points) >= 2 and shape_type in BOX_TYPES:
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        return min(xs), min(ys), max(xs), max(ys)
    return None


def find_image(json_path: Path, images_dir: Path, image_name: Optional[str]) -> Optional[Path]:
    """根据 JSON 中的 imagePath 或 JSON 同名文件查找图片。"""
    candidates: List[Path] = []
    if image_name:
        candidates.append(images_dir / image_name)
        candidates.append(json_path.parent / image_name)

    for suffix in IMAGE_SUFFIXES:
        candidates.append(images_dir / f"{json_path.stem}{suffix}")
        candidates.append(json_path.parent / f"{json_path.stem}{suffix}")

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def read_image_size(image_path: Optional[Path]) -> Tuple[Optional[int], Optional[int]]:
    """从图片文件读取宽高。"""
    if not image_path or Image is None:
        return None, None
    with Image.open(image_path) as image:
        return image.size


def image_size(data: Dict[str, Any], json_path: Path, images_dir: Path) -> Tuple[int, int]:
    """优先使用 JSON 内尺寸，缺失时读取图片尺寸。"""
    width = data.get("imageWidth") or data.get("width")
    height = data.get("imageHeight") or data.get("height")
    if width and height:
        return int(width), int(height)

    image_path = find_image(json_path, images_dir, data.get("imagePath") or data.get("image"))
    width, height = read_image_size(image_path)
    if width and height:
        return width, height
    raise ValueError(f"{json_path} 缺少图片尺寸，且无法从图片读取尺寸")


def read_visibility_value(shape: Dict[str, Any]) -> Any:
    """读取关键点可见性字段，兼容多个常见字段名。"""
    for container in (shape, shape.get("flags") or {}, shape.get("attributes") or {}):
        if not isinstance(container, dict):
            continue
        for key in ("visibility", "visible", "v", "is_visible", "occluded", "hidden"):
            if key in container:
                value = container[key]
                if key in {"occluded", "hidden"} and isinstance(value, bool):
                    return not value
                return value
    return None


def visibility_to_yolo(value: Any, has_xy: bool) -> int:
    """将不同来源的可见性值转换为 YOLOv8 Pose 的 0/1/2。"""
    if not has_xy:
        return 0
    if value is None:
        return 2
    if isinstance(value, bool):
        return 2 if value else 1
    if isinstance(value, (int, float)):
        number = int(value)
        if number <= 0:
            return 0
        if number == 1:
            return 1
        return 2

    text = str(value).strip().lower()
    if text in {"0", "missing", "none", "unlabeled", "not_labeled"}:
        return 0
    if text in {"1", "false", "hidden", "occluded", "invisible", "not_visible"}:
        return 1
    return 2


def validate_config(classes_pose: Dict[str, List[str]]) -> None:
    """检查手动配置是否有重复类别或重复 pose。"""
    if not classes_pose:
        raise ValueError("CLASSES_POSE 不能为空")
    for class_name, pose_names in classes_pose.items():
        if not class_name:
            raise ValueError("类别配置中存在空类别名")
        duplicated = {name for name in pose_names if pose_names.count(name) > 1}
        if duplicated:
            raise ValueError(f"类别 {class_name} 的 pose 配置重复：{sorted(duplicated)}")


def resolve_class_name(
    label: str,
    classes_pose: Dict[str, List[str]],
    difficulty_suffix: str,
    keep_difficulty_class: bool,
    json_path: Path,
    emit_warning: bool = True,
) -> Optional[str]:
    """将困难类别归并到普通类别，或保留显式配置的困难类别。"""
    if label in classes_pose:
        return label
    if keep_difficulty_class or not difficulty_suffix or not label.endswith(difficulty_suffix):
        return None

    normal_label = label[: -len(difficulty_suffix)]
    if normal_label in classes_pose:
        if emit_warning:
            warn(f"{json_path.name}: 类别 '{label}' 未配置，按普通类别 '{normal_label}' 处理")
        return normal_label
    return None


def validate_shapes(
    json_path: Path,
    shapes: Iterable[Dict[str, Any]],
    classes_pose: Dict[str, List[str]],
    difficulty_suffix: str,
    keep_difficulty_class: bool,
) -> None:
    """检查 JSON 中是否出现未配置的类别或 pose，并输出警告。"""
    configured_poses = set(global_pose_names(classes_pose))
    for shape in shapes:
        label = shape_label(shape)
        if not label:
            warn(f"{json_path.name}: 存在空 label，已忽略")
            continue
        if box_from_shape(shape):
            if not resolve_class_name(
                label,
                classes_pose,
                difficulty_suffix,
                keep_difficulty_class,
                json_path,
                emit_warning=False,
            ):
                warn(f"{json_path.name}: 类别 '{label}' 不在 CLASSES_POSE 中，已跳过该框")
        elif label not in configured_poses:
            warn(f"{json_path.name}: pose '{label}' 不在 CLASSES_POSE 任一 pose 列表中，已跳过该点")


def build_pose_by_group(
    shapes: Iterable[Dict[str, Any]], classes_pose: Dict[str, List[str]]
) -> Dict[Any, Dict[str, Dict[str, Any]]]:
    """按 group_id 收集关键点 shape。"""
    pose_by_group: Dict[Any, Dict[str, Dict[str, Any]]] = {}
    configured_poses = set(global_pose_names(classes_pose))
    for shape in shapes:
        label = shape_label(shape)
        if label not in configured_poses:
            continue
        pose_by_group.setdefault(shape_group_id(shape), {})[label] = shape
    return pose_by_group


def make_keypoints(
    json_path: Path,
    box_shape: Dict[str, Any],
    pose_by_group: Dict[Any, Dict[str, Dict[str, Any]]],
    image_w: int,
    image_h: int,
    classes_pose: Dict[str, List[str]],
    difficulty_suffix: str,
    keep_difficulty_class: bool,
) -> List[str]:
    """按全局 pose 顺序生成 YOLO 关键点字段。"""
    class_name = resolve_class_name(
        shape_label(box_shape),
        classes_pose,
        difficulty_suffix,
        keep_difficulty_class,
        json_path,
        emit_warning=False,
    )
    if class_name is None:
        return []
    allowed_pose_names = set(classes_pose[class_name])
    group_id = shape_group_id(box_shape)
    group_poses = pose_by_group.get(group_id, {})

    for pose_name in group_poses:
        if pose_name not in allowed_pose_names:
            warn(
                f"{json_path.name}: group_id={group_id} 的类别 '{class_name}' 不允许 pose '{pose_name}'，已按缺失点处理"
            )

    values: List[str] = []
    for pose_name in global_pose_names(classes_pose):
        pose_shape = group_poses.get(pose_name)
        if pose_name not in allowed_pose_names or not pose_shape:
            values.extend(["0", "0", "0"])
            continue

        points = shape_points(pose_shape)
        if not points:
            values.extend(["0", "0", "0"])
            continue

        x, y = points[0]
        visibility = visibility_to_yolo(read_visibility_value(pose_shape), True)
        if visibility == 0:
            values.extend(["0", "0", "0"])
        else:
            norm_x, norm_y = normalize_xy(x, y, image_w, image_h)
            values.extend([yolo_float(norm_x), yolo_float(norm_y), str(visibility)])
    return values


def convert_one(json_path: Path, args: argparse.Namespace, classes_pose: Dict[str, List[str]]) -> int:
    """转换单个 JSON，返回写出的目标数量。"""
    with json_path.open("r", encoding="utf-8-sig") as file:
        data = json.load(file)

    shapes = data.get("shapes") or []
    validate_shapes(json_path, shapes, classes_pose, args.difficulty_suffix, args.keep_difficulty_class)

    image_w, image_h = image_size(data, json_path, args.images_dir)
    id_map = class_to_id(classes_pose)
    pose_by_group = build_pose_by_group(shapes, classes_pose)
    lines: List[str] = []

    for shape in shapes:
        class_name = resolve_class_name(
            shape_label(shape), classes_pose, args.difficulty_suffix, args.keep_difficulty_class, json_path
        )
        if class_name is None:
            continue
        bbox = box_from_shape(shape)
        if not bbox:
            continue

        values = [str(id_map[class_name])]
        values.extend(yolo_float(value) for value in normalize_box(*bbox, image_w, image_h))
        values.extend(
            make_keypoints(
                json_path,
                shape,
                pose_by_group,
                image_w,
                image_h,
                classes_pose,
                args.difficulty_suffix,
                args.keep_difficulty_class,
            )
        )
        lines.append(" ".join(values))

    args.dst.mkdir(parents=True, exist_ok=True)
    output_path = args.dst / f"{json_path.stem}.txt"
    output_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")

    return len(lines)


def parse_args() -> argparse.Namespace:
    """解析命令行参数。默认路径按当前数据集结构设置。"""
    parser = argparse.ArgumentParser(description="将 cls3pose JSON 转换为 YOLOv8 Pose 标签")
    parser.add_argument(
        "--src",
        type=Path,
        default=DEFAULT_JSON_DIR,
        help=f"JSON 标注目录，默认：{DEFAULT_JSON_DIR}",
    )
    parser.add_argument(
        "--images-dir",
        type=Path,
        default=DEFAULT_IMAGE_DIR,
        help=f"图片目录，默认：{DEFAULT_IMAGE_DIR}",
    )
    parser.add_argument(
        "--dst",
        type=Path,
        default=DEFAULT_OUTPUT_LABEL_DIR,
        help=f"YOLO 标签输出目录，默认：{DEFAULT_OUTPUT_LABEL_DIR}",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="递归转换 src 下所有 JSON；默认只转换 src 第一层 JSON",
    )
    parser.add_argument(
        "--config-yaml",
        type=Path,
        default=None,
        help="可选：从 yaml 读取类别和 pose 配置；不传时使用脚本顶部 CLASSES_POSE",
    )
    parser.add_argument(
        "--difficulty-suffix",
        type=str,
        default="-d",
        help="困难类别后缀，默认：-d；例如 person-d 可归并为 person",
    )
    parser.add_argument(
        "--keep-difficulty-class",
        action="store_true",
        help="保留困难类别名称；若 CLASSES_POSE 中未配置该困难类别，则不归并并按未知类别跳过",
    )
    return parser.parse_args()


def main() -> None:
    """批量转换入口。"""
    args = parse_args()
    classes_pose = load_classes_pose(args.config_yaml)
    validate_config(classes_pose)
    pattern = "**/*.json" if args.recursive else "*.json"
    json_files = sorted(args.src.glob(pattern))
    if not json_files:
        raise FileNotFoundError(f"未在 {args.src} 找到 JSON 文件")

    total_objects = 0
    for json_path in json_files:
        count = convert_one(json_path, args, classes_pose)
        total_objects += count
        print(f"[OK] {json_path} -> {count} 个目标")

    print(f"完成：{len(json_files)} 个 JSON，{total_objects} 个目标，输出目录：{args.dst}")
    print(f"类别顺序：{class_names(classes_pose)}")
    print(f"pose 顺序：{global_pose_names(classes_pose)}")


if __name__ == "__main__":
    main()


"""demo
python .\convert_json_to_yolopose.py `
  --src .\tmp\cls3pose-tmp\jsons `
  --images-dir .\tmp\cls3pose-tmp\images `
  --dst .\tmp\cls3pose-yolov8pose-d\labels `
  --difficulty-suffix=-d

python .\convert_json_to_yolopose.py `
  --src .\datasets\cls3pose-tmp\jsons `
  --images-dir .\datasets\cls3pose-tmp\images `
  --dst .\datasets\cls3pose-yolov8pose\labels `
  --config-yaml .\datasets\cls3pose-tmp\yolov8_pose.yaml

使用注意事项：
1. 默认使用脚本顶部 CLASSES_POSE 中的类别和 pose 配置；yaml 不是必需文件。
2. 只有显式传入 --config-yaml 时，脚本才会读取 yaml 中的类别和 pose 配置。
3. --src 指向 JSON 标注目录，--images-dir 指向图片目录，--dst 指向 YOLO 标签输出目录。
4. --difficulty-suffix 默认是 -d；当 JSON 中出现 person-d 且 CLASSES_POSE 未配置 person-d，但配置了 person 时，会按 person 处理并输出 [WARN]。
5. 如果需要严格保留 person-d 这类类别名，可添加 --keep-difficulty-class；未配置的困难类别会作为未知类别跳过。
6. 矩形框类别或 pose 名称超出配置范围时会输出 [WARN]，并跳过超出范围的内容。
7. YOLOv8 Pose 标签格式为：class_id cx cy w h x1 y1 v1 x2 y2 v2 ...
8. 关键点可见性 v：0 表示未标注，1 表示已标注但不可见，2 表示已标注且可见。
"""
# CLASSES_POSE: Dict[str, List[str]] = {
#     "person": [
#         "nose",
#         "left_eye",
#         "right_eye",
#         "left_ear",
#         "right_ear",
#         "left_shoulder",
#         "right_shoulder",
#         "left_elbow",
#         "right_elbow",
#         "left_wrist",
#         "right_wrist",
#         "left_hip",
#         "right_hip",
#         "left_knee",
#         "right_knee",
#         "left_ankle",
#         "right_ankle",
#     ],
#     "head": [],
#     "face": [],
# }
