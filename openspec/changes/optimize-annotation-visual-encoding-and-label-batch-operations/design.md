## Context

参见 `proposal.md` 的动机。当前实现有四个直接影响方案的约束：

- `label_widget.py` 和 `canvas.py` 各自创建一份调色板，并对同一
  `group_id` 使用不同索引公式；形状本体保存 `QColor` 和 selected/fill
  等绘制状态，基础颜色、交互状态与模型对象紧耦合。
- `Shape.paint()` 以单层轮廓绘制矩形，选中线统一变白；画布只在选中
  或 hover 时根据开关填充，无法独立表达基础颜色、组聚焦、质检状态
  和活动边反馈。
- 标签管理器的标签扫描已在后台执行，但确认修改仍在 GUI 主线程遍历
  图片列表并原地重写范围内所有 JSON；颜色和可见性修改也错误进入这
  条数据迁移路径。
- 项目已有纯 Python 的筛选、矩形精修、数据集索引和质检内核。新策略
  应继续采用“纯逻辑内核 + PyQt 适配层”，并保持虚拟复核可见性、活动
  边 overlay、undo、dirty 和 JSON 契约不变。

上游 Labelme 已开始把 shape 数据与 `ShapeRenderContext` 分离，本变更
采用同一方向，但通过兼容适配逐步落地，不把上游的大范围 Shape 重构
整体移植进来。

## Goals / Non-Goals

**Goals:**

- 建立一个确定性、无 Qt 依赖且可单测的外观解析入口。
- 让基础配色、组聚焦、交互反馈和质检提示使用明确的视觉通道与优先级。
- 让显示设置实时生效而不修改标注数据或逐 shape 触发重绘。
- 将标签管理器变成草稿驱动、可预检、可取消、可恢复的批量操作入口。
- 复用数据集索引缩小候选范围，并保证每个 JSON 的替换原子性。

**Non-Goals:**

- 不改变 shape JSON schema、`group_id` 业务语义或导出格式。
- 不在本变更中重写 Canvas 的全部绘制/命中测试系统。
- 不实现依赖图像采样或模型推理的动态背景颜色识别。
- 不保证超过调色板容量后每个 group/instance 都拥有全局唯一颜色；
  身份由颜色与 GID/标签/交互反馈共同表达。
- 不把标签重命名/删除升级为数据库主存储；JSON 仍是唯一真实数据源。

## Decisions

### Decision 1: 用纯外观策略生成不可变绘制上下文

新增 `widgets/appearance/` 纯 Python 子包，建议包含：

- `types.py`：颜色模式、外观设置、shape 视觉输入和不可变输出类型。
- `palette.py`：跳过背景项的确定性 label/group/instance 颜色映射。
- `policy.py`：把基础模式、焦点和交互状态解析为绘制样式。
- `focus.py`：按 image token、选择集合和有效 group_id 管理瞬态焦点。

纯逻辑输出只包含 RGB/RGBA、透明度、描边层级、徽标内容和布尔状态；
Qt 适配器负责创建 `QColor/QPen/QBrush`。Canvas 每次绘制可见 shape 时
构造轻量上下文，`Shape.paint()` 在迁移期接受可选上下文；旧颜色属性仅
作为未迁移调用方的兼容回退，最终不再作为显示状态来源。

**Alternatives considered:** 继续在 `_update_shape_color()` 中直接修改每个
Shape。该方式改动较小，但会继续把瞬态焦点写进模型对象、制造多处索引
公式，并使状态组合测试必须启动 Qt，因此放弃。

### Decision 2: 一个设置决定颜色依据，Focus 为默认工作模式

颜色模式采用单一枚举：

```text
focus | label | group | instance | uniform
```

- `focus`：无焦点时使用低干扰基础样式；有焦点时只强调当前组。
- `label`：按项目 label 颜色稳定映射。
- `group`：按有效 group_id 稳定映射，未分组对象为中性色。
- `instance`：按会话内稳定 shape identity 映射，适合密集同类对象。
- `uniform`：所有普通对象使用相同基础色，专注几何边界。

Group 与 Instance 总览使用有限的可访问调色板并允许循环；视觉身份同时
依赖徽标与选择反馈，而不是假定人能记住十几种颜色。

**Alternatives considered:** 保留“存在 group_id 就强制覆盖 label 色”的
隐式优先级。该行为不可预测、无法针对不同任务切换，也是本次视觉混乱
的根因，因此废弃。

### Decision 3: 使用多通道视觉层级而不是继续扩充调色板

