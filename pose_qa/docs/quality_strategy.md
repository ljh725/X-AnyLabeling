# 视觉语义标注质量检查四层策略

## 背景

现有数据检查能力主要覆盖标签名、`group_id`、`shape_type`、必填字段、
同组唯一性等结构化规则。这类规则适合发现“数据格式不合法”或
“标签体系不一致”的问题，但很难发现画面语义层面的错误，例如：

- `nose` 关键点被标到脚踝位置。
- `face` 检测框明显超过 `head` 检测框。
- 左右手、左右脚关键点互换。
- 关键点整体落在人体框外，但坐标本身仍然合法。
- 头部、脸部、人体框之间的包含关系或空间比例明显异常。

这类问题的本质不是单纯的坐标错误，而是“图像内容与标注语义不一致”。
如果完全依靠硬编码坐标规则，会遇到几个限制：

- 姿态、遮挡、截断、俯仰角、多人重叠会让固定阈值变得脆弱。
- 规则越写越多，但仍然覆盖不了真实场景里的长尾错误。
- 一些错误需要结合图像内容判断，仅凭 JSON 中的坐标无法确认。
- 自动判错容易误伤，适合做“可疑样本排序”，不适合直接替代人工复查。

因此建议把标注质量检查拆成四层：硬规则、人体结构规则、模型差异规则、
主动复查队列。目标不是一次性自动判断全部对错，而是把大量数据压缩为
少量高风险样本，让人工复查更集中、更高效。

## 总体架构

```text
┌─────────────────────────────────────────────────────────────┐
│                  Annotation Quality Strategy                 │
├─────────────────────────────────────────────────────────────┤
│  L1: 硬规则检查                                               │
│      标签合法性、字段完整性、bbox 包含关系、shape_type 绑定     │
├─────────────────────────────────────────────────────────────┤
│  L2: 人体结构规则                                             │
│      同一 group 内关键点、人体框、头脸框之间的几何关系           │
├─────────────────────────────────────────────────────────────┤
│  L3: 模型差异规则                                             │
│      人工标注与检测/姿态模型预测进行 IoU、OKS、PCK 等比对       │
├─────────────────────────────────────────────────────────────┤
│  L4: 主动复查队列                                             │
│      汇总风险分、按问题类型导出、跳转复查、人工确认/忽略         │
└─────────────────────────────────────────────────────────────┘
```

四层之间不是互斥关系，而是逐层增强：

- L1 便宜、确定性强，适合默认开启。
- L2 仍然不依赖模型，但开始引入领域知识。
- L3 依赖图像内容和模型预测，是发现语义错误的关键。
- L4 负责把检查结果变成可执行的复查工作流。

## L1：硬规则检查

### 目标

发现不需要理解图像内容即可判断的问题。此类规则应当稳定、快速、误报低，
适合作为数据入库和日常标注过程中的基础检查。

### 适用问题

- 标签名不在允许列表。
- `shape_type` 与标签类型不匹配。
- `points` 为空或点数量异常。
- `group_id` 类型非法或缺失。
- 同一 `group_id` 内重复出现唯一标签。
- `face` 框明显大于或超出 `head` 框。
- 关键点坐标超出图片范围。
- bbox 面积为 0 或宽高过小。

### 示例规则

#### FaceInsideHeadRule

检查同一 `group_id` 内的 `face` 框是否基本位于 `head` 框内。

建议逻辑：

- 查找同组的 `face` rectangle 和 `head` rectangle。
- 计算 `face` 超出 `head` 的面积比例。
- 允许小幅容差，例如 `5%` 到 `10%`，避免边缘手抖造成误报。
- 如果 `face` 面积大于 `head` 面积，直接标记为高风险。
- 如果 `face` 与 `head` 中心点距离过大，标记为中风险。

输出示例：

```text
rule: FaceInsideHeadRule
severity: error
message: face 框超出 head 框 28.4%，疑似头脸框关系错误
target: group_id=12, label=face
```

#### KeypointInsidePersonRule

检查关键点是否落在同组 `person` 框附近。

建议逻辑：

- 查找同组 `person` rectangle。
- 对 person 框做少量扩展，例如宽高各扩展 `5%`。
- 关键点必须位于扩展后的 person 框内。
- 对 `nose`、`eye`、`ear` 等头部关键点可进一步要求位于 person 上半区。

注意：这一规则不应该过严。人体截断、遮挡和框标注习惯会导致合理标注
落在 person 框边缘外。

