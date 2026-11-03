# Inspector / Dense Review 界面改造方案

- 日期：2026-11-03
- 对象：CUSTOM-109 Inspector（`views/labeling/inspector/dialog.py`）、CUSTOM-110 Dense Review（`views/labeling/dense_review/workspace.py`）
- 证据：本目录 `01`–`06` 六张真实渲染截图，渲染脚本 `render_ui.py`
- 改造稿：`mockup.html`（可在「现状 / 改后」之间切换）

## 结论

“丑”不在配色，而在三件事：

1. **没有专属样式层**。`dialog.py` 0 处 `setObjectName` / `setStyleSheet`；`workspace.py` 0 处 `objectName`，仅对 `completion_label` 有两处内联着色。关键前提：**浅色模式下 `get_app_stylesheet()` 直接返回空串**（`theme.py:230`），两个窗口实际吃的是 Fusion 默认样式；深色模式才有一层只含按钮基础态的 QSS。所以 Inspector 六个操作按钮全部白底同高、**没有任何主按钮**；唯一带蓝色的是「加载记录」的 1px 默认按钮边框（Fusion 高亮色 `#308cc6`，实测仅上下两行像素），与设计系统 `#0071E3` 无关。
2. **空间分配反了**。Inspector 820px 高里，真正干活的队列只有 **130px**，而顶部表单 247px、候选表格 176px、文本状态区 125px。Dense 的卡片区在 1280 宽下右侧余 128px（约 13%），批次列表把两行文字压进 **16px** 行高。
3. **边界与层级缺失**。卡片没有边框、选中变成深灰实心块、表格 6 列固定宽度溢出、九个按钮同权重平铺。

P0 只改布局、表格和按钮变体，不动任何业务逻辑，约 0.5–1 天就能看到质变。

## 一、现状证据

渲染方式：真实 `MainWindow` + 1280×720、35 个框、6 类的合成数据集，`QT_QPA_PLATFORM=offscreen`，PyQt6 6.10 / Python 3.12。

> 环境坑：offscreen 平台的字体库为空，直接渲染中文全是方块。脚本里 `QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc")` 后才能正常出字，后续做离屏视觉回归也要带这一步。

### Inspector

| 问题 | 实测 / 代码证据 | 影响 |
| --- | --- | --- |
| 主工作区被挤扁 | `QSplitter` 实测高 **160px**；顶部表单 247、候选 tab 176、五轴状态 125 | 问题表 **130px** 高，一屏只看到 4 条（行高 30） |
| 表格横向溢出 | 表宽 695 / viewport 693；列宽 `70+150+180+210+120+100 = 830` | 溢出 137px，横向滚动条可见，最后一列「人工判断」默认看不到 |
| 对象列内容被裁 | 行高固定 **30px**（非自适应），`dup-000, shape-000` 在 210px 列内截断 | 无法确认是哪个对象，只能点开详情 |
| 详情区过矮 | `QTextBrowser` 实测 **70px** | 选中问题后正文只能显示三四行 |
| 九个按钮同权重 | `action_grid` 3×3 平铺，全部 155×24、白底同色 | 「定位」和「删除画布选中框」视觉权重相同 |
| 顶部四个全宽下拉 | `QFormLayout` 每行一个控件，组高 247 | 右侧约 40% 空白 |
| 空状态缺失 | 未选中时详情区纯白；未运行时表格空白 | 用户不知道下一步做什么 |
| 无主按钮变体 | 全局 QSS 无 `QPushButton` 变体；唯一蓝色是「加载记录」默认按钮的 1px 边框（Fusion `#308cc6`） | 六个操作无主次，与 `#0071E3` 设计色不一致 |

### Dense Review

