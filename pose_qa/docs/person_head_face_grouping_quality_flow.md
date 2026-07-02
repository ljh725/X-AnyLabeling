# Person/Head/Face 三类框分组与空间质检流程

## 目标

三类检测框的空间质检，第一步不是直接判断框的位置是否正确，而是先把
`person`、`head`、`face` 按真实目标统一起来。

核心问题是：

- 这个 `head` 属于哪个 `person`？
- 这个 `face` 属于哪个 `head` 或 `person`？
- 这三个框是否描述同一个真实目标？

只有先完成目标级分组，后续的包含关系、面积比例、相对位置、重复框、漏框、
框偏移检查才有可靠基础。

## 总体流程

```text
原始标注 JSON
  │
  ├─ person 框集合
  ├─ head 框集合
  └─ face 框集合
        │
        ▼
空间匹配 / 目标归并
        │
        ▼
生成 qa_group_id
        │
        ▼
基于 qa_group_id 做空间语义检查
        │
        ▼
输出高风险复查队列
```

建议将这一阶段称为 **目标归并** 或 **三类框重分组**，并把它放在所有空间
语义质检规则之前。

## 为什么要先统一 group

真实标注里经常出现：

- `person` 和关键点共享一个 `group_id`，但 `head`、`face` 使用独立 `group_id`。
- 标注员忘记给 `head` 或 `face` 设置正确 `group_id`。
- 多人场景中，`head` / `face` 被归到了错误的人。
- 框的位置本身可能正确，但实例关系错误。
- 后续规则按 `group_id` 聚合时，把同一个人的三类框拆散。

因此，空间语义质检前必须先建立一个可信的目标级分组。

## 不建议直接覆盖原始 group_id

第一版不建议直接修改原始 `group_id`。更稳妥的方式是生成质检用字段：

```json
{
  "label": "head",
  "group_id": 18,
  "qa_group_id": 0,
  "qa_match": {
    "matched_person_gid": 0,
    "score": 0.91,
    "method": "spatial"
  }
}
```

这样可以：

- 保留标注员原始分组，方便追溯错误。
- 使用 `qa_group_id` 做后续质检，不污染原始数据。
- 对低置信匹配单独复查。
- 等规则稳定后，再提供独立脚本批量写回 `group_id`。

## 第一步：解析三类框

从每个 JSON 中分别收集：

- `person` rectangle
- `head` rectangle
- `face` rectangle

解析 rectangle 时必须兼容两种格式：

```text
两点格式：[[x1, y1], [x2, y2]]
四角格式：[[x1, y1], [x2, y1], [x2, y2], [x1, y2]]
```

统一转换为：

```text
(min_x, min_y, max_x, max_y)
```

注意：不要假设 rectangle 一定只有两个对角点。之前关键点飞框问题的根因之一
就是把四角 rectangle 当成两点 rectangle 解析，导致框高度塌成 0。

## 第二步：head 匹配 person

对每个 `head`，寻找最可能所属的 `person`。

不要只看 IoU。`head` 是 `person` 的子区域，IoU 通常不会很大，应该重点看
包含比例和相对位置。

推荐评分：

```text
head -> person score =
  0.5 * head_inside_person_ratio
+ 0.3 * center_closeness
+ 0.2 * size_reasonableness
```

指标含义：

- `head_inside_person_ratio`：`head` 面积中有多少比例落在 `person` 内。
- `center_closeness`：`head` 中心点是否靠近 `person` 上半身合理区域。
- `size_reasonableness`：`head_area / person_area` 是否在合理范围。

如果 `head` 明显落在 `person` 下半身，即使包含比例较高，也应降低匹配分数。

## 第三步：face 匹配 head

对每个 `face`，优先寻找最合适的 `head`：

```text
face -> head score =
  0.6 * face_inside_head_ratio
+ 0.3 * center_closeness
+ 0.1 * size_reasonableness
```

指标含义：

- `face_inside_head_ratio`：`face` 面积中有多少比例落在 `head` 内。
- `center_closeness`：`face` 中心点与 `head` 中心点距离。
- `size_reasonableness`：`face_area / head_area` 是否合理。

如果找不到可信 `head`，再尝试将 `face` 直接匹配到 `person`，但要标记为低置信
或待复查。

## 第四步：生成 qa_group_id

以 `person` 为主目标生成 `qa_group_id`：

```text
qa_group_id = 0
  ├─ person: gid=0
  ├─ head: gid=18
  └─ face: gid=21

qa_group_id = 1
  ├─ person: gid=1
  ├─ head: gid=19
  └─ face: gid=22
```

建议规则：

- 每个 `person` 对应一个 `qa_group_id`。
- 匹配到该 `person` 的 `head` 和 `face` 使用相同 `qa_group_id`。
- 无法匹配的 `head` / `face` 输出为 orphan issue。
- 匹配分数低于阈值的结果不自动合并，进入人工复查队列。

## 第五步：基于 qa_group_id 做空间质检

统一目标分组后，每组可以稳定检查三类框关系。

