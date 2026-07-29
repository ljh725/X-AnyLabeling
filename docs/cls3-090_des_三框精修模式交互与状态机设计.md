# 三框精修模式交互与状态机设计

> 状态：实现级设计基线（待代码实现与 Review）  
> 功能范围：`person` / `head` / `face` 水平矩形框精修  
> 文档类型：功能结构 + 交互设计 + 工作流 + 状态机 + 接口契约 + 验收标准  
> 版本：v1.0（2026-07-23）  
> 当前阶段：设计冻结候选，不包含应用代码实现

本文是交付给代码实现者的设计依据。第 1～20 节定义产品语义，第 21 节
以后定义实现级结构、接口和验收门禁。若代码、测试或口头说明与本文冲突，
以本文为准；实现者不得自行改变 GID 语义、保存时机、回滚边界或可见层
规则。

## 更新记录

- 2026-07-24：本次修正为“任务可见层仅在工作组存在时启用”；同时确认
  锚点必须来自用户基础可见层，工作组推导扫描当前图片全部三框矩形；
  `SELECTING` 不启用矩形边拖动；模式开启和结束需要在画布主界面显示
  非模态提示。

## 1. 文档定位

“功能结构”“工作流程”和“状态机”分别只能覆盖本需求的一部分。本功能
同时包含：

- 从“视图”菜单开启功能的交互入口；
- 鼠标选择对象后自动建立临时工作组；
- person/head/face 的非对称几何推导；
- GID 与几何证据的合并和冲突处理；
- 工作组内对象显示、隐藏和纠错；
- 通过、回滚、保存和连续处理；
- 模式、工作组和矩形边拖动之间的状态转换。

因此本文使用“交互与状态机设计文档”作为名称。

## 2. 业务背景

标注员需要精修三类水平矩形框：

- `person`
- `head`
- `face`

标注数据中的三类框可能：

- 使用统一 `group_id`；
- 只有部分框使用相同 `group_id`；
- 完全没有统一 `group_id`；
- 存在错误或重复的 `group_id`。

本功能不能把 GID 当作强制关系。临时工作组只用于当前精修交互，不写入
标注 JSON，也不修改任何正式 `group_id`。

## 3. 精修业务规则

### 3.1 包含关系

典型关系：

```text
face ⊆ head ⊆ person
```

### 3.2 水平边关系

大多数情况下：

```text
head.y_min ≈ person.y_min
head.y_max ≈ face.y_max
```

其中：

- `y_min` 是矩形上沿；
- `y_max` 是矩形下沿；
- 精修完成后，实际原图坐标误差通常为 `1～3 px`。

系统内部实时计算：

```text
top_delta = abs(head.y_min - person.y_min)
bottom_delta = abs(head.y_max - face.y_max)
```

误差必须使用原图坐标中的实际几何差异，不得根据：

- UI 对象线宽；
- 当前缩放倍率；
- 屏幕渲染后的视觉重合区域；
- 抗锯齿效果

进行计算。

实际差值只用于内部判断，不在 UI 中显示具体数字。

当某一条当前比较关系满足：

```text
delta < 3.0 px
```

Canvas 显示绿色非模态提示框。正好 `3.0 px` 或大于 `3.0 px` 时不显示
任何提示。

### 3.3 垂直边

三类矩形的垂直边是否重叠没有统一规则，由标注员根据实际画面判断。

### 3.4 人工确认

标注员通过画布实际图像和矩形边界确认结果。绿色提示框只表示当前水平
边的实际距离小于 `3 px`，不表示整个工作组准确，也不自动通过。

## 4. 功能入口

在“视图”菜单增加可勾选功能：

```text
三框精修模式
```

交互规则：

- 点击功能名称直接开启，不增加二次确认弹窗；
- 菜单勾选状态表示模式正在运行；
- 再次点击已勾选功能退出模式；
- 模式启动后通过鼠标选择 Shape 触发临时工作组；
- 不设置“建立工作组”按钮；
- 不设置“更换 Person/Head/Face”按钮；
- 三框精修模式为连续模式。

第一版不要求为开启/关闭模式分配默认快捷键，避免误触。后续如有明确
需求，可通过设置系统增加可配置快捷键。

## 5. 连续模式

开启一次模式后可以连续处理多个对象：

```text
开启模式
→ 选择对象
→ 建立工作组
→ 精修
→ 通过或回滚
→ 返回选择状态
→ 选择下一个对象
```

通过、Esc 或切换图片都不自动关闭三框精修模式。

只有以下操作退出模式：

- 用户再次点击“视图 → 三框精修模式”；
- 用户主动切换到与三框精修互斥的其他工作模式；
- 应用关闭。

## 6. 可见状态分层

### 6.1 用户基础可见层

进入模式时保存用户现有状态：

- label 筛选；
- GID 筛选；
- shape_type 筛选；
- 标签级可见状态；
- Shape 手动可见状态。

该状态在模式运行期间不得被任务筛选覆盖或改写。

### 6.2 任务可见层

任务可见层只控制三框精修主画布，并且只在临时工作组存在时启用。

模式刚开启并进入选择状态时，不得立即应用任务可见层，不得覆盖或隐藏
第 6.1 节保存的用户基础可见效果。此时：

```text
主画布显示 = 用户基础可见层
导航器显示 = 用户基础可见层
```

工作流只监听用户最终正式选中的有效锚点：

```text
label ∈ {person, head, face}
shape_type = rectangle
```

被用户基础可见层隐藏的三框对象，在选择状态下不得被任务层强行显示或选中。

临时工作组成功建立后，任务可见层才接管主画布。工作组状态只显示临时
工作组中的具体 Shape。其他标注全部隐藏，并且不可 hover、不可选中、
不可编辑。

### 6.3 导航器

导航器始终显示用户基础可见层，而不是主画布的任务可见层。

因此：

- 主画布可以只显示当前工作组；
- 导航器仍保留用户原筛选下的全局预览；
- 工作组切换不得改变导航器的原始筛选语义。

### 6.4 恢复规则

- 工作组结束：清除任务可见层，返回模式选择状态，主画布恢复用户基础
  可见效果；
- 切换图片：释放工作组，新图片进入模式选择状态，主画布使用新图片的
  用户基础可见效果；
- 退出模式：恢复用户进入模式前的基础可见状态。

连续模式依靠模式继续监听后续有效锚点实现，不依靠在选择状态强行显示
全部三框对象实现。

## 7. 鼠标选择触发

模式处于选择状态时，标注员直接在 Canvas 上点击
`person/head/face rectangle`。

复用项目现有对象命中和选择算法，不重新实现底层 hit-test。

现有算法负责解决：

- 顶点优先；
- 可编辑边优先；
- 包含区域兜底；
- 嵌套矩形中较小对象优先；
- 堆叠顺序。

工作流控制器只监听最终正式选中的 Shape，再根据 Shape 标签决定推导
方向。

用户直接点击的 Shape 是本次推导锚点，算法不得替换锚点。

锚点必须是当前用户基础可见层中可见并由 Canvas 正式选中的 Shape。锚点
确定后，工作组推导范围不再受用户基础可见层限制，而是扫描当前图片中全部
`person/head/face rectangle` Shape。这样模式开启时不打乱用户原筛选，
但建组后仍能把被原筛选隐藏的关联 `head/face/person` 拉入临时工作组。

## 8. 非对称推导

### 8.1 选择 Person

只有用户直接点击 `person` 时，才执行完整向下推导：

```text
person
→ 查找关联 head
→ 从 head 查找关联 face
```

临时工作组可以包含：

```text
{选中的 person, 一个或多个 head, 一个或多个 face}
```

允许：

- 缺少 head；
- 缺少 face；
- 几何上存在多个 head；
- 几何上存在多个 face。

### 8.2 选择 Head

选择 `head` 时只向上推导：

```text
head
→ 查找所属 person
→ 到 person 截止
```

临时工作组：

```text
{选中的 head, 推导出的 person}
```

找到 person 后不得再从 person 向下推导 face。

### 8.3 选择 Face

选择 `face` 时沿父级链向上推导：

```text
face
→ 查找所属 head
→ 查找所属 person
→ 到 person 截止
```

临时工作组可以是：

```text
{选中的 face, 推导出的 head, 推导出的 person}
```

若中间对象缺失，允许形成不完整工作组。找到 person 后不得重新从
person 向下扩展其他 head/face。

## 9. Person 的 GID 向下候选路径

用户直接选择 person 时，同时运行两条候选路径：

```text
选中 person
      │
      ├─ GID 路径
      └─ 几何路径
```

GID 路径只收集：

```text
group_id == person.group_id
label ∈ {head, face}
shape_type == rectangle
```

关键点和其他标签不得进入临时工作组。

GID 只作为候选证据，不能绕过几何合理性检查。

### 9.1 部分统一 GID

允许混合推导：

- person/head 同 GID，face 无 GID：head 使用 GID，face 使用几何；
- person/face 同 GID，head 无 GID：head 使用几何，再验证 face；
- 只有 person 有 GID：完全使用几何；
- person 无 GID：跳过 GID 路径。

### 9.2 结果一致

GID 与几何路径指向同一对象时，采用该对象。

### 9.3 结果冲突

以下属于冲突：

- 同 GID head 位于其他人物附近；
- 几何最合理 head 与同 GID head 不是同一个对象；
- 同 GID face 与推导 head 没有合理空间关系；
- GID 被复制或错误复用到其他人物；
- 同一 GID 下存在多个 `head`；
- 同一 GID 下存在多个 `face`。