| 问题 | 实测 / 代码证据 | 影响 |
| --- | --- | --- |
| 批次项被压扁 | `batch_list` 实测行高 **16px**（`sizeHintForRow(0)=16`），条目文本两行 | 「类别 0/13 · 框 0/13」只露出半行 |
| 卡片无边界 | `card_list` 透明背景、无边框；缩略图 180×120 灰块 | 卡片范围不可辨，像加载失败 |
| 选中态突兀 | 系统选中色整块深灰 | 与「当前对象」语义冲突，抢注意力 |
| 网格固定 216px | `setGridSize(216,176)`；卡片区 992 宽 → 4 列 864px，右侧余 **128px**（13%），列内留白 36px | 宽屏不会多排一张，视觉上偏空 |
| 顶部三行纯文本 | 三个 QLabel 各 16px 高：「对象 35 · 全图待审 35 · …」「未完成 · 查漏尚未开始」「类别统计…」 | 没有进度条，扫读成本高 |
| 操作区主次不分 | 「完成本批」实测 728px，其余 80–86px，全部 24px 高 | 主操作不突出，禁用按钮无原因 |
| 查漏页几乎空白 | 6 行 `r00-00 待查` + 一行按钮 | 看不出「哪些区域已查」，与网格语义脱节 |

## 二、改造方案

### 2.1 结构：把空间还给主任务

**Inspector**（1200×820 → 保持，内部重排）

```text
┌ 44  工具条：方案 220 | 阶段 110 | 范围 120 | 运行历史(12) ····· 取消 | 开始检查
├ 36  状态行：进度 ────────  1/1 文件 · 4 问题 · 已处理 0 · 1.2s      执行完成
├ 1fr ┌ 队列 flex:1 ───────────────────┬ 详情 360 ─────────────┐
│     │ 筛选 chips + 搜索 + 上/下       │ 详情 | 外部候选 0     │
│     │ 表头 34px / 行 34px，5 列       │ 规则 / 证据 / 建议    │
│     │ 双击定位，列宽随面板自适应      │ 3×3 判定按钮          │
├ 36  五轴：● 执行 1/1  ● 问题 0/4  ● 对象 0/35  ● 空间 0/6  ● 正式 未接受
```

- 顶部四个下拉改为一行，运行历史收成按钮 + 菜单，菜单项显示「今天 09:02 · 4 问题 · completed」。
- 队列与详情**已经是** `QSplitter` 3:2（`dialog.py:194`、`:276`）；真正的问题是没有 `minimumWidth`，且详情里的按钮网格按 sizeHint 抢高度（详情区被压到 70px）。保留 splitter，补最小宽度与高度预算。
- 「外部候选」从整宽 tab 移入右栏 tab，省下 176px。
- 五轴从 125px 文本块改为 36px 徽标条，长说明放「展开说明」。

**Dense Review**（1280×860）

```text
┌ 44  工具条：进度 180 ── 35 对象 · 已确认 0 · 待审 35 · 疑难 0 · 暂跳 0 ··· 配置 | 刷新
├ 1fr ┌ 批次 248 ─┬ 卡片 flex:1（auto-fill minmax(178px,1fr)）────────────┐
│     │ 批次卡片  │ 当前对象行：#1 举手 · 类别待审 · 框待审 · 本类规则    │
│     │ 名称+数量 │ 卡片：色条 + 缩略图 + 角标 + #ID/状态                  │
├ 56  操作条：聚焦|全部|原图  看全图 ····· 暂跳 疑难 完成并下一个 | 完成本批（13）
```

- 批次列表改为 3 行卡：名称 + 数量 pill / 4px 进度条 / 「类别 0/13 · 框 0/13」。
- 卡片网格按容器宽度算列数（`(width - padding + gap) // (min + gap)`），`resizeEvent` 里重算，替代固定 `gridSize`。
- 底部操作条固定一行，主操作靠右，显示模式改分段控件，按钮高度沿用 `get_dialog_style()` 的 36px（见 §2.2）。
- 空间查漏页改为「网格示意图 + 区域列表」：3×2 小方块按状态着色（已查绿 / 未查灰 / 疑难橙），点方块等同定位。

### 2.2 视觉：接入既有对话框样式，而不是再造一套

仓库已有统一入口 `utils/style.py::get_dialog_style()`（`style.py:767`），覆盖按钮 / 表格 / 滚动条 / GroupBox / 下拉，20 个界面文件在调用；这两个窗口没接。**第一步就是各加一行 `setStyleSheet(get_dialog_style())`**，而不是新增 `workbench_style.py`。按钮高度沿用它的 36px，不额外引入第三种尺寸。