## L2：人体结构规则

### 目标

利用人体关键点和检测框之间的结构关系，发现明显不符合人体布局的标注。
这层仍然只读取标注 JSON，不依赖模型预测。

### 适用问题

- `nose` 落在 person 框下半身。
- `ankle` 落在 person 框上半身。
- 左右肩、左右髋、左右膝、左右踝关系严重交叉。
- limb 长度比例异常。
- 头部关键点远离 `head` / `face` 框。
- 同组存在关键点但缺少 `person` 框。
- 同组存在 `face` 但缺少 `head`。

### 推荐规则

#### HeadKeypointsNearHeadBoxRule

检查头部关键点是否靠近 `head` 或 `face` 框。

适用标签：

- `nose`
- `left_eye`
- `right_eye`
- `left_ear`
- `right_ear`

建议逻辑：

- 若同组有 `head` 框，优先使用 `head` 框。
- 若无 `head` 框但有 `face` 框，可使用 `face` 框扩展区域。
- 计算关键点到框中心的归一化距离。
- 若关键点完全远离头脸区域，标记为可疑。

示例：

```text
nose 到 head 框中心距离为 head 对角线的 3.2 倍，疑似 nose 标注位置错误
```

#### BodyPartVerticalBandRule

按 person 框高度划分粗略人体区域：

```text
person box y-axis

0%   ┌───────────────┐
     │ head / face   │  nose, eye, ear
25%  ├───────────────┤
     │ upper body    │  shoulder, elbow, wrist
60%  ├───────────────┤
     │ lower body    │  hip, knee
85%  ├───────────────┤
     │ foot area     │  ankle
100% └───────────────┘
```

这不是绝对判错规则，而是风险提示：

- `nose` 出现在 `80%` 以下区域：高风险。
- `ankle` 出现在 `40%` 以上区域：中高风险。
- `shoulder` 出现在 `75%` 以下区域：中风险。

阈值应支持配置，因为不同数据集可能包含半身、俯视、坐姿或倒地姿态。

#### LeftRightConsistencyRule

检查左右关键点是否严重互换。

可检查的关系：

- `left_shoulder` 与 `right_shoulder`
- `left_elbow` 与 `right_elbow`
- `left_wrist` 与 `right_wrist`
- `left_hip` 与 `right_hip`
- `left_knee` 与 `right_knee`
- `left_ankle` 与 `right_ankle`

注意事项：

- 图像坐标中的“左/右”可能对应人体自身左右，也可能对应画面左右。
- 如果标签定义是人体解剖学左右，正面和背面都会影响画面左右关系。
- 因此该规则应输出 warning，不建议默认作为 error。

#### LimbLengthOutlierRule

检查骨架边长度是否异常。

示例骨架边：

- shoulder -> elbow
- elbow -> wrist
- hip -> knee
- knee -> ankle
- shoulder -> hip

建议逻辑：

- 用 person 框对角线或高度做归一化。
- 在单张图内检查左右 limb 是否差异过大。
- 在数据集级别统计 limb 长度分布，识别离群值。

## L3：模型差异规则

### 目标

使用检测模型、姿态模型或已经训练过的业务模型，将模型预测与人工标注进行
对比。此层是发现视觉语义错误的核心，因为它引入了图像内容本身。

### 基本思想

```text
image
  │
  ├── human annotation ───────┐
  │                           ├── compare ── suspicious issues
  └── model prediction ───────┘
```

模型不直接替代人工标注，只提供“另一种视觉判断”。当模型预测和人工标注
差异很大时，系统把样本标为可疑，并交给人工确认。

### 检测框比对

适用于：

- `person`
- `head`
- `face`
- 其他 rectangle 类别

推荐指标：

- IoU：人工框与模型框重叠程度。
- center distance：中心点距离。
- area ratio：面积比例。
- containment ratio：一个框被另一个框包含的比例。

示例规则：

```text
if label == "face":
    match model face prediction by max IoU
    if best_iou < 0.3 and center_distance > threshold:
        report suspicious face box
```

### 关键点比对

适用于：

- `nose`
- `eye`
- `ear`
- `shoulder`
- `elbow`
- `wrist`
- `hip`
- `knee`
- `ankle`

推荐指标：

- PCK：关键点距离是否小于归一化阈值。
- OKS：COCO 风格的 Object Keypoint Similarity。
- nearest-part check：人工关键点是否更接近其他类别的模型关键点。

