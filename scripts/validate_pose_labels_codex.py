#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validate X-AnyLabeling pose JSON annotations."""

import argparse
import csv
import io
import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

try:
    from tqdm import tqdm
except ImportError:
    tqdm = None


# ========== IDE direct-run config ==========
INPUT_PATH = r""
WORKERS = None
REPORT_NAME = None
DEFAULT_FORMAT = "tsv"
# ==========================================


ALLOWED_LABELS = {
    "person",
    "face",
    "head",
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
}
RECTANGLE_LABELS = {"person", "face", "head"}
POINT_LABELS = ALLOWED_LABELS - RECTANGLE_LABELS
INSPECTOR_FIELDNAMES = [
    "file_path",
    "shape_index",
    "rule_name",
    "severity",
    "message",
]


@dataclass
class ValidationIssue:
    """A single validation issue in one annotation shape."""

    file_path: str
    shape_index: int
    label: str
    group_id: Any
    error_type: str
    message: str


def is_number(value: Any) -> bool:
    """Return whether value is an int or float, excluding bool."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def expected_shape_type(label: str) -> Optional[str]:
    """Return expected shape_type for a known label."""
    if label in RECTANGLE_LABELS:
        return "rectangle"
    if label in POINT_LABELS:
        return "point"
    return None


def format_gid(group_id: Any) -> str:
    """Format group_id for reports."""
    return "null" if group_id is None else repr(group_id)


def add_issue(
    issues: List[ValidationIssue],
    file_path: str,
    shape_index: int,
    shape: Dict[str, Any],
    error_type: str,
    message: str,
) -> None:
    """Append a validation issue for one shape."""
    issues.append(
        ValidationIssue(
            file_path=file_path,
            shape_index=shape_index,
            label=shape.get("label", ""),
            group_id=shape.get("group_id"),
            error_type=error_type,
            message=message,
        )
    )


def validate_points(
    issues: List[ValidationIssue],
    file_path: str,
    shape_index: int,
    shape: Dict[str, Any],
    image_width: Any,
    image_height: Any,
) -> None:
    """Validate points length, point format, and coordinate bounds."""
    shape_type = shape.get("shape_type")
    points = shape.get("points")

    if not isinstance(points, list):
        add_issue(
            issues,
            file_path,
            shape_index,
            shape,
            "points字段异常",
            "points 不是列表",
        )
        return

    if shape_type == "rectangle" and len(points) not in {2, 4}:
        add_issue(
            issues,
            file_path,
            shape_index,
            shape,
            "points长度错误",
            f"rectangle 的 points 长度应为 2 或 4，实际为 {len(points)}",
        )
    elif shape_type == "point" and len(points) != 1:
        add_issue(
            issues,
            file_path,
            shape_index,
            shape,
            "points长度错误",
            f"point 的 points 长度应为 1，实际为 {len(points)}",
        )

    has_image_size = is_number(image_width) and is_number(image_height)
    if not has_image_size:
        add_issue(
            issues,
            file_path,
            shape_index,
            shape,
            "图片尺寸字段异常",
            "imageWidth/imageHeight 缺失或不是数字，无法检查坐标越界",
        )
        return

    for point_index, point in enumerate(points):
        if not isinstance(point, list) or len(point) != 2:
            add_issue(
                issues,
                file_path,
                shape_index,
                shape,
                "坐标格式错误",
                f"points[{point_index}] 应为 [x, y]，实际为 {point!r}",
            )
            continue

        x, y = point
        if not is_number(x) or not is_number(y):
            add_issue(
                issues,
                file_path,
                shape_index,
                shape,
                "坐标类型错误",
                f"points[{point_index}] 坐标必须是数字，实际为 {point!r}",
            )
            continue

        if x < 0 or x > image_width or y < 0 or y > image_height:
            add_issue(
                issues,
                file_path,
                shape_index,
                shape,
                "坐标越界",
                (
                    f"points[{point_index}]=[{x}, {y}] 超出图片范围 "
                    f"width={image_width}, height={image_height}"
                ),
            )


def validate_groups(
    issues: List[ValidationIssue],
    file_path: str,
    shapes: Sequence[Dict[str, Any]],
) -> None:
    """Validate group_id consistency and duplicate labels in each group."""
    groups: Dict[int, List[Tuple[int, Dict[str, Any]]]] = {}
    head_face_groups: Dict[int, List[Tuple[int, Dict[str, Any]]]] = {}

    for shape_index, shape in enumerate(shapes):
        label = shape.get("label", "")
        gid = shape.get("group_id")
        if label in {"head", "face"} and gid is None:
            add_issue(
                issues,
                file_path,
                shape_index,
                shape,
                "head/face group_id为空",
                f"label='{label}' 的 group_id 不能为 null",
            )
            continue
        if not isinstance(gid, int) or isinstance(gid, bool) or gid < 0:
            add_issue(
                issues,
                file_path,
                shape_index,
                shape,
                "group_id异常",
                "group_id 必须是非负整数",
            )
            continue
        groups.setdefault(gid, []).append((shape_index, shape))
        if label in {"head", "face"}:
            head_face_groups.setdefault(gid, []).append((shape_index, shape))

    for gid, grouped_shapes in head_face_groups.items():
        if len(grouped_shapes) <= 1:
            continue
        for shape_index, shape in grouped_shapes:
            add_issue(
                issues,
                file_path,
                shape_index,
                shape,
                "head/face group_id重复",
                f"head/face 的 group_id={gid} 出现 {len(grouped_shapes)} 次",
            )

    for gid, grouped_shapes in groups.items():
        label_map: Dict[str, List[Tuple[int, Dict[str, Any]]]] = {}
        has_person = False
        for shape_index, shape in grouped_shapes:
            label = shape.get("label", "")
            label_map.setdefault(label, []).append((shape_index, shape))
            if label == "person" and shape.get("shape_type") == "rectangle":
                has_person = True

        for label, same_label_shapes in label_map.items():
            if label not in ALLOWED_LABELS or len(same_label_shapes) <= 1:
                continue
            for shape_index, shape in same_label_shapes:
                add_issue(
                    issues,
                    file_path,
                    shape_index,
                    shape,
                    "同组标签重复",
                    (
                        f"group_id={gid} 内 label='{label}' 出现 "
                        f"{len(same_label_shapes)} 次"
                    ),
                )

        if has_person:
            continue

        for shape_index, shape in grouped_shapes:
            label = shape.get("label", "")
            if label not in POINT_LABELS:
                continue
            add_issue(
                issues,
                file_path,
                shape_index,
                shape,
                "group_id分组不一致",
                f"group_id={gid} 下存在 '{label}'，但缺少 person rectangle",
            )


def validate_json_file(
    file_path: str,
) -> Tuple[str, List[ValidationIssue], Optional[str]]:
    """Validate one JSON file and return issues or load error."""
    try:
        with open(file_path, "r", encoding="utf-8") as file_obj:
            data = json.load(file_obj)
    except json.JSONDecodeError as exc:
        return file_path, [], f"JSON 解析错误: {exc}"
    except OSError as exc:
        return file_path, [], f"文件读取错误: {exc}"

    issues: List[ValidationIssue] = []
    shapes = data.get("shapes")
    if not isinstance(shapes, list):
        return (
            file_path,
            [
                ValidationIssue(
                    file_path=file_path,
                    shape_index=-1,
                    label="",
                    group_id=None,
                    error_type="shapes字段异常",
                    message="shapes 缺失或不是列表",
                )
            ],
            None,
        )

    image_width = data.get("imageWidth")
    image_height = data.get("imageHeight")

    for shape_index, shape in enumerate(shapes):
        if not isinstance(shape, dict):
            issues.append(
                ValidationIssue(
                    file_path=file_path,
                    shape_index=shape_index,
                    label="",
                    group_id=None,
                    error_type="shape字段异常",
                    message=f"shape #{shape_index} 不是对象",
                )
            )
            continue

        label = shape.get("label", "")
        shape_type = shape.get("shape_type")
        if label not in ALLOWED_LABELS:
            add_issue(
                issues,
                file_path,
                shape_index,
                shape,
                "标签名异常",
                f"label='{label}' 不在允许标签列表内",
            )

        expected_type = expected_shape_type(label)
        if expected_type is not None and shape_type != expected_type:
            add_issue(
                issues,
                file_path,
                shape_index,
                shape,
                "标签类型错误",
                (
                    f"label='{label}' 的 shape_type 应为 {expected_type}，"
                    f"实际为 {shape_type!r}"
                ),
            )

        validate_points(
            issues,
            file_path,
            shape_index,
            shape,
            image_width,
            image_height,
        )

    validate_groups(issues, file_path, shapes)
    return file_path, issues, None


def collect_json_files(input_path: str) -> List[str]:
    """Collect JSON files from a file path or directory path."""
    if os.path.isfile(input_path):
        if input_path.lower().endswith(".json"):
            return [os.path.abspath(input_path)]
        raise ValueError(f"输入文件不是 JSON: {input_path}")

    if not os.path.isdir(input_path):
        raise ValueError(f"输入路径不存在: {input_path}")

    json_files = []
    for root, _, filenames in os.walk(input_path):
        for filename in filenames:
            if filename.lower().endswith(".json"):
                json_files.append(
                    os.path.abspath(os.path.join(root, filename))
                )
    return sorted(json_files)


def build_report_text(
    directory: str,
    file_results: Dict[str, List[ValidationIssue]],
    load_errors: Dict[str, str],
) -> str:
    """Build TXT report content for one directory."""
    lines = [
        "X-AnyLabeling 姿态标签检测报告",
        f"目录: {directory}",
        "",
    ]

    directory_files = sorted(
        set(file_results.keys()) | set(load_errors.keys()),
        key=lambda path: os.path.basename(path).lower(),
    )
    issue_count = sum(
        len(file_results.get(path, [])) for path in directory_files
    )
    lines.append(f"异常数量: {issue_count + len(load_errors)}")
    lines.append("")

    if not issue_count and not load_errors:
        lines.append("未发现异常。")
        lines.append("")
        return "\n".join(lines)

    for path in directory_files:
        filename = os.path.basename(path)
        if path in load_errors:
            lines.append(f"文件: {filename}")
            lines.append(f"  错误类型: 文件读取/解析错误")
            lines.append(f"  详情: {load_errors[path]}")
            lines.append("")
            continue

        issues = file_results.get(path, [])
        if not issues:
            continue

        lines.append(f"文件: {filename}")
        for issue in issues:
            lines.append(
                "  "
                f"shape_index={issue.shape_index}, "
                f"label={issue.label!r}, "
                f"group_id={format_gid(issue.group_id)}, "
                f"错误类型={issue.error_type}, "
                f"详情={issue.message}"
            )
        lines.append("")

    return "\n".join(lines)


def iter_inspector_rows(
    file_results: Dict[str, List[ValidationIssue]],
    load_errors: Dict[str, str],
) -> List[Dict[str, Any]]:
    """Build Inspector-importable rows with the required core fields."""
    rows: List[Dict[str, Any]] = []
    all_paths = sorted(
        set(file_results.keys()) | set(load_errors.keys()),
        key=lambda p: os.path.basename(p).lower(),
    )
    for path in all_paths:
        if path in load_errors:
            rows.append(
                {
                    "file_path": os.path.basename(path),
                    "shape_index": -1,
                    "rule_name": "file_level_error",
                    "severity": "error",
                    "message": load_errors[path],
                }
            )
            continue
        for issue in file_results.get(path, []):
            rows.append(
                {
                    "file_path": os.path.basename(path),
                    "shape_index": issue.shape_index,
                    "rule_name": issue.error_type,
                    "severity": "error",
                    "message": issue.message,
                }
            )
    return rows


def build_report_tsv(
    file_results: Dict[str, List[ValidationIssue]],
    load_errors: Dict[str, str],
) -> str:
    """Build TSV report content for Inspector import."""
    output = io.StringIO()
    writer = csv.DictWriter(
        output, fieldnames=INSPECTOR_FIELDNAMES, delimiter="\t"
    )
    writer.writeheader()
    writer.writerows(iter_inspector_rows(file_results, load_errors))
    return output.getvalue()


def build_report_csv(
    file_results: Dict[str, List[ValidationIssue]],
    load_errors: Dict[str, str],
) -> str:
    """Build CSV report content for Inspector import."""
    output = io.StringIO()
    writer = csv.DictWriter(
        output, fieldnames=INSPECTOR_FIELDNAMES, delimiter=","
    )
    writer.writeheader()
    writer.writerows(iter_inspector_rows(file_results, load_errors))
    return output.getvalue()


def build_report_json(
    file_results: Dict[str, List[ValidationIssue]],
    load_errors: Dict[str, str],
) -> str:
    """Build JSON report content for Inspector import."""
    issues = iter_inspector_rows(file_results, load_errors)
    return json.dumps({"issues": issues}, ensure_ascii=False, indent=2)


def default_report_name(fmt: str) -> str:
    """Return the default report name for an output format."""
    return f"pose_label_validation_report.{fmt}"


def write_reports(
    file_results: Dict[str, List[ValidationIssue]],
    load_errors: Dict[str, str],
    report_name: str,
    output_dir: Optional[str] = None,
    fmt: str = DEFAULT_FORMAT,
) -> List[str]:
    """Write report file(s) in the specified format."""
    if fmt == "txt":
        if output_dir is not None:
            os.makedirs(output_dir, exist_ok=True)
            report_path = os.path.join(output_dir, report_name)
            report_text = build_report_text(
                output_dir, file_results, load_errors
            )
            with open(report_path, "w", encoding="utf-8") as f:
                f.write(report_text)
            return [report_path]

        directories = sorted(
            {
                os.path.dirname(path)
                for path in set(file_results) | set(load_errors)
            }
        )
        written_paths = []
        for directory in directories:
            dir_results = {
                path: issues
                for path, issues in file_results.items()
                if os.path.dirname(path) == directory
            }
            dir_errors = {
                path: error
                for path, error in load_errors.items()
                if os.path.dirname(path) == directory
            }
            report_path = os.path.join(directory, report_name)
            report_text = build_report_text(directory, dir_results, dir_errors)
            with open(report_path, "w", encoding="utf-8") as f:
                f.write(report_text)
            written_paths.append(report_path)
        return written_paths

    if fmt in ("tsv", "csv", "json"):
        if output_dir is None:
            directories = sorted(
                {
                    os.path.dirname(path)
                    for path in set(file_results) | set(load_errors)
                }
            )
            output_dir = directories[0] if directories else "."
        os.makedirs(output_dir, exist_ok=True)

        if fmt == "tsv":
            report_text = build_report_tsv(file_results, load_errors)
        elif fmt == "csv":
            report_text = build_report_csv(file_results, load_errors)
        else:
            report_text = build_report_json(file_results, load_errors)

        report_path = os.path.join(output_dir, report_name)
        with open(report_path, "w", encoding="utf-8", newline="") as f:
            f.write(report_text)
        return [report_path]

    raise ValueError(f"不支持的输出格式: {fmt}")


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "多线程检测 X-AnyLabeling 姿态 JSON 标签，并生成 Inspector 可导入报告。"
        )
    )
    parser.add_argument(
        "-i",
        "--input",
        default=INPUT_PATH,
        help="输入 JSON 文件或目录，默认使用脚本顶部 INPUT_PATH",
    )
    parser.add_argument(
        "-w",
        "--workers",
        type=int,
        default=WORKERS,
        help="线程数，默认 min(32, CPU核心数 * 4)",
    )
    parser.add_argument(
        "-rn",
        "--report-name",
        default=REPORT_NAME,
        help="报告文件名，默认按输出格式自动生成",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        default=None,
        help="报告输出目录，默认写入 JSON 同级目录",
    )
    parser.add_argument(
        "-f",
        "--format",
        choices=["txt", "tsv", "csv", "json"],
        default=DEFAULT_FORMAT,
        help="报告输出格式：tsv（默认）/ csv / json / txt",
    )
    return parser.parse_args()


def main() -> int:
    """Run pose label validation."""
    args = parse_args()
    try:
        json_files = collect_json_files(args.input)
    except ValueError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 2

    if not json_files:
        print(f"未找到 JSON 文件: {args.input}")
        return 0

    report_name = args.report_name or default_report_name(args.format)
    workers = args.workers or min(32, (os.cpu_count() or 1) * 4)
    file_results: Dict[str, List[ValidationIssue]] = {}
    load_errors: Dict[str, str] = {}
    lock = threading.Lock()

    print(f"发现 {len(json_files)} 个 JSON 文件")
    print(f"工作线程: {workers}")
    print("开始检测...")

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [
            executor.submit(validate_json_file, path) for path in json_files
        ]
        completed_futures = as_completed(futures)
        if tqdm is not None:
            completed_futures = tqdm(
                completed_futures,
                total=len(futures),
                desc="检测进度",
                unit="file",
            )

        for completed_count, future in enumerate(completed_futures, 1):
            file_path, issues, load_error = future.result()
            with lock:
                file_results[file_path] = issues
                if load_error:
                    load_errors[file_path] = load_error
            if tqdm is None:
                print(
                    f"\r检测进度: {completed_count}/{len(futures)}",
                    end="",
                    flush=True,
                )

        if tqdm is None:
            print()

    report_paths = write_reports(
        file_results, load_errors, report_name, args.output_dir, args.format
    )
    issue_count = sum(len(issues) for issues in file_results.values())
    total_errors = issue_count + len(load_errors)
    bad_file_count = sum(1 for issues in file_results.values() if issues)
    bad_file_count += len(load_errors)

    print(f"检测完成: 文件数={len(json_files)}, 异常文件数={bad_file_count}")
    print(f"异常总数: {total_errors}")
    for report_path in report_paths:
        print(f"报告: {report_path}")

    return 1 if total_errors else 0


if __name__ == "__main__":
    sys.exit(main())


"""
功能说明：
    这个脚本用来批量检查 X-AnyLabeling 姿态估计的 JSON 标注文件有没有错误。
    它会检查这些内容：
    1. 标签名是否在允许列表里（比如 person、face、nose、l_eye 等）
    2. 标签和图形类型是否匹配（person 应该是矩形，关键点应该是点）
    3. points 长度对不对（矩形应该是 2 或 4 个点，关键点应该是 1 个点）
    4. 坐标是不是数字，有没有超出图片边界
    5. group_id 是不是非负整数，head 和 face 的 group_id 不能为 null
    6. 同一个 group_id 里有没有重复的标签
    7. 一个 group_id 里有关键点的话，必须要有 person 矩形框
    支持多线程并行处理，检测完后会生成报告。
    支持 4 种输出格式（通过 -f/--format 选择）：
      - tsv：Tab 分隔表格，适合导入 Inspector 外部结果（默认）
      - csv：逗号分隔表格，也可导入 Inspector
      - json：结构化 JSON，也可导入 Inspector
      - txt：人类可读的文本报告
    tsv / csv / json 只输出 Inspector 导入所需的 5 个核心字段：
      file_path, shape_index, rule_name, severity, message
    脚本不再默认额外生成 readable.txt；可读性由 Inspector 导入后的显示层负责。
    默认在每个 JSON 文件夹里生成报告；
    也可以通过 -o/--output-dir 参数指定一个本地目录统一输出，
    避免因为网络路径没有写入权限而报错。