窗口专属的差异（主/次/弱按钮、浅底选中、卡片）作为 `QDialog#annotationInspector` / `#denseReviewWorkspace` 作用域的追加 QSS，写进 `style.py` 的新函数 `get_workbench_qss()`，避免出现第三套样式系统。

| 元素 | 现状 | 建议 |
| --- | --- | --- |
| 窗口底色 | 纯白 | `#FFFFFF` 内容区 + `#F9F9F9` 工具栏/状态条，用底色分层代替描边 |
| 分区 | `QGroupBox` 1px 描边 + 标题压在边框上 | 去掉边框，标题 13px/500 `#86868B`，靠 12px 间距分组 |
| 主按钮 | 无；唯一蓝色是「加载记录」的默认按钮边框（Fusion `#308cc6`） | `#0071E3` 底、白字、高 **36**（与 `get_dialog_style()` 一致）、圆角 8、`padding 0 14` |
| 次按钮 | 全部一样 | 白底 + `#D2D2D7` 描边 |
| 弱按钮 | 无 | 透明底，`#86868B` 字，用于「展开说明 / 运行历史」 |
| 危险动作 | 与其他按钮同色 | `#FF453A` 字，仅图标/文字，不加底色 |
| 表头 | 系统默认粗体灰 | 11px/400 `#86868B`，底边 1px `#E5E5E5`，行高 34 |
| 选中行 | 接入 `get_dialog_style()` 后是实心主色 + 白字（`style.py:941`） | 二选一：跟随全局实心选中，或本窗口用 `#EAF4FE` 浅底 + 左侧 2px 条（需在作用域 QSS 内覆盖 `::item:selected`） |
| 徽标 | 无 | 高 20、圆角 99、11px；风险高/中/低用红/橙/灰三档 |
| 间距 | 12 / 8 / 6 混用 | 统一 8 栅格：窗口 16，区块 12，控件 8 |
| 字号 | 全部随系统 9pt | 标题 15/500，区块 13/500，正文 13/400，辅助 11/400 |

颜色全部走 `utils/theme.get_theme()`，深色模式自动跟随；不要写死 `#FFFFFF`。注意：`#EAF4FE` / `#FFF4E0` / `#FDECEA` / `#EFEFF2` 目前在 `LIGHT` / `DARK` 里**都没有对应 token**，要先成对补齐，否则「全部走 get_theme()」无法成立。

### 2.3 交互：顺手修掉的可用性问题

- 双击问题行 = 定位；`Enter` = 定位；`1`–`4` 直接标记四种判定（可选）。
- 卡片 `←`/`→` 切换，`Enter` 完成，`Alt+X` 疑难——接线**已经存在**（`workspace.py:48` 调用 `:1355` 的 `_install_shortcuts`），缺的是提示文案、作用域，以及 mockup 把实际绑定（`Ctrl+Return` / `Alt+Return`）写成了「Enter 完成」。
- 所有禁用按钮加 `setToolTip` 说明原因（「请先加载图片文件夹」「请先在画布选中对象」）。
- 空状态：详情区「选择左侧问题查看证据」；候选「本轮没有外部候选」；查漏「尚未生成区域计划，点『重建区域计划』」。
- 表格长 ID 省略 + `Qt.ToolTipRole` 显示完整 ID；多对象显示 `shape-000 +2`。

## 三、落地顺序

| 优先级 | 改动 | 文件 | 验收 |
| --- | --- | --- | --- |
| P0 | Inspector 工具条两行化、候选并入右栏、五轴改徽标条 | `inspector/dialog.py::_build_ui` | 队列可见高度 ≥ 380px，≥ 8 行 |
| P0 | 问题表 5 列 + `Stretch` + 行高 34 + 长 ID 省略 | `dialog.py` 表格初始化 | 1200px 下无横向滚动条 |
| P0 | 按钮三变体 + 禁用 tooltip | 新增 `workbench_style.py` | 每屏只有一个蓝底主按钮 |
| P0 | 空状态 | 两窗口 refresh 分支 | 空白区有指引 |
| P1 | Dense 顶部进度条、批次卡片、卡片边框/色条/角标 | `dense_review/workspace.py` | 卡片可辨，右侧无固定留白 |
| P1 | 网格列数随宽度重算 | `workspace.resizeEvent` | 1280 宽 4 列、1000 宽 3 列 |
| P1 | 操作条单行化、显示模式分段控件 | `workspace._build_object_tab` | 主操作靠右，控件同高 |
| P2 | 查漏网格示意 | `workspace._build_coverage_tab` | 不读列表也能看出进度 |
| P2 | 详情结构化（规则/证据/建议） | `dialog._show_selected_details` | 不再是一段 HTML 文本墙 |
| P2 | 快捷键接线与提示 | `workspace._install_shortcuts` | 与设置页 6 项一致 |

