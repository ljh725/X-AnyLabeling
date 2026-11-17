# CUSTOM-123：Inspector 双屏导航简化（问题队列 + F1／F2 + 保存并复查）

- 状态：已验证（代码与自动化有证据；6.3 实际双屏验收按用户 2026-11-17 人工实测声明通过，仓库内未附截图）
- 功能分类：原功能修改（Inspector 日常界面与导航收敛）
- 创建日期：2026-11-06；最后更新日期：2026-11-17（Asia/Shanghai）
- 原始版本与基线提交：X-AnyLabeling 4.2.1；变更起点 2026-11-06，实施产物入库于 `e4430b30`（2026-11-10）
- 实现提交：`e4421908`（持久化检查/复核与可见扫描进度）、`3ddee158`（数字键矩形类别修复与 Inspector 问题导航）、`e4430b30`（补齐变更产物）；本次归档只改文档
- 前置依赖：`refactor-data-inspector-workflow`（已归档，检查引擎/报告/反馈/桥接）、`polish-inspector-dense-review-ui`（主题与 UI 样式）

## 问题与目标

Inspector 原先能检查、定位和复查，但日常界面同时铺开阶段选择、历史、导入导出、外部候选与密集复核等高级入口，判定与高级操作混在一起；“上一个／下一个”只切换表格行，用户需要自己再去找对象。

用户 2026-11-06 确认主流程：**检查出不符合规则的数据 → 在原主画布修改或删除 → 保存复查 → 下一个问题**，并要求第二屏独立窗口与 F1／F2 导航。参考效果图：`openspec/changes/archive/2026-11-17-simplify-inspector-dual-screen-navigation/assets/inspector-dual-screen-approved.png`。

不在本项中：重写规则引擎、增加第二个图像查看器／缩略图／标注画布／主窗口停靠面板、操作系统全局热键、自动决定重复框中删哪个、直接写标注 JSON、改变正式审核字段、迁移报告格式。

## 修改位置与方法

| 文件 / 函数 | 原行为 | 改后行为 | 迁移注意事项 |
| --- | --- | --- | --- |
| `anylabeling/views/labeling/inspector/dialog.py` | 高级入口常驻；上一个／下一个只切行；保存与复查分离 | 日常区收敛为规则/范围、运行状态、问题列表、简短原因、对象下拉、单组导航、忽略、保存并复查；高级能力移入“更多”；导航统一入口；保存成功后用报告冻结方案复查 | 约 2797–2880 行是快捷键绑定与回调；`_reconcile_candidate_intents` 有既有 C901（25），未改动 |
| `anylabeling/views/labeling/inspector/controller.py` | — | 问题稳定键游标、跨分页队列、三态投影、导航锚点 | 以稳定键而非行号作游标 |
| `anylabeling/views/labeling/label_widget.py` | 主窗口无 Inspector 问题导航 | 桥接 `inspection_navigate_to()`：切图 + 按稳定对象身份选中/聚焦；F1／F2 以窗口作用域接入同一回调（约 5586 行附近） | 跨图前校验目标图片与对象身份；取消/加载失败恢复原文件、选择、形状历史与编辑状态 |
| `anylabeling/configs/xanylabeling_config.yaml`（241 行附近） | 无 | 新增 `inspector_previous_issue: F1`、`inspector_next_issue: F2` | 与既有普通切图键区分；不覆盖用户自定义绑定 |
| `anylabeling/views/labeling/settings/schema.py`（555 行附近）、`settings/runtime_applier.py` | — | 两个键接入冲突检测、改键、清空、持久化与运行时生效；按钮提示反映实际绑定 | 设置字段计数由 147/90 变为 149/92，已同步断言 |
| `docs/zh_cn/inspector.md`、四语言 `.ts`／`.qm`、内嵌 Qt 资源 | — | 中文操作说明与中英日韩文案 | 需重跑 `scripts/compile_languages.py`；未扩大旧目录完备性声明 |

要点：

- 三类视图是**既有状态的投影**，不新增第二套完成状态。优先级：失效/待复查/过期 → 有效已解决 → 有效已忽略 → 其余待处理。人工“确认错误/标记修改”不算解决。
- “忽略此问题”写入既有可接受判断，不改正式审核状态。
- 导航一次按键只切一次；首尾不循环；仅在无选中且无有效锚点时 F2 进首项、F1 进末项。
- “通过后进入下一个问题”默认开启、可持久化；只有复查完整通过且报告与反馈均写盘成功才推进。

