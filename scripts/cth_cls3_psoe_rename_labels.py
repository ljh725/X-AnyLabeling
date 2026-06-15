#!/usr/bin/env python
# -*- coding: utf-8 -*-

import json
from pathlib import Path

# 定义映射关系
LABEL_MAPPING = {
    "nose": "nose",
    "left_eye": "l_eye",
    "right_eye": "r_eye",
    "left_ear": "l_ear",
    "right_ear": "r_ear",
    "left_shoulder": "l_sho",
    "right_shoulder": "r_sho",
    "left_elbow": "l_elb",
    "right_elbow": "r_elb",
    "left_wrist": "l_wri",
    "right_wrist": "r_wri",
    "left_hip": "l_hip",
    "right_hip": "r_hip",
    "left_knee": "l_knee",
    "right_knee": "r_knee",
    "left_ankle": "l_ank",
    "right_ankle": "r_ank"
}

# 获取所有允许的标签名称（包括原始名称和简写）
ALLOWED_LABELS = set(LABEL_MAPPING.keys()) | set(LABEL_MAPPING.values()) | {"person", "head", "face"}

# 定义不同类型标签应该具有的形状类型
RECTANGLE_LABELS = {"person", "head", "face"}
POINT_LABELS = set(LABEL_MAPPING.keys()) | set(LABEL_MAPPING.values())

def rename_labels_in_json(json_path):
    """修改单个JSON文件中的label名称"""
    with open(json_path, 'r', encoding='utf-8') as file:
        data = json.load(file)
    
    invalid_labels = set()  # 记录无效标签
    wrong_shape_types = []  # 记录类型错误的shape
    
    # 修改shapes中的label
    for shape in data.get('shapes', []):
        original_label = shape['label']
        shape_type = shape.get('shape_type', '').lower()
        
        # 检查是否为无效标签
        if original_label not in ALLOWED_LABELS:
            invalid_labels.add(original_label)
        
        # 检查shape_type是否正确
        expected_shape_type = None
        if original_label in RECTANGLE_LABELS:
            # rectangle类型的标签应使用矩形形状
            if shape_type not in ['rectangle', 'bbox', 'box']:
                expected_shape_type = 'rectangle/bbox/box'
        elif original_label in POINT_LABELS:
            # point类型的标签应使用点形状
            if shape_type != 'point':
                expected_shape_type = 'point'
        
        if expected_shape_type:
            wrong_shape_types.append({
                'label': original_label,
                'actual_type': shape_type,
                'expected_type': expected_shape_type
            })
        
        # 如果label在映射表中，则替换为简写
        if original_label in LABEL_MAPPING:
            shape['label'] = LABEL_MAPPING[original_label]
            print(f"  已将 '{original_label}' 替换为 '{LABEL_MAPPING[original_label]}'")
    
    # 保存修改后的文件
    with open(json_path, 'w', encoding='utf-8') as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
    
    return invalid_labels, wrong_shape_types

def process_json_folder(folder_path):
    """处理文件夹中的所有JSON文件"""
    folder = Path(folder_path)
    json_files = list(folder.glob('*.json'))
    
    print(f"找到 {len(json_files)} 个JSON文件")
    
    files_with_errors = {}

    for json_file in json_files:
        print(f"正在处理: {json_file.name}")
        invalid_labels, wrong_shape_types = rename_labels_in_json(json_file)
        
        if invalid_labels or wrong_shape_types:
            files_with_errors[json_file.name] = {
                'invalid_labels': invalid_labels,
                'wrong_shape_types': wrong_shape_types
            }
        
        print(f"完成: {json_file.name}\n")
    
    # 打印包含错误的文件
    if files_with_errors:
        print("="*50)
        print("发现包含错误的文件:")
        for filename, errors in files_with_errors.items():
            print(f"\n文件: {filename}")
            
            if errors['invalid_labels']:
                print(f"  - 无效标签: {', '.join(errors['invalid_labels'])}")
            
            if errors['wrong_shape_types']:
                print(f"  - 类型错误:")
                for error in errors['wrong_shape_types']:
                    print(f"    标签 '{error['label']}' 使用了 '{error['actual_type']}' 类型，应为 '{error['expected_type']}' 类型")
    else:
        print("所有文件中没有发现错误！")
    
    print("所有JSON文件处理完成！")

if __name__ == "__main__":
    # 指定包含JSON文件的文件夹路径
    json_folder = input("请输入包含JSON文件的文件夹路径: ").strip()
    process_json_folder(json_folder)