## 四、风险与回归

1. **不要改全局 `QPushButton`**。设置、点云、主工具栏都依赖当前基础态；新样式必须挂在 `QDialog#annotationInspector` / `QDialog#denseReviewWorkspace` 下，或走动态属性 `[variant="primary"]`。
2. **表格列宽**：`ResizeMode.Stretch` 在 < 980px 时会挤压「规则」列，保留 `minimumSectionSize=64`，低于阈值允许横向滚动而不是压字。
3. **网格重排抖动**：`resizeEvent` 里先比较缓存的列数再 `setGridSize`，避免递归。
4. **测试影响**：现有 `tests/test_inspection` 80 项 + `tests/test_dense_review` 78 项（实测 collect = 158），主要断言状态与数据，不依赖像素；但 `test_workspace.py` 若断言了按钮文本/数量，重排后需同步。改完跑这两个目录与 `tests/test_canvas` 定向回归。
5. **深色模式**：本次截图只覆盖浅色；样式全部取 `get_theme()`，改完补一张深色渲染对照。

## 五、验收标准

- 同一数据集、同一窗口尺寸下，改造前后截图可对比（`mockup.html` 已内置切换）。
- Inspector：队列一屏 ≥ 8 行；无横向滚动；详情区 ≥ 220px；每屏 1 个主按钮。
- Dense：卡片边界清晰、选中为主色描边；1280 宽下卡片列数 ≥ 4 且右侧无 > 40px 空白；操作条单行。
- 深色模式无写死颜色导致的低对比。
- 业务行为零变化：检查结果、复核进度、保存内容与改造前逐字节一致。

## 六、补丁：复核补充与冲突修正（追加）

> 本节为追加内容，不修改 §一–§五。基于同一批截图与代码复核，补充三类：改造稿自身需要先修的地方（6.1）、计划未覆盖的 UI 层（6.2）、增补排期与验收（6.3）。与原文冲突处，以本节为准，冲突清单见 6.4。

### 6.1 改造稿需先修正的 9 处

| # | 位置 | 问题 | 修正 |
| --- | --- | --- | --- |
| 1 | `mockup.html:154`、`:194` | 同屏两个蓝底主按钮（「开始检查」+「定位」），违反 §五「每屏 1 个主按钮」 | 「定位」降为次按钮；列表双击已经能定位 |
| 2 | `mockup.html:146` | 多画了约 40px 的假标题栏（「只读检查 / 关闭」），§2.1 的 ASCII 里没有这一行 | 删掉，或改成真工具栏；垂直预算需重算 |
| 3 | `mockup.html:147-156` | 静默删掉 7 个真实入口：继续上次处理 / 复制 / 导入 / 导出方案 / 加载记录 / 导入旧问题 / 导出报告，以及「说明 / 本次启用」两个信息块；Dense 还删了「开始 / 重建本轮」（唯一的建队入口，`workspace.py:74`） | 收进「方案 ▾ / 更多 ▾」菜单，不能直接消失 |
| 4 | `mockup.html:166` | 8 个筛选项砍成 5 个，丢了「待复查 / 可接受 / 需讨论」，「待复查」是「检查 → 修改 → 复查」闭环的核心状态（`dialog.py:199-207`） | 全保留，chips 折行或收进「更多筛选」 |
| 5 | `mockup.html:181` vs §2.1 ASCII | ASCII 里有「搜索」，HTML 里没有搜索框 | 补搜索框，或明确砍掉并同步验收 |
| 6 | `mockup.html:146` / `:196` | 标「只读检查」，同屏却有「删除选中框 / 重标选中框」，而这两个操作真的会改画布 | 去掉「只读」标签，或把这两个动作挪进二次确认流程 |
| 7 | `mockup.html:283` | 底部胶囊放了「并排比较 / 查看成员 / 重建剩余队列」三个真实按钮，与 §2.1 ASCII 的「快捷键提示」位置冲突 | 二选一：底部只放快捷键，批次操作收到操作条菜单 |
| 8 | `mockup.html:158` | 100% 进度条旁写「已处理 0」，把执行进度和复核进度画成一根 | 拆成两根，或执行进度降为状态行细条 |
| 9 | 「现状 / 改后」对比法 | 现状是 PNG 缩放、改后是 HTML，字体 / 行高 / metrics 不同源，「队列 ≥380px、≥8 行」无法被这张稿子证明 | 见 6.6：改后先落代码，用同一个 `render_ui.py` 出图对比 |

