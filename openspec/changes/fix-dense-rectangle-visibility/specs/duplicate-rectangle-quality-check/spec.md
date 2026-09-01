## Purpose

为检测结果提供只读、可复核且低误报的几何重复矩形识别能力，把由重复检测造成的视觉遮挡与合法的 person/head/face 嵌套区分开来，并保留人工最终决定权。

## ADDED Requirements

### Requirement: 质检 SHALL 只比较同一文件内的有效同标签矩形

系统 SHALL 仅为同一标注文件中的有效矩形生成重复候选，并 SHALL 要求候选具有相同非空 label。不同 label 的矩形、非矩形 shape、非法或零面积 bbox 以及不同文件的对象 MUST NOT 进入重复判定。

#### Scenario: person 与 head 合法嵌套
- **WHEN** 一个 person 矩形高度包含一个 head 矩形但两者 label 不同
- **THEN** 系统不得将该组合报告为重复矩形

#### Scenario: 非法矩形不参与重复判定
- **WHEN** 一个 shape 的 bbox 为零面积或 points 无法形成有效矩形
- **THEN** 重复规则跳过该 shape，并由既有 L1 合法性规则负责报告

### Requirement: 重复严重度 SHALL 由组关系和几何阈值共同决定

对于相同 label 的有效矩形，系统 SHALL 使用可配置阈值判断重复：同一有效 group_id 且 IoU 达到默认 `0.95` 时产生 error；group_id 不同或至少一方未分组且 IoU 达到默认 `0.97` 时产生 warning；同一有效 group_id 且四条边坐标差均不超过默认 `2` 图像像素时 SHALL 产生 error。阈值 SHALL 从质量配置加载并接受模式校验。

#### Scenario: 同组同标签高度重合
- **WHEN** 同一文件内两个 person 矩形的 group_id 都为 9 且 IoU 为 `0.96`
- **THEN** 系统生成 error 级重复矩形问题

#### Scenario: 未分组同标签近乎完全重合
- **WHEN** 同一文件内两个未分组 face 矩形的 IoU 为 `0.98`
- **THEN** 系统生成 warning 级疑似重复问题

#### Scenario: 重合度未达阈值
- **WHEN** 两个同标签矩形的 IoU 和边坐标差均未达到适用阈值
- **THEN** 系统不得为该对象对生成重复问题

### Requirement: 每个重复对象对 SHALL 只产生一个稳定问题

系统 SHALL 对无序对象对去重，使 A-B 与 B-A 只产生一个问题。相同输入、阈值和实体身份 SHALL 生成稳定的 issue_id，并 SHALL 在报告中包含双方的实体标识或 shape 索引、label、group_id、IoU、最大边坐标差、严重度和触发原因。

#### Scenario: 候选顺序变化
- **WHEN** 相同两个矩形以相反遍历顺序进入重复规则
- **THEN** 输出仍只有一个问题，且 issue_id 与问题字段保持稳定

#### Scenario: 报告提供复核证据
- **WHEN** 系统报告一个重复矩形问题
- **THEN** 复核者能够从报告字段识别双方对象并看到触发阈值的几何证据

### Requirement: 重复检测 SHALL 保持只读并支持人工复核

重复扫描 MUST NOT 删除、合并、移动或修改任何 shape，也 MUST NOT 写回标注 JSON。问题 SHALL 进入现有质检报告和 Inspector 复核队列，支持导航到涉及对象；保留或删除对象必须由用户通过既有编辑与保存流程决定。

#### Scenario: 扫描发现高置信重复框
- **WHEN** 重复规则产生 error
- **THEN** 标注文件内容和修改时间保持不变
- **AND** 用户可以从 Inspector 导航到该问题进行人工处理

#### Scenario: 用户暂不处理
- **WHEN** 用户把疑似重复问题标记为暂不处理或误报
- **THEN** 系统保存复核反馈，但不得修改阈值配置或标注 JSON

### Requirement: 重复检测 SHALL 避免密集场景的无界全量比较

系统 SHALL 在每个文件内使用空间候选筛选，仅对可能达到配置阈值的矩形对计算完整 IoU，并 SHALL 保持输出结果与等价的穷举判定一致。

#### Scenario: 大量互不相邻矩形
- **WHEN** 一张图片包含大量空间上互不相交的同标签矩形
- **THEN** 系统通过空间候选筛选排除明显不重叠对象对
- **AND** 输出与逐对穷举的重复判定结果一致