| 规则 | 说明 |
| ---- | ---- |
| `HeadInsidePersonRule` | `head` 应基本位于 `person` 内 |
| `FaceInsideHeadRule` | `face` 应基本位于 `head` 内 |
| `FaceSmallerThanHeadRule` | `face` 不应明显大于 `head` |
| `HeadUpperBodyRule` | `head` 应位于 `person` 上部 |
| `DuplicateHeadFaceRule` | 同一目标下不应有严重重叠的多个 `head` / `face` |
| `MissingHeadFaceRule` | 有 `person` 但缺少必要的 `head` / `face` |
| `OrphanHeadFaceRule` | 有 `head` / `face` 但找不到可信 `person` |

## 推荐初始阈值

| 检查项 | 初始阈值 | 说明 |
| ------ | -------- | ---- |
| `head_inside_person_ratio` | `< 0.70` 可疑，`< 0.40` 高风险 | 允许截断和边缘误差 |
| `face_inside_head_ratio` | `< 0.75` 可疑，`< 0.50` 高风险 | `face` 应主要在 `head` 内 |
| `face_area / head_area` | `> 1.10` 高风险 | `face` 不应大于 `head` |
| `head_area / person_area` | `> 0.60` 高风险 | 防止 `head` 框异常大 |
| `head_center_y / person_height` | `> 0.55` 可疑，`> 0.70` 高风险 | 检查头部是否落到身体下方 |
| 同类框 IoU | `> 0.85` 可疑 | 疑似重复框 |

这些阈值只适合作为初始值。更稳妥的方式是从高质量样本统计正常分布，再用
分位数自动生成阈值。

## 分布异常检查

从可信标注中统计：

- `head_area / person_area`
- `face_area / head_area`
- `head_center_x/y` 在 `person` 内的相对位置
- `face_center_x/y` 在 `head` 内的相对位置
- `head`、`face` 的宽高比

示例：

```text
face_area / head_area
  median = 0.42
  p5 = 0.18
  p95 = 0.76
```

质检时：

```text
超出 p5~p95：中风险
超出 p1~p99：高风险
```

这种方式比固定阈值更适合不同拍摄视角、数据来源和标注习惯。

## 框本身位置错误

三类框之间的相对位置可以通过几何规则和分布异常发现大量问题，但单个框本身
是否画错，通常不能只靠 JSON 判断。

例如：

- `head` 框画到了背景，但仍然位于 `person` 上半身。
- `face` 框画到了帽子或头发区域，但面积比例合理。
- `person` 框本身偏移，导致 `head` / `face` 关系也被带偏。

这类问题需要引入模型预测进行反查：

```text
图片
  ├─ 人工标注框
  └─ 模型预测框
        │
        ▼
同类框 IoU / 中心距离 / 面积比对
```

推荐模型差异规则：

| 情况 | 可能问题 |
| ---- | -------- |
| 人工框找不到同类模型框匹配 | 人工框可能画错或框住非目标 |
| 模型高置信框没有人工框匹配 | 可能漏标 |
| 同一位置模型预测 A，人工标 B | 可能类别错 |
| 同类匹配 IoU 很低 | 人工框位置或大小可能偏 |
| 中心点接近但面积差很大 | 框大小可能不准 |
| 中心点差很大但类别相同 | 框位置可能飞了 |

模型差异不应直接判错，只应作为高风险复查证据。

## 推荐落地顺序

```text
第 1 步：只读 JSON，不改原文件
  解析 person/head/face，兼容 2 点和 4 点 rectangle。

第 2 步：生成空间匹配报告
  输出 head->person、face->head/person 的匹配分数。

第 3 步：生成 qa_group_id
  只对高置信匹配生成质检分组，低置信进入复查队列。

第 4 步：基于 qa_group_id 做空间规则检查
  检查包含、面积比、中心位置、重复框、孤儿框、缺失框。

第 5 步：增加分布异常检查
  用高质量样本统计正常范围，减少手写阈值误差。

第 6 步：接入模型反查
  用检测模型预测结果检查框本身是否偏移、漏标、多标。

第 7 步：人工确认与写回
  人工确认高风险样本后，再决定是否批量统一原始 group_id。
```

## 输出建议

目标归并阶段建议输出：

```text
grouping_report.json
grouping_report.md
low_confidence_matches.txt
```

`grouping_report.json` 示例：

```json
{
  "image": "s1860.jpg",
  "groups": [
    {
      "qa_group_id": 0,
      "person_gid": 0,
      "head_gid": 18,
      "face_gid": 21,
      "match_score": 0.91,
      "issues": []
    }
  ],
  "orphans": [
    {
      "label": "face",
      "group_id": 33,
      "reason": "no matched head or person above threshold"
    }
  ]
}
```

后续空间质检报告可以直接引用 `qa_group_id`：

```json
{
  "qa_group_id": 0,
  "rule": "FaceInsideHeadRule",
  "severity": "error",
  "message": "face 框仅 42.5% 位于 head 框内，疑似 face/head 关系错误"
}
```

## 结论

三类框空间质检的地基是 **目标级分组**。推荐先生成 `qa_group_id`，把
`person`、`head`、`face` 归并到同一个真实目标，再做空间语义检查。

最终流水线可以概括为：

```text
先归并目标
  再检查相对位置
    再统计分布异常
      再用模型反查框本身位置
        最后只把高风险样本交给人工复查
```
