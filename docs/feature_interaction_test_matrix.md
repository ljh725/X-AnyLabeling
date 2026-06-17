# 功能交互冲突分析与测试矩阵

> 日期：2026-06-17
> 阶段：Phase A（发现 & 文档化，零代码风险）
> 后续：Phase B 建测试基座 + 回归测试；Phase C 逐个修冲突
> 调研方法：explore 子代理全仓扫描 + 关键 file:line 人工核验

## 0. 一句话结论

**是的，扩展功能与原生标注功能之间存在相互影响，其中有 3 处是确定的真实 bug（会产生可见错误行为），5 处是行为不符预期 / 健壮性隐患。** 根因高度集中：多个功能共享同一份可变状态（`hidden_by_filter` / `selected_shapes` / `pose_config.enabled` / 绘制管线），且无统一协调层。

---

## 1. 自定义功能清单（5 组）

| # | 功能 | 入口 | 主要文件 |
|---|------|------|----------|
| F1 | **检查器（Inspector）** | View→Data Inspector | `widgets/inspector/`（9 文件，11 条校验规则） |
| F2 | **Pose View** | View→Pose View | `widgets/pose_label/`（renderer/config/3 个面板） |
| F3 | **自动聚合 / 自动聚焦** | H / Shift+H / Ctrl+Shift+H / Alt+H / Esc | `label_widget.py:7365-7537` |
| F4 | **交互守卫** | （内部） | `canvas.py:484-500` `is_shape_interactive` / `_should_draw_standard_label` |
| F5 | **稀疏标签模式** | View→Show Labels / Label on Selection | `canvas.py:200-211`、`label_widget.py:1430-1492` |

## 2. 共享状态矩阵（冲突的根）

| 共享状态 | 声明位置 | 写入方 | 读取方 | 冲突点 |
|---|---|---|---|---|
| `shape.hidden_by_filter` | `shape.py:100`（运行时，**不序列化**） | **F3 自动聚合** `label_widget.py:7411,7429,7438,7502,7504`；**Undo 快照**（经 `shape.copy()`） | F4 守卫 `canvas.py:489`；绘制管线 9 处；**F2 PoseRenderer** `pose_renderer.py:106` | 热点 1 / 2 / 5 |
| `shape.visible` / `canvas.visible[shape]` | `shape.py:92` / `canvas.py:480` | **原生过滤引擎** `filter_engine.py:120-121`；原生"切换可见" `label_widget.py:8195`；标签列表勾选 | F4 守卫；绘制；PoseRenderer | 热点 2 |
| `canvas.selected_shapes` / `shape.selected` | `canvas.py` / `shape.py:85` | **F3 直改** `label_widget.py:7506-7510`；F1 导航 `select_shapes`；原生选择流 | 绘制；PoseRenderer `pose_renderer.py:203-206`；F5 稀疏门 | 热点 3 / 5 |
| `canvas.pose_config.enabled` | `canvas.py:214` | F2 开关 `label_widget.py:6949`；Pose 面板（共享单例） | `_should_draw_standard_label` `canvas.py:496`；外层守卫 `canvas.py:2732`；pose overlay `canvas.py:2938` | 热点 8 |
| `label_on_selection` | `canvas.py:206` | 原生菜单 `label_widget.py:1485` | 绘制稀疏门 `canvas.py:2900`；**pose overlay 忽略它**（硬编码 True `canvas.py:2948`） | 热点 4 |
| `selection_changed` 信号 | `canvas.py:76` | `select_shape_point` / `select_shapes` / `deselect_shape` | `shape_selection_changed` `label_widget.py:5971` → 触发 F3 / F1 刷新 | 热点 3 |

> 关键洞察：`hidden_by_filter`（F3）与 `shape.visible`（原生过滤）是**两套并行的可见性系统，互不知道对方存在**，但都被同一个绘制/交互守卫读取。

---

## 3. 冲突热点目录（8 个，按严重度排序）

每个热点包含：**现象 / 根因（file:line）/ 复现步骤 / 预期 / 当前实际 / 严重度 / 修复方向**。

---

### 🔴 H1 — Undo 会复活 `hidden_by_filter`，造成"幽灵隐藏"

- **现象**：自动聚合隐藏某组后，按 Esc 清除隐藏、再按 Ctrl+Z 撤销，该组又变成隐藏状态，且无法通过常规操作恢复。
- **根因**：
  - `shape.copy()` = `copy.deepcopy`（`shape.py:869-871`）
  - `__getstate__` 只剥离 Qt 缓存（`_cached_*`），**保留 `hidden_by_filter`**（`shape.py:873-880`）
  - `store_shapes()` 用 `shape.copy()` 做备份（`canvas.py:321-334`）
  - 还原（Undo）路径无任何地方清除 `hidden_by_filter`
