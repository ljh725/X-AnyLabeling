# ViTPose 分歧排序质检 V1

## 目标

V1 只解决一个问题：

> 用 ViTPose 预测结果和人工关键点标注进行对比，找出差异最大的关键点，
> 让人工优先修改最可能出错的少量样本。

这个版本刻意削弱统计分析、规则检测和复杂报告，不做“大而全”的质检系统。
它的定位是一个**最大分歧定位器**。

## 核心思路

```text
人工 person 框
  -> ViTPose 预测 17 个 COCO 关键点
  -> 与人工关键点逐点对比
  -> 按单点最大差异排序
  -> 人工只复查 Top N
```

排序对象不是整张图片，也不是整个人，而是：

```text
图片 + group_id + 关键点名
```

因为实际修复动作通常是“把某个 nose 点改回来”，而不是泛泛地判断整张图。

## 输入

### 标注 JSON

使用 X-AnyLabeling / LabelMe 风格 JSON。

每个目标通过 `group_id` 关联：

- `person` rectangle
- 17 个 COCO 关键点 point

关键点标签使用当前数据集中的缩写：

```text
nose,
l_eye, r_eye,
l_ear, r_ear,
l_sho, r_sho,
l_elb, r_elb,
l_wri, r_wri,
l_hip, r_hip,
l_knee, r_knee,
l_ank, r_ank
```

### 图片目录

根据 JSON 中的 `imagePath` 或 JSON 文件名匹配图片。

### ViTPose 模型

使用 COCO 17 点版本 ViTPose。V1 不跑检测器，直接使用人工标注的 `person`
框做 top-down 姿态预测。

## 不做的事

V1 明确不做以下内容：

- 不跑目标检测器。
- 不检查 `person` 框本身是否正确。
- 不检查 `face/head` 框关系。
- 不做复杂 OKS 分布统计。
- 不做规则系统。
- 不自动修改 JSON。
- 不集成进 X-AnyLabeling UI。
- 不生成复杂 Markdown 总报告。

这些能力可以后续作为 V2/V3 增强。

## 最小流程

### Step 1：解析人工标注

遍历 JSON，按 `group_id` 提取每个 `person`：

```text
AnnotatedPerson
  image_path
  json_path
  group_id
  person_bbox
  keypoints[17, 2]
  visibility[17]
```

解析规则：

- `person` 必须是 `shape_type == "rectangle"`。
- rectangle 的两个点需要排序成 `(x1, y1, x2, y2)`。
- point 根据 label 映射到 17 点顺序。
- 缺失点填空，不参与对比。
- `description == "invisible"` 的点不参与对比。

### Step 2：ViTPose 预测

对每张图片中的所有人工 `person` 框进行 ViTPose top-down 推理。

```text
image + person_bbox
  -> crop/affine
  -> ViTPose
  -> pred_keypoints[17, 2]
  -> pred_scores[17]
```

建议一张图内多个 person 框 batch 推理，减少 GPU 调用次数。

### Step 3：逐点差异计算

对每个可比较关键点计算：

```text
diff_px = distance(gt_point, pred_point)
norm_diff = diff_px / person_bbox_diagonal
```

其中：

- `gt_point` 是人工标注点。
- `pred_point` 是 ViTPose 预测点。
- `person_bbox_diagonal` 是人工 person 框对角线长度。

归一化后可以消除人体大小差异。大人和小人都能放在同一个排序表中比较。

### Step 4：过滤无效点

V1 只保留最少过滤条件：

| 条件 | 处理 |
| ---- | ---- |
| 人工点缺失 | 跳过 |
| 人工点 `description == "invisible"` | 跳过 |
| ViTPose `pred_score < 0.3` | 降权或跳过 |
| person 框面积过小 | 跳过或标记低可信 |
| 图片不存在 | 记录失败，不参与排序 |

除这些必要条件外，不再加入复杂规则。

### Step 5：排序输出

第一版主排序字段：

```text
norm_diff desc
```

更稳一点可以使用：

```text
rank_score = norm_diff * pred_score
```

这样 ViTPose 自己也不确定的点不会过度靠前。

## 输出