### 6.2 计划未覆盖的 UI 层

#### 6.2.1 P0：4 项，先做（合计约 0.5 天）

**A. 接既有对话框样式，而不是新建样式层**

仓库已有统一入口 `utils/style.py::get_dialog_style()`（`style.py:767`），覆盖按钮 / 表格 / 滚动条 / GroupBox / 下拉，`label_widget`、点云、batch 等对话框都在用；12 个 `QDialog` 子类里有 6 个没接，这两个窗口都在其中。各加一行 `setStyleSheet(get_dialog_style())`，「吃默认 Fusion」的问题就消掉一半。

- §2.2 的「新增 `workbench_style.py`」应改为 **在 `style.py` 内新增 `get_workbench_qss()`**，避免出现 theme.py + style.py 之外的第三套样式系统。
- 尺寸冲突：`get_dialog_style()` 里按钮是 `min-width:100 / height:36`（`style.py:916`），§2.2 写的 28px 是第三个尺寸。**建议这两窗口保持 36**，不要为一个窗口动全局按钮高度。
- 生效方式：根 `objectName` 仍按 §四.1 挂，写成 `QDialog#annotationInspector {...}` 追加，不改全局 `QPushButton`。

**B. 深色模式：4 处写死颜色 + token 缺口**

| 位置 | 现状 | 风险 |
| --- | --- | --- |
| `dialog.py:1037-1039` | `#c0392b` / `#b9770e`，且把整行 6 列都染色 | 深色底上对比不足；文件、人工判断列也变色 |
| `workspace.py:549` | 完成标签 `#22A06B` | 深色模式下偏暗 |
| `workspace.py:742` | 缩略图占位 `#EEF1F4` | 深色下是亮白块 |

另：§2.2 要的 `#EAF4FE` / `#FFF4E0` / `#FDECEA` / `#EFEFF2` 在 `theme.py` 的 `LIGHT` / `DARK` 里**没有对应 token**，必须成对补齐后才能「全部走 `get_theme()`」。

同名冲突：§2.2 的「选中行 `#EAF4FE` 底 + 左侧 2px 条」与全局 `QTableWidget::item:selected`（实心主色 + 白字，`style.py:941`）不一致。**二选一**：全局统一（影响所有表格）或这两窗口放弃浅底选中。

**C. 窗口行为（原文 0 覆盖）**

- 两窗口都没有 `minimumSize`，也没有 `saveGeometry` / `restoreGeometry` → 每次重开回默认 1200×820 / 1280×860，用户每次重排。
- 尺寸超屏：`1280×860` 在 1920×1080@150%（逻辑 1280×720）放不下；`1200×820` 在 1366×768 也超屏，底部按钮会被任务栏切掉。
- 做法：按 `objectName` 分键存 `QSettings`；最小 1000×700；打开时用 `QScreen.availableGeometry` 裁剪；宽度 < 1100 时把「运行历史 / 复核配置」折进菜单。

**D. 键盘与焦点**