发生明确冲突时：

1. 不建立临时工作组；
2. 自动回到模式选择状态；
3. 显示非模态提示；
4. 不自动修改 GID；
5. 由标注员重新点击目标对象。

提示示例：

```text
GID 12 中存在 2 个 head，无法建立唯一工作组
```

### 9.4 几何多候选不属于 GID 错误

没有统一 GID 时，几何上出现多个 head 或 face 是允许场景。所有合理候选
都加入工作组并显示，由标注员使用现有对象选择算法选择要编辑的矩形。

## 10. 几何候选原则

几何推导不得使用最终 `1～3 px` 精修标准作为硬过滤，否则需要修正的框
可能被排除。

关联计算优先使用内框包含率：

```text
head_person_containment =
    intersection_area(head, person) / area(head)

face_head_containment =
    intersection_area(face, head) / area(face)
```

完全包含时结果接近 `1.0`。普通 IoU 不适合作为主要指标，因为 head
通常远小于 person、face 通常远小于 head；即使内框完全正确，普通 IoU
也可能很低。

普通 IoU 可以作为次级排序指标，但不能单独决定关联关系。

### 10.1 Head 候选

综合考虑：

- head 在 person 中的内框包含率；
- head 中心位于 person 上部或附近；
- head 面积小于 person；
- head 上沿与 person 上沿的距离；
- 宽高和面积关系；
- 普通 IoU（次级排序）；
- GID 证据（仅作为辅助）。

### 10.2 Face 候选

综合考虑：

- face 在 head 中的内框包含率；
- face 面积小于 head；
- face 下沿与 head 下沿的距离；
- 中心和面积关系；
- 普通 IoU（次级排序）；
- GID 证据（仅作为辅助）。

候选搜索应允许在外框周围保留宽松扩展区域，以覆盖本来就存在包含关系
错误的待精修数据。

### 10.3 计算量

轴对齐矩形的一次包含率或 IoU 计算只需要常数次 `min/max`、乘法和
除法，单对计算复杂度为 `O(1)`。

先按 `person/head/face` 和 `rectangle` 过滤后，候选匹配约为：

```text
O(person_count × head_count + head_count × face_count)
```

常规单图的计算量很小，不是本功能的主要性能风险。实现仍应复用当前图片
索引并避免对无关标签做全量两两比较。

## 11. 临时工作组

临时工作组只存在于内存中，包含：

- 锚点 Shape；
- 推导出的其他 Shape；
- 工作组建立时的几何快照；
- 工作组建立前的 dirty 状态；
- 推导来源和冲突信息；
- 当前工作组状态。

临时工作组不得：

- 写入 JSON；
- 写入 Shape `other_data`；
- 修改 `group_id`；
- 修改 label；
- 持久化到用户配置。

建立工作组后：

- 仅工作组 Shape 在主画布可见；
- 锚点保持正式选中；
- 其他成员可由鼠标正常选择；
- 不新增“更换成员”入口；
- 推导错误时使用 Esc 退出后重新选择。

## 12. 精修交互

`SELECTING` 只负责点选锚点，不允许直接拖动矩形边修改框。即使模式内部
已经为后续工作组准备 Rectangle Edge Editing 能力，待选锚点状态下也不得
让矩形边拖动生效。

工作组建立后复用现有矩形边编辑能力：

- 鼠标直接选择任意可见矩形；
- 鼠标拖动矩形的水平边或垂直边；
- 精修降速保持现有行为；
- 一次完整拖边保留现有撤销粒度；
- 不改变 Rectangle Edge Editing 的底层命中算法。

业务上优先调整：

- person/head 上沿；
- head/face 下沿。

垂直边仍由标注员根据画面自由判断。

## 13. Esc 规则

Esc 使用分层优先级：

1. 正在拖动矩形边：回滚当前一次拖动；
2. 存在矩形边 pending 状态：取消 pending；
3. 存在临时工作组：恢复工作组初始几何，释放工作组；
4. 没有工作组：执行 Canvas 原有 Esc 行为。

释放工作组后：

- 模式保持开启；
- 清除任务可见层，主画布恢复用户基础可见效果；
- 返回待选锚点状态；
- 可以立即选择下一个对象；
- 不改写用户基础筛选和手动可见状态。

## 14. 通过当前工作组

### 14.1 默认快捷键

建议默认快捷键：

```text
Ctrl+Enter
```

选择理由：

- 当前默认快捷键配置未发现冲突；
- 表达“确认并提交”；
- 不占用单键，降低拖边期间误触；
- 可以纳入项目现有设置系统，允许用户修改。

配置键建议：

```yaml
shortcuts:
  accept_rect_refine_workgroup: Ctrl+Enter
```

第一版只要求快捷键入口，不讨论额外的工具栏按钮或菜单按钮。

### 14.2 可执行条件

只有满足以下条件时动作有效：

- 三框精修模式已开启；
- 当前存在临时工作组；
- 没有正在进行的边拖动；
- 没有未完成的 pending 边交互。

无工作组时按下快捷键不得保存文件或改变选择状态。

### 14.3 保存规则

执行“通过当前工作组”：

1. 保留工作组当前几何；
2. 调用项目现有保存路径；
3. 只有保存成功后才释放工作组；
4. 返回模式选择状态；
5. 模式保持开启；
6. 可以立即选择下一个对象。

如果保存失败、用户取消保存路径选择或写盘异常：

- 工作组保持激活；
- 当前几何保持不变；
- 不进入下一个对象选择状态；
- 显示现有保存错误信息；
- 允许用户重试。

通过操作不写入额外复核字段。

## 15. 模式状态机

```text
OFF
 │ 点击“视图 → 三框精修模式”
 ▼
SELECTING（保持用户基础可见效果）
 │ 鼠标正式选中可见的 person/head/face rectangle
 ▼
INFERRING
 ├─ GID冲突/重复 ───────────────→ SELECTING
 └─ 成功或允许的不完整工作组
 ▼
ACTIVE（仅工作组成员可见/可交互）
 ├─ 拖边 ─→ ACTIVE
 ├─ Esc ──→ 回滚并清任务层 ─────→ SELECTING
 ├─ Ctrl+Enter
 │    ├─ 保存成功并清任务层 ─────→ SELECTING
 │    └─ 保存失败 ───────────────→ ACTIVE
 ├─ 切换图片 → 回滚并清任务层 ───→ SELECTING（新图片）
 └─ 退出模式 → 回滚并恢复基础状态 → OFF
```

`INFERRING` 可以是同步瞬时状态，不要求显示阻塞式进度 UI。

## 16. 切换图片

三框精修模式开启期间切换图片：

1. 若存在工作组，恢复工作组建立时的几何；
2. 释放临时工作组；
3. 保留模式开启状态；
4. 保留用户基础筛选状态；
5. 新图片进入待选锚点状态，主画布按新图片的用户基础可见层显示；
6. 导航器更新为新图片的基础可见层。

不得把未通过工作组修改带入保存结果。

回滚工作组时不得清除工作组建立前已经存在的 dirty 状态。

## 17. 退出模式

用户再次点击“视图 → 三框精修模式”：

1. 若正在拖边，先回滚当前拖动；
2. 若存在工作组，回滚未通过的工作组修改；
3. 释放工作组；
4. 移除任务可见层；
5. 恢复用户基础筛选和可见状态；
6. 取消菜单勾选；
7. 在画布主界面显示非模态结束提示；
8. 不自动关闭导航器。

## 18. UI 确认信息

已确认原则：

- 标注员以 Canvas 图像和框线为主要确认依据；
- 对象线宽使用设置中的实际运行时值；
- 实际误差使用原图坐标在内部计算；
- UI 不显示具体 `top_delta/bottom_delta` 数字；
- 当前比较关系的实际差值 `<3.0 px` 时显示绿色提示框；
- 实际差值 `>=3.0 px` 时不显示提示；
- 绿色提示框不得自动决定通过；
- 模式开启但尚未建立工作组时，主画布保持用户基础可见效果；
- 工作组建立后，工作组之外的标注在主画布完全隐藏；
- 多个几何候选全部显示；
- 多候选不增加数值列表或汇总面板；
- 不增加成员更换按钮。

模式开启和结束必须在画布主界面显示非模态提示，用于弥补开启模式时主画布
不立即改变可见效果的问题。该提示只说明功能状态，例如“三框精修模式已开启”
和“三框精修模式已结束”，不要求用户点击确认，不写入 JSON，不进入撤销栈，
不设置 dirty。提示可以与状态栏同步显示，但不得只依赖菜单勾选状态。

绿色提示框是 Canvas 临时 Overlay：

- 不修改 Shape 原有颜色和线宽；
- 不写入 JSON；
- 不进入撤销栈；
- 不设置 dirty；
- 不弹出需要点击确认的窗口；
- 拖边时根据实际几何实时出现或消失；
- 文案只说明“上沿已接近”或“下沿已接近”，不显示像素数值。

提示对应当前正式选中的比较对象：

- 当前选中 head：判断该 head 与关联 person 的上沿；
- 当前选中 face：判断该 face 与关联 head 的下沿；
- 当前选中 person 且工作组中的 head/face 唯一：可以同时判断两组关系；
- 存在多个同类几何候选时，不显示候选汇总数据。

## 19. 建议代码结构

不建议继续把全部逻辑直接加入大型 `label_widget.py`。

建议拆分：