普通矩形采用两次描边：深色半透明外轮廓负责跨背景可见性，内部语义色
负责 label/group/instance 区分。正常填充默认关闭，选中和 hover 使用
低透明度填充。

状态职责固定为：

| 通道 | 职责 |
| --- | --- |
| 内描边色 | 当前颜色模式的基础身份 |
| 外描边 | 跨明暗背景的几何可见性 |
| 透明度 | 当前组与无关对象的注意力层级 |
| 线宽、控制点 | selected / hover / editing |
| 标签与 GID 徽标 | 精确身份，解决颜色碰撞 |
| 独立角标/overlay | QA error、warning 与矩形活动边 |

绘制优先级为：先执行既有可见性门禁，再解析基础模式与焦点弱化，然后
应用 selected/hover 样式；矩形活动边和 QA 标记最后以独立 overlay
绘制。活动边不复用基础 palette，避免 Group 模式下丢失精修反馈。

**Alternatives considered:** 对每个框采样背景亮度后选择黑/白描边。它会
增加高频绘制成本、缓存失效和边跨越明暗区域时的不稳定，双层描边更简单
可靠。

### Decision 4: 个人偏好与项目标签颜色分层持久化

个人显示偏好继续写入用户配置：

```yaml
annotation_appearance:
  color_mode: focus
  high_contrast_outline: true
  normal_fill_opacity: 0
  selected_fill_opacity: 28
  unrelated_opacity: 0.28
  show_labels: true
  show_gid: focus
```

项目共享的 label 颜色写入标注根目录下的
`.xanylabeling/appearance.yaml`：

```yaml
schema_version: 1
label_colors:
  person: [0, 114, 178]
  head: [0, 158, 115]
```

标注根目录优先使用显式 `output_dir`，否则使用当前数据集解析出的标注
目录。项目侧文件只保存共享 palette，不保存当前焦点、选中态或用户个人
透明度。

**Alternatives considered:** 把颜色写进每个 shape JSON 会污染数据契约并
触发全量迁移；只写全局用户配置又无法随项目共享，二者均不采用。

### Decision 5: 组焦点是独立瞬态状态机

焦点状态至少包含：

```text
image_token, focused_group_id, selected_shape_tokens
```

状态转移只消费规范化选择快照：

```text
no focus -- select one valid group --> focused(group)
focused(A) -- select valid B -------> focused(B)
focused(A) -- clear/mixed selection -> no focus
any focus -- image/mode change -----> no focus
```

多选全部属于同一有效组时可保持焦点；跨组、包含未分组对象或空选择时
退出。焦点控制器不读取 QColor、不修改 Shape，也不决定对象是否基础
可见；Canvas 仅对通过 `main_visible/base_visible` 的 shape 应用弱化。

**Alternatives considered:** 直接复用矩形精修 focus 对象集合。现有 focus
服务服务于 person/head/face 精修并包含 shape identity，生命周期与通用
颜色模式不同；强行复用会互相清除状态，因此只共享选择事件和角色配置，
不共享状态容器。

### Decision 6: 标签管理器先生成不可变变更计划

对话框打开时复制 label 元数据形成草稿，所有控件只修改草稿。确认时
生成计划：

```text
visual_changes: color_map, visibility_map
dataset_changes: rename_map, delete_labels
scope: selected range / resolved annotation roots
```

空计划直接结束。只有 `visual_changes` 时在 UI 线程更新项目视觉配置，
用 signal blocker 和 updates-disabled 批量刷新受影响列表/当前 shape，
最后只调用一次 Canvas 更新。

有 `dataset_changes` 时先处理当前 dirty 文件，再把计划交给后台 worker；
对话框原始 parent 状态在成功报告返回前不提交。重命名到已有 label 被
建模为显式 merge，需要二次确认。

**Alternatives considered:** 继续让颜色按钮直接修改 `parent.label_info`。
这使取消无法回滚、失败后 UI 与磁盘不一致，因此放弃。

### Decision 7: 批量迁移采用“预检—暂存—提交—同步”协议

后台操作分为四阶段：

1. **预检**：查询数据集索引；不可用时后台扫描；统计文件和 shape。
2. **暂存**：只转换真实命中文件，将结果写到同卷临时文件并重新解析
   验证，同时生成事务 manifest 和原文件备份。
3. **提交**：进入短暂不可取消阶段，以 `os.replace` 逐文件原子替换；
   单次只允许一个数据集写事务，并暂停会与目标文件竞争的保存动作。
