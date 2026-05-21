#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Convert LabelMe JSON labels for cls3 pose annotations."""

import argparse
import json
import os
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

# ========== IDE direct-run config ==========
INPUT_DIR = (
    r"\\192.168.3.248\opt\chengdu\cls3pose_cly\cls3pose_v1\train\annotations"
)
OUTPUT_DIR = (
    r"\\192.168.3.248\opt\chengdu\cls3pose_cly\cls3pose_v1\train\new-annotations"
)
WORKERS = None
# ==========================================

try:
    from tqdm import tqdm
except ImportError:

    def tqdm(iterable, **kwargs):
        """Return iterable unchanged when tqdm is unavailable."""
        return iterable


def ensure_flags(shape):
    """Ensure shape has a writable flags dict."""
    flags = shape.get("flags")
    if not isinstance(flags, dict):
        flags = {}
        shape["flags"] = flags
    return flags


def clear_transform_flags(shape):
    """Clear stale transform flags from previous script runs."""
    flags = ensure_flags(shape)
    for key in (
        "orphan_head",
        "has_face",
        "entity_source",
        "unmatched_orphan_face",
    ):
        flags.pop(key, None)


def collect_label_group_duplicates(shapes, label):
    """Collect duplicate group_id values for a label."""
    gid_to_shapes = {}
    duplicates = {}
    for shape in shapes:
        if shape.get("label") != label:
            continue
        gid = shape.get("group_id")
        if gid is None:
            continue
        gid_to_shapes.setdefault(gid, []).append(shape)

    for gid, same_gid_shapes in gid_to_shapes.items():
        if len(same_gid_shapes) > 1:
            duplicates[gid] = same_gid_shapes

    return duplicates


def validate_entity_rules(shapes):
    """Validate final entity rules and return warnings."""
    warnings = []

    duplicates = collect_label_group_duplicates(shapes, "person")
    for gid, same_gid_shapes in sorted(duplicates.items()):
        warnings.append(
            f"duplicate person group_id={gid}: count={len(same_gid_shapes)}"
        )

    return warnings


def process_json_data(data):
    """Process one JSON data object and return data with warnings."""
    shapes = data.get("shapes", [])
    if not shapes:
        data["imageData"] = None
        return data, []

    shapes = [
        shape
        for shape in shapes
        if not re.match(r"^\d+_fullperson$", shape.get("label", ""))
    ]
    data["shapes"] = shapes

    max_gid = max(
        (
            shape.get("group_id")
            for shape in shapes
            if isinstance(shape.get("group_id"), int)
        ),
        default=-1,
    )
    warnings = []

    # Round 1: normalize labels and rewrite person/keypoint group_id values.
    for shape in shapes:
        clear_transform_flags(shape)
        label = shape.get("label", "")
        shape_type = shape.get("shape_type")

        match = re.match(r"^(\d+)_person$", label)
        if match:
            gid = int(match.group(1))
            shape["label"] = "person"
            shape["group_id"] = gid
            if gid > max_gid:
                max_gid = gid
            continue

        match = re.match(r"^person_(\d+)_(.+)$", label)
        if match:
            gid = int(match.group(1))
            shape["label"] = match.group(2)
            shape["group_id"] = gid
            if gid > max_gid:
                max_gid = gid
            continue

        if re.match(r"^\d+_head$", label):
            shape["label"] = "head"
            shape["group_id"] = None
            continue

        if re.match(r"^\d+_face$", label):
            shape["label"] = "face"
            shape["group_id"] = None
            continue

        # Re-running converted data should overwrite head/face ids again.
        if shape_type == "rectangle" and label in ("head", "face"):
            shape["group_id"] = None

    next_gid = max_gid + 1
    for shape in shapes:
        if shape.get("label") in ("head", "face"):
            shape["group_id"] = next_gid
            next_gid += 1

    warnings.extend(validate_entity_rules(shapes))

    data["imageData"] = None
    return data, warnings


def process_single_file(input_path, output_path):
    """Process one file and return success, error message, warnings."""
    try:
        with open(input_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        data, warnings = process_json_data(data)

        out_dir = os.path.dirname(output_path)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        return True, None, warnings

    except json.JSONDecodeError as e:
        return False, f"JSON 解析错误: {e}", []
    except Exception as e:
        return False, f"处理异常: {type(e).__name__}: {e}", []


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "JSON 标签转换脚本：提取 group_id、规范化 label、"
            "过滤 fullperson、head/face 顺序赋新 id、多线程批处理"
        )
    )
    parser.add_argument(
        "-i", "--input", type=str, default=None, help="输入 JSON 文件所在目录"
    )
    parser.add_argument(
        "-o", "--output", type=str, default=None, help="输出目录（不存在则自动创建）"
    )
    parser.add_argument(
        "-w",
        "--workers",
        type=int,
        default=None,
        help="线程池工作线程数，默认 min(16, CPU核心数)",
    )

    args = parser.parse_args()

    if args.input is None:
        args.input = INPUT_DIR
    if args.output is None:
        args.output = OUTPUT_DIR
    if args.workers is None:
        args.workers = (
            WORKERS
            if WORKERS is not None
            else min(16, (os.cpu_count() or 1))
        )

    return args