- **复现步骤**：
  1. 打开含多组 group_id 标注的图片
  2. Alt+H 开启自动聚合 → 点击某组 → 其它组隐藏（`hidden_by_filter=True`）
  3. Esc 关闭聚合（`show_all_instances` 清除标志，全部恢复可见）
  4. 做一次会触发 `store_shapes` 的编辑（移动/删除点）
  5. Ctrl+Z 撤销
- **预期**：撤销后画面与撤销前一致，所有组可见。
- **当前实际**：撤销后，曾被聚合隐藏的组**重新变为隐藏**（幽灵隐藏），因为快照里带着 `hidden_by_filter=True`。
- **严重度**：🔴 高（数据感知类 bug，用户会以为标注丢失）
- **修复方向**：在 `__getstate__` 中剥离 `hidden_by_filter`（与 Qt 缓存一同处理），或在 Undo 还原后统一清除所有 shape 的 `hidden_by_filter`。

---

### 🔴 H2 — 两套可见性系统互不协调，图形"卡死隐藏"

- **现象**：当一个组同时被原生过滤（`shape.visible=False`）和自动聚合（`hidden_by_filter=True`）隐藏后，任一单独的"显示全部"都无法让它恢复可见。
- **根因**：
  - 原生过滤引擎写 `shape.visible` + `canvas.visible[shape]`（`filter_engine.py:120-121`）
  - 自动聚合写 `hidden_by_filter`（`label_widget.py:7411,7502`）
  - 两者都被 `is_shape_interactive`（`canvas.py:487-489`）和绘制守卫读取
  - `show_all_instances()`（F3）只清 `hidden_by_filter`，不撤销原生过滤
  - 原生 `toggle_visibility_shapes` 只翻 `shape.visible`，不清 `hidden_by_filter`
- **复现步骤**：
  1. 用标签列表复选框或过滤引擎，把某组 `shape.visible` 设为 False
  2. Alt+H 自动聚合隐藏另一组（`hidden_by_filter=True`）
  3. （此时该组若同时被两个系统命中，则双重隐藏）
  4. 点"显示全部"（任一种）
- **预期**：任一"显示全部"应让所有图形恢复可见可交互。
- **当前实际**：只清一套标志，图形仍被另一套隐藏，无法选中/看见。
- **严重度**：🔴 高（用户体感"图形消失了且救不回"）
- **修复方向**：统一可见性入口——让两个"显示全部"操作都同时清 `hidden_by_filter` 和 `shape.visible`/`canvas.visible`；或把自动聚合改为复用 `shape.visible` 体系（需区分"过滤隐藏"与"聚合隐藏"语义）。

---

### 🔴 H3 — 自动聚合直接改 `selected_shapes`，绕过 `selection_changed` 信号

- **现象**：自动聚合聚焦某组后，属性面板 / 标签列表与画布实际选中状态不同步。
- **根因**：`label_widget.py:7506-7510` 直接重赋值 `self.canvas.selected_shapes = [...]`，并清 `shape.selected=False`（`7500-7501`），**全程不发 `selection_changed` 信号**；仅调用 `_sync_label_list_hidden_by_filter`（隐藏行，但不重选）。
- **复现步骤**：
  1. Alt+H 自动聚合 → 点击某组
  2. 观察右侧属性面板 / 标签列表高亮
- **预期**：选中状态变化应经 `selection_changed` 统一广播，所有依赖方同步。
- **当前实际**：属性面板仍显示旧选中内容；标签列表行被隐藏但高亮未更新。
- **严重度**：🔴 高（状态不一致，后续操作可能基于错误选中）
- **修复方向**：聚合时改走 `canvas.select_shapes([...])`（会发信号），而非直改列表；或在直改后显式 `emit selection_changed`。

---

### 🟠 H4 — Pose View 硬编码 `label_on_selection` / `zoom_reveals`，工具栏开关失效

- **现象**：顶部"Label on Selection"开关在 Pose View 下对关键点标签完全无效。
- **根因**：`canvas.py:2947-2950` 写死 `show_labels=True, label_on_selection=True, zoom_reveals=False`（上一轮为满足"按组按需显示"而加），忽略 `self.label_on_selection` 和缩放阈值。
- **复现步骤**：
  1. 开启 Pose View
  2. 关闭顶部"Label on Selection"
  3. 悬停某 person → 关键点标签仍按组显示
