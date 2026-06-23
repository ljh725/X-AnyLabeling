# 姿态标注质检流水线开发文档

> **目标**:对 3.5 万张图、约 5 万个人工标注目标做批处理质检,自动发现"nose 标到
> 脚踝""左右关键点互换"等视觉语义错误,把全量数据压缩为 5%~10% 高风险尾部样本,
> 供人工复查。
>
> **架构选型(已确认)**:方式 A —— 用**人工标注的 person 框**喂 ViTPose(纯
> Transformer 姿态模型,ONNX 推理)预测 17 个 COCO 关键点,再与人工关键点比对
> **OKS + 归一化距离**,按分歧程度排序输出可疑清单。
>
> **关联文档**:`docs/visual_semantic_annotation_quality_strategy.md` 的 **L3 模型
> 差异层 + 阶段二(外部模型结果导入)**。本脚本即该策略的落地实现之一。框的质量
> 检查(方式 A 的盲区)交给 L1/L2 几何规则,不在此脚本范围内。

---

## 一、需求与约束

### 1.1 核心需求

| 维度 | 要求 |
|------|------|
| 数据规模 | 3.5 万张图、约 5 万目标 |
| 性能 | 单卡 GPU 半小时内跑完全量推理 + 比对 |
| 输入 | 标注 JSON 目录(X-AnyLabeling 格式)+ 对应图片目录 |
| 模型 | ViTPose(纯 Transformer,ONNX),关键点检测 |
| 检测器 | **不跑检测器** —— 直接读人工 person 框 |
| 指标 | OKS(COCO 标准)+ 归一化距离(除以 person 框对角线/高度) |
| 输出 | 汇总报告(JSON + Markdown)+ 可疑清单(按风险分排序,取尾部 5%~10%) |
| 难点 | 侧身姿态多、关键点可见性不一致(`description: "invisible"`)、部分 person 不完整 |

### 1.2 关键约束(从真实标注数据 `scripts/s1860.json` 提炼)

这些是写脚本**必须处理**的现实情况,不处理会出错或漏判:

1. **关键点 label 用缩写**(不是 `left_shoulder`):
   ```
   nose, l_eye, r_eye, l_ear, r_ear, l_sho, r_sho, l_elb, r_elb,
   l_wri, r_wri, l_hip, r_hip, l_knee, r_knee, l_ank, r_ank
   ```
   正好 17 个 COCO 点,顺序与 `pose_constants.COCO_KEYPOINT_ORDER` 一致。

2. **可见性藏在 `description` 字段**:`"invisible"` 表示该点被遮挡/不可见,
   空字符串 `""` / `null` 表示可见。**OKS 计算必须区分** —— 不可见点不参与距离
   惩罚(COCO 约定:ground truth 标记为 not-labeled/occluded 的点不计算)。

3. **person 框与关键点通过 `group_id` 关联**:同一个 `group_id` 下的 `person`
   rectangle + 所有 point shape 构成一个人的完整标注。

4. **不是每个 person 都有全部 17 点**:如 group 3 缺 nose/l_eye/l_ear/l_knee/
   l_ank/r_ank(部分点漏标或不可见)。脚本要对缺失点做容错,不报错。

5. **person 框可能与 head/face 框 group_id 不共享**:head/face 是独立 group(见
   s1860.json 里 person group_id=0 但 head group_id=18)。脚本只关心 person 框,
   head/face 由 L1/L2 规则处理,不在此脚本范围。

6. **rectangle points 是两个对角点**:`[[x1,y1],[x2,y2]]`,不是四个角。需自行
   解析成 `(x1,y1,x2,y2)`(注意 x1 可能大于 x2)。

7. **图片路径**:`imagePath` 字段是相对标注文件目录的文件名(如 `s1860.jpg`),
   需要拼接图片目录。`imageData` 为 null,不内嵌。

### 1.3 不做的事(边界)

- ❌ 不做检测(不跑 RTMDet/YOLOX),检测框完全用人工标注。
- ❌ 不检查 person 框本身的对错(交给 L1/L2 几何规则)。
- ❌ 不检查 face/head 框关系(同上)。
- ❌ 不自动修正标注(只排序、只报告,人工复查才是终判)。
- ❌ 不集成进 X-AnyLabeling UI(独立脚本,符合策略文档"阶段二:外部脚本"原则)。
- ❌ 不做 SAM 级联(策略文档提到的可选增强,本版不做)。

