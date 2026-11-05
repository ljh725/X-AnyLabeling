# CUSTOM-112～116：v4.3.0 五项画布能力的恢复

- 状态：已实现待验证（自动化通过；性能、真实屏幕与配置交错保存未完成）
- 功能分类：原功能修改 / 迁移能力恢复（不新增上游整版功能）
- 创建日期、最后更新日期：2026-11-04（Asia/Shanghai）
- 原始版本与基线提交：本地 4.2.1 定制基线 `67c98a80171318f6ced1070c49fc82b2120a22c9`；上游参考 v4.3.0 `74407f633b61a8ff6adc0e7eafbafa6856825759`
- 实现提交 / PR：未提交（沙箱禁止普通写 `.git`；bundle 与工作区保存点见 `backups/restore-v430-20261104*`）
- 工作区已有修改、前置依赖：Inspector、Dense Review、配置持久化、矩形编辑等先前未提交成果；恢复只叠加五项能力，不回退它们

编号说明：原迁移的五项能力曾计划分别占用 CUSTOM 编号，但分配记录随实现丢失；本次按现存最大编号续编 112～116，未覆盖旧台账。

| 编号 | 能力 | 主要落点 |
| --- | --- | --- |
| CUSTOM-112 | 可视化工具栏（八类显示开关、适应窗口/宽度、成组/解组、窄窗口横向浏览） | `label_widget.py` 动作与 `actions.tool`；`widgets/toolbar.py::ToolBarScrollArea` |
| CUSTOM-113 | 滚轮导航模式与手势优先级（direct/traditional、Ctrl 缩放、Alt 工具、Alt+Shift 对比） | `widgets/canvas.py::wheelEvent`、`interaction_in_progress`；`label_widget.py::apply_wheel_navigation_mode` 等；`config.py`、settings schema/runtime、默认 YAML |
| CUSTOM-114 | 画布面板三态图片审核入口 | `widgets/canvas_adjustment.py` 状态行与信号；`label_widget.py::set_annotation_checked`、`_sync_annotation_checked_state` |
| CUSTOM-115 | 仅填充透明度 | `shape.py::paint`；`widgets/canvas.py` 掩码/普通/预览填充路径 |
| CUSTOM-116 | 透明度/亮度/对比度跨图保持 | `widgets/canvas_adjustment.py` pin 按钮；`label_widget.py::_flush_pending_brightness_contrast`、`load_file` 保持策略 |

## 问题与目标

原迁移把八类显示开关、滚轮模式、三态审核、仅填充透明度和显示参数保持迁入本地 4.2.1 并完成过 P2 复验，但随后实现与专项测试从工作区丢失，历史任务仍显示已实施。恢复目标是：

- 用可核验本地 blob（`label_widget.py` `63aca7d7`、`canvas.py` `6adda41a`、保持测试 `ad4dcfbe`）与规格重建五项能力；
- 保留 Inspector、Dense Review、数字改类、本地矩形编辑、对象身份、锁定与共享视图；
- 不引入四种显示模式、MultiTask、OCR、测量、旋转或跳图步长改造；
- 透明度只作用于填充；滚轮键位按原迁移设计从 Ctrl 迁移到 Alt。

## 修改位置与方法

| 文件 / 函数 | 原行为 | 改后行为 | 迁移注意事项 |
| --- | --- | --- | --- |
| `shape.py::paint` | 无填充参数；画布用全局 painter opacity | 新增 `fill_opacity=1.0`，复制填充色并缩放 alpha；边框/顶点/文字不受影响 | 位置参数在 `painter` 之后、`outline_path` 为关键字；不得修改共享颜色 |
| `canvas.py::paintEvent` | `p.setOpacity(shape_opacity)` 整体变暗 | 移除全局 opacity；掩码 alpha 乘 `shape_opacity`，各 `shape.paint` 传入乘数 | 掩码、选中、创建预览各乘一次；标签仍需 `setOpacity(1.0)` 复位 |
| `canvas.py::wheelEvent` | Ctrl 调笔刷/矩形、Shift 调对比、Ctrl 吞掉缩放 | Alt 笔刷、Alt 矩形、Alt+Shift 对比、Ctrl 缩放、裸滚轮按模式 | 一次事件一个分支；保留 angle/pixel、零增量与无图保护 |
| `canvas.py::interaction_in_progress` | 无 | 汇总拖动/旋转/平移/拟合/拖边/橡皮/魔棒/绘制/四极值草稿 | 供模式切换延迟使用 |
| `canvas_adjustment.py` | 三滑块 + 重置 | 新增三态审核行、三个保持按钮；保留既有节流与重置 | 状态同步用 `clicked`，程序更新用 `set_status`，阻断回流 |
| `label_widget.py` | 无工具栏显示入口、无审核/保持同步 | 显示动作入工具栏并补图标；审核/保持与既有动作双向同步；跨图策略与模式延迟应用 | 复用 `set_annotation_checked`、keep 动作和共享视图，不另建状态 |
| `toolbar.py::ToolBarScrollArea` | 普通 `QScrollArea`，滚轮可穿透 | 横向滚动并消费滚轮事件 | 不得吞掉工具栏按钮点击 |
| `config.py` / YAML / settings | 无 `wheel_navigation_mode` | 默认 `direct`，无效值归一化回退，schema 与 runtime applier 接入 | 配置落盘仍由配置持久化事务负责 |