- **预期**：（取决于产品定义）要么工具栏开关有效，要么 UI 明确告知"Pose View 内置该行为"。
- **当前实际**：开关无效，用户困惑。
- **严重度**：🟠 中（行为不符预期，但非数据错误）
- **修复方向**：明确产品语义后二选一——(a) Pose View 尊重工具栏开关；(b) UI 提示 Pose View 内置按组显示，或移除易混淆的开关联动。

---

### 🟠 H5 — `is_shape_interactive` 把所有选择路径耦合到自动聚合状态（检查器导航静默失效）

- **现象**：自动聚合隐藏某组时，检查器"跳转到该问题图形"会静默无反应。
- **根因**：检查器导航调 `canvas.select_shapes([shape])`（`label_widget.py:5192`）→ `select_shapes` 用 `is_shape_interactive` 过滤（`canvas.py:1460-1462`）→ 自动聚合设的 `hidden_by_filter=True` 使目标被过滤 → 选中列表为空。
- **复现步骤**：
  1. 开检查器，列出问题
  2. Alt+H 自动聚合聚焦 A 组（隐藏 B 组）
  3. 在检查器里点击属于 B 组的某个问题，尝试跳转
- **预期**：跳转应成功选中并居中该图形（或提示"该目标当前被聚合隐藏，是否取消聚合"）。
- **当前实际**：点击无反应，无任何提示。
- **严重度**：🟠 中（功能静默失效）
- **修复方向**：导航时检测目标是否 `hidden_by_filter`，若是则先解除聚合或显式覆盖可见性；或 `select_shapes` 对程序化调用不过滤。

---

### 🟠 H6 — 检查器编辑不可撤销 + 索引寻址漂移

- **现象**：在检查器表格里改 label/group_id/description 后，Ctrl+Z 撤销不掉；且若画布增删了图形导致下标漂移，可能改错图形。
- **根因**：`_on_inspector_shape_edit`（`label_widget.py:5249-5277`）改完字段只调 `set_dirty()` + `canvas.update()`，**不调 `store_shapes()`**（全文件 `store_shapes` 仅 `label_widget.py:6477` 一处，不在此路径）；且用 `shape_index` 下标寻址（`5259,5262`），无版本校验。
- **复现步骤**：
  1. 开检查器表格
  2. 改某行 label → 保存
  3. Ctrl+Z → 无反应
  4. （另一场景）改之前先在画布删一个图形使下标前移 → 再去表格改"同一行" → 改到的是错位后的另一个图形
- **预期**：检查器编辑可单独撤销；下标寻址有版本/token 校验，漂移时拒绝或重新对齐。
- **当前实际**：不可撤销；下标漂移会改错。
- **严重度**：🟠 中（数据正确性 + 用户体验）
- **修复方向**：编辑前调 `store_shapes()` 建快照；改用 shape 对象引用或 (id, token) 寻址而非下标。

---

### 🟡 H7 — Esc 键被无条件吞掉（比预想更激进）

- **现象**：`LabelingWidget.keyPressEvent` 里，**任何 Esc 按下都被 `accept()` 吞掉**，即便自动聚合未激活。
- **根因**：`label_widget.py:7530-7536`
  ```python
  if event.key() == Qt.Key.Key_Escape:
      if self._escape_auto_focus_if_active():
          event.accept(); return
      event.accept(); return      # ← 即便聚合未激活也吞
  ```
  第二个 `event.accept(); return`（7535-7536）无条件执行，Esc 永不传给 `super().keyPressEvent`。
- **复现步骤**：自动聚合关闭状态下按 Esc → 观察是否还能触发 LabelingWidget 父类链里的其它 Esc 行为。
- **预期**：自动聚合未激活时，Esc 应正常向上传递。
- **当前实际**：Esc 在此层被截断。
- **严重度**：🟡 低-中（Canvas 有独立 keyPressEvent 故多数场景不受影响，但父类链的 Esc 全失效）
- **修复方向**：删除 7535-7536 的无条件 accept；仅当 `_escape_auto_focus_if_active()` 返回 True 时才吞，否则 `super().keyPressEvent(event)`。

---

### 🟡 H8 — 绘制管线一致性脆弱（pose_config 三处守卫必须同步）

