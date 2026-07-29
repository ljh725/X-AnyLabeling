# 06 · 数据处理脚本集
#### Data Processing Toolkit

> 40 个统一 `argparse` CLI 风格的脚本，覆盖姿态数据生产全链路：标注 → 格式转换 → 数据集划分 → 可视化核验 → 模型预标注对比 → 规则质检。与规格文档、Inspector 队列深度集成。
>
> [← 返回作品集主页](../PORTFOLIO.md)

---

## 解决的痛点

姿态数据生产是一个**完整链路**，每一步都需要专门工具：

```
标注(JSON) → 格式转换(YOLO) → 数据集划分 → 可视化核验 → 模型预标注对比 → 规则质检
     ↑                                                                    │
     └────────────────────── 修复 ← 复核 ← 问题定位 ←──────────────────────┘
```

痛点：这些工具散落在各处，风格不一（有的硬编码路径、有的无 CLI 参数、有的无进度反馈），难以维护和交接。

---

## 方案：统一 CLI 风格的工具集

40 个脚本遵循统一规范：
- **`argparse` CLI** + IDE 配置区双入口（方便调试与生产两用）
- **多线程/多进程加速**（`ProcessPoolExecutor`/`ThreadPoolExecutor` + `tqdm` 进度条）
- **`orjson` 高性能解析**（处理大批量 JSON）
- **原文件只读**（`deepcopy` + `output_dir` 输出，绝不修改源数据）
- **与规格文档配套**（每个关键脚本对应一篇 spec 文档）

---

## 脚本分类

### A. YOLO Pose 三步流水线（数据集生产）

| 脚本 | 行数 | 用途 |
|------|------|------|
| [`step1-convert_json_to_yolopose.py`](../../scripts/step1-convert_json_to_yolopose.py) | 604 | LabelMe/cls3pose JSON → YOLOv8 Pose 标签（`class_id cx cy w h x1 y1 v1 ...`） |
| [`step2-split_yolov8pose_dataset.py`](../../scripts/step2-split_yolov8pose_dataset.py) | 239 | 按 train/val/test 划分 YOLO Pose 数据集 |
| [`step3-visualize_yolo_dataset.py`](../../scripts/step3-visualize_yolo_dataset.py) | 253 | 可视化 YOLO detection/pose 标签 |

**工程难点**：YOLOv8 Pose 有"同数据集固定关键点数"约束。`step1` 用所有类别 pose 并集作全局关键点顺序，缺失类别补 0，解决了多类姿态数据集转换的边界问题。

### B. ViTPose 预标注对比（数据治理）

| 脚本 | 行数 | 用途 |
|------|------|------|
| [`vitpose_rename_pred_jsons.py`](../../scripts/vitpose_rename_pred_jsons.py) | 291 | 将 `{stem}_pred.json` 按 stem 对齐图片重命名 |
| [`vitpose_labels_rename_pred_jsons.py`](../../scripts/vitpose_labels_rename_pred_jsons.py) | 396 | 按 group_id 把 ViTPose 预测关键点注入 X-AnyLabeling JSON |

**方法论价值**：用模型预测**反查人工标注盲点**——把 ViTPose 推理结果按 group_id 注入标注 JSON，对比差异，发现人工漏标/错标。配套 [`docs/qc-110_note_vitpose模型分歧排序qc方法.md`](../qc-110_note_vitpose模型分歧排序qc方法.md)。

### C. 质检 CLI（与 Inspector 联动）

| 脚本 | 行数 | 用途 |
|------|------|------|
| [`run_l1l2_qc.py`](../../scripts/run_l1l2_qc.py) | 172 | L1/L2 质检 CLI，输出 review.tsv + report.json（对接 Inspector 队列） |
| [`gen_threshold_suggestion.py`](../../scripts/gen_threshold_suggestion.py) | 113 | 阈值建议生成（见 [模块 01](01-quality-engine.md)） |
| [`validate_pose_labels_codex.py`](../../scripts/validate_pose_labels_codex.py) | 777 | 增强校验器：group_id 一致性 + head/face 重复检测 + 多格式输出 |
| [`validate_pose_labels.py`](../../scripts/validate_pose_labels.py) | 626 | pose JSON 标注校验 |

**关键**：`run_l1l2_qc.py` 输出的 review.tsv 直接被 Inspector 质检复核 Tab 导入，形成"规则定义 → CLI 执行 → 队列复核"闭环。

### D. 数据集统计与对比

