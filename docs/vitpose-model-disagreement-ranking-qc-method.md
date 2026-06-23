将“模型分歧排序法”具体落实为使用 ViTPose + 已有 Person 框的方案，4 步流程总结如下：
### 方案：基于 ViTPose 与已有框的模型分歧排序质检法
1.  **基于已有框的 ViTPose 批量推理（全自动）**
    解析你的标注文件，提取每张图片中所有的 Person 矩形框。将图片和对应的框送入 ViTPose（Top-down 模式），模型会自动裁剪框内区域并预测 17 个 COCO 关键点坐标。输出模型预测结果集。
2.  **差异计算与可见度过滤（全自动）**
    遍历每个 Person 目标，逐个对齐人工标注和模型预测的 17 个关键点。计算两者之间的**归一化欧氏距离**（即两点距离除以 Person 框的对角线长度，消除不同人体大小带来的绝对距离差异）。**关键规则**：如果人工标注中某个关键点的可见度为 0（即未标注），直接跳过该点，不计算差异。
3.  **全量目标分歧排序（全自动）**
    将所有计算过差异的目标，按“最大单点归一化距离”从大到小进行全局排序，输出为一个包含图片名、目标ID、最大差异点名称、归一化距离值的 CSV 清单。
4.  **尾部人工抽检（极速质检）**
    两名质检员仅审查排序榜单的前 5%-10%（通常是最严重的坐标偏离或漏标）。借助可视化脚本（高亮差异最大的点），质检员快速扫视。当连续审查 20-30 个目标均显示是“姿态特殊导致模型预测偏差”而非人工标错时，即可停止往下看。


