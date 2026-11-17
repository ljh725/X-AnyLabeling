# 实施任务勾选同步 · 2026-11-17

依据当前已保存实现、逐项源码核对及既有验证证据，将 `redesign-dense-review-workspace` 从 **25/91 调整为 30/91 已勾选，61 项保留未勾选**。新增勾选 1.5、9.1、13.7、15.3、15.5；没有改写条目要求、拆小分母或把部分实现当成整条完成。未勾选不等于完全没有代码。

核对起点为 `1c148da520eac71214a5a2c28727ae8e8a03fa33`，工作分支仍为 `codex/4.2.1/dense-review-redesign-plan`。源码实现见 `5d2d3002`、`a4efb042`；[独立复核](FIX_VALIDATION.md)记录了十四项原复现、密集复核 282 passed / 698 subtests、受影响画布 286 passed / 6 subtests。此次仅同步文档，不改代码，不重复运行相同 GUI 回归。

## 新增勾选及依据

| 任务 | 完成依据 | 提交 / 验证 |
| --- | --- | --- |
| 1.5 接入位置盘点 | 下节已列出显隐写入、绘制、标签、命中、快捷键、保存撤销、mask/属性/组连线、点拟合及 Inspector 的实际入口；盘点完成不表示其中所有接入工作完成 | 本报告源码盘点；路径与函数已核对 |
| 9.1 dock 与单画布 | 正常菜单默认右侧停靠，浮动/再次停靠与重复打开保持同一画布和会话，关闭重开保留进度；此次修复还验证浮动/停靠不改变持续原图模式和当前对象 | `5d2d3002`、`a4efb042`；`test_workspace_dock_tasks.py` 的菜单、重复打开、浮动/停靠用例，`test_workspace_review_fixes.py::test_float_keeps_original_display_mode`；均包含在 [282 项通过记录](validation-dense.txt) |
| 13.7 检查与未覆盖项记录 | 已运行相关格式、静态、链接及 OpenSpec strict 检查；翻译产物与编译入口已核对，磁盘/嵌入资源一致性有测试；工具栏布局和 Windows 点云明确记为未运行 | [实现报告](FIX_IMPLEMENTATION.md)、[独立复核](FIX_VALIDATION.md)；Black 通过，flake8 的 11 项既有告警与快照逐项一致；本次再次检查 OpenSpec、链接和 diff；不宣称 flake8 零告警 |
| 15.3 分批本地保存与台账 | 截至当前已实施批次均有本地保存；前轮依赖先保存，再单独提交 F1–F4，独立复核只提交文档；功能说明、操作台账和暂存范围核对均有记录 | `5d2d3002` 依赖保存、`a4efb042` 修复、`1c148da5` 独立复核；后续新批次仍须继续执行本条规则 |
| 15.5 当前阶段交付状态 | 已汇总当前本地实现、验证和未决项；集成目标已重新核对；没有推送/合入授权，按条目明确允许的本地交付路径记录 | 当前 HEAD `1c148da5`；本地目标 `codex/4.2.1-baseline-organization` 为 `a7a9a1048f2eab1e3a0272cd57b5c400becca970`；未推送、未开 PR、未合入；本报告保留所有未决任务 |

15.3、15.5 是已实施批次的提交和当前阶段交付记录，勾选不构成整个变更发布完成，也不免除后续批次继续执行相同要求。

## 任务 1.5 接入位置盘点

以下路径相对仓库根目录。只列当前真实入口，并保留尚未完整接入的边界。