- Inspector 目前 **0 个快捷键**（连 Esc / Enter 都没有）。建议 Esc = 关闭、F5 = 开始检查、Enter = 定位选中行、Ctrl+F = 搜索（若采纳 6.1-5）。
- 两窗口都未设 `setDefault` / `setAutoDefault(False)`。`QDialog` 中未指定默认按钮时，Enter 可能落到第一个 autoDefault 按钮（「开始检查」），在表格 / 下拉里回车有误触发风险。需显式指定 default，并对其余按钮置 `False`。
- Dense 的 5 个快捷键是 `ApplicationShortcut`（`workspace.py:1396`），窗口非激活时仍生效，会和画布 / 其它输入框抢 `Alt+Return`、`Alt+N`、`Alt+X`。应改为 `WindowShortcut`，或在 `showEvent` 里按 `isActiveWindow()` 门控。
- §2.3 的提示文案与实际绑定不符：实际是 `Ctrl+Return` / `Alt+Return`（`workspace.py:1361` 起），不是 mockup 写的「Enter 完成」。

#### 6.2.2 P1：结构性（约 1–2 天）

1. **按钮总量**：两窗口各 **25 个 `QPushButton`**。§2.2 只治「权重」，没治「数量」。建议常驻主操作 ≤4 个，其余按「方案级 / 批次级 / 区域级」收进菜单或右键；这些按钮同时 `Qt.NoFocus`，避免 25 项 Tab 链。
2. **表格排序 / 搜索 / 规模**：无 `setSortingEnabled`、无搜索；筛选一变就整表重建（`dialog.py:993`），上千条问题会卡。建议 `QAbstractTableModel` + 代理排序过滤，或至少 `sortItems` + 输入防抖。
3. **着色与 tooltip 粒度**：风险色染整行（`dialog.py:1037`），「文件 / 人工判断」列也变红；tooltip 全部是 `issue.message`（`dialog.py:1035`），长 ID / 路径没有 tooltip——§2.3 要的「省略 + 完整 ID tooltip」目前不成立，需要按列分别给 tooltip。
4. **进度语义**：执行进度与复核进度必须分开（见 6.1 表格第 8 行）。
5. **三态页**：原文只有空状态。现在「0 个问题」和「没跑过」长得一样（都是空表），失败只弹框然后回空表。建议表格区做状态页：未运行 / 运行中骨架 / 无问题 / 失败重试。
6. **本地化**：仓库有 4 套语言包，但 `STAGE_LABELS` / `SCOPE_LABELS` / `DECISION_LABELS` / `VERIFICATION_LABELS` / 筛选项 / 错误标题 / tooltip 都是裸中文（约 169 行含中文未包 `tr()`）；两窗口标题在 4 个 `.ts` 里 **0 条**；也没有 qtbase 翻译，`dialog.py:1888` 的 Yes/No 在中文界面显示英文。本次新增文案同样要进 `tr()` 并重生成 `.ts` / `.qm`。
7. **弹框与原生控件**：`_ask_dirty_batch`（`dialog.py:592`）与 `closeEvent` 用裸 `QMessageBox`，仓库的 `get_msg_box_style()` 没用上；`QInputDialog.getText`（`dialog.py:470`）同理。建议统一走既有样式助手。

#### 6.2.3 P2：细节

8. **图标与文案长度**：两窗口 0 图标（仓库有 `new_icon_path` 图标体系），主操作建议 icon + text；「完成本批并进入下一批」10 字，在 36px 高按钮上一行放不下，mockup 的「完成本批（13）」才是方向——**改文案，不是改排版**。
9. **卡片绘制路径**：`QListWidget` 的 `IconMode` 下，`card_list` 的边框 / 色条 / 角标无法用 QSS 实现，必须走 `QStyledItemDelegate`，或把边框和角标画进缩略图 pixmap。§2.2 未给实现路径，直接照做会卡在这里。
10. **HiDPI**：`setIconSize(180×120)` / `setGridSize(216×176)` 是逻辑像素，150% 缩放下字体放大后卡片文字会溢出；§五的「队列 ≥8 行」也应按缩放档位分别验收。

### 6.3 增补排期（并入 §三）