---

## 二、整体设计

### 2.1 流水线总览

```
┌─────────────────────────────────────────────────────────────────┐
│  输入: 标注 JSON 目录 + 图片目录                                  │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
        ┌──────────────────────────────────────┐
        │  Step 1: 解析人工标注                  │
        │  - 遍历每个 JSON                       │
        │  - 按 group_id 聚合 person 框 + 关键点  │
        │  - 标记每个点的可见性(description)      │
        │  - 对齐到 17 点标准顺序                 │
        └──────────────────┬───────────────────┘
                           │
                           ▼
        ┌──────────────────────────────────────┐
        │  Step 2: ViTPose 推理(ONNX)            │
        │  - 读图                                │
        │  - 对每个人工 person 框做 top-down:     │
        │      bbox_xyxy2cs(padding=1.25)        │
        │      → top_down_affine(192×256)        │
        │      → 归一化 → ViTPose ONNX            │
        │      → heatmap argmax + 亚像素          │
        │      → 反映射回原图坐标                 │
        │  - 输出每个框的 17 点 (x,y) + score     │
        └──────────────────┬───────────────────┘
                           │
                           ▼
        ┌──────────────────────────────────────┐
        │  Step 3: 比对(OKS + 归一化距离)         │
        │  - 人工框 IoU 匹配(此处框相同,跳过)     │
        │  - 对每个可见关键点:                    │
        │      计算欧氏距离                       │
        │      归一化(÷ person 框对角线)          │
        │      计算 OKS                          │
        │  - 聚合到目标级分数                     │
        └──────────────────┬───────────────────┘
                           │
                           ▼
        ┌──────────────────────────────────────┐
        │  Step 4: 排序 + 输出                    │
        │  - 按风险分(1-OKS 或最大归一化距离)排序 │
        │  - 取尾部 5%~10% 作为可疑清单           │
        │  - 输出 JSON 报告 + Markdown 报告        │
        └──────────────────────────────────────┘
```

### 2.2 文件清单

| # | 操作 | 文件 | 说明 |
|---|------|------|------|
| 1 | **已有** | `pose_qa/export/export_vitpose_onnx.py` | ViTPose ONNX 导出脚本 |
| 2 | **已有** | `pose_qa/inference/vitpose_inference_demo.py` | 单图推理 demo(含可视化 + 输出 `_pred.json`) |
| 3 | **已有** | `pose_qa/qa/pose_qa_compare.py` | QA 比对(OKS + 排序 + 报告) |
| 4 | **已有** | `pose_qa/docs/pipeline_design.md` | 本文档 |
| 5 | **已有** | `pose_qa/docs/quality_strategy.md` | 四层质检策略 |
| 6 | **待写** | `pose_qa/inference/batch_infer.py` | 批量推理(遍历目录) |
| 7 | **待写** | `pose_qa/README.md` | 使用说明(环境/导出/运行步骤) |

所有 Pose QA 相关文件集中在 `pose_qa/` 一棵树下。三阶段目录 `export/` →
`inference/` → `qa/` 对应流水线的"导出模型 → 推理 → 比对排序"。脚本风格沿用
`scripts/stats_json_shapes.py` 的"CONFIG 变量 + CLI + 线程池"。

### 2.3 运行依赖

```
# 推理(脚本运行时)
onnxruntime          # 或 onnxruntime-gpu,CPU/GPU 二选一,不可同装
numpy
opencv-python
pyyaml               # 读配置(可选)
tqdm                 # 进度条(已有 fallback)

# 导出 ONNX(仅运行 export_vitpose_onnx.py 时需要,不在质检依赖里)
mmpose
mmpretrain
mmengine
torch
```

---

## 三、核心算法

### 3.1 关键点顺序对齐(★最容易出错的地方)

ViTPose 输出顺序是 COCO 标准 17 点,你的标注 label 是缩写。必须建立映射表:

```python
# COCO 标准 17 点顺序(ViTPose 输出就是这个顺序)
COCO_17_ORDER = [
    "nose",                                           # 0
    "l_eye", "r_eye",                                 # 1, 2
    "l_ear", "r_ear",                                 # 3, 4
    "l_sho", "r_sho",                                 # 5, 6
    "l_elb", "r_elb",                                 # 7, 8
    "l_wri", "r_wri",                                 # 9, 10
    "l_hip", "r_hip",                                 # 11, 12
    "l_knee", "r_knee",                               # 13, 14
    "l_ank", "r_ank",                                 # 15, 16
]

LABEL_TO_IDX = {name: i for i, name in enumerate(COCO_17_ORDER)}
```

**注意**:`pose_constants.COCO_KEYPOINT_ORDER` 用的也是这套缩写,可复用,避免重复
定义。从 `anylabeling.views.labeling.widgets.pose_label.pose_constants` import。

### 3.2 人工标注解析

对每个 JSON,产出 `List[AnnotatedPerson]`:

```python
@dataclass
class AnnotatedPerson:
    json_path: str
    image_path: str
    group_id: int
    bbox: tuple[float, float, float, float]  # (x1, y1, x2, y2), 已排序
    keypoints: np.ndarray  # shape (17, 2), 缺失点用 NaN
    visibility: np.ndarray  # shape (17,), True=可见, False=不可见/缺失
```

解析逻辑:
1. 遍历 shapes,按 `group_id` 分组。
2. 每个 group 找 `label == "person" and shape_type == "rectangle"`,取其两角点
   排序成 `(min_x, min_y, max_x, max_y)`。
3. 同 group 的 point shapes,按 `label` 映射到 17 点数组对应位置。
4. `description` 字段:`"invisible"` → `visibility[i] = False`,其他 → `True`。
5. 该 group 没有 person rectangle → 跳过(记录到日志,方式 A 不处理无框 person)。
6. 缺失的关键点位置填 `NaN`,visibility 填 `False`。

**容错清单**(必须处理):
- rectangle 两点顺序乱(x1>x2 或 y1>y2)→ 排序。
- 关键点 label 不在 17 点表内(如笔误)→ 跳过 + 记日志。
- 同一 group 同一 label 出现多次 → 取最后一个 + 记警告。
- group_id 为 null 的 shape → 单独成组或跳过(记日志)。
- 图片文件不存在 → 跳过推理,记入错误报告。

### 3.3 ViTPose 推理(★核心,复用项目几何函数)

**关键复用**:`anylabeling/services/auto_labeling/pose/dwpose_onnx.py` 的几何函数
(`bbox_xyxy2cs`、`top_down_affine`、`get_warp_matrix`)是通用 top-down 预处理
代码,**ViTPose 直接复用**,不用重写。这些函数已被项目验证可用。

**不复用**的:DWPose 的 `decode` 是 SimCC 解码,ViTPose 是 heatmap,需新写解码。

**推理类设计**(`pose_qa_lib.py` 内):