```text
rect_refine_workflow.py
  模式和工作组状态机、通过/回滚、连续处理

rect_refine_grouping.py
  非对称推导、GID/几何候选、冲突检测

rect_refine_visibility.py
  用户基础可见层、任务可见层、导航器可见层

rect_refine_types.py
  工作组、候选结果、冲突结果等数据结构
```

现有模块继续负责：

```text
label_widget.py
  action 接线、保存入口、模式 UI

widgets/canvas.py
  Shape 选择、矩形边拖动、绘制

rect_edge_alignment.py
  矩形边几何

filter_engine.py
  现有多条件筛选计算与可见同步

quality/geometry.py、quality/matching.py
  可复用的纯几何与匹配基础
```

## 20. 验收场景

至少覆盖：

- person/head/face 无 GID；
- 三框统一 GID；
- 仅 person/head 同 GID；
- 仅 person/face 同 GID；
- person 只有自身 GID；
- 同 GID 存在多个 head；
- 同 GID 存在多个 face；
- GID 与几何候选冲突；
- 几何存在多个 head/face；
- 缺少 head；
- 缺少 face；
- 从 person、head、face 分别触发；
- head/face 向上到 person 后不再向下展开；
- Esc 取消活动拖边；
- Esc 回滚整个工作组；
- Ctrl+Enter 保存成功；
- Ctrl+Enter 保存失败；
- 连续处理多个工作组；
- 水平边差值 `2.9 px` 时显示绿色提示；
- 水平边差值 `3.0 px` 时不显示提示；
- 水平边差值大于 `3.0 px` 时不显示提示；
- UI 不显示实际像素差数字；
- 绿色提示不改变 Shape 或自动通过；
- 完全包含但尺寸差异很大的候选可通过包含率进入候选集；
- 普通 IoU 较低时不得单独排除合理嵌套候选；
- 工作组期间切换图片；
- 退出模式恢复用户原筛选；
- 导航器始终使用用户基础可见层；
- 临时工作组不进入 JSON。

## 21. 默认参数与后续校准

上述参数不再阻塞第一版实现。第一版采用独立的
`rect_refine` 配置块，并以现有 L1/L2 QA 匹配基线作为初始默认值。精修
功能不得在运行时直接依赖 QA 阈值配置，避免以后调整质检策略时静默改变
标注交互。

### 21.1 face → head 默认值

| 参数 | 默认值 |
|------|--------|
| 最小 x 轴重叠率 | `0.25` |
| 最小 y 轴重叠率 | `0.15` |
| 最大 face/head 面积比 | `0.85` |
| head 搜索扩展比例 | `0.15` |
| 最大 face 溢出率 | `0.30` |
| 包含率权重 | `0.35` |
| 中心对齐权重 | `0.20` |
| 面积比权重 | `0.20` |
| IoU/重叠权重 | `0.25` |

### 21.2 head → person 默认值

| 参数 | 默认值 |
|------|--------|
| 最小 x 轴重叠率 | `0.15` |
| head 中心最大相对 y | `0.60` |
| 最大 head/person 面积比 | `0.40` |
| person 搜索扩展比例 | `0.20` |
| 包含率权重 | `0.30` |
| 上半身位置权重 | `0.25` |
| x 轴重叠权重 | `0.20` |
| 面积比权重 | `0.15` |
| 中心距离权重 | `0.10` |
| 关键点辅助权重 | `0.00`（第一版不使用） |

### 21.3 通用判定默认值

| 参数 | 默认值 | 语义 |
|------|--------|------|
| `min_accept_score` | `0.55` | 低于该分数不进入合理几何候选集 |
| `ambiguous_top_gap` | `0.12` | top1 与 top2 分差小于该值视为几何歧义 |
| `alignment_hint_px` | `3.0` | 仅当实际差值严格小于该值时显示绿色提示 |

交互匹配不设置 `top_n` 截断。所有通过硬过滤且分数达到
`min_accept_score` 的合理候选都必须保留。后续只能通过真实数据评估修改
配置默认值，不得为了让个别测试通过而在算法中加入隐藏常量。

## 22. 设计目标、边界和不变量

### 22.1 第一版必须交付

第一版必须形成一个完整闭环：

```text
模式入口
→ 选择锚点
→ 临时推导工作组
→ 隔离显示和限制编辑权限
→ 实时边对齐提示
→ 通过保存或 Esc 回滚
→ 连续选择下一目标
```

### 22.2 第一版不做

- 不自动修改、补齐或重新分配正式 `group_id`；
- 不把临时关系写入 JSON、`Shape.other_data` 或用户配置；
- 不提供成员列表、候选分数、像素差或“更换成员”面板；
- 不自动吸附矩形边，不自动通过工作组；
- 不支持 rotation、polygon、quadrilateral 等非水平矩形；
- 不新增数据库、后台任务或跨图片工作组；
- 不用模型推理替代几何匹配；
- 不改变现有 Rectangle Edge Editing 的命中和拖动算法；
- 不在本功能中修复无关的全局保存或过滤历史问题。

### 22.3 强制不变量

以下不变量在任何状态和异常路径中都必须成立：

1. `OFF` 状态不存在工作组、任务可见层和精修 Overlay。
2. `SELECTING` 状态不存在工作组任务可见层，主画布保持用户基础可见效果。
3. 一个工作组只能属于一张图片，并用图片 token 防止跨图引用失效 Shape。
4. 锚点始终是用户最终正式选中的 Shape，推导算法不得替换锚点。
5. 工作组成员只保存 Shape 运行时引用和内存快照，不持久化临时字段。
6. `ACTIVE` 状态仅工作组成员能在主画布绘制、hover、选择和编辑。
7. 导航器永远使用用户基础可见层，不读取任务可见层结果。
8. 工作组修改不得触发自动保存；只有“通过当前工作组”可以保存这些修改。
9. 保存成功前不得释放工作组；保存取消或失败后必须仍为 `ACTIVE`。
10. 回滚必须同时恢复几何、dirty 状态和工作组期间新增的撤销历史。
11. 模式退出后，用户进入模式前的过滤和手动可见状态必须原样恢复。
12. 绿色提示是派生视图状态，不得改变 Shape、dirty、撤销栈或保存内容。
13. 所有阈值计算使用原图浮点坐标，不使用缩放后屏幕坐标。

## 23. 功能结构

### 23.1 总体分层

```text
┌─────────────────────────────────────────────────────────────┐
│ LabelWidget：组合根、Action 接线、保存/切图/互斥模式入口   │
└──────────────┬───────────────────────────┬──────────────────┘
               │                           │
               ▼                           ▼
┌──────────────────────────┐   ┌──────────────────────────────┐
│ RectRefineWorkflow       │   │ RectRefineVisibility        │
│ 状态机、工作组生命周期   │   │ 基础层/任务层/导航器分层   │
└──────────────┬───────────┘   └──────────────┬───────────────┘
               │                              │
               ▼                              ▼
┌──────────────────────────┐   ┌──────────────────────────────┐
│ RectRefineGrouping       │   │ Canvas / Navigator 适配面   │
│ 纯几何、GID 合并、冲突   │   │ 绘制、命中、选择、Overlay   │
└──────────────┬───────────┘   └──────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────┐
│ RectRefineTypes + quality.geometry 等纯数据/纯几何基础      │
└─────────────────────────────────────────────────────────────┘
```

### 23.2 模块职责

| 模块 | 必须负责 | 禁止负责 |
|------|----------|----------|
| `rect_refine_types.py` | 状态、工作组、快照、候选、冲突、保存结果等类型 | Qt UI、文件写入、全局单例 |
| `rect_refine_grouping.py` | 非对称推导、几何评分、GID 合并、冲突检测、关系图 | 改 Shape、改 GID、弹 UI、写 JSON |
| `rect_refine_visibility.py` | 捕获/恢复基础可见层、设置任务可见层、为导航器提供基础可见映射 | 推导候选、保存、改正式过滤条件 |
| `rect_refine_workflow.py` | 唯一工作流状态所有者、事件守卫、工作组快照、通过/回滚、切图协调 | 直接实现 Canvas hit-test、直接拼装 JSON |
| `label_widget.py` | 依赖组装、菜单/快捷键、保存适配、切图和互斥模式接线 | 持有分散的推导规则或复制状态机 |
| `widgets/canvas.py` | 原有选中/拖边、有效可见性查询、Esc 优先级、实时 Overlay 绘制 | GID 推导、保存、工作组生命周期 |
| `filter_engine.py` | 继续计算用户基础过滤结果 | 感知精修状态机 |
| `navigator_widget.py` | 按调用方提供的基础可见映射绘制 | 读取主画布任务层 |

### 23.3 依赖方向

依赖只能从 UI/工作流指向纯逻辑：

```text
LabelWidget/Canvas
    → Workflow/Visibility
        → Grouping/Types
            → pure geometry
```

`rect_refine_grouping.py` 和 `rect_refine_types.py` 必须可在不安装或不导入
PyQt6 的测试进程中加载。不得从纯逻辑模块反向 import `label_widget.py`、
`canvas.py` 或 Inspector UI。

## 24. 核心数据模型

以下名称是接口语义名称，实现可遵循项目命名风格微调，但字段语义不得
丢失。

### 24.1 `RectRefineState`

| 状态 | 含义 |
|------|------|
| `OFF` | 功能关闭，无任务可见层 |
| `SELECTING` | 模式开启，等待用户选择有效锚点；主画布保持用户基础可见效果 |
| `INFERRING` | 同步推导工作组，防止选择信号重入 |
| `ACTIVE` | 工作组已建立，可选择成员和拖边 |
| `SAVING` | 正在执行通过保存，拒绝重复通过和其他状态变更 |