针对“nose 标到脚踝”的建议逻辑：

```text
1. 找到人工 person 框和同组 nose 点。
2. 用姿态模型预测当前图中的 person 和 keypoints。
3. 将人工 person 与模型 person 匹配。
4. 计算人工 nose 到模型 nose 的归一化距离。
5. 同时计算人工 nose 到模型 ankle/knee/foot 的距离。
6. 如果人工 nose 远离模型 nose，且更接近下肢关键点，输出高风险问题。
```

输出示例：

```text
rule: KeypointPoseModelAgreementRule
severity: error
message: 人工 nose 距模型 nose 0.74 person 高度，但更接近模型 left_ankle，疑似关键点语义错误
target: group_id=8, label=nose
score: 0.93
```

### 模型选择建议

可以从轻到重分三档：

#### 轻量档：只做几何规则

- 不依赖模型。
- 开发成本低。
- 能快速覆盖 `face/head`、关键点越界、明显区域异常。
- 无法真正识别图像语义。

#### 中档：接入通用姿态模型

- 使用现成人体姿态模型，例如 RTMPose、YOLO pose、HRNet 等。
- 对 `nose`、`ankle`、`shoulder` 等关键点错误有明显帮助。
- 对业务自定义标签的支持有限。

#### 重档：训练业务专用模型

- 使用当前数据集训练检测/姿态模型。
- 用模型反查训练集中的高 loss、高不确定性、高冲突样本。
- 能适配业务标签体系，但需要维护训练和推理流程。

### 重要原则

模型差异不等于人工标注错误。以下情况会导致模型预测不可靠：

- 遮挡严重。
- 目标极小。
- 图片模糊。
- 罕见姿态。
- 数据集标签定义和模型训练标签定义不同。
- 业务标注习惯与通用模型语义不完全一致。

因此 L3 规则应使用 `warning` 或 `suspicious` 语义，并在 UI 中允许人工确认、
忽略或导出复查。

## L4：主动复查队列

### 目标

把 L1、L2、L3 的检查结果转化成可操作的复查流程。系统不只是列出问题，
还应该帮助标注员优先处理最可能出错的图片。

### 风险分设计

每个 issue 可以包含：

- `severity`：`error`、`warning`、`info`。
- `confidence`：规则或模型对该问题的置信度。
- `impact`：该错误对训练的影响程度。
- `fix_cost`：人工修复成本。

示例评分：

```text
risk_score =
    severity_weight * 0.4 +
    confidence * 0.3 +
    model_disagreement * 0.2 +
    historical_error_rate * 0.1
```

建议初期不要过度设计评分模型。可以先按简单优先级排序：

1. 高置信硬错误。
2. 模型与人工严重冲突。
3. 同一图片多个规则同时命中。
4. 同一标注员或同一批次反复出现的问题类型。

### UI 工作流

建议在 inspector 中支持：

- 按图片聚合问题。
- 按规则类型聚合问题。
- 按风险分排序。
- 点击 issue 跳转到对应图片和 shape。
- 对 issue 标记为“已确认错误”“已修复”“忽略”“规则误报”。
- 导出高风险样本及其 JSON、图片、问题报告。

推荐交互：

```text
Inspector
  ├── 数据检查
  │     ├── 结构规则
  │     ├── 人体结构规则
  │     └── 模型差异规则
  ├── 数据表格
  ├── 规则配置
  └── 导出
        ├── 导出全部问题
        ├── 只导出高风险问题
        └── 按规则名分目录导出
```

### 人工反馈闭环

人工处理结果很重要，应尽量保留：

- 这个 issue 是否真错。
- 是否已经修复。
- 是否属于规则误报。
- 是否属于模型预测错误。

这些反馈后续可以用于：

- 调整规则阈值。
- 训练更贴合业务数据的模型。
- 统计不同规则的命中准确率。
- 找出容易出错的标签类型和标注批次。

## 与现有 Inspector 模块的集成建议

现有 inspector 已经有 `FlatIndex`、`ValidationEngine`、`Issue`、
`ValidationRule`、`RuleConfigWidget` 和 `ExportManager`，适合逐步扩展。

### 阶段一：先加纯几何视觉规则

优先实现不依赖模型的规则：

- `FaceInsideHeadRule`
- `HeadKeypointsNearHeadBoxRule`
- `KeypointInsidePersonRule`
- `BodyPartVerticalBandRule`
- `LimbLengthOutlierRule`

好处：