```python
class ViTPoseRunner:
    """ViTPose ONNX top-down 推理器(批处理友好)。"""

    def __init__(
        self,
        onnx_path: str,
        input_size: tuple[int, int] = (192, 256),  # (w, h)
        device: str = "gpu",
        mean: tuple[float, float, float] = (123.675, 116.28, 103.53),
        std: tuple[float, float, float] = (58.395, 57.12, 57.375),
    ):
        from anylabeling.services.auto_labeling.engines import OnnxBaseModel
        from anylabeling.services.auto_labeling.pose.dwpose_onnx import (
            bbox_xyxy2cs, top_down_affine
        )
        self.net = OnnxBaseModel(onnx_path, device_type=device)
        self.input_w, self.input_h = input_size
        self.mean = np.array(mean)
        self.std = np.array(std)
        self._bbox_xyxy2cs = bbox_xyxy2cs
        self._top_down_affine = top_down_affine

    def predict(
        self, image_bgr: np.ndarray, bboxes: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray]:
        """对一张图的多个 person 框批量推理。

        Args:
            image_bgr: 原图(BGR, HxWx3)
            bboxes: (N, 4) person 框 (x1,y1,x2,y2)

        Returns:
            keypoints: (N, 17, 2) 原图坐标
            scores: (N, 17) 置信度(0~1)
        """
        if len(bboxes) == 0:
            return (np.empty((0, 17, 2)), np.empty((0, 17)))

        blobs, centers, scales = [], [], []
        for bbox in bboxes:
            center, scale = self._bbox_xyxy2cs(
                np.array(bbox, dtype=np.float32), padding=1.25
            )
            resized, scale = self._top_down_affine(
                (self.input_w, self.input_h), scale, center, image_bgr
            )
            resized = (resized - self.mean) / self.std
            blobs.append(
                resized.transpose(2, 0, 1).astype(np.float32)
            )
            centers.append(center)
            scales.append(scale)

        blob = np.stack(blobs, axis=0)  # (N, 3, H, W)
        heatmaps = self.net.get_ort_inference(blob)  # (N, 17, h, w)

        keypoints, scores = self._decode_heatmaps(
            heatmaps, centers, scales
        )
        return keypoints, scores

    def _decode_heatmaps(
        self, heatmaps, centers, scales
    ) -> tuple[np.ndarray, np.ndarray]:
        """heatmap → 关键点坐标。新写(ViTPose 是 heatmap,DWPose 是 SimCC)。"""
        n, k, hm_h, hm_w = heatmaps.shape
        stride_x = self.input_w / hm_w
        stride_y = self.input_h / hm_h
        keypoints = np.zeros((n, k, 2), dtype=np.float32)
        scores = np.zeros((n, k), dtype=np.float32)

        for i in range(n):
            for j in range(k):
                hm = heatmaps[i, j]
                py, px = np.unravel_index(np.argmax(hm), hm.shape)
                # 亚像素(可选,一阶泰勒,精度不够再加):
                # py, px = refine_with_dark(hm, py, px)
                keypoints[i, j] = [px * stride_x, py * stride_y]
                scores[i, j] = hm[py, px]
            # 反映射回原图(公式来自 dwpose_onnx.postprocess):
            s, c = scales[i], centers[i]
            keypoints[i, :, 0] = (
                keypoints[i, :, 0] / self.input_w * s[0] + c[0] - s[0] / 2
            )
            keypoints[i, :, 1] = (
                keypoints[i, :, 1] / self.input_h * s[1] + c[1] - s[1] / 2
            )
        return keypoints, scores
```

**实现要点**:
- `bbox_xyxy2cs` 和 `top_down_affine` 直接从项目 import,不复制代码。
- heatmap 尺度通常是输入的 1/4,stride 自动推算(`input_w/hm_w`),**不硬编码 4**。
- 坐标反向映射公式直接照搬 `dwpose_onnx.py` 的 `postprocess`。
- **归一化常数待验证**:默认用 mmpose 标准 `[123.675,...]/[58.395,...]`(不除
  255)。若导出 ONNX 时已含归一化,这里要去掉。导出脚本 docstring 会提示如何确认。
- 亚像素细化(DARK 算法):第一版可只做整数 argmax,精度不够再加。对质检排序够
  用,因为只看相对分歧,不追求绝对精度。

**性能优化(3.5 万图必做)**:
- 一张图内的多个 person 框 **batch 推理**(`np.stack` 后一次喂 ONNX),不要逐
  个循环调模型。
- 图片读取消耗大,用线程池并发读图 + 主线程串行推理(GPU 推理是瓶颈,读图重叠
  掉)。
- 大批量可分 chunk(如每 32 个框一组),避免显存溢出。

### 3.4 比对:OKS + 归一化距离

**OKS(Object Keypoint Similarity)** —— COCO 标准姿态相似度,值域 [0,1],越大越
相似。公式:

```
OKS = Σ exp(-d²ᵢ / 2·s·k²ᵢ) · δ(vᵢ>0) / Σ δ(vᵢ>0)

dᵢ  = 第 i 个关键点的欧氏距离(人工 vs 模型)
s   = 目标尺度 = person 框面积 / 常数(或 person 框对角线)
kᵢ  = 第 i 个关键点的 per-keypoint 尺度因子(COCO 标准值,见下)
δ   = 可见性门控:只对人工标注为可见的点计算
```

**COCO 17 点 k 值**(官方常数,固定):
```python
KAPPA = np.array([
    0.026, 0.025, 0.025, 0.035, 0.035,  # nose, eye, eye, ear, ear
    0.079, 0.079, 0.072, 0.072, 0.062, 0.062,  # sho, sho, elb, elb, wri, wri
    0.107, 0.107, 0.087, 0.087, 0.089, 0.089,  # hip, hip, knee, knee, ank, ank
])
```