`SAVING` 即使在当前同步保存实现中也是必要的瞬时状态，用于明确重入和
异常恢复语义。

### 24.2 `ShapeRefineView`

纯逻辑输入视图，至少包含：

| 字段 | 说明 |
|------|------|
| `shape_id` | 当前图片生命周期内稳定且唯一的标识，用于候选去重 |
| `shape_ref` | UI 层可选的运行时回连引用；纯逻辑只将其视为不透明值 |
| `shape_index` | 当前 `canvas.shapes` 顺序索引，仅用于稳定排序和诊断 |
| `label` | `person/head/face` |
| `shape_type` | 第一版只接受 `rectangle` |
| `group_id` | 原始 GID，只读 |
| `points` | 原图坐标的不可变副本 |
| `bbox` | 从 points 计算出的 `(x1, y1, x2, y2)` |

有效 GID 定义为非 bool 的整数。缺失、非法类型或非法值只表示“没有可用
GID 证据”，不得在精修模式中自动修复。

### 24.3 `GroupingCandidate`

至少记录：

- 候选 Shape 标识；
- 关系类型：`head_of_person`、`face_of_head`、`person_of_head`；
- 来源集合：`geometry`、`gid` 或两者；
- 总分及用于解释冲突的分项指标；
- 是否通过硬过滤；
- 是否达到接受分数；
- 与 top1 的分差；
- 稳定排序键。

分数只用于内部判定和测试，不在 UI 中显示。

### 24.4 `RectRefineRelationGraph`

工作组必须保留明确关系，而不是只有一个 Shape 集合：

- `person_to_heads`；
- `head_to_faces`；
- `head_to_person`；
- `face_to_head`；
- 对歧义向上关系允许值为空；
- 一个 Shape 只能在成员集合中出现一次。

Overlay 只能读取该关系图，禁止在绘制阶段重新运行全图匹配。

### 24.5 `WorkgroupSnapshot`

工作组建立时一次性捕获：

| 字段 | 用途 |
|------|------|
| `image_token` | 防止跨图回滚错误对象 |
| `anchor_shape_id` | 锚点身份 |
| `member_shape_ids` | 工作组成员 |
| `original_points` | 每个成员 points 的深拷贝 |
| `dirty_before` | 建组前文档 dirty 状态 |
| `undo_floor` | 建组前 Canvas 撤销栈边界 |
| `relation_graph` | Overlay 和内部关系 |
| `provenance` | GID/几何来源和内部诊断 |

### 24.6 `RectRefineWorkgroup`

至少包含：

- 不可变的建组快照；
- 当前成员运行时引用；
- 当前工作组状态；
- 当前正式选中成员；
- 是否发生已提交到内存的几何变更；
- 最后一次冲突或提示信息。

### 24.7 `SaveResult`

保存适配必须返回明确枚举，不得使用窗口 dirty 状态反推：

| 结果 | 状态机处理 |
|------|------------|
| `SUCCESS` | 保留几何，释放工作组，转 `SELECTING` |
| `CANCELLED` | 保留工作组和几何，转回 `ACTIVE` |
| `FAILED` | 保留工作组和几何，转回 `ACTIVE` |

## 25. 工作流状态机

### 25.1 状态图

```text
OFF
 │ ENABLE
 ▼
SELECTING
 │ VALID_ANCHOR_SELECTED
 ▼
INFERRING
 ├─ CONFLICT / ERROR ──────────────────────────→ SELECTING
 └─ GROUP_READY（允许不完整）─────────────────→ ACTIVE
                                                   │
                   ┌───────────────────────────────┤
                   │ ESC_ROLLBACK                  │ ACCEPT
                   ▼                               ▼
               SELECTING                         SAVING
                                                   ├─ SUCCESS → SELECTING
                                                   ├─ CANCEL  → ACTIVE
                                                   └─ FAILURE → ACTIVE

任意非 OFF 状态
 ├─ DISABLE / MUTEX_MODE → 回滚活动工作组、恢复基础层 → OFF
 ├─ BEFORE_IMAGE_CHANGE  → 回滚活动工作组、释放成员
 └─ APP_CLOSE            → 回滚活动工作组、恢复基础层 → OFF

新图片 AFTER_IMAGE_LOADED：
模式仍开启时进入 SELECTING；模式关闭时保持 OFF。
```

### 25.2 事件与守卫

| 事件 | 允许状态 | 守卫 | 核心效果 |
|------|----------|------|----------|
| `ENABLE` | `OFF` | 无保存进行中 | 捕获基础状态、准备编辑能力、进入待选锚点状态 |
| `DISABLE` | 非 `OFF` | 无 | 取消拖边、回滚工作组、恢复基础状态 |
| `ANCHOR_SELECTED` | `SELECTING` | 恰好一个有效三框矩形 | 固定锚点并进入推导 |
| `GROUP_READY` | `INFERRING` | 推导未冲突 | 建快照、应用成员可见层、锚点保持选中 |
| `GROUP_CONFLICT` | `INFERRING` | 有明确 GID 冲突 | 清选择、显示非模态提示 |
| `ESC_WORKGROUP` | `ACTIVE` | Canvas 无 drag/pending | 回滚完整工作组 |
| `ACCEPT` | `ACTIVE` | 无 drag/pending，工作组仍属于当前图 | 进入 `SAVING` |
| `SAVE_SUCCESS` | `SAVING` | 无 | 保留几何、释放组、选择层 |
| `SAVE_CANCELLED` | `SAVING` | 无 | 工作组保持活动 |
| `SAVE_FAILED` | `SAVING` | 无 | 工作组保持活动 |
| `BEFORE_IMAGE_CHANGE` | 非 `OFF` | 无 | 回滚活动组；模式保持开启 |
| `AFTER_IMAGE_LOADED` | 模式开启 | 图片装载成功 | 为新图计算基础层并进入待选锚点状态 |
| `MUTEX_MODE_ENTERED` | 非 `OFF` | 无 | 等同退出模式后再进入目标模式 |
| `APP_CLOSE` | 非 `OFF` | 无 | 回滚并清理所有临时状态 |

### 25.3 Esc 双状态机仲裁

工作流状态机不得复制 Canvas 的矩形边交互状态。Esc 必须按以下固定顺序
仲裁：

```text
Canvas rect-edge DRAGGING?
  是 → cancel_rect_edge_drag()，消费事件
  否
Canvas rect-edge PENDING?
  是 → clear pending，消费事件
  否
Workflow ACTIVE?
  是 → rollback_workgroup()，消费事件
  否
执行 Canvas/Qt 原有 Esc 行为
```

Canvas 应提供一个位于现有边交互处理之后、默认处理之前的窄 Esc 委托或
等价同步契约。不得使用抢在 Canvas 前面的通用 event filter，否则会破坏
“当前拖动优先回滚”的既有语义。

### 25.4 非法或重复事件

- `SELECTING` 中收到空选择、无效 Shape 或多选：忽略并保持 `SELECTING`；
- `ACTIVE` 中因拖边按下造成选择清空：不得释放工作组；
- `INFERRING` 中的程序化选择变化：不得再次触发推导；
- `SAVING` 中重复按 `Ctrl+Enter`：忽略；
- 对已释放工作组重复回滚：必须是幂等 no-op；
- 旧图片 token 的回调：忽略并记录调试日志，不得操作新图。

## 26. 详细工作流程

### 26.1 开启模式

1. 用户勾选“视图 → 三框精修模式”。
2. 若当前处于绘制、自动标注或关键点填充等互斥模式，先按其既有契约安全
   退出；若无法退出，则拒绝开启并恢复菜单未勾选状态。
3. 捕获模式级用户基础状态：
   - `FilterState` 副本；
   - 标签级可见状态；
   - 当前图每个 Shape 的手动可见状态；
   - label list check state；
   - `shape.visible`、`canvas.visible` 和 `hidden_by_filter` 的基础值；
   - 矩形边编辑开关原值。
4. 暂停会改变基础过滤或手动可见性的 UI 动作。导航器缩放、平移和窗口开关
   仍可使用。
5. 强制进入 Canvas `EDIT` 模式。
6. 为后续工作组准备 Rectangle Edge Editing 能力，但记录并保留用户原
   开关值；在 `SELECTING` 中不得启用拖边修改。
7. 不安装任务可见层，主画布继续使用用户基础可见效果。
8. 清除或忽略进入模式前已有的正式选择，避免旧选择自动触发建组。
9. 进入 `SELECTING`。
10. 菜单保持勾选，状态栏和画布主界面显示非阻塞开启提示。

如果尚未加载图片，模式仍可开启；此时保持 `SELECTING`，待图片成功加载后
建立该图的基础层，主画布仍按基础层显示。

### 26.2 从正式选择建立工作组

1. 只监听 Canvas 已提交后的 `selection_changed`，不自行做 hit-test。
2. 仅在 `SELECTING` 且最终正式选择恰好包含一个有效矩形时处理。
3. 立即记录该 Shape 为不可替换锚点，并先转 `INFERRING`，阻断信号重入。
4. 从当前 `canvas.shapes` 构建只读 `ShapeRefineView` 列表，候选范围为
   当前图片全部 `person/head/face rectangle`，不受用户基础可见层限制。
5. 根据锚点标签执行第 29 节的非对称推导。
6. 若发生明确 GID 冲突：
   - 不创建工作组；
   - 清除正式选择；
   - 确保未安装任务可见层，主画布保持用户基础可见效果；
   - 转 `SELECTING`；
   - 状态栏显示具体但不含分数的提示。