| 范围 | 实际位置 / 入口 | 当前边界 |
| --- | --- | --- |
| 用户显隐写入 | `label_widget.py::_sync_label_list_visibility`、`_apply_shape_filter_visibility`、`toggle_visibility_shapes`、`_manually_hidden_shapes`；`shape_filter.py::desired_visibility` | 全局开关、手动隐藏、过滤与临时例外分开计算；任务 3.4/3.6 的完整缓存和范围组合仍待闭环 |
| 显示解析与安装 | `services/dense_review/display.py::resolve_all/_resolve`；`label_widget.py::dense_review_display_context/refresh_dense_review_display`；`canvas.py::set_dense_review_display` | 当前角色、绘制与命中同源；查漏 point 全组件清零由 `a4efb042` 修复 |
| 主画布、mask 与图形组件 | `canvas.py::paintEvent` 的 mask 路径；`Shape.paint/_paint_with_display_style`、`Canvas.dense_review_paint_sequence` | 普通画布与复核覆盖层分支；深浅背景、高 DPI 与完整像素证据仍属 4.6 |
| 标签、底板、引线及角度/属性 | `canvas.py::_overlay_visible`、`_dense_review_label_strength`、`_dense_review_attribute_strength` 及 `paintEvent` 的标签、degrees、attributes 绘制循环 | 标签避让、缓存、四语言可读性尚不完整，保留 6.2/6.3/6.5 |
| 组连线与组命中 | `canvas.py::_paint_groups`、`_group_visible_shapes`、`_group_editable_shapes`、`_dense_review_linking_strength`、`group_move_targets` | 已有有效成员过滤和锁定回归；不替代所有组合操作验收 |
| 普通命中与拖动目标 | `canvas.py::_shape_hit_candidates`、`dense_review_hittable`、`mouseMoveEvent` | 当前边/手柄优先；重叠候选选择 UI 尚属 5.3 |
| 快捷键与几何命令 | `canvas.py::keyPressEvent/move_by_keyboard/rotate_by_keyboard`；`workspace.py::_install_shortcuts`；`label_widget.py::existing_shortcut_sequences` | 当前 dock 作用域不能替代主窗口/浮动面板、输入框、模态、忙碌状态的全部要求，保留 9.5/12.3 |
| 原图对照和生命周期 | `label_widget.py::dense_review_set_display_mode/dense_review_begin_hold_original/dense_review_end_hold_on_blur/dense_review_workspace_closed`；`workspace.py::showEvent/hideEvent/_release_hidden_review_view/closeEvent/shutdown` | 真正 hide/close 与浮动临时 hide/show 已区分；取消切图与资源释放全链仍保留 9.6 |
| 点拟合与拖边预览 | `widgets/point_fit.py::_point_fit_lock_move/_point_fit_commit/_point_fit_cancel_round`；`widgets/rectangle_edge.py::_rectangle_edge_drag_move/_rectangle_edge_cancel`；`canvas.py::suspend_active_editing` | 已有暂停/收尾回归，完整提交、取消及退出组合仍保留 4.5/5.5 |
| 内容/进度保存与外部冲突 | `label_widget.py::_save_file/_dense_review_resolve_conflict`、`label_file.py` 原子写入；`services/dense_review/storage.py` 与 `session.py` 的签名/进度序列化 | 已有保存失败、外部冲突、旧进度测试；不视为 11.6/11.7 全分支已验证 |
| 撤销与重做 | `label_widget.py::undo_shape_edit/redo_shape_edit`；`services/dense_review/session.py` 与 `editing_commands.py` 的历史入口 | 进度与内容历史已有回归；删除关联对象、区域重建与派生卡片完整顺序仍保留 11.5 |
| Inspector 交接 | `label_widget.py::inspection_navigate_to` 及相关 inspection 接受入口 | 当前已有普通检测导航；跨批次双对象、关联点/无框区域与过期请求的完整复核上下文仍属 11.8，不因盘点而宣称已接入 |

上述 `label_widget.py`、`canvas.py`、`shape.py`、`shape_filter.py`、`label_file.py`、`editing_commands.py` 均位于 `anylabeling/views/labeling/`；`canvas.py` 位于其 `widgets/` 子目录，`workspace.py` 位于其 `dense_review/` 子目录。

## 全部保留未勾选项及缺口

本表覆盖当前全部 61 项未勾选任务。缺口表示整条要求尚未形成充分闭环，不把已有部分实现抹掉；没有执行新的功能补齐工作。