### 1. CSV 排序表

主输出是一个 CSV，按差异从大到小排序。

字段建议：

```text
rank,
image,
json_path,
group_id,
keypoint,
gt_x,
gt_y,
pred_x,
pred_y,
pred_score,
diff_px,
norm_diff,
rank_score
```

示例：

```csv
rank,image,json_path,group_id,keypoint,gt_x,gt_y,pred_x,pred_y,pred_score,diff_px,norm_diff,rank_score
1,s1860.jpg,s1860.json,3,nose,521.0,410.0,520.3,180.2,0.91,229.8,0.62,0.56
2,s1867.jpg,s1867.json,8,l_ank,302.4,144.0,301.1,502.8,0.88,358.8,0.59,0.52
```

### 2. Top 差异可视化图

为 CSV 前 N 条生成可视化图片。

建议画法：

- 人工点：绿色。
- ViTPose 点：红色。
- 两点之间画一条黄色线。
- 当前问题点放大标记。
- 图片角落写 `image / group_id / keypoint / norm_diff`。

可视化比 Markdown 报告更重要，因为质检人员需要快速判断：

```text
是人工标错？
还是模型预测错？
```

### 3. 可选 Top 图片列表

输出去重后的图片名列表，便于在 X-AnyLabeling 中按顺序打开。

```text
s1860.jpg
s1867.jpg
s1902.jpg
```

## 人工复查方式

建议操作流程：

1. 打开 CSV，从第一行开始看。
2. 对照可视化图快速判断。
3. 如果是人工标错，回 X-AnyLabeling 修改对应图片、`group_id`、关键点。
4. 如果是模型误判，跳过。
5. 当连续 20 到 30 个样本都是模型误判或可接受差异时，可以停止继续往下看。

V1 的目标不是检查完全部数据，而是优先处理最离谱的一小段。

## 推荐检查规模

对约 5 万个人工目标，可以优先看：

```text
Top 500 点
Top 1000 点
Top 5%
Top 10%
```

推荐从 `Top 1000` 开始。若前 1000 中错误密度很高，再继续扩大范围；
若很快变成模型误判，说明排序尾部已经进入低收益区。

## 与完整流水线的取舍

| 能力 | 完整流水线 | V1 |
| ---- | ---------- | -- |
| ViTPose 预测 | 保留 | 保留 |
| 人工关键点对比 | 保留 | 保留 |
| 最大差异排序 | 保留 | 作为核心 |
| OKS | 主指标之一 | 只作为可选辅助 |
| 统计分布 | 有 | 暂不做 |
| Markdown 总报告 | 有 | 暂不做 |
| 规则检查 | 有 L1/L2 | 弱化 |
| 自动修正 | 不做 | 不做 |
| UI 集成 | 后续 | 不做 |

## 为什么 V1 更适合当前目标

当前目标是降低人工操作量，而不是建立完整质检平台。最大分歧排序能直接把：

```text
5 万个人工目标
  -> 所有可见关键点差异
  -> 差异最大的 Top N
  -> 少量高风险人工复查
```

像 `nose` 标到脚踝这类问题，通常会在 `norm_diff` 排序中非常靠前。
相比写大量规则，这个方法更能利用图像内容本身。

## V1 成功标准

第一版可以用以下标准判断是否有效：

- 能成功解析真实 JSON 中的 `person + 17 点`。
- 能使用人工 `person` 框跑通 ViTPose。
- 能输出按单点差异排序的 CSV。
- 人工查看 Top 100 后，能发现明显错标样本。
- 质检人员不需要阅读复杂统计报告即可开始修正。

## 后续增强方向

V1 跑通后，再考虑逐步增加：

- OKS 作为辅助排序字段。
- 每个 keypoint 分别输出 Top N。
- 可视化图自动裁剪 person 区域。
- 在 CSV 中增加跳转 X-AnyLabeling 所需的图片路径和 group_id。
- 对模型低置信点做更精细降权。
- 将 CSV 导入 inspector 面板形成复查队列。

这些增强都不应改变 V1 的主线：**按 ViTPose 与人工标注的最大单点分歧排序**。