- **现象**：未来任何动到标签绘制管线的改动，若只改一处守卫，会重现"标签穿透"或"标签不显示"。
- **根因**：`pose_config.enabled` 在三处被独立检查，须保持一致：
  - `_should_draw_standard_label` `canvas.py:496`
  - 外层标签块守卫 `canvas.py:2732`（`if self.show_labels and not self.pose_config.enabled:`）
  - pose overlay 块 `canvas.py:2937-2940`
  另有 9 处 `hidden_by_filter` 绘制检查（`canvas.py:2268,2341,2399,2499,2651,2684,2744,2919,2931` 等）。
- **预期**：绘制可见性应有单一真相源，而非散落多处守卫。
- **当前实际**：多点守卫，改动易遗漏。
- **严重度**：🟡 低（当前正确，但维护风险高）
- **修复方向**：抽取统一的 `shape_draw_visibility(shape)` / `label_draw_visibility(shape)` 谓词，所有绘制点调用它。

---

## 4. 人工交互测试矩阵（二维）

行 = 功能 A 处于激活/特定状态；列 = 在此状态下执行功能 B 的操作。单元格标注预期与对应热点。

### 4.1 总矩阵

| 功能 A ↓ \ 操作 B → | 原生过滤/标签勾选 | Ctrl+Z 撤销 | 检查器跳转 | 检查器表格编辑 | 原生编辑(移动/删点/删图形) | 标签列表勾选显隐 |
|---|---|---|---|---|---|---|
| **F3 自动聚合 ON（已聚焦某组）** | 卡死隐藏 (H2) | 幽灵隐藏 (H1) | 静默失效 (H5) | 下标漂移 (H6) | 选择不同步 (H3) | 行隐藏冲突 (H2) |
| **F3 自动聚合 + Esc 关闭后** | — | 幽灵隐藏 (H1) | — | — | — | — |
| **F2 Pose View ON** | 标签穿透?(H8) | — | 关键点能否选中编辑? | — | 移动后骨架是否跟随? | — |
| **F1 检查器表格编辑中** | — | 不可撤销 (H6) | — | — | 下标漂移 (H6) | — |
| **F5 label_on_selection OFF + Pose ON** | 开关无效 (H4) | — | — | — | — | — |

> 空白格 = 未发现明显冲突（仍建议冒烟测试）。"?" = 需手测确认。

### 4.2 重点格子详细手测步骤

**[F3 自动聚合 ON × Ctrl+Z 撤销] — 验证 H1**
1. 多组标注图 → Alt+H → 点 A 组（B/C 组隐藏）
2. Esc 关闭聚合（全部恢复）
3. 移动一个图形（触发 store_shapes）
4. Ctrl+Z
5. ✅ 预期：所有组可见；❌ 实际预期：B/C 组又隐藏

**[F3 自动聚合 ON × 原生过滤] — 验证 H2**
1. 标签列表取消勾选 X 组（`shape.visible=False`）
2. Alt+H → 点 Y 组（其它组 `hidden_by_filter=True`）
3. 点"显示全部"（先试 F3 的 Ctrl+Shift+H，再试原生切换可见）
4. ✅ 预期：X 组恢复可见；❌ 实际预期：X 组仍隐藏

**[F3 自动聚合 ON × 检查器跳转] — 验证 H5**
1. 开检查器，生成问题列表
2. Alt+H → 聚焦 A 组（B 组被隐藏）
3. 检查器里点一个属于 B 组的问题
4. ✅ 预期：跳转成功或提示；❌ 实际预期：无反应

**[F3 自动聚合 ON × 原生编辑] — 验证 H3**
1. Alt+H → 聚焦 A 组
2. 观察属性面板内容
3. ✅ 预期：属性面板显示当前选中；❌ 实际预期：显示旧内容（不同步）

**[F1 检查器编辑 × Ctrl+Z] — 验证 H6**
1. 开检查器表格 → 改某行 label → 回车
2. Ctrl+Z
3. ✅ 预期：label 回退；❌ 实际预期：无反应

**[F2 Pose View × 原生编辑] — 验证（未编号，需确认）**
1. 开 Pose View
2. 选中某 person 的关键点 → 移动
3. 观察：骨架/标签是否实时跟随？pose_config 的 selected 触发是否正确？

**[F5 × F2] — 验证 H4**
1. 开 Pose View
2. 关闭顶部 Label on Selection
3. 悬停 person
4. ✅ 预期：开关有效（或 UI 明确）；❌ 实际预期：开关无效

---

## 5. 修复优先级排序