| 任务 | 保留原因 |
| --- | --- |
| 1.3 | 未有指定样本副本中四项旧问题的完整真实入口复现记录 |
| 1.4 | 样本及合成测试已有部分覆盖，尚无覆盖该条所有样本类型的完整可复现清单 |
| 2.2 | 现有“session switch”测试只构造空状态/检查 missing 路径不存在，并未实际执行失败加载；失败、重试、重开、切图和无效动作仍缺整体验证 |
| 3.4 | 有多处失效重建，尚无完整缓存失效和鼠标移动成本闭环 |
| 3.6 | 稳定成员已有测试，原图/零强度/折叠与确认范围全组合仍缺证据 |
| 4.5 | 预览暂停和退出已有回归，所有预览类型的提交/取消/退出复核组合未完整覆盖 |
| 4.6 | 深浅背景、重叠、点和高 DPI 的整组图像与差异证据未齐 |
| 5.3 | 重叠候选选择界面尚未实现 |
| 5.5 | 锁定/隐藏/点拟合等部分通过；Ctrl 多选、数字改类、微调、撤销的完整复核组合仍待核对 |
| 6.2 | 框外有限锚点、避让、引线和编号回退尚未完成 |
| 6.3 | 标签布局缓存与拖动冻结未完成 |
| 6.5 | 长中文及日韩文、焦点/手柄的可读性与 M2 人工证据未齐 |
| 7.3 | 人物主卡与展开子点的完整 UI 同步未完成 |
| 7.4 | 稳定批次和改组已有服务回归，派生人物卡在所有增删复制/撤销场景中的同步未完成 |
| 8.2 | 高度独立/重排列数已验证；宽度限制提示和主画布查看入口仍缺 |
| 8.3 | 矩形及关联点并集裁切、框外点提示/主体与逐点定位未完成 |
| 8.4 | DPR/尺寸缓存键和比较窗口已有实现；仍需比较窗口在几何、尺寸和上下文变化后的当前版本完整验证；旧“比较窗口未实现”表述已更正 |
| 8.5 | 虚拟化和部分容量有限，源图/图块/图形资源/在途/结果队列各自预算及合并请求全要求未齐 |
| 8.6 | 切图/改目录丢弃旧结果已有回归；尺寸变化、真正关闭后结果更新停止及拖动延迟全生命周期未闭环 |
| 8.7 | 冷缓存比较、失败、重试及关闭窗口已有测试；失败对象重试期间及成功后按当前范围恢复确认候选的边界未充分验证，不能仅凭图块显示成功勾选 |
| 8.8 | 快速滚动/尺寸/淘汰全组合和冷暖缓存实测数据未齐 |
| 9.2 | 三任务、目标及视口恢复已实现并验证；编辑中切换、取消后保留原对象/视口/待提交内容的全部 WL-08 分支仍缺证据 |
| 9.3 | 收起批次/卡片已有测试，窄窗口完整类名读取、审核范围及全部主要动作可达性未全验证 |
| 9.4 | 布局与任务偏好持久化、屏幕移除/DPI 恢复尚未完成 |
| 9.5 | 当前快捷键为 dock 子控件作用域，主画布/浮动面板与输入/模态/忙碌全要求未完成 |
| 9.6 | hide/close/浮动/重开已修复；取消切图、加载失败、主窗口退出和后台/比较资源的全链证据未齐 |
| 10.1 | 原图小地图尚未实现，现有 CoverageGrid 不等于原图小地图 |
| 10.2 | 普通网格/列表已有导航，缺原图小地图及共用导航的完整联动 |
| 10.3 | 查漏淡矩形/原图预设和刷新不移动已验证；切区保留用户参数、全图/对象往返的全部区域及策略恢复证据未齐 |
| 10.4 | 已有默认计划和空图覆盖，窗口/DPI 变化保留原计划身份的完整证据未齐 |
| 10.5 | 重建确认已有入口，网格设置收纳、取消时视口保持及重建撤销完整要求未齐 |
| 10.6 | 区域状态部分已实现，全部完成后任一区域复看及平移缩放组合未完整验证 |
| 10.7 | 服务层旧新范围和外部变更失效已有测试，所有真实入口及补框后仍待审的整条证据未齐 |
| 10.8 | 保存重开区域已有测试，混合图框/点/查漏分项状态与实际视口恢复全要求未齐 |
| 11.2 | 候选/排除/屏外计数与成员入口已有实现，策略收起及各排除来源呈现的完整验证未齐 |
| 11.3 | 维度/稳定成员/指纹/幂等/撤销已有服务测试，界面已展示范围在新增或外部刷新后需重新明确确认的全链证据未齐 |
| 11.4 | 矩形失效及改组已有测试，点编辑的关联裁切和保守覆盖失效未完整接入/验证 |
| 11.5 | 内容与进度撤销已有测试，删除关联对象、区域重建与卡片目标完整顺序未齐 |
| 11.6 | 旧 v1、版本拒绝、图像/输出隔离等已有测试；缺失/重复身份、未知扩展和混合卡片布局的所有分支未形成完整证据 |
| 11.7 | 冲突、失败保存、自动保存已有测试；取消切图测试未充分断言实际取消发生、当前位置/视口及 dirty 全部保留 |
| 11.8 | Inspector 完整上下文交接尚未完成 |
| 11.9 | 混合形状待支持已有逻辑，分项状态和 Inspector/正式验收互不影响的完整 UI 证据未齐 |
| 12.1 | 新偏好的默认配置/schema/runtime 接入和重启恢复未完成 |
| 12.2 | 配置写保护持续保留，新偏好保存失败时的视图和提示验证仍缺 |
| 12.3 | 完整快捷键设置、冲突及真实生效提示未完成 |
| 12.4 | 四语言已编译且磁盘/嵌入一致性通过；`label_widget.py::dense_review_refresh_coverage_region/dense_review_show_coverage_region` 的“查漏区域”仍为硬编码，不能将整条四语言完成勾选 |
| 12.5 | 无障碍名称已有部分接入；焦点/Tab/长类名/窄窗/高缩放完整验证未齐 |
| 13.1 | DP 自动化已有大量测试，标签避让和相关预览场景尚未实现，不能宣称 DP-01–18 全覆盖 |
| 13.2 | 菜单/dock/切换已有回归，快捷键、设置恢复及资源全生命周期仍缺 |
| 13.3 | 群组/尺寸/DPI/异步部分有测试，关联裁切和所有 OC 场景未完成 |
| 13.4 | 小地图及全部 SN 场景未齐 |
| 13.5 | 编辑/保存/撤销已有回归，Inspector 交接与全部 PC 场景未齐 |
| 13.6 | 密集复核已全过，完整画布有已知原生退出和测试桩失败，标注/设置/Inspector 目录未全部运行 |
| 14.1 | 同机同样本三轮冷暖性能及 GUI/拖动延迟测量未执行 |
| 14.2 | 300 框/1000 点和各资源预算的峰值/稳定阶段完整实测未执行 |
| 14.3 | M1–M4 真实屏幕验收未执行 |
| 14.4 | M5–M8、双屏/DPI/四语言真实操作验收未执行 |
| 14.5 | 两位用户各两轮质量与减负试用未执行 |
| 15.1 | 实际操作说明和真实截图未齐 |
| 15.2 | 全部 86 个规格场景到 node ID/人工证据的逐项结果映射未完成 |
| 15.4 | 定向回退、依赖及测试副本重开演练未执行 |

## 检查与交付

本次核对任务总数不变、勾选集合只增加上述五项、保留项 ID 与所有未勾选项完全相等，并检查新增链接、OpenSpec strict、diff 空白和暂存范围。本轮不更改源码、测试、生成资源，也不标记人工验收完成。

本地提交采用现有中文 docs 格式，并同步 CUSTOM-121 索引与操作台账。没有推送、PR 或合入授权，本轮交付止于本地提交；集成目标沿用 `codex/4.2.1-baseline-organization`。