4. **同步**：返回 succeeded/failed/skipped/cancelled 明细；UI 依据磁盘
   实际结果重建 label 摘要、当前文件和受影响索引。

事务目录建议为：

```text
<annotation-root>/.xanylabeling/transactions/<transaction-id>/
  manifest.json
  backups/
```

取消只在预检和暂存阶段接受；提交开始后完成既定替换，避免产生“用户
以为已取消但一半文件已经写入”的模糊状态。提交失败时保留 manifest 与
备份，恢复操作按 manifest 逐文件原子还原。

**Alternatives considered:** 多线程直接原地写 JSON。它会放大磁盘竞争、
无法安全取消且容易造成部分截断；读取可有限并行，写入与提交保持有界
顺序执行。

### Decision 8: 索引只优化候选选择，不成为正确性来源

数据集索引用于查询包含待修改 label 的文件集合。每个候选仍须读取 JSON
并检查真实 shape 内容；索引缺失、过期或查询失败时在 worker 内回退到
文件扫描。转换完成后只失效/更新受影响路径，JSON 始终是最终真相。

**Alternatives considered:** 完全信任索引可减少读取，但索引是可丢弃缓存，
不能承担破坏性迁移的正确性责任。

### Decision 9: 用性能门禁和视觉回归验收

自动化验收至少覆盖：

- 五种颜色模式、group_id 0/None/负数/布尔值、调色板循环和配置迁移。
- 明暗背景、不同 zoom、selected/hover/active edge/QA 组合的截图或像素
  回归。
- 聚焦状态机、过滤/虚拟复核不可见性、切图和删除清理。
- 颜色-only 零 JSON I/O、no-op 零写入、候选索引与扫描回退。
- 取消、rename merge、dirty 文件、未知字段保留、原子替换失败和恢复。
- 1 万 JSON / 少量命中基准中 GUI 线程无文件 I/O，进度持续推进；当前
  图片大量 shape 改色只产生一次合并重绘。

这里的性能门禁关注主线程停顿和无关写入数量，不用总耗时掩盖 GUI
卡死问题。

## Risks / Trade-offs

- **[Risk] 双层轮廓增加每帧绘制次数** → 只绘制 viewport 内可见 shape，
  缓存解析后的样式，并用密集框基准验证；必要时对非矩形保持单层路径。
- **[Risk] Focus 默认值让习惯全场组色的用户感到行为改变** → 保留一键
  Group 模式、迁移显式旧设置，并提供一次性说明。
- **[Risk] 弱化对象后不易发现遗漏框** → 无焦点总览保持所有对象可见，
  点击空白即可退出焦点，并提供 Uniform/Label/Group 模式。
- **[Risk] 项目 sidecar 的根目录解析错误** → 使用明确优先级、在 UI 显示
  实际保存位置，并在根目录不可写时只读运行和给出非阻塞警告。
- **[Risk] 事务备份占用磁盘** → 预检估算空间、空间不足时拒绝开始，成功
  后按保留策略清理，失败事务始终保留到用户确认。
- **[Risk] 提交阶段无法立即取消** → UI 明确显示“正在原子提交，不可取消”，
  且提交前的扫描/暂存阶段均可取消。
- **[Risk] 后台迁移与自动保存竞争** → 迁移前解决 dirty，提交阶段持有数据集
  写锁并暂停目标文件保存，完成后再恢复。
- **[Risk] 部分替换失败导致标签定义不一致** → 每文件原子替换、明确部分
  结果、磁盘实态重扫和 manifest 恢复，不提前提交预期 UI 状态。

## Migration Plan

1. 先增加纯 Python 外观类型、palette、focus 状态机和批量变更计划模型，
   保持现有 UI 行为不变并建立测试基线。
2. 实现安全批量 worker、事务 manifest/备份和恢复入口，先消除颜色-only
   全量写盘与 GUI 主线程迁移。
3. 接入新绘制上下文与高对比矩形样式，通过 feature flag 保持旧颜色路径
   可回滚；补齐五种模式和 Appearance 设置。
4. 接入 group focus 与现有选择、过滤、虚拟复核和矩形边 overlay，完成
   密集十组人工对比验收。
5. 启用新配置迁移：显式旧 manual/label 配色映射到 `label`，旧 uniform
   映射到 `uniform`，未显式选择的用户采用 `focus`；不自动覆盖旧配置文件。
6. 稳定一个版本后停止新写旧颜色键，保留一个版本的兼容读取。回滚时
   关闭新绘制 flag 并恢复旧读取路径；项目 sidecar 和事务清单不影响旧版
   标注 JSON 加载。