| 优先级 | 热点 | 理由 | 建议阶段 |
|--------|------|------|----------|
| P0 | **H1 幽灵隐藏** | 数据感知 bug，用户以为标注丢失 | Phase C 首批 |
| P0 | **H2 卡死隐藏** | 图形救不回，阻断工作流 | Phase C 首批 |
| P0 | **H3 选择不同步** | 状态不一致引发连锁误操作 | Phase C 首批 |
| P1 | H5 检查器导航失效 | 功能静默失效 | Phase C 二批 |
| P1 | H6 检查器不可撤销/漂移 | 数据正确性 | Phase C 二批 |
| P2 | H4 Pose 开关无效 | 体验问题，需先定产品语义 | 待产品确认 |
| P2 | H7 Esc 吞键 | 父类链 Esc 失效，影响面待评估 | Phase C 末批 |
| P2 | H8 管线一致性 | 当前正确，重构性改进 | 长期 |

---

## 6. 衔接 Phase B / C

**本文件如何驱动后续**：
- **Phase B** 的回归测试 `tests/test_feature_interactions.py` 应针对 H1/H2/H3/H5/H6 各写一个最小复现测试（用现有 `test_canvas_interaction.py` 的 `Canvas()` + `MockShape` 模式）。这些测试**当前应为红色**（证明 bug 存在），即"用测试得到结果"。
- **Phase C** 按 P0→P1→P2 顺序修，每修一个看对应测试转绿。P0 三条（H1/H2/H3）建议作为首批，因为它们是真实数据/状态 bug。

**Phase B 测试基座修复清单**（独立于本文件，但属于 B 阶段）：
- `pyproject.toml` 加 `testpaths = ["tests"]`（阻止 `--doctest-modules` 收集源码触发 `supervision`/`onnxruntime` 导入失败，这是当前全量 pytest 崩溃的根因）
- 新建 `tests/conftest.py`：注册 `--slow`（当前未注册，`pytest --slow` 会报错）、收口共享 fixture（`qapp` / `make_shape` / `make_canvas` / `make_fake_widget`，现有 7 处重复 MockShape/_FakeShape/_write_label）

---

## 附录：核验过的关键 file:line 索引

| 引用 | 含义 |
|------|------|
| `shape.py:92` | `self.visible = True` |
| `shape.py:100` | `self.hidden_by_filter = False`（运行时，不序列化） |
| `shape.py:124-138` | `to_dict()` 不含 `hidden_by_filter` |
| `shape.py:869-871` | `copy()` = `copy.deepcopy` |
| `shape.py:873-880` | `__getstate__` 只剥离 Qt 缓存，**保留 `hidden_by_filter`**（H1 根因） |
| `canvas.py:321-334` | `store_shapes` 用 `shape.copy()`（H1 根因） |
| `canvas.py:484-490` | `is_shape_interactive` 守卫 |
| `canvas.py:492-500` | `_should_draw_standard_label` |
| `canvas.py:2732` | 标签块外层守卫 `show_labels and not pose_config.enabled` |
| `canvas.py:2936-2951` | pose overlay 块 + 硬编码参数（H4） |
| `canvas.py:1460-1464` | `select_shapes` 程序化选择过滤（H5 路径） |
| `label_widget.py:5249-5277` | 检查器编辑，无 `store_shapes`（H6） |
| `label_widget.py:7485-7517` | `_auto_focus_on_selection` |
| `label_widget.py:7506-7510` | 直改 `selected_shapes`，不发信号（H3） |
| `label_widget.py:7411,7502` | 写 `hidden_by_filter`（H1/H2） |
| `label_widget.py:7530-7536` | Esc 无条件吞键（H7） |
| `filter_engine.py:120-121` | 原生过滤写 `shape.visible`/`canvas.visible`（H2） |

---

## 7. Phase B 执行结果（测试基座 + 回归测试）

> 状态：已完成。本节为客观基线，驱动 Phase C。

### 7.1 测试基座修复

| 改动 | 文件 | 作用 |
|------|------|------|
| 加 `testpaths = ["tests"]` | `pyproject.toml` | 阻止 `--doctest-modules` 扫描 `anylabeling/` 源码（修复全量 pytest 因 `supervision`/`onnxruntime` 崩溃） |
| 加 `python_functions = "test_*"` | `pyproject.toml` | 避免独立脚本的裸 `def test(...)` 被误收集 |
| 新建 `conftest.py` | `tests/conftest.py` | 注册 `--slow`（此前 `pytest --slow` 报未识别参数）；`pytest_collection_modifyitems` 跳过 `slow`；共享 fixture（`qapp`/`canvas`/`MockShape`）；`collect_ignore_glob` 排除断头脚本 |
| 修 importlib 加载器 | `tests/test_inspector_validation.py` | 给两模块加伪包前缀 `inspector_test.`，让相对导入 `from .flat_index` 解析（**顺带救回 18 个 inspector 校验测试**——此前静默崩在 collection） |

