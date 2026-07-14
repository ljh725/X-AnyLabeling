# 个人作品集 · X-AnyLabeling 扩展功能

> 基于 [CVHub520/X-AnyLabeling](https://github.com/CVHub520/X-AnyLabeling) beta.4 的标注工具增强实践。
>
> [English](PORTFOLIO_EN.md) | 简体中文

---

## 关系说明

本仓库是我（[@ljh725](https://github.com/ljh725)）从 `CVHub520/X-AnyLabeling` fork 出来的个人增强版。
**所有列出的功能均为我在 beta.4 基础上独立设计并实现的扩展**，不包含 upstream 已有功能。

```
CVHub520/X-AnyLabeling (upstream, beta.4)
        │  fork
        ▼
ljh725/X-AnyLabeling  ← 本仓库（93 commits / ~1.5 万行扩展代码）
```

| 维度 | 数据 |
|------|------|
| 提交数 | **93**（相对 upstream main） |
| 新增代码 | **~18,500 行**（功能代码 + 测试） |
| 测试用例 | **300+**（功能相关） |
| 设计文档 | **116 篇**（`docs/` 目录） |
| 功能模块 | **15 个** |

---

## 功能矩阵

| # | 模块 | 代码规模 | 测试 | 核心价值 | 详述 |
|---|------|---------|------|---------|------|
| 1 | **L1/L2 质检引擎** | 4,354 行 / 12 文件 | 148 | 12 条几何/视觉关系规则 + face→head→person 跨类匹配，纯 Python（零 PyQt 依赖），CLI/UI 共享同一份逻辑 | [→ 01](portfolio/01-quality-engine.md) |
| 2 | **Inspector 数据检查面板** | 3,785 行 / 10 文件 | 60+ | 5-Tab 质检工作台、插件化规则引擎、点击问题即跳转 Canvas，标注-质检闭环内化 | [→ 02](portfolio/02-inspector-panel.md) |
| 3 | **优先级排序拾取模式** | ~90 行核心算法 | 6 | 「决策转排序」范式：4 维优先级元组取代 if-elif 链，解决密集/嵌套标注选错痛点 | [→ 03](portfolio/03-selection-optimization.md) |
| 4 | **矩形边编辑** | 407 行几何 + ~250 行 canvas | 21 | 独立拖动矩形单条边，几何层/UI 层严格解耦，反翻转 clamp 保证矩形永不坍塌 | [→ 04](portfolio/04-rect-edge-edit.md) |
| 5 | **Pose View 标签解耦** | 1,994 行 / 9 文件 | 36 | filter-driven 单字段解耦标签列表与选中焦点，4 种防遮挡布局算法，总览/选中两态显示 | [→ 05](portfolio/05-pose-view.md) |
| 6 | **数据处理脚本集** | 40 个脚本（核心逾 3,000 行） | — | YOLO Pose 三步流水线 + ViTPose 预标注对比 + 质检 CLI，覆盖姿态数据生产全链路 | [→ 06](portfolio/06-data-toolkit.md) |
| 7 | **新建 person 自动实例化** | ~60 行核心 + 设置/集成 | 9 | 手动画 person 自动生成 group_id，优先级链 `bind_draw > 本功能 > auto_use_last_gid`，静态测试钉死 Non-Goal | [→ 07](portfolio/07-auto-person-instance.md) |
| 8 | **数字快捷绑定绘制** | 414 行管理器 + 集成 | 19 | 选中来源按数字键新建同实例框，懒回填保证 undo 原子，两阶段 TOCTOU 防重复 | [→ 08](portfolio/08-digit-bind-draw.md) |
| 9 | **精修控制模式** | ~250 行 canvas + 设置 | 14 | 鼠标 zoom/fixed 降速 + Tab 选边 + 1px/5px 单边微调，虚拟游标隔离零污染基础交互 | [→ 09](portfolio/09-precision-mode.md) |
| 10 | **局部边缘吸附（实验性）** | 212 行纯 Python + canvas 桥接 | 11 | Sobel 梯度 ±4px 搜索 + 双重阈值，纯算法可单测；诚实记录「方向偏差」并主动降级 | [→ 10](portfolio/10-local-edge-snap.md) |
| 11 | **筛选系统** | ~1,400 行 / 5 文件 | — | 切图保留筛选态 + JSON 筛选引擎 + SQLite 索引缓存（5000 图加速）+ 跨文件导航；State/Engine/UI 三层 | [→ 11](portfolio/11-filter-system.md) |
| 12 | **缩放中心点修复** | ~70 行核心 + 2 篇分析文档 | — | 修 upstream 竖图缩放漂移 bug：width 检测失效 + y 轴误用比率；用 transform_pos 逆变换重写 | [→ 12](portfolio/12-zoom-center-fix.md) |
| 13 | **数字快捷键分页** | 311 行分页管理器 | — | 扩展 upstream 10 键限制：F1 切页，10×N 槽位，单页完全向后兼容 | [→ 13](portfolio/13-digit-shortcut-pagination.md) |
| 14 | **数字快捷键改名** | 400 行管理器 + 对话框 | — | 选中 shape 按数字键批量重命名（upstream 无此能力）；独立配置 + 完整副作用链 | [→ 14](portfolio/14-digit-rename.md) |
| 15 | **视口状态保持** | 359 行控制器 | — | 切图保留缩放级别+视图中心；图像坐标持久化跨尺寸存活，复用模块 12 坐标模型 | [→ 15](portfolio/15-viewport-persistence.md) |

---

## 模块卡片

### 1. L1/L2 数据质检引擎

**痛点**：姿态标注数据量大，人工逐张检查 face/head/person 三类框的几何关系（face 是否在 head 内、head 是否在 person 上端、关键点是否越界）成本极高，且规则难以固化复用。

**方案**：一套纯 Python 的双层质检引擎——L1 检查 JSON 结构合法性，L2 用 12 条几何/视觉规则评估跨类关系，配 face→head→person 跨类匹配算法（硬过滤 + 加权打分）和阈值评估系统。

**技术亮点**：
- 🏗️ **纯 Python / PyQt 严格分层**：`quality/` 12 个文件 **0 个 PyQt import**，可在无显示器的 CI 环境直接跑批，CLI 与 UI 共享同一份逻辑
- 🎯 **12 条 L2 规则**：L2-01 face 匹配 head、L2-03 face/head 面积比、L2-06 head/person 空间位置、L2-09 关键点越界、L2-12 图级密度异常……
- 🔗 **跨类匹配**：face→head（严格，5 条硬过滤 + 4 维打分）/ head→person（宽松，4 条硬过滤 + 5 维打分），用三角函数峰值衰减做平滑评分
- ⚖️ **阈值评估**：4 种 direction + `error_requires` 二次确认降级机制（error 命中但确认条件不满足时自动降级为 warning）
- 💡 **阈值建议**：9 级优先级触发表，基于人工复核统计产出非约束性建议（永远 pending，不自动改配置）

📊 数据：4,354 行 · 148 测试用例 · [详细文档](portfolio/01-quality-engine.md)

---

### 2. Inspector 数据检查面板

**痛点**：原工作流是「标注 → 导出 JSON → 外部 Python 脚本检查 → 手动定位问题文件 → 逐张打开修复 → 再导出 → 再检查」，质检闭环在外部脚本，发现的问题无法直接跳转回标注位修复。

**方案**：一个 5-Tab 的 QDockWidget 工作台（数据检查 / 质检复核 / 数据表格 / 规则配置 / 导出），把外部脚本能力搬进标注工具，点击问题点直接跳转 Canvas 上的 shape。

**技术亮点**：
- 🧩 **插件化规则引擎**：`ValidationRule` ABC + `check`/`check_all` 双层级，新增规则零侵入
- 📋 **8 条内置规则**：标签白名单、group_id 唯一性、person 框必须有 gid、label-shape 绑定、关键点完整性……
- 🔁 **信号契约复用**：质检复核 Tab 复用既有 `issue_navigate_requested` 通路，**父级 LabelingWidget 零改动**即可接入新功能
- 🗂️ **三维内存索引**：`FlatIndex` 的 `_by_file/_by_label/_by_group` 支撑 500~1000 文件/批次扫描

📊 数据：3,785 行 · 60+ 测试用例 · [详细文档](portfolio/02-inspector-panel.md)

---

### 3. 优先级排序拾取模式

**痛点**：密集/嵌套标注场景（多框堆叠、关键点压在矩形上、大背景框套小目标框）下，旧的 `reversed + 首次命中` 策略只能选到"最后创建且整体命中"的对象，经常选错或选不到想要的对象。

**方案**：「决策转排序（Decision → Sort）」范式——对每个候选 shape 计算 4 维优先级元组，按字典序排序后返回，让"抓顶点 > 抓边 > 抓小对象 > 抓栈顶"在排序中自然生效。

**技术亮点**：
- 🎯 **4 维优先级元组**：`(级别, 距离/面积, 面积, -stack_index)`，零 if 分支
- 🧠 **面积当"具体性"代理**：嵌套场景下小对象面积小自然排前面
- 🔁 **三入口统一复用**：悬停高亮、点击选择、双击编辑都取排序后的首个候选
- 🧪 **纯算法可单测**：6 个场景在无 PyQt 环境下验证

📊 数据：~90 行核心算法 · 6 场景测试 · [详细文档](portfolio/03-selection-optimization.md)

---

### 4. 矩形边编辑

**痛点**：标注矩形时经常需要精修某条边（贴合图像边界、对齐相邻框），但原生编辑只能拖角点——拖角点会同时改变两条边，破坏另一方向的对齐。

**方案**：独立选中并拖动矩形的任意一条边（左/右/上/下），保留其他三条边不变。几何计算层与 Canvas UI 层严格解耦。

**技术亮点**：
- 📐 **几何层/UI 层解耦**：`RectEdgeRef` 只是临时编辑句柄，持有 Shape 活动引用，但**绝不写回 JSON/不进 Shape.other_data**
- 🛡️ **反翻转 clamp**：`geometry_with_edge_coord` 保证 `min < max`，矩形拖过头也不会坍塌/翻转
- 🔄 **Canvas 状态机**：hover → 按下选中 → 实时改坐标 → 松开提交（一次 release = 一个 undo 粒度）→ Esc 取消恢复
- 🔒 **绘制模式双向互斥**：进 create 模式自动关闭边编辑，反之亦然
- 📝 **诚实呈现**：本功能经历了「边对齐（吸附到参考边）→ 简化为边编辑」的演进，文档如实记录

📊 数据：407 行几何模块 + ~250 行 canvas · 21 测试用例 · [详细文档](portfolio/04-rect-edge-edit.md)

---

### 5. Pose View 标签解耦

**痛点**：开启 Pose View 后渲染器完全接管整张图，普通矩形/多边形标签被隐藏，"分割感"强；且选中某人会污染普通标签流程的选中态。

**方案**：filter-driven 架构——用单一字段 `pose_focus_group_id` 驱动标签列表与选中焦点的解耦；按 shape 类型过滤而非模式切换，让 Pose View 与原生标签共存。

**技术亮点**：
- 🎛️ **filter-driven 单字段解耦**：`pose_focus_group_id` 一个字段驱动总览/选中两态切换，不污染原生选中流程
- 📐 **4 种防遮挡布局**：direct（沿身体外放）/ anti（优先级排序消重叠）/ column（四象限垂直堆叠）/ category（按部位分组）
- 👁️ **总览/选中两态显示**：总览态 person 分色看全景，选中态显示骨架+标签+引线看细节
- 🧱 **纯模块优先原则**：`pose_constants`/`pose_config`/`pose_layout` 零 QWidget 依赖，可独立单测
- 🔧 **事件来源区分**：Keypoint Fill 模式的程序性空选中用 `is_active` 守卫，避免误清聚焦

📊 数据：1,994 行 / 9 文件 · 36 测试用例 · [详细文档](portfolio/05-pose-view.md)

---

### 6. 数据处理脚本集

**痛点**：姿态数据生产是一个完整链路（标注 → 格式转换 → 数据集划分 → 可视化核验 → 模型预标注对比 → 规则质检），每一步都需要专门工具，散落在各处难以维护。

**方案**：40 个统一 `argparse` CLI 风格的脚本，覆盖姿态数据生产全链路，与规格文档、Inspector 队列深度集成。

**亮点脚本**：
- 🔄 **YOLO Pose 三步流水线**：`step1-convert_json_to_yolopose.py`（604 行）→ `step2-split_yolov8pose_dataset.py` → `step3-visualize_yolo_dataset.py`
- 🤖 **ViTPose 预标注对比**：按 group_id 注入预测关键点，用模型预测反查人工标注盲点
- ✅ **质检 CLI**：`run_l1l2_qc.py`（输出 review.tsv + report.json）、`gen_threshold_suggestion.py`
- 📊 **数据集统计/对比**：唯一 label 提取、stem 对比、shape 统计

📊 数据：40 个脚本（核心逾 3,000 行） · [详细文档](portfolio/06-data-toolkit.md)

---

> **模块 7-10** 围绕「手动标注精修」一个主题展开，分两个方向：**人物实例绑定**（7、8）解决 `group_id` 的自动生成/继承/回填，**矩形框精修**（9、10）降低 1-3 像素误差。设计文档统一在 [docs/feature_summary.md](feature_summary.md)。

### 7. 新建 person 自动实例化

**痛点**：手动给每个 `person` 框敲 `group_id` 是纯机械、易错、低价值的操作（跳号、重号、错号）。

**方案**：手动绘制 `person` 矩形提交时，自动 `gen_new_group_id()`（max+1），状态栏提示「已创建 person #n」。

**技术亮点**：
- 🔗 **优先级解析链**：`bind_draw > auto_person_instance > auto_use_last_gid > 手动`，用 `if bound is None` 守卫从结构上杜绝与 bind_draw 冲突
- ♾️ **正交共存**：与 `auto_use_last_label` 不互斥——label 复用、gid 各开
- 🔒 **静态 Non-Goal 测试**：用 `inspect.getsource` 断言该 key 只在手动路径、不在 auto-labeling 落地路径
- ⚡ **按需读取**：设置不缓存到 widget 属性，现读现用，零状态同步

📊 数据：~60 行核心 + 设置/集成 · 9 测试用例 · [详细文档](portfolio/07-auto-person-instance.md)

---

### 8. 数字快捷绑定绘制

**痛点**：给已有 person 补 head/face 时，要手动把 `group_id` 从来源框"抄"到新框，既慢又错。

**方案**：`Digit Shortcut Mode = bind_draw` 下，选中 person/head/face 来源框，按数字键进入绑定绘制，完成后新框继承或回填来源 `group_id`。

**技术亮点**：
- 🧩 **独立管理器 + 窄接口**：`DigitBindDrawManager`（414 行）全状态机内聚，与 `LabelWidget` 仅 4 处接口协作
- ⏳ **懒回填**：来源 `group_id` 按下时绝不写，推迟到提交时与新框同快照——保证 undo 原子性
- 🛡️ **两阶段防重复（TOCTOU）**：按下挡一次、提交前再挡一次，绘制期间数据变化也不产生非法状态
- 🚦 **单点边界决策表**：与功能 7 的边界在 `handle_digit` 入口用早于来源校验的判断短路

📊 数据：414 行管理器 + 集成 · 19 测试用例 · [详细文档](portfolio/08-digit-bind-draw.md)

---

### 9. 精修控制模式

**痛点**：400% 放大下鼠标手抖导致 1-3 像素过冲/欠冲；键盘整体平移无法单独移动一条边。

**方案**：鼠标精修降速（`zoom`/`fixed`）+ Ctrl 临时精修 + Tab 键盘选边 + 方向键 1px/Shift+5px 单边微调。精修主流程。

**技术亮点**：
- 🎯 **虚拟游标隔离**：独立累加器缩放 delta，**绝不改 `prev_point`**——hit-test/hover/transform 零污染，回归风险为零
- 📈 **zoom 模式消僵硬**：`min(scale, max_factor)` + `max(1.0, ...)` 双向 clamp，400% 最多降到 1/2 而非 1/4
- ⌨️ **Tab 单边操作**：选边后方向键只动那一条边（反翻转 clamp），`merge_window=0.5` 让连按合并成一次 undo
- ⚡ **Ctrl 单事件级**：未锁定时每事件现查修饰键，按住降速、松开恢复，零状态切换

📊 数据：~250 行 canvas + 设置 · 14 测试用例 · [详细文档](portfolio/09-precision-mode.md)

---

### 10. 局部边缘吸附（实验性）

**痛点**（与反思）：设想「精修到附近 → 算法按图像边缘补 1-3 像素」，但实现后发现**图像强边缘 ≠ 标注规则正确边界**（人物边界模糊、衣服纹理干扰、规范要求留白）。

**方案**：一次性命令（Ctrl+Alt+E），对 Tab 选中的边在 ±4 像素内用 Sobel 梯度 + 双重阈值（自适应 0.6 + 绝对下限 10）搜索吸附。**当前定位实验性，非主流程**。

**技术亮点**：
- 🧪 **纯 Python 评分模块**：`edge_snap.py`（212 行）零 PyQt，11 测试无 Qt 跑通
- ⚖️ **双重阈值**：`k×local_max`（自适应）+ `abs_floor`（绝对下限）同时满足才吸附，跨对比度稳定
- 🔒 **validate-before-apply**：候选会被 clamp 时视为失败而非部分应用，避免误导
- 📝 **诚实降级**：主动识别「方向偏差」并叫停，如实记录为实验命令——工程价值在于把「该不该用这个方法」显式化

📊 数据：212 行纯 Python + canvas 桥接 · 11 测试用例 · [详细文档](portfolio/10-local-edge-snap.md)

---

> **模块 11-14** 是早期基础设施类扩展：**筛选系统**（11）和**缩放修复**（12）解决 upstream 的基础体验缺陷，**数字快捷键分页/改名**（13、14）把 upstream 仅 10 键的快捷系统扩展成可批量操作的多页体系。

### 11. 筛选系统（保持 + 引擎 + 索引 + 导航）

**痛点**：upstream 只有 2 个裸 `QComboBox`——切图丢筛选、5000 图全量扫 JSON 卡死、无法在筛选结果间导航、逻辑与 UI 耦合无法单测。

**方案**：4 层子系统——`FilterState`（归一化态+快照恢复）/ `ShapeFilterEngine`（匹配计算，不碰 UI）/ SQLite 派生索引（可丢弃可重建）/ `FilterNavigationEngine`（跨文件导航纯逻辑）。

**技术亮点**：
- 🔒 **切图保留筛选态**：`load_file()` 快照/恢复链，label/gid/shape_type 在图片间存活
- ⚡ **SQLite 派生索引**：5000 图/18000 shape 从卡死到秒级，JSON 仍是唯一真相源，索引可丢弃可重建
- 🧱 **State/Engine/UI 三层**：Engine 零 PyQt 依赖，可无 Qt 单测；`filter_state_engine_pattern` 作为可复用模板
- 🧭 **跨文件导航**：`FilterNavigationEngine` 只在满足筛选的文件间跳转

📊 数据：~1,400 行 / 5 文件 · [详细文档](portfolio/11-filter-system.md)

---

### 12. 缩放中心点修复

**痛点**：upstream beta.4 在**竖图**上 Ctrl+滚轮缩放时鼠标下的点漂移——`setWidgetResizable(True)` 钳制 canvas width 使 guard 判 False 跳过补偿，且 y 轴误用 width 比率。

**方案**：用 `transform_pos` 的精确逆变换（坐标锚点算法）替换 width 比率启发式，保证缩放前后鼠标下的图像点不变。

**技术亮点**：
- 📐 **逆变换取代启发式**：`image_pos = widget_pos/scale - offset`，无 `setWidgetResizable` 失效路径
- 🛡️ **`_clamp_scroll_value`**：图像小于 viewport（maximum==0）时不持久化不可达滚动值
- 📝 **符号验证式文档**：设计文档用一节专门证明 `new_scroll = old_scroll + delta` 保持不变量
- 🎯 **诚实界定**：明确标注 navigator 相关方法仍用旧模型（Phase 2 延期），不打包票「全修了」

📊 数据：~70 行核心 + 2 篇分析文档 · [详细文档](portfolio/12-zoom-center-fix.md)

---

### 13. 数字快捷键分页扩展

**痛点**：upstream 数字快捷键只有 0-9 共 10 槽，标注任务常需 >10 种 label+shape_type 组合。

**方案**：在 upstream 的 `create_digit_mode` 加分页索引层，`F1` 切页，10×N 槽位，单页时与 upstream 完全一致（向后兼容）。

**技术亮点**：
- ⬅️ **向后兼容**：默认 1 页时 `get_actual_index` 返回原值，已有配置零迁移
- 🔢 **配置驱动页数**：`digit_shortcut_pages` 控制槽位上限，循环切页 + 信号通知
- 🧩 **共享索引层**：分页对 draw / rename / bind_draw 三种数字键模式都生效

📊 数据：311 行分页管理器 · [详细文档](portfolio/13-digit-shortcut-pagination.md)

---

### 14. 数字快捷键改名

**痛点**：改已有 shape 的 label 要逐个双击开对话框，AI 预标注批量修正时慢到无法用；upstream 完全没有此能力。

**方案**：编辑模式选中 shape 后按数字键，所有选中 shape 的 label 立刻改成该键绑定值——一步批量重命名。

**技术亮点**：
- 🔄 **完整副作用链**：一次重命名处理 undo 快照 + label 改值 + 列表更新 + 历史 + dirty + 筛选刷新
- 🔀 **与绘制分流互斥**：`digit_shortcut_mode` 切换 rename/draw/bind_draw，入口分流零冲突
- 📋 **独立配置**：`rename_shortcuts` 与 draw 的 `digit_shortcuts` 分开，互不干扰
- 🔗 **与分页协同**：也走 `digit_page_manager`，多页时每页 10 个改名槽位

📊 数据：400 行管理器 + 对话框 · [详细文档](portfolio/14-digit-rename.md)

---

### 15. 视口状态保持

**痛点**：逐张检查标注时放大到某级别聚焦某区域，切图就回到 fit-window——5000 张图每张都要重新放大定位。upstream 的 `keep_prev_scale` 只保留缩放比例，不保留「看哪个位置」。

**方案**：`ViewportController` 按 filename 缓存 `(zoom_mode, zoom_value, center_x, center_y)`，中心点存**图像坐标**而非滚动条像素——跨 widget resize、跨不同尺寸图片存活。

**技术亮点**：
- 📐 **图像坐标持久化**：捕获用 `transform_pos` 逆变换、恢复用正向变换，不存易失效的滚动条像素
- 🔁 **复用模块 12 坐标模型**：同一对公式一次证明两处复用，零新坐标数学
- 🏆 **三级解析优先级**：精确历史 > `keep_prev_viewport` 继承 > 无（回退默认），含 stale 状态清理
- 🎚️ **三缩放模式全保留**：FIT_WINDOW / FIT_WIDTH / MANUAL_ZOOM 连同数值一起还原

📊 数据：359 行控制器 · [详细文档](portfolio/15-viewport-persistence.md)

---

## 技术栈

| 层 | 技术 |
|----|------|
| GUI 框架 | PyQt6（QMainWindow / QDockWidget / QGraphicsView） |
| 质检引擎 | 纯 Python（stdlib + PyYAML），零 PyQt 依赖 |
| 配置驱动 | YAML 阈值 profile + 21 项 pose_view 配置键 |
| CLI 工具 | argparse + ProcessPoolExecutor + tqdm |
| 测试 | pytest + unittest，headless Qt（`QT_QPA_PLATFORM=offscreen`） |
| 代码质量 | black（line 79）+ flake8（max complexity 18）+ Google docstring |

---

## 设计方法论沉淀

在实现这些功能的过程中，我把一些可复用的设计决策记录成了「模式卡片」和设计文档：

- [PATTERN_CARD_001 决策转排序](PATTERN_CARD_001_decision_to_sort.md)——把多重 if-elif 决策转成可比较的元组排序
- [filter_state_engine_pattern.md](filter_state_engine_pattern.md)——单字段驱动状态机模式
- [canvas_refactor_plan.md](canvas_refactor_plan.md)——Canvas 分析与重构方法论
- [annotation_quality_methodology_prompt_guide.md](annotation_quality_methodology_prompt_guide.md)——标注质检方法论

---

## 如何浏览本作品集

1. **快速了解**：看上面的功能矩阵表
2. **深入某模块**：点击对应「详述」链接，每篇都包含痛点/架构/技术亮点/代码定位/测试
3. **看设计思路**：`docs/` 目录有 116 篇设计文档，按功能名前缀检索
4. **看代码**：所有 `file:line` 引用在 GitHub 上可点击跳转

---

## 致谢

- [CVHub520/X-AnyLabeling](https://github.com/CVHub520/X-AnyLabeling)——优秀的开源标注工具，是本 fork 的基础
- 所有 upstream 贡献者