def main():
    """Run batch JSON conversion."""
    args = parse_args()

    input_dir = args.input
    output_dir = args.output
    workers = args.workers

    if not input_dir or not output_dir:
        print("错误：必须指定输入目录和输出目录。")
        print(
            "方式 1：命令行运行  python label_transform.py "
            "-i <输入目录> -o <输出目录> [-w <线程数>]"
        )
        print("方式 2：IDE 直接运行  修改脚本顶部 INPUT_DIR 和 OUTPUT_DIR 的值")
        sys.exit(1)

    if not os.path.isdir(input_dir):
        print(f"错误：输入目录不存在或不是目录: {input_dir}")
        sys.exit(1)

    os.makedirs(output_dir, exist_ok=True)

    try:
        filenames = [
            f for f in os.listdir(input_dir) if f.lower().endswith(".json")
        ]
    except Exception as e:
        print(f"错误：无法读取输入目录: {e}")
        sys.exit(1)

    if not filenames:
        print(f"警告：输入目录中未找到 .json 文件: {input_dir}")
        sys.exit(0)

    print(f"发现 {len(filenames)} 个 JSON 文件")
    print(f"输出目录: {output_dir}")
    print(f"工作线程: {workers}")
    print("开始处理...\n")

    success_count = 0
    fail_count = 0
    warning_count = 0
    errors = []
    warnings = []
    lock = threading.Lock()

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {}
        for filename in filenames:
            in_path = os.path.join(input_dir, filename)
            out_path = os.path.join(output_dir, filename)
            future = executor.submit(process_single_file, in_path, out_path)
            futures[future] = filename

        for future in tqdm(as_completed(futures), total=len(futures), desc="处理进度"):
            filename = futures[future]
            try:
                ok, err, file_warnings = future.result()
            except Exception as e:
                ok, err, file_warnings = (
                    False,
                    f"线程异常: {type(e).__name__}: {e}",
                    [],
                )

            with lock:
                if ok:
                    success_count += 1
                    if file_warnings:
                        warning_count += len(file_warnings)
                        warnings.extend(
                            f"{filename}: {msg}" for msg in file_warnings
                        )
                else:
                    fail_count += 1
                    errors.append(f"{filename}: {err}")

    total = len(filenames)
    print(f"\n处理完成：成功 {success_count} / 失败 {fail_count} / 总计 {total}")

    if errors:
        error_log_path = os.path.join(output_dir, "error_log.txt")
        try:
            with open(error_log_path, "w", encoding="utf-8") as f:
                f.write("\n".join(errors))
            print(f"错误日志已保存至: {error_log_path}")
        except Exception as e:
            print(f"警告：无法写入错误日志: {e}")
            print("错误详情:")
            for err in errors[:10]:
                print(f"  {err}")
            if len(errors) > 10:
                print(f"  ... 还有 {len(errors) - 10} 条错误")
    else:
        print("全部处理成功，无错误记录。")

    if warnings:
        warning_log_path = os.path.join(output_dir, "warning_log.txt")
        try:
            with open(warning_log_path, "w", encoding="utf-8") as f:
                f.write("\n".join(warnings))
            print(f"告警 {warning_count} 条，已保存至: {warning_log_path}")
        except Exception as e:
            print(f"警告：无法写入告警日志: {e}")


if __name__ == "__main__":
    main()


"""
功能说明：
    这个脚本用来批量转换 LabelMe 格式的 JSON 标注文件，为 cls3 姿态估计做准备。
    它会做这几件事：
    1. 把标签名里带编号的人形框（比如 "0_person"）改成 "person"，并提取编号作为 group_id
    2. 把带编号的关键点标签（比如 "person_0_nose"）改成纯关键点名（"nose"），并配上对应的 group_id
    3. 删掉标签名里有 "fullperson" 的标注
    4. 给 head 和 face 这两个框自动分配新的 group_id（不跟人物组混用）
    5. 清理掉旧的转换标记，避免重复运行出问题
    6. 支持多线程并行处理，加快速度
    7. 自动输出错误日志和告警日志，方便检查

运行命令样例：

  # 基础用法：把 input 文件夹里的所有 JSON 标注处理后保存到 output 文件夹
  python scripts/label_transform.py \
      -i ./input \
      -o ./output

  # 指定 8 个线程并行处理
  python scripts/label_transform.py \
      -i ./input \
      -o ./output \
      -w 8

  # 使用长参数
  python scripts/label_transform.py \
      --input ./input \
      --output ./output \
      --workers 4

  # 不指定参数时，默认使用脚本顶部 INPUT_DIR 和 OUTPUT_DIR 的值（适合在 IDE 里直接运行）
  python scripts/label_transform.py
"""