**前**：全量 `pytest` 在 collection 阶段中止（supervision ImportError），**0 测试运行**。
**后**：全量 `pytest` 跑到结束，`150 passed / 20 failed`。

### 7.2 回归测试基线（`tests/test_feature_interactions.py`）

| 测试 | 热点 | 当前结果 | 含义 |
|------|------|----------|------|
| `test_h1_copy_does_not_propagate_hidden_by_filter` | H1 | 🔴 FAIL | 证明 deepcopy 保留 `hidden_by_filter` → Undo 复活隐藏 |
| `test_h2_show_all_instances_restores_native_hidden_shape` | H2 | 🔴 FAIL | 证明 `show_all_instances` 不清原生 `shape.visible` → 双重隐藏救不回 |
| `test_h3_autofocus_broadcasts_selection_via_signal` | H3 | 🔴 FAIL | 证明自动聚合不发 `selection_changed` → 面板不同步 |
| `test_h5_select_shapes_filters_out_hidden_by_filter` | H5 | 🟢 PASS（characterization） | 守卫当前过滤行为（检查器导航失效的根因） |
| `test_h6_inspector_edit_records_undo_backup` | H6 | 🔴 FAIL | 证明检查器编辑不调 `store_shapes` → 不可撤销 |

> **4 红 = 4 个 P0/P1 bug 的客观证据；1 绿 = 行为守卫。** Phase C 每修一个热点，对应测试转绿即证明修复且防回归。
>
> 未自动化（需人工/产品决策）：H4（Pose 开关系，需定语义+paint）、H7（Esc 键事件派发）、H8（paint 管线一致性，已有 `_should_draw_standard_label` 间接覆盖）。

### 7.3 预存失败（与 Phase B 无关，独立清理项）

全量 20 个失败中，除上述 4 个有意红外，其余 16 个为预存问题（Phase B 未触碰其源码）：

| 文件 | 数量 | 原因 |
|------|------|------|
| `test_settings/test_schema.py` | 4 | 字段计数漂移（`127 != 120`）——早期加 `pose_view.*`/inspector 字段未同步测试期望 |
| `test_settings/test_controller.py` | 5 | `SettingsValidationError`——校验逻辑变更未同步 |
| `test_settings/test_dialog_layout.py` | 1 | 同上 |
| `test_ppocr/test_latex_editor.py` | 6 | 缺 matplotlib（LaTeX 预览依赖） |
| `test_filter_persistence.py` | 1 | `clear_filt...` 属性缺失——预存 |

这些建议作为**独立清理任务**，不阻塞 Phase C。

### 7.4 Phase C 执行结果（已修复 H1/H2/H3/H6）

> 状态：4 个 P0/P1 bug 已修，对应红测试全部转绿，全量无回归。

| 热点 | 修复 | 文件:行 | 测试 |
|------|------|---------|------|
| **H1** 撤销复活隐藏 | `__getstate__` 复制时把 `hidden_by_filter` 重置为 `False`（保留键避免 deepcopy 丢属性） | `shape.py:873-884` | 🟢 H1 |
| **H3** 选择不发信号 | `_auto_focus_on_selection` 改走 `selection_changed.emit`（让标签列表/属性面板同步），加 `_auto_focus_in_progress` 重入守卫防 `shape_selection_changed` 回调死循环 | `label_widget.py:7477-7529` | 🟢 H3 |
| **H6** 检查器不可撤销 | `_on_inspector_shape_edit` 变更前调 `canvas.store_shapes()` 记录撤销快照 | `label_widget.py:5262-5267` | 🟢 H6 |
| **H2** 双重隐藏卡死 | `show_all_instances` 同时清 `hidden_by_filter` + `shape.visible` + `canvas.visible`，成为真正的"显示全部" | `label_widget.py:7435-7448` | 🟢 H2 |

**验证**：
- `tests/test_feature_interactions.py`：5/5 passed（4 原红转绿 + H5 守卫）
- 全量 `pytest`：`154 passed / 16 failed`（Phase B 时 `150/20`；4 个原红转绿，16 个预存失败**逐条不变**，零回归）
- `black`/`flake8`：改动处零新增问题（shape.py 零报错；label_widget.py 报错全在未编辑区域，预存）