7. 若成功或得到允许的不完整结果：
   - 构建成员集合和关系图；
   - 捕获 `WorkgroupSnapshot`；
   - 安装工作组任务可见层，使主画布仅显示成员；
   - 程序化恢复锚点正式选中；
   - 转 `ACTIVE`。

推导异常不得导致 UI 崩溃。无法解析的几何按不可靠候选处理；非预期异常
应记录日志、显示通用非模态提示并回到 `SELECTING`。

### 26.3 工作组内精修

`ACTIVE` 期间：

- 允许点击切换当前正式选中的工作组成员；
- 允许 Rectangle Edge Editing 直接拖动水平边或垂直边；
- 允许精修降速及其既有锁定行为；
- 禁止创建 Shape、删除、复制、粘贴、改 label、改 GID、分组/解组；
- 禁止整体拖动矩形、顶点拖动、键盘方向键移动和旋转；
- 非成员即使通过其他组件获得引用也不得被选择或编辑；
- 每次完成拖边仍形成一个撤销粒度；
- 工作组内撤销不得越过 `undo_floor`；
- 工作组几何变化只更新内存 dirty，不触发自动保存。

之所以禁止整体和顶点编辑，是因为本功能的事务边界是“矩形单边精修”。
若允许其他编辑动作，工作组回滚、Overlay 关系和验收范围都会变得不确定。

### 26.4 dirty 与自动保存

现有 `canvas.shape_moved → LabelWidget.set_dirty` 在启用 `auto_save` 时会
立即写盘，这与工作组事务语义冲突。设计要求提供统一的几何提交入口：

```text
普通模式的几何提交
  → 现有 set_dirty / auto_save 行为

三框精修 ACTIVE 的几何提交
  → 标记 workgroup changed
  → 设置窗口内存 dirty 和撤销可用状态
  → 不写盘
```

实现不得通过临时修改用户的 `auto_save` 配置值来达成暂停，也不得在异常
路径忘记恢复配置。应由几何提交适配器根据工作流状态显式路由。

### 26.5 通过当前工作组

1. 用户按配置快捷键 `Ctrl+Enter`。
2. 仅 `ACTIVE` 状态处理。
3. 若 Canvas 正在拖边或存在 pending，拒绝通过并保持 `ACTIVE`。
4. 验证工作组图片 token、成员引用和当前图片仍一致。
5. 转 `SAVING`，防止重复提交。
6. 调用明确返回 `SaveResult` 的保存适配器：
   - 已有 label file：覆盖原路径；
   - 配置 output file：使用该路径；
   - 无路径：打开现有保存对话框；
   - 用户取消对话框：返回 `CANCELLED`；
   - `save_labels()` 成功：返回 `SUCCESS`；
   - `save_labels()` 返回失败或抛出可处理异常：返回 `FAILED`。
7. `SUCCESS`：
   - 保留当前几何；
   - 保留工作组期间的合法撤销历史；
   - 清除工作组和 Overlay；
   - 任务层恢复模式选择层；
   - 清除正式选择；
   - 转 `SELECTING`。
8. `CANCELLED` 或 `FAILED`：
   - 不改几何、不改快照、不释放成员；
   - 重新应用工作组任务层；
   - 转回 `ACTIVE`；
   - 使用现有错误 UI 或状态提示允许重试。

即使工作组没有发生几何变化，“通过”仍执行一次现有保存路径，表示人工
已经确认当前结果。

### 26.6 回滚当前工作组

完整工作组回滚按固定顺序执行：

1. 若 Canvas 正在拖边，先调用现有单次拖动取消；
2. 清除 pending、hover 和 Overlay；
3. 验证图片 token；若不匹配，仅释放失效引用，不操作新图；
4. 将所有成员 points 恢复为 `original_points` 深拷贝；
5. 主动使 Shape 几何缓存失效；
6. 将 Canvas 撤销栈恢复到 `undo_floor`；
7. 将文档 dirty 精确恢复为 `dirty_before`；
8. 释放工作组；
9. 清除任务可见层，主画布恢复用户基础可见效果，并清除正式选择；
10. 转 `SELECTING`。

回滚不得调用通用“撤销 N 次”，因为工作组建立前可能已经存在用户修改，
且拖边次数不一定等于撤销栈变化次数。

### 26.7 切换图片

所有图片切换入口，包括文件列表、上一张/下一张、过滤结果导航、最近文件
和直接 `load_file()`，必须经过同一切图前置契约：

1. `before_image_change()` 幂等执行工作组回滚；
2. 保留模式级基础过滤快照和菜单勾选；
3. 如建组前已 dirty，继续执行项目原有 `may_continue()`；
4. 用户取消切图时，当前图片保持 `SELECTING`，不会重建已回滚工作组；
5. 图片成功装载后，为新 Shape 重新计算基础可见映射；
6. 不安装任务可见层，主画布按新图片基础层显示；
7. 导航器以新图片基础层刷新；
8. 模式保持开启并处于 `SELECTING`。

注意：未通过的工作组修改先无条件回滚，因此不得触发“是否保存这些临时
精修”的弹窗。建组前已经存在的 dirty 修改仍遵循项目原有询问逻辑。

### 26.8 退出模式和应用关闭

主动关闭模式或进入互斥模式：

1. 取消活动拖边；
2. 回滚活动工作组；
3. 移除任务可见层；
4. 恢复模式进入前的过滤控件状态和基础可见状态；
5. 恢复 Rectangle Edge Editing 原开关值；
6. 恢复被暂停的基础可见性相关动作；
7. 清除 Overlay、成员引用和图片 token；
8. 取消菜单勾选并转 `OFF`。

应用关闭前执行相同清理，再由原有 `may_continue()` 处理建组前 dirty
修改。关闭清理必须幂等，避免 Qt 多次 close 事件造成重复回滚。

## 27. 接口契约

接口契约描述调用语义，不要求逐字采用下列方法名。

### 27.1 Workflow 对外接口

| 接口 | 输入 | 输出 | 契约 |
|------|------|------|------|
| `enable()` | 当前图上下文 | 是否成功 | 仅 `OFF` 有效；成功后为 `SELECTING` |
| `disable(reason)` | 退出原因 | 无 | 幂等；最终必须 `OFF` |
| `on_selection_changed(shapes)` | 已提交正式选择 | 无 | 只在 `SELECTING` 建组；`ACTIVE` 只更新当前成员 |
| `handle_escape()` | 无 | 是否消费 | 仅负责工作组层，不抢占 drag/pending |
| `accept_workgroup()` | 无 | `SaveResult/是否启动` | 守卫失败不得保存 |
| `before_image_change()` | 无 | 无 | 幂等回滚，不关闭模式 |
| `after_image_loaded(context)` | 新图上下文 | 无 | 模式开启时建立基础层并保持 `SELECTING` |
| `enter_mutex_mode(reason)` | 模式标识 | 无 | 等同安全退出 |
| `overlay_model()` | 无 | 只读 Overlay 模型 | 无工作组时为空 |

### 27.2 Grouping 接口

| 接口 | 输入 | 输出 |
|------|------|------|
| `infer(anchor, all_shapes, config)` | 锚点、当前图只读 Shape 列表、独立配置 | `GroupingResult` |

`GroupingResult` 为判别联合：

- `READY`：成员、关系图、来源和可选非阻塞提示；
- `CONFLICT`：稳定冲突码、用户提示模板参数和内部诊断；
- 不使用异常表达合法的“缺少 head/face”或“向上关系歧义”。

### 27.3 Visibility 接口

| 接口 | 契约 |
|------|------|
| `capture_base_state(context)` | 深拷贝用户过滤与每 Shape 基础可见状态 |
| `base_visible(shape)` | 仅根据用户基础层判定 |
| `set_workgroup_task_layer(member_ids)` | 主画布只允许具体成员 |
| `clear_task_layer()` | 不改变基础层 |
| `main_visible(shape)` | `base/task` 的专用合成结果，按第 28 节规则执行 |
| `navigator_visibility()` | 返回仅基础层映射 |
| `restore_base_state()` | 恢复进入模式时的 UI 和 Shape 可见状态 |

### 27.4 Canvas 最小适配接口

Canvas 只需暴露或保持以下能力：

- 查询 `rect_edge_dragging`；
- 查询是否存在 rect-edge pending；
- 取消活动拖边；
- 清除 rect-edge pending/hover；
- 设置/清除任务可见性提供者；
- 设置/清除只读 Overlay 提供者；
- 在边交互 Esc 未消费时同步调用工作流 Esc 委托；
- 在 paint 时按当前 Shape 引用实时读取 Overlay 几何；
- 在 `is_shape_interactive()` 中使用主画布有效可见性；
- 提供受 `undo_floor` 限制的工作组撤销能力或等价适配。

不得把 Workflow 对象整体塞进 Canvas，也不得让 Canvas import grouping
模块。

### 27.5 LabelWidget 保存适配

现有 `save_file()` / `_save_file()` 不返回成功结果，不能直接作为状态机
判断依据。必须增加一个窄保存适配层，最终以 `save_labels()` 的布尔返回为
准，并区分用户取消和写盘失败。

保存适配层仍复用现有：

- 路径解析；
- `save_file_dialog()`；
- `save_labels()`；
- recent file 更新；
- `set_clean()`；
- 现有错误消息。

禁止复制一套 JSON 序列化逻辑。