| 脚本 | 用途 |
|------|------|
| [`collect_unique_labels.py`](../../scripts/collect_unique_labels.py) | 多进程提取全数据集唯一 label 集合 |
| [`compare_dataset_stems.py`](../../scripts/compare_dataset_stems.py) | 对比两目录文件名 stem，找出 A-only/B-only/共有 |
| [`stats_json_shapes.py`](../../scripts/stats_json_shapes.py) | 统计每个 JSON 的 point/rectangle/group_id 数量 |
| [`glm_compare_datasets.py`](../../scripts/glm_compare_datasets.py) | 数据集差异对比 + 报告 |

### E. 标签重排与批量操作

| 脚本 | 用途 |
|------|------|
| [`sort_pose_labels.py`](../../scripts/sort_pose_labels.py) | 按"矩形优先→有 gid 关键点→无 gid 关键点"重排 shapes |
| [`cth_cls3_psoe_rename_labels.py`](../../scripts/cth_cls3_psoe_rename_labels.py) | COCO 全称(left_eye) → 简写(l_eye) 批量重命名 |
| [`generate_empty_jsons_all.py`](../../scripts/generate_empty_jsons_all.py) | 批量生成空标注 JSON |
| [`align_image_json_pairs.py`](../../scripts/align_image_json_pairs.py) | 对齐图片与 JSON 配对 |
| [`sync_and_clear_shapes.py`](../../scripts/sync_and_clear_shapes.py) | 同步并清理 shapes |

---

## 完整数据闭环

```
┌─────────────────────────────────────────────────────────────┐
│                    姿态数据生产全链路                          │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  X-AnyLabeling 标注 (JSON)                                  │
│       │                                                     │
│       ├──► step1 转换 ──► YOLO Pose 标签                     │
│       │                         │                           │
│       │                    step2 划分 (train/val/test)       │
│       │                         │                           │
│       │                    step3 可视化核验                   │
│       │                                                     │
│       ├──► ViTPose 推理 ──► vitpose_rename ──► 注入对比       │
│       │                         (模型反查人工盲点)            │
│       │                                                     │
│       ├──► run_l1l2_qc ──► review.tsv + report.json          │
│       │                         │                           │
│       │              Inspector 质检复核 Tab 导入              │
│       │                         │                           │
│       │              人工复核 ──► review_feedback.tsv         │
│       │                         │                           │
│       │              gen_threshold_suggestion ──► 阈值建议    │
│       │                                                     │
│       └──► validate_pose_labels ──► 校验报告                 │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 工程能力体现

1. **完整数据闭环**：从 JSON 标注 → 格式转换 → 划分 → 可视化 → 预标注对比 → 规则质检，覆盖姿态数据生产全链路，而非孤立工具。

2. **质检体系化**：脚本与规格文档（[`qc-030_spec_l1_l2目标框质量校验规则规格表.md`](../qc-030_spec_l1_l2目标框质量校验规则规格表.md)、[`qc-040_spec_v0_阶段一l1_l2质检规则阈值与输出规格.md`](../qc-040_spec_v0_阶段一l1_l2质检规则阈值与输出规格.md)）配套，validate 脚本输出 Inspector 可导入的 8 列 review.tsv。

3. **预标注对比方法论**：ViTPose 脚本实现"按 group_id 注入预测关键点"的对齐策略，体现用模型预测反查人工标注盲点的数据治理思维。

4. **工程健壮性**：统一 argparse + IDE 配置区双入口、多进程加速、orjson 高性能、原文件只读。

5. **YOLO Pose 多类兼容**：step1 处理"同数据集固定关键点数"约束，用类别 pose 并集作全局顺序，工程上解决多类姿态转换边界问题。

---

## 代码定位

所有脚本位于 [`scripts/`](../../scripts/) 目录，共 **40 个 .py 文件**，核心脚本逾 3,000 行。

---

## 配套规格文档

- [`docs/qc-030_spec_l1_l2目标框质量校验规则规格表.md`](../qc-030_spec_l1_l2目标框质量校验规则规格表.md) — L1/L2 规则规格
- [`docs/qc-040_spec_v0_阶段一l1_l2质检规则阈值与输出规格.md`](../qc-040_spec_v0_阶段一l1_l2质检规则阈值与输出规格.md) — 阈值与输出规格
- [`docs/qc-110_note_vitpose模型分歧排序qc方法.md`](../qc-110_note_vitpose模型分歧排序qc方法.md) — ViTPose 分歧排序 QC 方法

---

## 截图

> `[截图待补]` — 计划补充：step3 可视化输出、ViTPose 对比报告、review.tsv 在 Inspector 中的展示