**H2 取舍说明**：`show_all_instances` 现会重置**已应用**的原生可见性（`shape.visible`/`canvas.visible`），但不触碰 `FilterEngine` 的持久状态——下次过滤动作会重算。语义：F3 的"显示全部"= 真正显示全部，能解决双标志卡死。若你希望两套系统严格分离（F3 只清自己的标志），可回退此改动并把 H2 测试改回 characterization。

### 7.5 待处理（需产品决策，未在本轮修复）

| 热点 | 原因 | 现状 |
|------|------|------|
| **H5** 检查器导航对聚合隐藏目标静默失效 | 导航是否应覆盖自动聚合隐藏（取消聚合 / 强制选中 / 提示）属产品决策；当前 `test_h5` 为 characterization 守卫（绿） | 留 characterization 测试，待决策 |
| **H4** Pose View 忽略 `label_on_selection` 开关 | 需定 Pose 标签是否应跟随工具栏开关 | 手测 |
| **H7** Esc 键无条件吞掉 | 父类链 Esc 是否需保留 | 手测 |
| **H8** 绘制管线多点守卫 | 重构性改进，当前正确 | 长期 |

### 7.6 预存失败（独立清理项，与 Phase B/C 无关）

16 个全量失败均为预存，建议作为独立任务：
- `test_settings/test_schema.py`（4）：字段计数漂移 `127 != 120`——早期加 `pose_view.*`/inspector 字段未同步期望
- `test_settings/test_controller.py`（5）+ `test_dialog_layout.py`（1）：`SettingsValidationError`——校验逻辑变更
- `test_ppocr/test_latex_editor.py`（5）：缺 matplotlib
- `test_filter_persistence.py`（1）：`clear_filt...` 属性缺失

---

## 8. Pose View 选中驱动聚焦流程（流程重设计）

> 日期：2026-06-17
> 状态：已实现，5 个新回归测试全绿，全量 `161 passed / 16 failed`（零回归）。
> 背景：原流程里 `label_on_selection` / 自动聚合 / Pose View 按组显示三套机制重叠互扰（见 §3 H4/H5、§6-1/6-2）。本次按"选中成为唯一驱动"重构，退役 Pose View 下的自动聚合。

### 8.1 目标流程

```text
Pose View ON
  → 全员骨架/关键点圆点/bbox 可见，无标签（干净）
  → 鼠标点击某 person  或  gid 下拉选某组
       → 该组保留可见 + 关键点标签显示
       → 其他组 hidden_by_filter 隐藏
  → 换一组：再点可见区某人 / 换 gid / 点空白(gid "-1") 退出聚焦
  → Alt+H：Pose View 下提示"不可用"（普通标注仍可用）
```

核心：**"选中/选组"同时决定"显示哪组标签"（req3）与"隐藏其他对象"（req5）**，自动聚合模式被它取代。Pose View 内只用**一套**隐藏机制 `hidden_by_filter`（受 H1/H3 修复保护），不混用原生 filter_engine 的 `shape.visible`，避免 H2 双系统重演。

### 8.2 行为矩阵

| 操作（Pose View ON） | 结果 |
|---|---|
| 点 person A / gid 下拉选 3 | 该组可见 + 标签显示，其他组隐藏 |
| 点 person B（可见区）/ 换 gid | 切换聚焦到 B / 新组 |
| 点空白 / gid 选 "-1" | 退出聚焦：全部恢复可见，无标签 |
| 点无 group_id 的 shape | 不隐藏，状态栏提示"该对象无 group_id，无法聚焦" |
| Alt+H | 提示"Pose View 下自动聚合不可用"（普通标注正常） |

### 8.3 改动清单（file:line）

| # | 需求 | 改动 | 位置 |
|---|------|------|------|
| 1 | req3 标签仅选中显示 | Pose overlay `hovered_group_id=None`（关悬停揭示） | `canvas.py:2949` |
| 2 | req5 选中→隐藏其他 | 新增 `_apply_group_focus(gid)`：非该组 `hidden_by_filter=True`、该组 False；emit `selection_changed`(该组)，`_auto_focus_in_progress` 防重入 | `label_widget.py` |
| 3 | req5 接线 + 空白退出 + 无 gid 提示 | 新增 `_pose_focus_on_selection`：空选中→`show_all_instances()`；无 gid→`status` 提示；否则 `_apply_group_focus`。`shape_selection_changed` 改 `if pose_config.enabled: _pose_focus… elif auto_focus_instance: _auto_focus…` | `label_widget.py:6022` + 新方法 |
| 4 | req2 gid 下拉切对象 | `gid_selection_changed`：Pose View 下走 `_apply_group_focus(int(gid))`（`-1`→`show_all`），**不走**原生 filter；否则原逻辑 | `label_widget.py:6426` |
| 5 | req2 gid 自然排序 | `sorted(..., key=lambda x: (x != "-1", int(x)))`（`-1` 置顶，其余按数值；原为字符串排序） | `label_widget.py:6293` |
| 6 | req1 Alt+H Pose View 失效 | `toggle_auto_focus_instance`：Pose View 下 `status` 提示 + return | `label_widget.py:7495` |
| 7 | req1b 进 Pose View 清干净 | `toggle_pose_view`：启用时若 `auto_focus_instance` → 关闭 + `show_all_instances()` | `label_widget.py:6966` |

