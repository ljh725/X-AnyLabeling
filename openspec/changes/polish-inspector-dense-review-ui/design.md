## 背景

P0 已把两个窗口接入 `get_dialog_style() + get_workbench_qss()`，并把主区域
让给队列/卡片。P2 只处理遗留的四类细节，前提是**不引入第三套样式系统**、
**不改服务层状态机**。

## 决策

### 1. 查漏网格用自绘 `QWidget`，不用 `QListWidget` IconMode

`CoveragePlan` 已给出 `columns / rows / overlap / image_width / image_height`
与每个区域的 `rect`。用 `QPainter` 直接按「区域 rect → 控件矩形」等比映射绘制：

- 填充色：已完成 `theme["success"]`、疑难 `theme["warning"]`、暂跳
  `theme["primary"]`、待查 `theme["surface"]`；边框 `theme["border"]`，
  当前区域 2px `theme["primary"]` 描边。
- 命中测试按区域 rect 反算，重叠区域取「行优先、后绘制者优先」的最后一个，
  与列表顺序一致；不引入新的选择语义。
- 点击只发 `region_clicked(region_id)`，由 `workspace` 复用现有
  `_select_region_by_id()` → `set_current_region()` + host 定位，避免两套状态。
- 无 `plan` 时控件画空状态文案（`tr("尚无区域计划")`），不留在空白矩形。

不选 `QListWidget(IconMode)`：网格需要按图像宽高比等比而非固定 `gridSize`，
且重叠区域必须按几何反算；用 `QListView` + delegate 反而要自己处理布局，
比自绘多一层。

### 2. 详情分节仍用 `QTextBrowser`，只重写 HTML 结构

`details` 是 `QTextBrowser`，现有选中/滚动/链接行为都在它上面。P2 不改控件，
只把 `_show_selected_details()` 的输出改为带 `section` 头的分节 HTML：

- 每节：11px `text_secondary` 小标题 + 正文；节间 1px `border` 分隔线。
- 颜色全部从 `get_theme()` 取，删除 `#86868b` 等硬编码。
- 证据指标改为两列小表（指标名 / 值），不再用 `key=value · …` 拼串。
- 空证据显示「本轮没有证据项」，不省略整节。

不选「用 QWidget 卡片重做详情」：会破坏现有 `setHtml` 的复制/选择行为，
也超出 P2 范围。

### 3. 快捷键作用域

- Dense 的 `QShortcut` 由 `ApplicationShortcut` 改为 `WindowShortcut`：窗口
  非激活时不再抢 `Alt+Return / Alt+N / Alt+X`。
- Inspector 新增 `F5`（开始检查）、`Enter`（定位选中行，仅焦点在表格时）、
  `Ctrl+F`（聚焦筛选搜索）。`Esc` 由 `QDialog` 原生支持，不重复注册。
- 所有提示文案引用真实绑定：`Ctrl+Return` 完成本批、`Alt+Return` 完成对象。
  设置页已有的 6 项快捷键配置保持不变。

### 4. 本地化边界

只包「用户可见的界面文案」：`QLabel / QPushButton / QCheckBox / 标题 /
占位符 / tooltip / 状态行 / QMessageBox 文本`。以下保持原样：

- 配置键、快捷键键名、枚举值（`completed` / `difficult` 等）；
- 数据文件字段、JSON 键、`tr()` 之外用于 `assert` 或字典查找的字符串；
- 日志与异常内部信息（不影响界面）。

用 `pylupdate6` 重生成四套 `.ts`，用 `lrelease` 编译 `.qm`。qtbase 标准按钮
翻译不在本次范围（需要额外 `.qm` 资源，单独立项）。

### 5. 图标

只给主/常用操作加图标（开始检查、完成本批、完成对象、定位），用现有
`new_icon_path()`，不新增图标资源；次要按钮保持纯文字，避免图标噪音。

## 风险

| 风险 | 处置 |
| --- | --- |
| 网格点击与列表选中互相触发递归 | 复用 `_updating` 门控；点击只调 `set_current_region` 一次 |
| 详情重排导致既有测试断言 HTML 片段 | 先查 `tests/test_inspection` 是否断言详情文本，必要时只改样式不改语义 |
| `tr()` 包裹改变运行时字符串，影响按文本断言的测试 | 同步更新测试中的期望文案；断言状态值的地方不动 |
| `.ts` 重生成带入无关差异 | 只提交本次新增/变更的 message，逐语言核对 diff |
| 图标在深色背景不可见 | 用主题色 pixmap 或现有彩色图标，截图核对 |