## 兼容与数据影响

- 标注 JSON 格式不变；不写入检查事件；不修改图片正式审核字段。
- 检查报告/反馈文件格式沿用旧变更；“保存并复查”复用报告内冻结的规则快照。
- 窗口几何与自动推进偏好走已有本地配置；第二屏拔除后回到当前可见屏幕。
- 快捷键为窗口作用域，非系统全局热键；关闭 Inspector 后会话快捷键停用。

## 验证

代码与自动化（2026-11-06 实施轮，`C:/Users/20441/.conda/envs/x-anylabeling-cu12/python.exe`，Python 3.12 / PyQt6，`QT_QPA_PLATFORM=offscreen`，全部在 `.tmp/` 隔离）：

| 范围 | 实际结果 | 证据 |
| --- | --- | --- |
| 完整 Inspector 与设置首轮 | 300 passed、1 skipped、4 failed（后确认为字段计数与按钮常驻的预期变化，已更新） | `automated-tests.xml` |
| 第二轮 | 307 passed、1 failed、9 subtests | `automated-tests-final.xml` |
| 图片切换/编辑范围/锁定/拖动/稳定身份/UI+schema | 68 passed、16 subtests | `related-tests.xml` |
| 导航、规则入口与翻译 UI | 27 passed | `final-ui-tests.xml` |
| 最终完整 Inspector 与设置 | 308 passed、9 subtests | `delivery-tests.xml` |
| 活动窗口守卫定向导航 | 19 passed | `session-guard-tests.xml` |
| `openspec validate ... --strict` | 通过 | — |
| flake8 | 修改文件（排除两项既有 C901）通过 | — |

人工验收：

- 2026-11-07 原生双屏尝试：检测到 Q27G2S 2560×1440 + 2490W1 1920×1080，独立验收实例启动成功；但 Computer Use 截图与点击通道超时（`FrameArrived timed out`、`coordinate input geometry is unavailable`），**未记为通过**。证据：`assets/native-startup-state-20261107.json`。
- 现有“实现后截图”为离屏合成渲染，不是双屏证据（`assets/offscreen-screens.json` 显示离屏只有 800×800 单屏）。
- 2026-11-17 用户声明“已经通过人工验证 勾选通过”，据此关闭任务 6.3 并归档。**仓库内没有对应的双屏截图或逐条操作记录**，此项为人工实测声明，不是可复现证据。

未覆盖：完整 `tests/test_labeling`、`tests/test_canvas` 全量；Windows 点云；其他语言的旧翻译完备性。

## 迁移与回退

- 归档位置：`openspec/changes/archive/2026-11-17-simplify-inspector-dual-screen-navigation/`（含 proposal、design、两份规格、tasks、verification、JUnit 与截图）。
- 主规格：`openspec/specs/inspector-focused-review/`、`openspec/specs/inspection-result-navigation/`（`openspec archive` 自动写入，14 条 ADDED）。
- 回退：移除两个快捷键绑定与主窗口桥接、把 Inspector 默认界面恢复为展开式布局；保留已生成的检查报告/反馈文件与用户已保存标注，不逆向修改标注数据。不删除本变更的归档目录。
- 上游变化时的适配点：`inspection_navigate_to()` 的取消/失败恢复路径、`SettingsRuntimeApplier` 的字段计数断言、四语言资源生成。

## 后续修订

| 日期 | 原因 | 实际改动 / 提交 | 验证结果 |
| --- | --- | --- | --- |
| 2026-11-06 | 建立变更与规格 | 提出双层导航、双屏独立窗口、保存并复查规格 | 仅为规划，任务全部未完成 |
| 2026-11-10 | 纳入版本控制 | `e4430b30` 归档旧 Inspector 变更并入库本变更产物（25/26） | 沿用 2026-11-06 测试证据，未重跑 |
| 2026-11-17 | 用户宣布人工验收通过并要求归档 | 勾选 6.3，`openspec archive simplify-inspector-dual-screen-navigation --yes` 退出码 0 | 归档 26/26；两份规格同步主规格；未新增截图 |