**尺度 s 的选择**(三种常见做法,推荐第 2 种):
1. `s = person 框面积 / 10000`(COCO 原版,框很大时 OKS 偏乐观)。
2. `s = person 框对角线长度`(项目质检用,对侧身/瘦长框更稳)。
3. `s = person 框高度`(最简单,但侧躺时失效)。

**归一化距离**(辅助指标,直观):
```
norm_dist_i = dᵢ / person_box_diagonal
```
配合 OKS 用:OKS 是整体相似度,归一化距离能定位"具体哪个点偏得最远"。

**目标级风险分**(用于排序,综合 OKS 和距离):
```python
def risk_score(oks, max_norm_dist, n_visible):
    """风险分越高越可疑。"""
    if n_visible == 0:
        return 0.0  # 没有可比点,不判
    # 主分:1 - OKS(差异越大分越高)
    main = 1.0 - oks
    # 加权:如果单点严重偏移(max_norm_dist > 0.3),额外加分
    if max_norm_dist > 0.3:
        main += 0.2 * min(max_norm_dist, 1.0)
    return main
```

**比对函数**:
```python
def compare_person(
    gt_kpts: np.ndarray,      # (17,2) 人工点, NaN=缺失
    gt_vis: np.ndarray,       # (17,)  人工可见性
    pred_kpts: np.ndarray,    # (17,2) 模型点
    bbox: tuple,              # person 框
) -> dict:
    diag = np.sqrt((bbox[2]-bbox[0])**2 + (bbox[3]-bbox[1])**2)
    mask = gt_vis & ~np.isnan(gt_kpts[:, 0])  # 可见且有人工坐标
    if mask.sum() == 0:
        return {"oks": None, "valid": 0, "max_norm_dist": None,
                "worst_kpt": None}

    d = np.linalg.norm(gt_kpts - pred_kpts, axis=1)  # (17,)
    norm_d = d / diag

    s = diag  # 用对角线作尺度
    oks_terms = np.exp(-(d[mask]**2) / (2 * s * KAPPA[mask]**2))
    oks = oks_terms.mean()

    worst_idx = np.where(mask)[0][np.argmax(norm_d[mask])]
    return {
        "oks": float(oks),
        "valid": int(mask.sum()),
        "max_norm_dist": float(norm_d[mask].max()),
        "worst_kpt": COCO_17_ORDER[worst_idx],
        "per_kpt_norm_dist": {
            COCO_17_ORDER[i]: float(norm_d[i])
            for i in range(17) if mask[i]
        },
    }
```

**重要**:
- 不可见点(`gt_vis=False`)和缺失点(NaN)**都不参与** OKS 和距离计算,这是 COCO
  约定。否则遮挡点会大量误报。
- 模型预测的 score 也应设阈值(如 `< 0.3` 的模型点视为模型自己也不确定,降权或
  不计入最坏点),避免"模型没看清 → 假分歧"。

### 3.5 可疑清单筛选

两种策略(可配置,默认都用):

1. **绝对阈值**:OKS < 0.5 或 max_norm_dist > 0.2 的目标直接进可疑清单。
2. **分位数**:按风险分排序,取尾部 top 5%~10%。

策略文档 L4 建议初期**简单优先级排序**,不过度设计评分模型。所以:
- 默认按风险分降序。
- 输出全量 + 标记"是否在尾部 10%"。
- 用户可调 `--tail-percent` 参数。

---

## 四、输出格式

### 4.1 汇总报告 JSON(`<output_prefix>.json`)

```json
{
  "config": {
    "json_dir": "D:/data/labels",
    "image_dir": "D:/data/images",
    "vitpose_onnx": "D:/models/vitpose-b-coco.onnx",
    "device": "gpu",
    "input_size": [192, 256],
    "tail_percent": 10
  },
  "summary": {
    "total_images": 35000,
    "processed_images": 34987,
    "failed_images": 13,
    "total_persons": 51203,
    "comparable_persons": 50180,
    "uncomparable_persons": 1023,
    "tail_persons": 5018,
    "oks_distribution": {
      "mean": 0.82, "median": 0.88, "p10": 0.45, "p90": 0.95
    }
  },
  "per_image": [
    {
      "json_path": "D:/data/labels/s1860.json",
      "image_path": "D:/data/images/s1860.jpg",
      "persons": [
        {
          "group_id": 0,
          "oks": 0.91,
          "max_norm_dist": 0.12,
          "worst_kpt": "l_ear",
          "valid_kpts": 16,
          "in_tail": false,
          "risk_score": 0.09
        },
        {
          "group_id": 3,
          "oks": 0.28,
          "max_norm_dist": 0.61,
          "worst_kpt": "nose",
          "valid_kpts": 11,
          "in_tail": true,
          "risk_score": 0.94,
          "per_kpt_norm_dist": {
            "nose": 0.61, "r_eye": 0.04, "r_ear": 0.05
          }
        }
      ]
    }
  ],
  "failures": [
    {"json_path": "...", "reason": "image not found"},
    {"json_path": "...", "reason": "no person rectangle"}
  ]
}
```