| 优先级 | 改动 | 文件 | 验收 |
| --- | --- | --- | --- |
| P0 | 两窗口接入 `get_dialog_style()`，统一按钮高度 36 | 两窗口 `__init__` 末尾 | 与设置 / 点云对话框视觉一致 |
| P0 | 深色模式 4 处硬编码 + theme 补齐浅底 token | `dialog.py:1037`、`workspace.py:549/742`、`theme.py` | 深色截图无亮块、无低对比 |
| P0 | 几何持久化 + `minimumSize` + 屏幕可用区裁剪 | 两窗口 `__init__` / `showEvent` | 重开保持位置；1280×720 逻辑分辨率可完整操作 |
| P0 | 快捷键作用域 + default button + Esc | 两窗口 | 画布聚焦时 `Alt+Return` 不误触 |
| P1 | 25 个按钮 → 常驻 ≤10 + 菜单化 | 两窗口 `_build_ui` | 一屏能找到「出口」 |
| P1 | 排序 / 搜索 / 大数据模型 | `dialog.py` 表格 | 1000 条问题筛选 < 300ms |
| P1 | 三态页 + 进度拆分 | 两窗口 refresh 分支 | 「0 问题」与「未运行」可区分 |
| P2 | 本地化包裹 + `.ts` 重生成 | `dialog.py`、`workspace.py`、`resources/translations` | en_US 下无中文残留 |

### 6.4 与原文冲突清单

| 原文位置 | 原文表述 | 实际情况 / 修正 |
| --- | --- | --- |
| §1 结论 1 | 两模块「0 处 `setStyleSheet`」 | `workspace.py:548` 有 1 处；且浅色模式下 `get_app_stylesheet()` 返回空串（`theme.py:230`），浅色根本没有全局 QSS |
| §2.1 Inspector 段 | 「队列与详情改用 `QSplitter`」 | 已经是 `QSplitter` 3:2（`dialog.py:194`、`:276`）；真问题是无 `minimumWidth` 与内部控件 sizeHint 抢高度 |
| §2.2 | 「新增 `workbench_style.py`」 | 改为扩展 `style.py`（见 6.2.1-A） |
| §2.2 主按钮 | 高 28 | 与 `get_dialog_style()` 的 36 冲突，建议保持 36 |
| §2.3 | 「快捷键已在配置里，只差接线」 | 接线已存在（`workspace.py:48`、`:1355`），缺的是提示文案与作用域 |
| §3 P0 第一行 | 「工具条两行化」省出 90px | 需扣除 mockup 多画的假标题栏，实际收益以 6.6 的实测图为准 |

### 6.5 验收增补（并入 §五）

- 深色模式：同一页面在 `theme=dark` 下重截，无亮色块、无对比度不足。
- 缩放：125% / 150% 各截一张，卡片文字不溢出、队列可见行数 ≥ 5。
- 语言：`language=en_US` 下重截一张，无中文残留（含窗口标题与标准按钮）。
- 规模：1000 条问题的报告，筛选响应 < 300ms，滚动无卡顿。
- 焦点：画布 / 其它对话框聚焦时，Dense 的 `Alt+Return` 等不触发。
- 窗口：关闭重开保持位置与尺寸；在 1280×720 逻辑分辨率下所有主按钮可点。

### 6.6 方法说明

`mockup.html` 只作意向沟通，不作为验收依据：现状是缩放后的 PNG，改后是 HTML，字体族、行高、控件 padding 均不同源，像素级结论不可比。改后稿落地后，用同一个 `render_ui.py`（相同的 1200×820 / 1280×860、相同的合成数据集、相同的 `Microsoft YaHei` 9pt 字体注入）出图，与 `01`–`06` 做同参数对比，§五的数字才算被验证。

### 6.7 对 §六 的核查结果（2026-11-03）

核查方式：`measure_ui.py` 实测控件几何；grep + AST 核对代码、翻译与字符串；`QTest` 验证 Esc / Enter。下表结论**优先于 6.2 / 6.4 的对应表述**。

#### 成立，可直接执行