### 8.4 回归测试（`tests/test_feature_interactions.py`，全绿）

| 测试 | 断言 |
|------|------|
| `test_pose_focus_hides_other_groups` | 选中组 1 → 组 2 `hidden_by_filter=True`，组 1 False |
| `test_pose_focus_blank_exits` | 聚焦后空选中 → 所有 `hidden_by_filter=False` |
| `test_pose_focus_no_group_id_hinted_not_hidden` | 选无 gid shape → 不隐藏任何对象 |
| `test_alt_h_noop_in_pose_view` | Pose View 下 `toggle_auto_focus_instance` 不改变 `auto_focus_instance` |
| `test_gid_dropdown_natural_sort` | `["2","10","1"]` → `["-1","1","2","10"]` |

### 8.5 与之前热点的关系

- **H1/H2/H3**：新流程复用 `hidden_by_filter`，直接受益于 Phase C 修复（Undo 不复活、`show_all` 清两套、发信号同步）。
- **H4**（Pose 忽略 `label_on_selection`）：本次明确产品决策——Pose View 标签**不跟随**工具栏开关，改由"选中"驱动（`hovered_group_id=None` + `label_on_selection=True` 写死于 pose overlay）。工具栏开关在 Pose View 下对关键点标签无效属**预期**（未来可灰掉该开关消除误导）。
- **H5**（检查器导航失效）：Pose View 下点问题会触发聚焦隐藏——可接受（导航本就是聚焦目标）；非 Pose View 下 H5 仍为 characterization。

### 8.6 边界

- **两人重叠**：聚焦后其他组隐藏，画布上只能靠 **gid 下拉**切换（req2 存在的理由）。
- **原生 filter 共存**：Pose View 不触碰 `shape.visible`；退出 Pose View 后原生过滤状态原样恢复。进入 Pose View 时若原生 filter 仍生效，"点空白"的 `show_all_instances` 会清两套（H2 修复），可恢复。
- **重入**：`_apply_group_focus` 的 emit 复用 `_auto_focus_in_progress` 守卫，不会与 `shape_selection_changed` 互相回调死循环。

### 8.7 列表与聚焦解耦（后续调整）

> 状态：已实现，2 个新测试全绿。

两条调整，把右侧对象列表从聚焦系统里解耦出来：

| 调整 | 行为 | 实现 |
|------|------|------|
| **列表始终显示全部对象名** | Pose View 聚焦时只在画布隐藏其他组，**列表行全部保持可见**，仅选中高亮跟随聚焦 | `_apply_group_focus` 移除 `_sync_label_list_hidden_by_filter()` 调用（`label_widget.py:7605`） |
| **列表点击只作用于对象本身** | 在列表里点击对象 = 选中该对象，**不触发聚焦隐藏** | `label_selection_changed` 用 `_list_selecting` 守卫包住 `select_shapes`；`_pose_focus_on_selection` 检测到该标志即 return |

效果：
- 画布点击 / gid 下拉 → 触发聚焦（隐藏其他组、显示该组标签）。
- 列表点击 → 只选中该对象（勾选/高亮变化），不动聚焦状态，列表始终全员可见。
- 列表因此成为稳定的"全对象索引"，随时可点选任意对象进行编辑/查看，不受当前聚焦影响。

回归测试（`tests/test_feature_interactions.py`，全绿）：
- `test_pose_focus_keeps_label_list_rows_visible`：聚焦后其他组在画布 `hidden_by_filter=True`，但 `_sync_label_list_hidden_by_filter` **未被调用**（行不隐藏）。
- `test_list_selection_does_not_trigger_pose_focus`：`_list_selecting=True` 时 `_pose_focus_on_selection` 不隐藏任何对象。