### 4.2 Markdown 报告(`<output_prefix>.md`)

仿 `stats_json_shapes.py` 的 `generate_markdown` 风格:
- Summary 表格(总数/失败数/可比数/OKS 分布)。
- **Top 50 可疑目标表**(风险分降序):图片名 / group_id / OKS / 最坏点 /
  归一化距离 / 可比点数。
- 失败文件列表。

### 4.3 可疑清单(可选独立文件 `<output_prefix>_tail.txt`)

纯文件名列表(去重),方便喂给后续工具或直接在 X-AnyLabeling 里打开复查:
```
s1860.jpg
s1861.jpg
...
```

---

## 五、主脚本结构(`pose_qa/qa/pose_qa_compare.py`)

完全仿 `stats_json_shapes.py` 的风格(CONFIG 变量 + CLI + 线程池):

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pose annotation QA pipeline: ViTPose vs human annotation."""

# ============================================
# CONFIG 区域 - 变量配置模式
# ============================================

JSON_DIR: str = r"D:\data\labels"
IMAGE_DIR: str = r"D:\data\images"
VITPOSE_ONNX: str = r"D:\models\vitpose-b-coco.onnx"
OUTPUT_PREFIX: str = r"D:\report\pose_qa"
DEVICE: str = "gpu"              # "cpu" or "gpu"
INPUT_SIZE: tuple = (192, 256)   # (w, h)
TAIL_PERCENT: float = 10.0       # 尾部可疑比例
KPT_SCORE_THR: float = 0.3       # 模型点置信度阈值
WORKERS: int = 4                 # 读图线程数
NO_PROGRESS: bool = False

# ============================================
# 主流程
# ============================================

def main():
    cfg = merge_config(parse_args())
    # 1. 收集 JSON 路径
    json_paths = collect_json_paths(cfg["json_dir"])
    # 2. 加载 ViTPose(单例,线程间共享)
    runner = ViTPoseRunner(cfg["vitpose_onnx"], cfg["input_size"],
                          device=cfg["device"])
    # 3. 逐图处理(读图用线程池,推理串行 - GPU 是瓶颈)
    results = process_all(json_paths, runner, cfg)
    # 4. 计算风险分 + 排序 + 筛尾部
    ranked = rank_and_tail(results, cfg["tail_percent"])
    # 5. 输出报告
    write_reports(ranked, cfg)
```

**线程模型说明**:
- **推理必须串行**(GPU 单卡,并发推理反而因上下文切换变慢)。
- **读图可以并发**(IO 密集):用一个 producer-consumer 队列,读图线程喂图,主
  线程消费推理。或简单点:预先用线程池把一批图读进内存,再批量推理。
- 不要用 `ThreadPoolExecutor` 并发推理(ONNX session 不是线程安全的,会崩或变
  慢)。

---

## 六、ViTPose ONNX 导出脚本

**文件**:`pose_qa/export/export_vitpose_onnx.py`

ViTPose 官方只发 PyTorch 权重,需导出 ONNX。这是**一次性准备步骤**,不在质检主
流程里。

**前置**:`pip install mmpose mmpretrain mmengine torch`

**步骤**(脚本 docstring 要写清楚):
1. 从 [ViTPose Model Zoo](https://github.com/ViTAE-Transformer/ViTPose#model-zoo)
   下载 `.pth`,如 `vitpose-b-coco.pth`(COCO 17 点版,**不要**下 wholebody)。
2. 找对应 mmpose config,如
   `mmpose/configs/body/2d_kpt_sview_rgb_img/topdown_heatmap/coco/ViTPose_base_coco_256x192.py`。
3. 运行:
   ```
   python pose_qa/export/export_vitpose_onnx.py \
       --config <mmpose_config.py> \
       --checkpoint <vitpose-b-coco.pth> \
       --output vitpose-b-coco.onnx \
       --input-size 256 192
   ```

**脚本核心**:
```python
def main():
    args = parse_args()
    from mmpose.apis import init_pose_model
    import torch

    model = init_pose_model(args.config, args.checkpoint, device="cpu")
    model.eval()
    h, w = args.input_size
    dummy = torch.randn(1, 3, h, w)

    torch.onnx.export(
        model, dummy, args.output,
        input_names=["input"], output_names=["output"],
        opset_version=11,
        dynamic_axes=None,  # 静态 batch=1,推理端自己 stack
    )
    print(f"Exported: {args.output}")
    print(f"Verify input shape: (1, 3, {h}, {w})")
    print(f"Expected output: (1, 17, {h//4}, {w//4})")
```

**归一化验证(关键)**:导出后必须确认 ONNX 是否含归一化:
```python
# 验证脚本片段(可放进 export 脚本末尾)
import onnxruntime as ort
import numpy as np
sess = ort.InferenceSession("vitpose-b-coco.onnx")
# 喂一张已知图,看输出是否合理
# 如果喂 0-255 原图输出合理 → ONNX 含归一化,推理端不归一化
# 如果必须手动 (img-mean)/std 才合理 → ONNX 不含归一化,推理端要归一化
```
导出脚本末尾自动跑这个验证,打印结论,避免用户踩坑。

---

## 七、验证方案

### 7.1 单元测试(无需模型/图片)

放 `tests/test_pose_qa_lib.py`,测纯逻辑:

1. **解析测试**:用 `scripts/s1860.json` 作 fixture,断言:
   - 解析出 9 个 person(group 0~9)。
   - group 0 有 person 框 + 15 个点(group 0 实际有 15 个 point,缺 r_ear)。
   - group 2 的 `r_sho` visibility=False(description="invisible")。
   - group 3 缺失点用 NaN + visibility=False。

2. **比对测试**:构造已知 GT 和 pred,断言 OKS 计算正确:
   - GT=pred 时 OKS=1.0。
   - 单点偏移一定距离,OKS 下降符合公式。
   - 不可见点不参与计算。

3. **排序测试**:构造多个目标不同 OKS,断言风险分降序、尾部筛选数量正确。

4. **bbox 解析测试**:两点乱序输入 → 正确排序成 `(min,min,max,max)`。

### 7.2 集成验证(需 ONNX + 少量真实图)

1. 先跑导出脚本拿到 ONNX。
2. 用 `scripts/s1860.json` + 对应图片单图跑通。
3. 检查输出:9 个 person 都有 OKS,group 0(标注好的)OKS 应较高(>0.7),
   人为改坏一个点(如把某 person 的 nose 坐标改成脚踝位置)→ 该 person OKS
   暴跌、进尾部。
4. 小批量跑 100 张图,确认无崩溃、性能符合预期。
5. 全量跑 3.5 万图。

### 7.3 性能基线

- 单图单 person 推理应 < 50ms(GPU)。
- 3.5 万图 × 平均 1.5 person/图 ≈ 5.25 万次推理,batch 后应在 20~30 分钟内。
- 读图 IO 不应成为瓶颈(线程池预读)。
- 内存:避免一次性 load 所有图,流式处理。

---

## 八、风险与应对

| 风险 | 影响 | 应对 |
|------|------|------|
| ONNX 归一化不一致 | 所有点偏移,全量误报 | 导出脚本自动验证 + 打印结论;推理端归一化做成可配置开关 |
| 人工框画错 | ViTPose 出错的点,误判为人工点错 | 这是方式 A 固有局限;框错交给 L1/L2 规则;报告里附 person 框坐标供人工复核 |
| heatmap stride 非固定 4 | 坐标错位 | stride 自动推算,不硬编码 |
| 侧身/遮挡 OKS 偏低 | 误报多 | OKS 的 kappa 已对遮挡点宽松;额外设模型 score 阈值过滤"模型自己不确定"的点 |
| person 框对角线作尺度在极端框(极扁/极瘦)下不稳 | OKS 失真 | 监控框长宽比,极端框标注 warning,人工复核 |
| 3.5 万图耗时超预期 | 跑不完 | batch 推理 + 读图并发;可分批跑(脚本支持断点续跑:跳过已输出的图) |
| onnxruntime 线程不安全 | 崩溃 | 推理严格串行,只用读图并发 |
| 部分 JSON 没有 person 框(只有点) | 该 person 无法推理 | 跳过 + 记 failures,不影响其他 |

---

## 九、执行顺序

1. **步骤 6**(导出脚本)—— 先有 ONNX 才能测推理。可先用 ViTPose-B COCO 版。
2. **步骤 2**(`pose_qa_lib.py`)—— 解析 + 比对 + 排序逻辑,配单元测试。
3. **步骤 1**(`pose_qa_pipeline.py`)—— 主脚本,串起 lib。
4. **7.1 单元测试** —— 不需要模型就能跑通解析/比对/排序。
5. **7.2 集成验证** —— 单图 → 小批量 → 全量。
6. **步骤 4**(README)—— 使用说明最后补。

---

## 十、与策略文档的对应关系

| 本脚本职责 | 策略文档章节 |
|-----------|-------------|
| ViTPose 推理 + OKS 比对 | L3 模型差异层 → 关键点比对 |
| 按风险分排序输出尾部 | L4 主动复查队列 → 风险分设计 |
| 独立脚本批处理 | 与 Inspector 集成 → 阶段二(外部模型结果导入) |
| `nose 标到脚踝` 检测 | L3 → nearest-part check(本版用 OKS+距离简化实现) |
| 框质量检查 | **不在本脚本**,属 L1/L2 几何规则,另写脚本 |

本脚本输出格式(4.1 节)与策略文档"阶段二外部结果格式"兼容,后续可直接被
inspector 面板导入复查。

---

## 附录 A:关键复用点速查

| 复用什么 | 来源 | 用途 |
|---------|------|------|
| `OnnxBaseModel` | `anylabeling/services/auto_labeling/engines/` | ONNX 推理基类 |
| `bbox_xyxy2cs` | `pose/dwpose_onnx.py:114` | 框 → center/scale |
| `top_down_affine` | `pose/dwpose_onnx.py:260` | 仿射对齐到固定尺寸 |
| `get_warp_matrix` | `pose/dwpose_onnx.py:204` | 仿射矩阵(top_down_affine 内部用) |
| `COCO_KEYPOINT_ORDER` | `pose_constants.py:18` | 17 点缩写名,避免重复定义 |
| CONFIG+CLI+线程池风格 | `scripts/stats_json_shapes.py` | 脚本骨架 |
| JSON shape 结构 | `scripts/s1860.json` | 真实标注格式参考 |

## 附录 B:COCO 17 点 OKS kappa 值

```python
KAPPA = np.array([
    0.026,  # 0  nose
    0.025,  # 1  l_eye
    0.025,  # 2  r_eye
    0.035,  # 3  l_ear
    0.035,  # 4  r_ear
    0.079,  # 5  l_sho
    0.079,  # 6  r_sho
    0.072,  # 7  l_elb
    0.072,  # 8  r_elb
    0.062,  # 9  l_wri
    0.062,  # 10 r_wri
    0.107,  # 11 l_hip
    0.107,  # 12 r_hip
    0.087,  # 13 l_knee
    0.087,  # 14 r_knee
    0.089,  # 15 l_ank
    0.089,  # 16 r_ank
])
```

## 附录 C:人工标注字段对照(`s1860.json` 实测)

| 字段 | 含义 | 示例 |
|------|------|------|
| `label` | 关键点缩写 / `person`/`head`/`face` | `"nose"`、`"l_sho"` |
| `points` | point:[[x,y]];rectangle:[[x1,y1],[x2,y2]] | `[[541.0,191.0]]` |
| `group_id` | 同一人 person+points 共享;head/face 独立 group | `0` |
| `description` | `"invisible"`=不可见;`null`/`""`=可见 | `"invisible"` |
| `shape_type` | `point` / `rectangle` | `"point"` |
| `imagePath` | 图片文件名(相对标注目录) | `"s1860.jpg"` |
| `imageData` | 内嵌图片(本数据集为 null) | `null` |