### 27.6 信号接线

| 现有/新增事件 | 接收方 | 说明 |
|---------------|--------|------|
| `canvas.selection_changed(list)` | Workflow，经 LabelWidget 中转 | 正式选择是唯一锚点来源 |
| 边几何提交事件 | dirty 路由器 + Workflow | ACTIVE 时禁止 auto-save |
| 当前选择变化 | Overlay 模型 | 仅变更比较对象，不重新推导全组 |
| 图片装载前/后 | Workflow | 统一切图事务 |
| 模式 QAction toggled | Workflow | QAction 只是入口，不是状态真相 |
| 接受 QAction/shortcut | Workflow | 默认 `Ctrl+Enter` |

Workflow 的 `state` 是唯一状态真相。菜单勾选、Canvas 开关和 Overlay
可见性都必须由状态同步，不能反向拼出状态。

## 28. 可见层与交互权限设计

### 28.1 不得复用单一 `canvas.visible`

当前导航器直接读取 `canvas.visible`，而现有过滤执行会同时修改 label
list check state、`shape.visible` 和 `canvas.visible`。若精修功能继续覆盖
这些字段，将无法同时满足：

- 待选锚点状态保留用户基础显示；
- 工作组期间主画布仅显示任务 Shape；
- 导航器保留用户基础过滤；
- 退出模式精确恢复原状态。

因此任务层必须是独立的临时层，不得通过调用现有过滤 UI 来模拟。

### 28.2 三种可见性

| 名称 | 计算依据 | 使用者 |
|------|----------|--------|
| `base_visible` | 用户过滤、标签可见性、Shape 手动可见性 | 导航器、恢复逻辑 |
| `task_visible` | `ACTIVE` 的成员集合 | 主画布精修任务 |
| `main_visible` | `OFF/SELECTING` 为基础层；`ACTIVE/SAVING` 为任务层 | Canvas 绘制和交互 |

待选锚点状态不得为了三框精修覆盖用户原筛选。因此：

```text
OFF / SELECTING:
main_visible(shape) = base_visible(shape)
```

工作组建立后，主画布进入任务隔离视野：

```text
ACTIVE / SAVING:
main_visible(shape) = task_visible(shape)
```

`INFERRING` 是同步瞬时状态，推导期间不得先改变主画布可见层；只有成功
建立工作组并转入 `ACTIVE` 时才安装任务可见层。

### 28.3 待选锚点状态

```text
valid_anchor(shape) =
    base_visible(shape)
    and shape.label in {person, head, face}
    and shape.shape_type == rectangle
```

选择状态不定义 `task_visible`，也不强行显示被用户基础层隐藏的三框对象。
工作流只在 Canvas 已提交的正式选择满足 `valid_anchor` 时触发推导。

无效/退化矩形若在基础层中可见，可以由用户选中以发现问题；选择后若无法
生成有效 bbox，只建立锚点不完整工作组并提示“矩形几何无效，无法推导关联
对象”；不得崩溃。

### 28.4 工作组任务层

```text
task_visible(shape) = shape.shape_id in workgroup.member_shape_ids
```

工作组任务层只在 `ACTIVE/SAVING` 存在。工作组释放、回滚、保存成功或
切图后必须清除任务层，使 `SELECTING` 回到基础层显示。

Canvas 绘制、hover、hit-test、边命中、正式选择和键盘编辑必须使用同一个
`main_visible` 判定，禁止出现“看不见但可选中”或“可见但不可拖边”的分裂。

### 28.5 导航器

导航器调用必须改为显式传入 `navigator_visibility()`，不能读取主画布任务
层。工作组内当前 hover/选择高亮不得通过修改共享 Shape 临时字段污染导航器；
若导航器需要高亮，应使用独立参数。

### 28.6 模式期间基础状态控制

为保证“退出后原样恢复”，模式运行期间暂停以下基础状态修改入口：

- label/GID/shape_type 过滤变更；
- 标签级 show/hide；
- Shape 手动 show/hide；
- 全部显示/隐藏；
- 会间接批量改可见性的快捷键。

若用户触发，显示非模态提示“请先退出三框精修模式再调整筛选或可见性”。
导航器的窗口显示、缩放和平移不属于基础 Shape 可见状态，可继续使用。

## 29. 工作组推导设计

### 29.1 通用预过滤

只把以下 Shape 放入推导索引：

```text
label ∈ {person, head, face}
shape_type == rectangle
bbox 有限且面积 > 0
```

锚点本身即使几何无效也不得被替换；这种情况建立仅含锚点的不完整工作组，
不再推导其他成员。

### 29.2 评分公式

第一版评分必须确定且可由单元测试复算。

face→head：

```text
center_alignment = 1 - min(1, center_distance_norm(face, head))
area_score = triangle(face_area / head_area, ideal=0.30, high=0.85)

score =
    0.35 * containment(face, head)
  + 0.20 * center_alignment
  + 0.20 * area_score
  + 0.25 * iou(face, head)
```

head→person：

```text
head_y_rel = (head_center_y - person.y_min) / person.height
upper_score = 1.0                         when 0.10 <= head_y_rel <= 0.30
              head_y_rel / 0.10           when 0.00 <= head_y_rel < 0.10
              (0.60-head_y_rel) / 0.30    when 0.30 < head_y_rel < 0.60
              0.0                         otherwise

center_alignment = 1 - min(1, center_distance_norm(head, person))
area_score = triangle(head_area / person_area, ideal=0.08, high=0.40)

score =
    0.30 * containment(head, person)
  + 0.25 * upper_score
  + 0.20 * x_overlap_ratio(head, person)
  + 0.15 * area_score
  + 0.10 * center_alignment
```

三角面积比分数定义为：

```text
ratio <= 0 or ratio >= high: 0
0 < ratio <= ideal: ratio / ideal
ideal < ratio < high: (high - ratio) / (high - ideal)
```

普通 IoU 只出现在 face→head 的次级加权项中，任何候选仍需先经过以包含、
扩展框和面积关系为主的硬过滤。第一版不读取关键点，不允许 GID 或关键点
分数把未通过硬过滤的候选拉回候选集。

### 29.3 稳定排序

几何候选必须使用稳定排序：

```text
总分降序
→ 包含率降序
→ 中心距离升序
→ 面积升序
→ shape_index 升序
```

相同输入必须得到相同成员顺序，避免工作组和测试随机抖动。

### 29.4 选择 person：完整向下推导

执行顺序：

1. 固定用户 person 为锚点。
2. 运行 person 的 GID 路径：
   - 仅有效整型 GID；
   - 只收集同 GID 的 head/face rectangle；
   - 同 GID 多个 head 或多个 face 立即产生重复冲突。
3. 对所有 head 运行 head→person 的反向合理性评分，以选中 person 为
   指定外框；保留全部通过硬过滤且分数 `>= 0.55` 的 head。
4. 合并 GID head：
   - GID head 未通过硬过滤：冲突；
   - GID head 是合理候选：加入并标记来源；
   - 有另一个几何 top1，且其分数比 GID head 高至少 `0.12`：冲突；
   - 分差小于 `0.12`：视为几何歧义，保留所有合理候选，不判 GID 错误。
5. 对每个已接受 head 搜索全部合理 face，取并集并建立 `head_to_faces`。
6. 合并同 GID face：
   - 必须能通过至少一个已接受 head 的 face→head 硬过滤；
   - 若所有 head 都无法验证该 face：冲突；
   - 若不存在任何已接受 head，则同 GID face 不得绕过几何校验进入组，
     只返回非阻塞提示，不判冲突。
7. 几何 face 多候选全部保留；同一 face 被多个 head 接受时：
   - top1 与 top2 分差 `>= 0.12`，记录唯一 `face_to_head`；
   - 分差 `< 0.12`，成员仍保留，但 `face_to_head` 为空，避免错误 Overlay。
8. 工作组至少包含锚点 person，可合法缺少 head 或 face。

### 29.5 选择 head：仅向上

1. 固定用户 head 为锚点。
2. 对所有 person 运行 head→person 推导。
3. 最高分 `< 0.55`：不加入 person，形成仅 head 的不完整组。
4. top1/top2 分差 `< 0.12`：视为向上歧义，不自动加入任何 person，
   显示“存在多个 Person 候选，请改为直接点击目标 Person”。
5. 唯一可靠 top1：加入该 person 并建立 `head_to_person`。
6. 到此停止，不从 person 查找任何其他 head 或 face。

选择 head 的向上路径第一版只使用几何关系。person GID 向下合并规则不得
反向套用，以免正式 GID 解耦场景产生错误强绑定。

### 29.6 选择 face：沿父链向上

1. 固定用户 face 为锚点。
2. 运行 face→head 推导：
   - 无可靠候选：形成仅 face 的不完整组；
   - 多个可靠候选且 top gap `< 0.12`：不自动选 head，显示歧义提示并停止；
   - 唯一可靠 top1：加入 head。
3. 若已得到 head，再按第 29.5 节查找唯一可靠 person。
4. 任一步缺失或歧义即停止向上链，但已确定的下层成员保留。
5. 找到 person 后停止，绝不从 person 向下展开其他成员。

### 29.7 冲突分类

冲突码必须稳定，便于测试和 Review；用户文案可以翻译。