| 断言 | 证据 |
| --- | --- |
| 浅色模式没有全局 QSS | `theme.py:230` 明确 `return ""`，深色才返回 QSS |
| 仓库已有 `get_dialog_style()`，按钮 36px | `style.py:767`；`min-width:100 / height:36` 在 `style.py:913-919` |
| 两窗口各 25 个 `QPushButton` | grep 计数：`dialog.py` 25，`workspace.py` 25 |
| Inspector 已经是 `QSplitter` 3:2 | `dialog.py:194`、`:276`；实测 `sizes=[695,477]` |
| 4 处硬编码浅色 | `dialog.py:1037-1039`（`#c0392b` / `#b9770e`）；`workspace.py:549`（`#22A06B`）、`:742`（`#EEF1F4`） |
| Dense 快捷键是 `ApplicationShortcut` | `workspace.py:1396`；实际序列 `Ctrl+Return` / `Alt+Return`（`:1361` 起） |
| 无 `minimumSize` / 几何持久化 | 两文件 grep `minimumSize/saveGeometry/restoreGeometry/setGeometry` 均为 0 |
| 筛选一变整表重建 | `dialog.py:368` 直连 `_populate_table` |
| 裸 `QMessageBox` / `QInputDialog` | `dialog.py:592`、`:470`；`get_msg_box_style()` 确实存在于 `style.py:93` 但未使用 |
| 两窗口标题 0 条翻译 | 4 个 `.ts` 中 `Annotation Inspector` / `Dense Annotation Review` 均为 0 条 |
| 无 qtbase 翻译 | `app.py:382` 只加载 `:/languages/translations/<lang>.qm` |
| 主题 token 缺失 | `theme.py` 中无 `#EAF4FE` / `#FFF4E0` / `#FDECEA` / `#EFEFF2` |
| Inspector 中文多数未包 `tr()` | AST：233 个中文字面量，仅 48 个在 `self.tr()` 内；Dense 为 113 / 112 |

#### 不成立或需改写

| 断言 | 实测 | 修正 |
| --- | --- | --- |
| 「Inspector 连 Esc 都没有」 | `QTest.keyClick(dialog, Esc)` 后 `isVisible()` 变 `False` | Esc 由 `QDialog` 原生支持；缺的是 F5 / Enter / Ctrl+F 这类业务快捷键 |
| 「12 个 QDialog 子类里有 6 个没接」 | 全仓 **56** 个 `QDialog` 子类，**19** 个界面文件引用 `get_dialog_style` | 改为「全仓 56 个子类，多数未接；这两个是其中之二」 |
| 「两窗口 0 图标」 | Inspector 0；Dense 6 处 `setIcon`，全部是卡片缩略图 | 操作按钮确实 0 图标，但不能说两个窗口「0 图标」 |
| 「`workspace.py:548` 有 1 处 `setStyleSheet`」 | `:548` 与 `:552` 两处，是同一 `if/else` | 改为 2 处 |
| 「10 字在 36px 按钮上一行放不下」 | 现按钮实测 728×24，10 字远未占满；高度不限制横向排版 | 不成立。只有把按钮压到 200px 以下才需要改文案 |
| 「150% 缩放字体放大后卡片文字溢出」 | Qt6 按逻辑像素统一缩放，字体与 `gridSize` 同比放大 | 不成立。只有用户自定义大字体或写死 px 字号才会溢出 |
| 「Enter 可能误触开始检查」 | 焦点在表格按 Enter，`report` 仍为 `None`；`start_button.isDefault()=False` | 未复现。`autoDefault=True` 属实，风险需限定「焦点在非按钮控件且未被消费」 |

#### 部分成立

- 「整行染色」：实现是逐单元格 `setForeground`（6 列都设），视觉效果等同整行，措辞可保留。
- 「QSS 画不了卡片」：`QListWidget::item` 能设统一边框/底色，但**按卡片动态**的色条与角标确实要走 `QStyledItemDelegate` 或画进 pixmap，需加这个限定。
- 「浅底选中与全局冲突」：全局 `QTableWidget::item:selected` 是实心主色（`style.py:941`），但它只在接入 `get_dialog_style()` 后生效——浅色现在根本没有 QSS，冲突是接入之后才出现。

#### 对 6.1 的核对

9 条全部成立（行号 `146 / 154 / 166 / 194 / 283` 与内容一致）。两处细节：
- 第 5 条引用的 `:181` 实际是表格下方说明行，搜索缺失的判断本身成立，行号应指向队列头（`:162-165`）。
- 第 7 条说与「§2.1 ASCII 的快捷键提示」冲突，但 ASCII 里并没有这一行——真实问题是多出了一条 36px 的底栏未计入垂直预算。