运行命令样例：

  # 基础用法：检测指定目录下的所有 JSON 文件
  python scripts/validate_pose_labels_codex.py -i ./annotations

  # 检测单个 JSON 文件
  python scripts/validate_pose_labels_codex.py -i ./annotations/0001.json

  # 使用 8 个线程加速
  python scripts/validate_pose_labels_codex.py -i ./annotations -w 8

  # 指定报告文件名
  python scripts/validate_pose_labels_codex.py -i ./annotations --report-name my_report.tsv

  # 指定报告输出目录（避免写入无权限的网络路径）
  python scripts/validate_pose_labels_codex.py -i ./annotations -o D:/reports

  # 默认输出 TSV（可导入 Inspector 外部结果）
  python scripts/validate_pose_labels_codex.py -i ./annotations

  # 指定输出格式为 JSON
  python scripts/validate_pose_labels_codex.py -i ./annotations -f json --report-name result.json

  # 在 IDE 里直接运行（修改脚本顶部的 INPUT_PATH）
  python scripts/validate_pose_labels_codex.py

大白话版：
    你标了一堆姿态估计的数据（画框、打点），但难免有手滑的时候：
    比如把 "person" 打成了 "peson"，或者忘了给关键点配 group_id，
    或者某个点的坐标飞到图片外面去了……
    这个脚本就是帮你自动"挑毛病"的：
    它把标注文件扫一遍，看看有没有不符合规则的，
    然后把问题整理成报告，你就知道该修哪些文件了。
"""