| 冲突码 | 触发条件 | 用户结果 |
|--------|----------|----------|
| `DUPLICATE_GID_HEAD` | person GID 路径有多个 head | 不建组 |
| `DUPLICATE_GID_FACE` | person GID 路径有多个 face | 不建组 |
| `GID_HEAD_GEOMETRY_INVALID` | 同 GID head 未通过 person 几何硬过滤 | 不建组 |
| `GID_HEAD_DISAGREES_WITH_GEOMETRY` | 另一 head 明显优于 GID head，分差 ≥ `0.12` | 不建组 |
| `GID_FACE_GEOMETRY_INVALID` | 同 GID face 无法由任一已接受 head 验证 | 不建组 |

纯几何多候选、缺少成员、无可靠候选和向上歧义都不是 GID 冲突，不使用
上述错误码。

### 29.8 几何基础复用

可复用 `quality/geometry.py` 的 bbox、面积、包含率、扩展框、重叠和归一化
距离等纯函数。现有 `quality/matching.py` 使用 `QcShape` 并服务质检报告，
不得让 UI 工作流直接依赖其报告模型。

允许的实现路径：

1. 抽取一个不依赖 `QcShape` 的通用纯匹配核心，让 QA 和精修分别适配；
2. 或在 `rect_refine_grouping.py` 使用相同纯几何函数实现独立候选评分。

无论采用哪种路径，都必须保证 QA 现有行为和测试不被静默改变。

## 30. 实时 Overlay 设计

### 30.1 Overlay 模型

Overlay 模型只包含：

- 当前是否为 `ACTIVE`；
- 当前正式选中的成员身份；
- 可比较的 `(outer, inner, edge_kind)` 关系；
- `alignment_hint_px`；
- 对应的翻译文案 key。

模型保留 Shape 只读引用，因此拖边过程中 Canvas 每次 repaint 都能读取
最新 points，不依赖 `shape_moved` release 信号。

### 30.2 比较规则

| 当前选择 | 比较 |
|----------|------|
| 唯一关联 head | `abs(head.y_min - person.y_min) < 3.0` |
| 唯一关联 face | `abs(head.y_max - face.y_max) < 3.0` |
| person 且组内 head/face 关系均唯一 | 可以同时比较上沿和下沿 |
| 关系缺失或歧义 | 不显示对应提示 |

`2.999...` 显示，`3.0` 不显示。不得先取整。

### 30.3 绘制要求

- 在主图和 Shape 绘制完成后绘制；
- 使用绿色非模态 Canvas 提示框；
- 文案仅为“上沿已接近”或“下沿已接近”；
- 不显示数值、分数、候选数量或 GID；
- 不改变 Shape pen/brush；
- 不参与 hit-test；
- 不进入截图以外的数据输出、撤销栈或 JSON；
- 模式非 `ACTIVE`、关系不唯一或阈值不满足时立即消失。

## 31. 配置、快捷键与国际化

### 31.1 配置结构

主配置新增独立 `rect_refine` 块，至少包含：

- `alignment_hint_px`；
- face→head 硬过滤和评分参数；
- head→person 硬过滤和评分参数；
- `min_accept_score`；
- `ambiguous_top_gap`。

配置加载必须验证：

- 比例和分数在合法范围；
- 权重非负且可归一化；
- `alignment_hint_px > 0`；
- 非法用户配置回退默认值并记录警告，不导致启动失败。

### 31.2 快捷键

```yaml
shortcuts:
  accept_rect_refine_workgroup: Ctrl+Enter
```

模式总开关第一版无默认快捷键。接受 QAction 只在 `ACTIVE` 且通过守卫时
有效；无工作组时按键不得转发到保存动作。

### 31.3 国际化

新增 UI 文案必须使用项目现有翻译机制，包括：

- 菜单名和 tooltip；
- 模式开关状态提示；
- 画布主界面的模式开启/结束提示；
- GID 冲突提示；
- 几何歧义/缺失提示；
- Overlay 文案；
- 过滤动作暂停提示。

实现者需更新 `.ts` 并通过 `scripts/compile_languages.py` 生成资源，不得
手工编辑 `anylabeling/resources/resources.py`。

## 32. 失败处理与一致性

### 32.1 保存失败

- 用户取消路径选择与写盘失败必须区分；
- 两者都不得释放工作组；
- 写盘失败使用现有错误消息；
- 保存异常不得把状态留在 `SAVING`；
- 保存成功但派生索引刷新失败仍按现有 `save_labels()` 契约视为成功。

### 32.2 Shape 生命周期变化

`ACTIVE` 期间相关删除/创建动作已禁用。若插件或外部组件仍移除成员：

- 下一事件先验证成员仍在当前 `canvas.shapes`；
- 失效时取消拖边并回滚仍存活成员；
- 释放整个工作组并回到 `SELECTING`；
- 不对已销毁对象调用方法。

### 32.3 dirty 精确恢复

- `dirty_before=False`：回滚后必须 clean；
- `dirty_before=True`：回滚后仍 dirty；
- 回滚不得调用无条件 `set_clean()`；
- 通过成功后遵循现有保存语义变为 clean；
- 自动保存开启时，工作组内仍不得提前写盘。

### 32.4 撤销边界

- 每个已完成拖边保留现有一个撤销粒度；
- 工作组内 Ctrl+Z 不能越过 `undo_floor`；
- Esc 完整回滚后不得通过 Ctrl+Z 重新出现已取消几何；
- 保存成功后撤销历史按项目现有行为保留；
- 切图后的撤销栈由现有 Canvas reset 负责，不保留跨图引用。

## 33. 验收标准

验收不是“界面能打开”或“主流程演示成功”。必须同时满足纯逻辑、状态机、
Qt 交互、持久化隔离和既有功能回归。

### 33.1 功能入口与连续模式

| ID | Given | When | Then |
|----|-------|------|------|
| AC-001 | 功能关闭 | 点击视图菜单 | 菜单勾选，状态为 `SELECTING`，无二次确认 |
| AC-002 | 模式开启无工作组 | 再次点击菜单 | 状态为 `OFF`，恢复基础状态 |
| AC-003 | 模式开启 | 通过或 Esc 结束一组 | 模式仍开启，可立即选择下一锚点 |
| AC-004 | 模式开启 | 进入绘制/自动标注/关键点填充模式 | 先安全回滚并关闭三框精修 |
| AC-005 | 应用无已加载图片 | 开启模式后加载图片 | 新图直接进入 `SELECTING` |
| AC-006 | 功能关闭 | 开启模式成功 | 画布主界面显示非模态开启提示 |
| AC-007 | 模式开启 | 退出模式成功 | 画布主界面显示非模态结束提示 |

### 33.2 锚点与非对称推导

| ID | 场景 | 预期 |
|----|------|------|
| AC-010 | 点击 person | 向下查 head，再从每个 head 查 face |
| AC-011 | 点击 head | 只查 person，不向下展开 face |
| AC-012 | 点击 face | 先查 head，再查 person，到 person 停止 |
| AC-013 | 嵌套框重叠点击 | 锚点等于 Canvas 现有 hit-test 最终选中对象 |
| AC-014 | head 向上有多个近分 person | 不任选父级，形成不完整组并提示 |
| AC-015 | face 向上缺 head | 仅 face 进入组，不直接跨级找 person |
| AC-016 | 无效 bbox 锚点 | 不崩溃，锚点保留，形成不完整组 |
| AC-017 | 锚点可见但关联对象被用户基础筛选隐藏 | 锚点可触发建组，推导仍可扫描全图并把合理关联对象加入工作组 |

### 33.3 GID 与几何合并

| ID | 场景 | 预期 |
|----|------|------|
| AC-020 | 三框统一有效 GID 且几何一致 | 三者进入组，来源包含 GID+geometry |
| AC-021 | person/head 同 GID，face 无 GID | head 由合并证据加入，face 由几何加入 |
| AC-022 | person/face 同 GID，head 无 GID | 先几何找 head，再验证并加入 face |
| AC-023 | 只有 person 有 GID | 等价于纯几何推导 |
| AC-024 | person 无有效 GID | 跳过 GID 路径 |
| AC-025 | 同 GID 两个 head | 返回 `DUPLICATE_GID_HEAD`，不建组 |
| AC-026 | 同 GID 两个 face | 返回 `DUPLICATE_GID_FACE`，不建组 |
| AC-027 | 同 GID head 几何硬不合理 | 返回 `GID_HEAD_GEOMETRY_INVALID` |
| AC-028 | 几何 top1 明显优于同 GID head ≥0.12 | 返回 GID/几何冲突 |
| AC-029 | 几何 top1 与同 GID head 分差 <0.12 | 视为歧义，保留合理候选，不判冲突 |
| AC-030 | 同 GID face 与所有已接受 head 不合理 | 返回 `GID_FACE_GEOMETRY_INVALID` |
| AC-031 | 同 GID face 但没有可验证 head | face 不绕过几何进入组，不改 GID |
| AC-032 | GID 值为 bool/字符串/非法值 | 只视为无可用 GID 证据 |

### 33.4 几何候选

| ID | 场景 | 预期 |
|----|------|------|
| AC-040 | 无 GID 且多个合理 head | 全部进入 person 工作组 |
| AC-041 | 每个 head 有多个合理 face | 合理 face 取并集且去重 |
| AC-042 | 缺 head | person 锚点仍可建立不完整组 |
| AC-043 | 有 head 缺 face | person+head 可建立不完整组 |
| AC-044 | 内框完全包含但普通 IoU 低 | 不得仅因 IoU 低排除 |
| AC-045 | 候选分数 0.5499 | 不进入合理候选 |
| AC-046 | 候选分数 0.55 | 进入合理候选 |
| AC-047 | 同一输入重复推导 | 成员和关系顺序完全一致 |
| AC-048 | 几何多候选超过 3 个 | 不得被 QA 的 `top_n=3` 截断 |