以下是**完整 Python 执行脚本**，包含了数据解析、框扩张、ViTPose 推理、差异计算与排序的全过程。你可以在本地 CPU 环境下使用少量数据测试跑通。
### 完整执行脚本：`vitpose_qa_pipeline.py`
请确保你已经按照之前的步骤安装好了 ViTPose 环境，并且下载了 `ViTPose-S` 的预训练权重。
```python
import os
import json
import math
import csv
import cv2
import numpy as np
from tqdm import tqdm
from mmpose.apis import init_pose_model, inference_top_down_pose_model
# ================= 配置区域 =================
# 模型配置文件和权重路径 (请根据你的实际路径修改)
CONFIG_FILE = 'ViTPose/configs/body/2d_kpt_sview_rgb_img/topdown_heatmap/coco/ViTPose_small_coco_256x192.py'
CHECKPOINT_FILE = 'ViTPose/pretrained/vitpose-s.pth'
DEVICE = 'cpu'  # 本地测试用 cpu，服务器部署改为 'cuda:0'
# 数据路径
IMAGE_DIR = 'path/to/your/images' # 图片文件夹
JSON_DIR = 'path/to/your/jsons'   # JSON文件夹 (假设每张图一个JSON)
OUTPUT_CSV = 'qa_result_ranked.csv'
# 框扩张比例 (因为框紧贴人体，需要扩张 20% 避免截断)
EXPAND_RATIO = 1.2
# COCO 17 关键点顺序 (供参考对照)
COCO_KEYPOINT_NAMES = [
    'nose', 'left_eye', 'right_eye', 'left_ear', 'right_ear',
    'left_shoulder', 'right_shoulder', 'left_elbow', 'right_elbow',
    'left_wrist', 'right_wrist', 'left_hip', 'right_hip',
    'left_knee', 'right_knee', 'left_ankle', 'right_ankle'
]
# ============================================
def expand_bbox(bbox, img_width, img_height, ratio=1.2):
    """扩张边界框，并确保不越界"""
    x1, y1, x2, y2 = bbox
    w = x2 - x1
    h = y2 - y1
    cx = x1 + w / 2
    cy = y1 + h / 2
    
    new_w = w * ratio
    new_h = h * ratio
    
    new_x1 = max(0, cx - new_w / 2)
    new_y1 = max(0, cy - new_h / 2)
    new_x2 = min(img_width, cx + new_w / 2)
    new_y2 = min(img_height, cy + new_h / 2)
    
    return [new_x1, new_y1, new_x2, new_y2]
def parse_labelme_json(json_path):
    """解析 LabelMe JSON，提取 Person 框和对应的 17 个关键点"""
    with open(json_path, 'r') as f:
        data = json.load(f)
    
    persons = []
    # 1. 先找出所有的 Person 框
    person_bboxes = {}
    for shape in data['shapes']:
        if shape['label'] == 'person' and shape['shape_type'] == 'rectangle':
            gid = shape['group_id']
            if gid is not None:
                # points 格式: [[x1,y1], [x2,y2]]
                x1, y1 = shape['points'][0]
                x2, y2 = shape['points'][1]
                person_bboxes[gid] = [x1, y1, x2, y2]
    
    # 2. 找出对应 group_id 的关键点
    for gid, bbox in person_bboxes.items():
        keypoints = []
        is_visible = []
        # 按 COCO 顺序初始化
        point_dict = {}
        for shape in data['shapes']:
            if shape['group_id'] == gid and shape['shape_type'] == 'point':
                pt_name = shape['label']
                # 尝试匹配 COCO 名称
                if pt_name in COCO_KEYPOINT_NAMES:
                    px, py = shape['points'][0]
                    # 检查 description 是否为 invisible
                    desc = shape.get('description', '')
                    visible = 0 if (desc and 'invisible' in desc.lower()) else 1
                    point_dict[pt_name] = (px, py, visible)
        
        # 组装成 [x, y, v] 列表，顺序严格按 COCO_KEYPOINT_NAMES
        for name in COCO_KEYPOINT_NAMES:
            if name in point_dict:
                keypoints.append([point_dict[name][0], point_dict[name][1]])
                is_visible.append(point_dict[name][2])
            else:
                # 如果该点完全没标，记为不可见
                keypoints.append([0.0, 0.0])
                is_visible.append(0)
                
        persons.append({
            'bbox': bbox,
            'keypoints': np.array(keypoints),
            'is_visible': np.array(is_visible)
        })
    return persons, data['imageWidth'], data['imageHeight']
def main():
    print("正在初始化 ViTPose 模型...")
    model = init_pose_model(CONFIG_FILE, CHECKPOINT_FILE, device=DEVICE)
    
    json_files = [f for f in os.listdir(JSON_DIR) if f.endswith('.json')]
    
    all_results = []
    
    print(f"开始处理 {len(json_files)} 个 JSON 文件...")
    for json_file in tqdm(json_files):
        json_path = os.path.join(JSON_DIR, json_file)
        # 假设图片名和 json 名相同，后缀不同
        base_name = os.path.splitext(json_file)[0]
        img_path = os.path.join(IMAGE_DIR, base_name + '.jpg') # 根据实际后缀修改
        
        if not os.path.exists(img_path):
            continue
            
        img = cv2.imread(img_path)
        if img is None:
            continue
            
        img_h, img_w = img.shape[:2]
        
        # 1. 解析数据
        persons, json_w, json_h = parse_labelme_json(json_path)
        if not persons:
            continue
            
        # 2. 准备 ViTPose 输入 (扩张框)
        person_results_input = []
        for p in persons:
            expanded_bbox = expand_bbox(p['bbox'], img_w, img_h, EXPAND_RATIO)
            person_results_input.append({'bbox': expanded_bbox})
            
        # 3. 模型推理
        pose_results, _ = inference_top_down_pose_model(
            model, img, person_results_input, bbox_thr=0.0, format='xyxy',
            dataset='TopDownCocoDataset'
        )
        
        # 4. 计算差异
        for i, p in enumerate(persons):
            human_kpts = p['keypoints']      # (17, 2)
            visible_flags = p['is_visible']  # (17,)
            model_kpts = pose_results[i]['keypoints'][:, :2] # (17, 2) 只取xy
            
            # 计算框对角线长度用于归一化
            x1, y1, x2, y2 = p['bbox']
            diag = math.sqrt((x2-x1)**2 + (y2-y1)**2)
            if diag == 0: continue
            
            max_dist = 0.0
            max_dist_idx = -1
            
            for j in range(17):
                if visible_flags[j] == 0:
                    continue # 跳过 invisible 点
                    
                hx, hy = human_kpts[j]
                mx, my = model_kpts[j]
                
                dist = math.sqrt((hx - mx)**2 + (hy - my)**2)
                norm_dist = dist / diag
                
                if norm_dist > max_dist:
                    max_dist = norm_dist
                    max_dist_idx = j
                    
            if max_dist_idx != -1:
                all_results.append({
                    'image': base_name + '.jpg',
                    'group_id': i, # 或者从原始数据中保留真实的 group_id
                    'max_dist': max_dist,
                    'max_dist_point': COCO_KEYPOINT_NAMES[max_dist_idx]
                })
                
    # 5. 排序并输出 CSV
    all_results.sort(key=lambda x: x['max_dist'], reverse=True)
    
    with open(OUTPUT_CSV, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['image', 'group_id', 'max_dist', 'max_dist_point'])
        writer.writeheader()
        writer.writerows(all_results)
        
    print(f"处理完成！结果已保存至 {OUTPUT_CSV}")
if __name__ == '__main__':
    main()
```
### 使用说明与测试建议
1.  **配置路径**：修改脚本顶部的 `CONFIG_FILE`、`CHECKPOINT_FILE`、`IMAGE_DIR` 和 `JSON_DIR` 为你本地的实际路径。
2.  **图片后缀**：脚本中默认假设图片是 `.jpg`，如果你的图片是 `.png`，请修改第 106 行的 `base_name + '.jpg'`。
3.  **关键点名称匹配**：脚本在 `parse_labelme_json` 函数中，通过 `shape['label']` 匹配 COCO 的 17 个关键点名称（如 `nose`, `left_eye` 等）。**请确保你 JSON 中的关键点 label 与 `COCO_KEYPOINT_NAMES` 列表中的名称完全一致（区分大小写）**。如果不一致，你需要修改 `COCO_KEYPOINT_NAMES` 列表以适应你的数据。
4.  **本地 CPU 测试**：在本地 CPU 环境下，建议不要跑全部数据。可以先在 `JSON_DIR` 中只放 5-10 个 JSON 文件，跑通流程，看看生成的 `qa_result_ranked.csv` 是否符合预期。
5.  **可视化验证**：你可以写一个简单的辅助脚本，读取 CSV 中的前几名，用 OpenCV 将人工点（绿色）和模型点（红色）画在图片上，直观看一下差异是否真的很大。
这个脚本完全实现了“模型分歧排序法”的核心逻辑，并且针对你的框紧贴、`invisible` 标记等特殊需求做了适配。一旦在本地 CPU 跑通，部署到 3090 服务器只需将 `DEVICE` 改为 `'cuda:0'` 并换上 `ViTPose-B` 的配置和权重即可全量运行。