- 不涉及模型部署和推理性能。
- 易于调试。
- 可以马上覆盖一批高频错误。
- 可以复用现有规则配置和问题列表。

### 阶段二：增加外部模型结果导入

不急着把模型推理塞进 UI 主线程。可以先设计一种外部结果格式：

```json
{
  "image": "000001.jpg",
  "predictions": [
    {
      "label": "person",
      "shape_type": "rectangle",
      "points": [[10, 20], [200, 400]],
      "score": 0.97,
      "source": "pose_model_v1"
    },
    {
      "label": "nose",
      "shape_type": "point",
      "points": [[87, 55]],
      "score": 0.91,
      "group_id": 1,
      "source": "pose_model_v1"
    }
  ]
}
```

Inspector 只负责读取模型结果并与人工标注比对。模型推理可以由独立脚本完成，
这样实现风险更低，也更容易批处理大数据集。

### 阶段三：接入在线模型推理

当外部结果导入稳定后，再考虑在 X-AnyLabeling 内部提供：

- 当前图片运行模型检查。
- 当前文件夹批量运行模型检查。
- 后台任务进度条。
- 推理结果缓存。
- 模型配置选择。

需要注意：

- 不要阻塞 PyQt UI 主线程。
- 需要处理 onnxruntime CPU/GPU 环境差异。
- 模型下载和缓存应复用 auto-labeling 服务已有机制。
- 结果缓存应能被 inspector 复用，避免重复推理。

## 推荐落地顺序

```text
第 1 步：FaceInsideHeadRule
  低成本，高确定性，能快速解决 face 超出 head 的问题。

第 2 步：KeypointInsidePersonRule + BodyPartVerticalBandRule
  覆盖 nose 到脚踝、ankle 到头部这类明显区域错误。

第 3 步：HeadKeypointsNearHeadBoxRule
  利用已有 head/face 框加强头部关键点检查。

第 4 步：外部模型结果格式
  先支持导入模型预测结果，不直接集成推理。

第 5 步：KeypointPoseModelAgreementRule
  对人工关键点和模型关键点做 PCK/OKS/nearest-part 检查。

第 6 步：复查队列和反馈闭环
  让问题排序、人工确认、误报反馈成为日常工作流。
```

## 阈值配置建议

初始阈值可以保守一些，优先减少误报：

| 规则 | 初始阈值 | 说明 |
| ---- | -------- | ---- |
| face 超出 head | `10%` | 超出面积比例 |
| face 面积 / head 面积 | `> 1.1` | 超过则高风险 |
| 关键点超出 person 扩展框 | 扩展 `5%` | 防止边界误报 |
| nose 位于 person 下半区 | `y > 0.65h` | warning |
| nose 位于 person 脚部区域 | `y > 0.80h` | error |
| ankle 位于 person 上半区 | `y < 0.45h` | warning |
| 人工点与模型点距离 | `> 0.15 person height` | suspicious |
| bbox IoU | `< 0.3` | suspicious |

所有阈值都应该可以在规则配置中调整。不同项目的数据分布差异很大，固定阈值
只适合作为默认值。

## 数据导出与报告建议

高风险样本导出时，建议包含：

- 原图。
- 原始 JSON。
- 问题报告 JSON。
- 可选的可视化图片。

问题报告示例：

```json
{
  "image": "000001.jpg",
  "json": "000001.json",
  "issues": [
    {
      "rule": "FaceInsideHeadRule",
      "severity": "error",
      "label": "face",
      "group_id": 3,
      "message": "face 框超出 head 框 28.4%",
      "score": 0.88
    },
    {
      "rule": "KeypointPoseModelAgreementRule",
      "severity": "warning",
      "label": "nose",
      "group_id": 3,
      "message": "nose 与模型预测 nose 距离过远，且更接近 left_ankle",
      "score": 0.93
    }
  ]
}
```

## 结论

视觉语义错误不适合只用坐标规则硬判。更稳妥的方向是：

```text
硬规则兜底
  + 人体结构规则发现明显异常
  + 模型差异规则提供视觉判断
  + 主动复查队列让人工高效确认
```

其中 `face` 超出 `head` 这类问题可以先用 L1/L2 快速解决；
`nose` 标到脚踝这类问题则建议最终引入 L3 模型差异检查。系统的定位应是
“高风险样本发现器”，而不是“完全自动判官”。这样既能显著减少人工复查成本，
也能避免模型或规则误判直接污染数据。