### 33.5 可见层和交互权限

| ID | 场景 | 预期 |
|----|------|------|
| AC-050 | 用户进入前有 label/GID/type 过滤 | `SELECTING` 主画布保持进入模式前的基础可见效果，不强行显示三类矩形 |
| AC-051 | 工作组建立 | 主画布只显示成员，其他 Shape 不可 hover/选择/编辑 |
| AC-052 | 工作组活动且导航器打开 | 导航器仍按进入模式前基础过滤显示 |
| AC-053 | 工作组结束 | 清除任务可见层，主画布回到用户基础可见效果，模式保持 `SELECTING` |
| AC-054 | 退出模式 | 过滤控件、标签可见和 Shape 手动可见状态逐项恢复 |
| AC-055 | 模式中触发过滤/隐藏动作 | 动作被拒绝且基础快照不变 |
| AC-056 | 模式前矩形边编辑关闭 | `SELECTING` 不可拖边，`ACTIVE` 工作组内可拖边，退出后恢复关闭 |
| AC-057 | 模式前矩形边编辑开启 | `SELECTING` 不可拖边，`ACTIVE` 工作组内可拖边，退出后仍开启 |
| AC-058 | ACTIVE 中尝试删除/移动整体/改 GID | 操作不可执行 |

### 33.6 Esc、回滚和撤销

| ID | 场景 | 预期 |
|----|------|------|
| AC-060 | 正在边拖动 | 第一次 Esc 只回滚本次拖动，工作组仍 ACTIVE |
| AC-061 | 存在 pending | Esc 只取消 pending，工作组仍 ACTIVE |
| AC-062 | ACTIVE 且无边交互 | Esc 恢复整组初始几何并回到 SELECTING |
| AC-063 | SELECTING 无工作组 | Esc 执行 Canvas 原有行为 |
| AC-064 | 建组前 clean，组内多次拖边 | Esc 后 clean，points 与初始逐点相同 |
| AC-065 | 建组前 dirty | Esc 后仍 dirty |
| AC-066 | Esc 完整回滚后按 Ctrl+Z | 已取消几何不会重新出现 |
| AC-067 | 工作组内多次 Ctrl+Z | 不得撤销到建组前历史 |

### 33.7 保存与自动保存

| ID | 场景 | 预期 |
|----|------|------|
| AC-070 | 无工作组按 Ctrl+Enter | 不保存、不切状态 |
| AC-071 | ACTIVE 且无 pending/drag | Ctrl+Enter 只调用一次保存 |
| AC-072 | 正在 drag/pending | Ctrl+Enter 不保存 |
| AC-073 | 保存成功 | 保留几何、清工作组、回 SELECTING、模式保持开启 |
| AC-074 | 用户取消保存对话框 | 工作组和几何保持 ACTIVE |
| AC-075 | `save_labels()` 返回失败 | 工作组和几何保持 ACTIVE，显示现有错误 |
| AC-076 | 保存抛出可处理异常 | 不停留在 SAVING，可重试 |
| AC-077 | `auto_save=true` 且组内完成拖边 | 通过前磁盘 JSON 不发生变化 |
| AC-078 | `auto_save=true` 后通过 | 只在通过路径写入最终几何 |
| AC-079 | 工作组未改几何直接通过 | 仍执行一次成功保存并回 SELECTING |

### 33.8 切图与关闭

| ID | 场景 | 预期 |
|----|------|------|
| AC-080 | ACTIVE 时切换图片 | 当前组回滚，新图 SELECTING，模式保持开启 |
| AC-081 | 建组前 clean、组内有修改后切图 | 不弹出保存临时精修提示 |
| AC-082 | 建组前 dirty、组内有修改后切图 | 先回滚组，再由原流程询问建组前修改 |
| AC-083 | 用户取消切图 | 当前图保持 SELECTING，已回滚组不自动重建 |
| AC-084 | ACTIVE 时关闭模式 | 回滚并恢复基础层，状态 OFF |
| AC-085 | ACTIVE 时关闭应用 | 临时修改不写盘，原 dirty 语义保留 |
| AC-086 | 切图回调晚到且 token 属于旧图 | 不操作新图 Shape |

### 33.9 Overlay

| ID | 场景 | 预期 |
|----|------|------|
| AC-090 | 实际差值 2.9 px | 显示对应绿色提示 |
| AC-091 | 实际差值 3.0 px | 不显示 |
| AC-092 | 实际差值 >3.0 px | 不显示 |
| AC-093 | 改变缩放倍率 | 判断结果不变 |
| AC-094 | 拖边尚未 release | Overlay 随实时 points 出现/消失 |
| AC-095 | 当前关系歧义 | 不显示该关系提示 |
| AC-096 | Overlay 出现 | dirty、撤销栈、Shape 样式和 JSON 均不变 |
| AC-097 | UI 文本检查 | 不出现实际像素数字或候选分数 |

### 33.10 持久化隔离

序列化前后必须验证：

- Shape 数量、label、group_id、flags、attributes 不因建组改变；
- 只有用户通过后确认的 points 可以变化；
- JSON 中不存在 `rect_refine`、临时成员、来源、冲突、`qa_entity_id` 等字段；
- 用户配置只包含稳定配置参数和快捷键，不包含运行时工作组。

## 34. 测试分层要求

### 34.1 纯 Python 单元测试

建议至少包含：

- `tests/test_rect_refine_grouping.py`；
- `tests/test_rect_refine_workflow.py`；
- `tests/test_rect_refine_visibility.py`。

其中 grouping/types 测试不得 import PyQt6。覆盖：

- 三种锚点方向；
- 全部 GID 合并和冲突码；
- 阈值边界；
- 多候选、不完整组、歧义；
- 稳定排序和去重；
- 状态转移、非法事件和幂等性；
- dirty/undo floor 快照语义。

### 34.2 PyQt offscreen 测试

建议至少包含：

- 菜单和快捷键；
- Canvas 最终选择触发；
- 任务可见层同时约束绘制和 hit-test；
- Esc 四级优先级；
- 拖边实时 Overlay；
- 互斥动作禁用；
- 导航器基础层与主画布任务层分离；
- 保存成功、取消、失败的状态恢复。

### 34.3 回归测试

必须运行并保持通过：

- 现有 Rectangle Edge Editing 测试；
- precision mode 测试；
- Canvas 选择优先级测试；
- filter engine/filter state 测试；
- navigator 相关测试；
- save/load 和 label 序列化测试；
- quality geometry/matching 测试。

## 35. GLM‑5.2 实现交付清单

GLM‑5.2 交付代码时必须同时提供：

1. 修改文件列表和每个文件的职责；
2. 设计章节到实现点的映射；
3. 新增配置项和默认值；
4. 新增/修改测试及测试结果；
5. Black、flake8、py_compile 结果；
6. 未实现、偏离或采用替代方案的明确清单；
7. 不得把“测试未运行”写成“应当可以通过”；
8. 不得提交自动生成资源以外的无关格式化变更。

## 36. Codex Review 门禁

代码 Review 按 findings-first 输出，至少检查：

### 36.1 架构

- 是否把状态机集中在 Workflow，而不是散落进 `label_widget.py`；
- grouping/types 是否保持纯 Python；
- Canvas 是否只承担适配和绘制；
- 是否出现 UI、QA 报告模型和精修工作流的反向耦合。

### 36.2 状态与事务

- 每个状态是否只有合法事件可执行；
- Esc、保存、切图、互斥模式和关闭是否覆盖全部异常路径；
- 保存失败是否错误释放组；
- auto-save 是否泄漏；
- dirty 和撤销边界是否精确恢复；
- 是否存在旧图回调或失效 Shape 引用。

### 36.3 数据安全

- 是否修改 GID、label、other_data 或 JSON 临时字段；
- 工作组快照是否深拷贝 points；
- 是否可能把临时几何在未通过时写盘；
- 是否通过清空全部撤销栈掩盖回滚问题。

### 36.4 UI 与可见性

- 主画布和导航器是否真正使用不同可见层；
- 隐藏 Shape 是否仍能 hover/选中/拖边；
- 模式退出是否逐项恢复用户状态；
- Overlay 是否严格 `<3.0` 且使用原图坐标；
- 国际化和 QAction checked/enabled 是否与状态同步。

### 36.5 验收结论

Review 只有以下三种结论：

- `PASS`：所有阻断项解决，必需测试通过；
- `PASS WITH NON-BLOCKING FINDINGS`：仅有不影响需求和数据安全的低风险项；
- `CHANGES REQUIRED`：存在状态、保存、回滚、可见性、数据污染或测试缺口。

任何导致未通过工作组写盘、错误修改 GID、跨图操作 Shape、保存失败后
释放组、或导航器被任务层覆盖的问题，均为阻断级问题。

## 37. 完成定义

本功能只有在以下条件全部满足时才算完成：

- 第 33 节所有适用验收场景通过；
- 新增测试和相关回归测试通过；
- 无临时关系持久化；
- auto-save 场景验证通过；
- 保存取消/失败实测通过；
- 主画布/导航器可见层分离实测通过；
- Esc、切图、退出和应用关闭均无未回滚几何；
- Black/flake8/py_compile 通过；
- GLM‑5.2 明确披露所有设计偏离；
- Codex Review 结论至少为 `PASS WITH NON-BLOCKING FINDINGS`。