新增测试：`tests/test_canvas/test_fill_opacity.py`、`test_wheel_navigation.py`、`tests/test_config/test_wheel_navigation_config.py`、`tests/test_labeling/test_canvas_display_retention.py`（按 blob 恢复）、`test_review_status_panel.py`、`test_toolbar_display_actions.py`。四语言 `.ts` 新增 9 条文案并更新笔刷键位提示，由 `lrelease` 生成 `.qm`；源码运行按 `app.py` 磁盘优先加载，`resources.py` 未重生成。

## 兼容与数据影响

- 标注 JSON 格式不变；审核仍写顶层 `checked`（`false`/`true`/`"failed"`），不新增字段。
- 快捷键可见变化：笔刷半径由 Ctrl+滚轮改为 Alt+滚轮；对比分割由 Shift+滚轮改为 Alt+Shift+滚轮；Ctrl+滚轮统一缩放。工具提示与四语言翻译已同步。
- 透明度保持为会话状态，不落盘；亮度/对比度沿用既有 `keep_prev_*` 配置与单图缓存。
- 模式切换只改变滚动条策略与视图折算，不改变对象坐标、身份或撤销记录；传统模式按边界夹紧。
- 恢复不修改 Dense Review 的合并历史、异步代际与卡片节流，也不改 Inspector handoff。

## 验证

环境：Windows DSH 沙箱，Python 3.12（`x-anylabeling-cu12`），PyQt6 offscreen。

- 五项专项六模块：**52 passed**（98.71s），命令与逐项对照见 `openspec/changes/restore-v430-canvas-controls/verification.md`。
- 受影响回归：导航、分组、仅选中标签、矩形编辑迁移、审核状态、切图共 **203 passed / 1 failed**；失败项在 2026-11-03 基线副本同样失败，原因是环境缺失 Qt 字体目录，非本次改动。
- Inspector / Dense Review 选择性子集：**95 passed**（调框、数字改类、统一撤销/重做、保存重开与异步代际）。
- 翻译：`lrelease` 四语言编译成功，`QTranslator` 校验 zh_CN 5 条、其余语言各 2 条关键文案。
- 未执行：拖框/切图性能基准、真实屏幕/主题/系统缩放人工验收、与配置持久化的交错保存与重启联测；`resources.py` 未重生成，打包前需在兼容 rcc 环境重新编译资源。

## 迁移与回退

- 迁移顺序：先恢复 `Shape.paint` 与画布填充乘数，再恢复面板审核/保持控件，然后接入 `label_widget` 同步与工具栏动作，最后恢复滚轮模式、配置与视图折算。
- 上游变化时的适配点：`paintEvent` 的绘制顺序与新增绘制路径、滚轮事件消费分支、`load_file` 的跨图节点、settings schema 字段插入位置。
- 需保留的原行为：Inspector/Dense Review 历史与异步代际、矩形拖边/拟合/四极值、对象身份与锁定、仅选中标签、共享视图按尺寸分组。
- 按功能回退：CUSTOM-115 只撤 `shape.py` 的 `fill_opacity` 与画布乘数；CUSTOM-114 撤状态行与三处同步；CUSTOM-116 撤 pin 与跨图策略；CUSTOM-112 撤工具栏动作与 `ToolBarScrollArea`；CUSTOM-113 撤滚轮分支、配置键与 schema/runtime。共享文件按补丁回退，禁止整文件回滚。

## 后续修订

2026-11-05 代码实施：工具栏横向滚轮恢复原生方向；成组/解组改走现有字段编辑事务，避免关闭自动保存时重新载入丢失未保存数据，并保留锁定、撤销及身份；设置字段定位改为窗口持有的定时器，关闭后不再访问已销毁控件。新增真实交互、16 位图、原生窗口和独立进程重启验证；最终专项 127 通过，受影响回归 403 通过/1 项既有字体失败。性能和实际 Windows 系统缩放仍待完整验收。详见 `openspec/changes/restore-v430-canvas-controls/implementation-20261105.md`，不自动归档。

| 日期 | 原因 | 实际改动 / 提交 | 验证结果 |
| --- | --- | --- | --- |
| 2026-11-04 | 恢复丢失能力并补齐证据 | 未提交；实现与测试见 `openspec/changes/restore-v430-canvas-controls/` | 专项 52 通过；性能/人工/配置联测待完成 |
