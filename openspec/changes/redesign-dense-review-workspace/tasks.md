# 密集复核工作区重设计任务清单

状态为实施中（2026-11-17），当前 **33/91 项已勾选，58 项未勾选**。已勾选项表示有对应实现或文档工作及验证证据，详见 [PROGRESS.md](../../../reports/dense_review_redesign/2026-11-16/PROGRESS.md)、[最新独立复核](../../../reports/dense_review_redesign/2026-11-17/FIX_VALIDATION.md) 和 [逐项勾选核对](../../../reports/dense_review_redesign/2026-11-17/TASK_STATUS_SYNC.md)。未勾选项表示整条尚未闭环，可能已有部分实现；提案和文档校验不能代替功能验收。过程条款 15.3、15.5 按截至当前已实施批次登记，后续批次仍须继续执行，整个变更未完成。

依据为 [设计](design.md) 和五份 [显示](specs/dense-review-display-policy/spec.md)、[布局](specs/dense-review-workbench-layout/spec.md)、[卡片](specs/dense-review-object-cards/spec.md)、[查漏](specs/dense-review-spatial-navigation/spec.md)、[进度](specs/dense-review-progress-compatibility/spec.md) 规格。场景 ID、测试方法和人工步骤见 [验收矩阵](acceptance.md)。

每项完成时记录实际修改、对应提交、验证命令和结果。规格新增的回归使用最小必要测试，已有测试能证明的行为优先复用。一个任务组可分多个独立提交，存在调用依赖时按下表连接。

| 阶段 | 任务组 | 主要依赖 | 可检查的结果 |
| --- | --- | --- | --- |
| 基线与可用性 | 1–2 | 当前代码和正常入口 | 可重现问题及可操作列表 |
| 显示与交互 | 3–6 | 1，4依赖3，5依赖3–4，6依赖3–5 | 分层显示、标签、编辑目标一致 |
| 对象卡 | 7–8 | 1–3，8依赖7 | 准确关联、可调大卡片和有界图块 |
| 工作区与查漏 | 9–10 | 2–8，10依赖9 | 可停靠面板及原图区域检查 |
| 状态与设置 | 11–12 | 3–10 | 可信确认、保存撤销、交接与配置 |
| 验证与交付 | 13–15 | 相关实现组 | 场景证据、性能、人工结果和回退记录 |

## 1. 实施基线与样本

- [x] 1.1 分支、HEAD、工作区与集成目标已核对（`reports/dense_review_redesign/2026-11-16/PROGRESS.md`）
- [x] 1.2 环境与基线退出码已记录，写保护 guard 保留
- [x] 1.3 基线 `052239f2` 的私有样本副本与真实菜单动作已复现：有效会话三列表仍禁用、滚轮 0→0、图块 108/行高 176、独立窗口与画布重叠 1154×864；动作、样本哈希与控件状态见 [BASELINE_AND_SESSION.md](../../../reports/dense_review_redesign/2026-11-17/BASELINE_AND_SESSION.md)（WL-05、OC-16）。
- [x] 1.4 `216e903f`；确定性样本清单覆盖 s1274 的 6 框92点、30框多类别、300框、1000点、空图、遮挡小目标、长类名、孤立点、group 0、同组多框、离群点和混合不支持形状；私有样本仅在 `.tmp` 副本使用，公共样本由 `test_samples.py` 9 项测试验证，清单见 [BASELINE_AND_SESSION.md](../../../reports/dense_review_redesign/2026-11-17/BASELINE_AND_SESSION.md)。
- [x] 1.5 盘点显隐写入、绘制、标签、命中、快捷键、保存和撤销入口，覆盖 mask、属性、组连线、点拟合预览与 Inspector 交接；在验证记录中列明接入位置。接入盘点及未完成边界见 [TASK_STATUS_SYNC.md](../../../reports/dense_review_redesign/2026-11-17/TASK_STATUS_SYNC.md) 的任务 1.5 位置表；盘点完成不代表所有接入工作完成。
- [x] 1.6 已建立 `reports/dense_review_redesign/2026-11-16/PROGRESS.md`，场景与测试对应关系见该记录；CUSTOM-110 原状态未改

## 2. 列表与会话启用修复

- [x] 2.1 `bf75b13f`；`test_workspace_lists.py::test_empty_state_then_session_enables_all_lists`
- [x] 2.2 `216e903f`；失败加载清空旧批次/卡片/区域并使旧图块代际失效，无效会话导航受保护；重试、关闭重开及切图恢复正确列表和目标。`test_workspace_lists.py::test_failed_load_retry_reopen_and_image_switch_restore_session`；组合回归 28 passed（WL-06）。
- [x] 2.3 `bf75b13f`；`test_workspace_lists.py::test_wheel_and_scrollbar_move_view_without_moving_target`
- [x] 2.4 `bf75b13f`；`test_workspace_lists.py::test_background_refresh_does_not_force_scroll_back`

## 3. 有效显示状态与优先级

- [x] 3.1 `3b09eefd`；`test_display_policy.py`
- [x] 3.2 `3b09eefd`；`test_display_policy.py` 优先级用例
- [x] 3.3 `05b1a26b`：排除原因可读（`dense_review_exclusion_reason`）；临时显示/结束动作经面板入口接入；单框与全部手动隐藏保持 `manual-hidden` 并可临时显示，真实全局关闭与对照仍优先；显现保留原隐藏记录与批次排除资格（`test_display_consistency.py::test_single_manual_hide_is_not_a_global_shutdown`、`test_hiding_every_object_by_hand_is_not_a_global_shutdown`、`test_real_global_switch_beats_temporary_show`、`test_original_mode_outranks_temporary_show_reason`）
- [ ] 3.4 使显示解析响应实际选择、内容变更、偏好变更和过滤变更，建立准确缓存失效，避免每次鼠标移动扫描或重建全部对象状态。
- [x] 3.5 `4af3c92f` + `47c7018d`：关闭后改显隐/过滤保持普通画布，重开恢复同一会话；`test_display_consistency.py::test_closed_workspace_keeps_regular_canvas_after_visibility_edit`（DP-17、WL-12）
- [ ] 3.6 核对类别变更后角色按稳定批次成员继续计算，临时原图、强度为零和布局折叠各自保留原确认范围，满足 PC-01、PC-05。

## 4. 分层绘制与组件弱化

- [x] 4.1 `96e93981`；`test_canvas_display_overlay.py`、`test_display_policy.py` 角色分级
- [x] 4.2 `96e93981`；`test_canvas_display_overlay.py::test_handles_follow_role_while_formal_points_stay`
- [x] 4.3 `96e93981`；`test_canvas_display_overlay.py::test_zero_strength_role_paints_nothing`
- [x] 4.4 `96e93981` + `7d9a27b3`：`test_canvas_display_overlay.py`、`test_display_consistency.py::test_current_object_paints_last_without_reordering_data`；绘制按其他→本批→当前对象，保存顺序不变（DP-08）
- [ ] 4.5 接入单点拟合、拖边、创建草稿、旋转手柄与选择预览的原有显示约束，验证提交、取消和退出复核后的状态，满足 DP-16。
- [ ] 4.6 用像素、几何和真实主画布回归验证深浅背景、重叠框、关键点和高 DPI；保存正确图与失败差异作为本组证据。

## 5. 鼠标命中与当前编辑对象

- [x] 5.1 `96e93981`；`test_canvas_display_overlay.py::test_installed_overlay_gates_paint_and_hit_together`
- [x] 5.2 `4af3c92f`；`test_display_consistency.py::test_current_object_edges_and_handles_win_over_a_keypoint`
- [ ] 5.3 提供重叠候选选择，列出编号、类名和形状类型；鼠标或键盘明确选择后同步当前目标，取消选择保持原状态。
- [x] 5.4 `4af3c92f`；`test_display_consistency.py::test_dragging_keeps_its_start_target`
- [ ] 5.5 回归锁定、手动隐藏、Ctrl多选、数字改类、Shift单点拟合、方向微调及撤销，验证编辑命令只作用于明确对象，记录差异及其归属。

## 6. 类别文字与原图对照

- [x] 6.1 `26fed309`；`test_display_text_and_original.py::test_review_label_policy_overrides_ordinary_switch`、`test_review_never_writes_back_the_ordinary_label_settings`
- [ ] 6.2 实现有限框外锚点避让和短引线，碰撞包括已放置文字与当前编辑手柄；空间不足时显示编号并映射侧栏完整名称，支持准确定位。
- [ ] 6.3 标签布局按字体、DPI、文本和视口缓存，拖动时固定锚点，结束后重新排布；验证缩放后文字屏幕尺寸及对象身份稳定，满足 DP-06。
- [x] 6.4 `26fed309` + `47c7018d` + `05b1a26b`：原图对照暂停命中与几何修改；工具栏「按住看原图」真实按键进入，松开/失焦/关闭/切图恢复（`test_display_text_and_original.py::test_hold_original_button_press_and_release`、`test_hold_original_button_ends_on_blur_close_and_image_switch`）；原图模式下标签/底板/引线/属性/遮罩停止绘制（`test_display_text_and_original.py::test_original_mode_renders_without_annotation_labels`）（DP-13、DP-14、DP-15）
- [ ] 6.5 验证当前对象、本批标签回退、关联点名称、长中文及日/韩文本、手柄和键盘焦点；将文字可读性人工步骤加入 M2。

## 7. 矩形卡与关联点导航

- [x] 7.1 `96e93981`；`test_workspace_mixed_shapes.py::test_group_zero_associates_points_with_its_only_rectangle`
- [x] 7.2 `96e93981`；`test_workspace_mixed_shapes.py::test_ambiguous_group_does_not_guess_an_owner`、`test_ungrouped_point_is_not_associated` 同文件
- [ ] 7.3 子对象展开、点选和主卡选择共同同步面板、当前编辑目标与主画布，子点选择保留人物上下文，满足 OC-13。
- [ ] 7.4 跨类修改保持矩形卡位置和原批次，新建、复制、删除、改组与撤销更新卡片、关联及计数，满足 OC-05、OC-06、PC-09、PC-13。
- [x] 7.5 `96e93981`；`test_workspace_mixed_shapes.py::test_keypoints_remain_observable_and_editable`
- [x] 7.6 `96e93981`；`test_workspace_mixed_shapes.py::test_batch_confirmation_never_confirms_keypoints`

## 8. 卡片尺寸、裁切和异步图块

- [x] 8.1 `c569a29f`；`test_card_geometry.py::test_card_image_height_defaults_to_320`
- [ ] 8.2 部分完成 `c569a29f`：高度独立与列数重排已验证（`test_card_geometry.py::test_widening_changes_columns_but_keeps_height`、`test_context_change_keeps_the_selected_height`）；**宽度受限提示与「在主画布查看」入口未实现**，故不勾选
- [ ] 8.3 裁切包含矩形及明确关联点并集，任一有效框外点即提供提示、主体观察及逐点定位，边界点视为框内；裁切钳制真实图像边界，满足 OC-11、OC-12。
- [ ] 8.4 部分完成 `c569a29f`、`5d2d3002`：目标像素与 DPR、尺寸进入缓存键已验证（`test_thumbnail_target_follows_size_and_dpr`、`test_height_change_invalidates_cached_crops`）；比较窗口及冷缓存请求已有实现（`test_workspace_evidence.py::test_compare_cold_cache_requests_updates_and_failures`），但几何、尺寸及上下文变化后的比较图块当前版本联动仍缺完整验证，故不勾选；不再沿用“比较窗口未实现”的旧描述。
- [ ] 8.5 合并尺寸滑块与布局变化请求，优先可见项和有限预取，保留虚拟列表；为源图、图块、图形资源、在途请求与结果队列登记各自容量或字节预算，满足 OC-18。
- [ ] 8.6 切图、改目录、调整尺寸和关闭工作区时取消或丢弃旧结果，后台线程仅提交当前代际可用数据；拖动期间遵守现有后台延迟策略。
- [ ] 8.7 实现明确失败、重试和冷缓存比较，关闭比较窗口后停止更新，成功恢复后按当前范围重算确认候选，满足 OC-19、OC-20、PC-07。
- [ ] 8.8 在快速滚动、反复调尺寸、切图和缓存淘汰场景验证对象定位、图块版本、失败恢复及资源有界，记录冷暖缓存数据。

## 9. 停靠工作区和任务视图

- [x] 9.1 将复核内容组件接入既有 dock 体系，默认右侧停靠，支持浮动和再次停靠，复用一个主画布和会话，满足 WL-01、WL-02。`5d2d3002` + `a4efb042`；`test_workspace_dock_tasks.py::test_menu_entry_docks_the_panel_beside_the_editable_canvas`、`test_reopening_reuses_dock_canvas_session_and_history`、`test_dock_visibility_events_do_not_rebuild_the_round`；浮动/停靠原图状态见 `test_workspace_review_fixes.py::test_float_keeps_original_display_mode`，均在 [最新全目录回归](../../../reports/dense_review_redesign/2026-11-17/validation-dense.txt) 通过。
- [ ] 9.2 接入类别核对、框与关键点观察、空间查漏三个任务入口，各自保存对象或区域视口，切换沿用编辑边界，满足 WL-07、WL-08。
- [ ] 9.3 分别支持批次和卡片收起，窄窗口保留当前对象、计数、审核范围与主要动作，紧凑列表仍有完整类名读取路径，满足 WL-03。
- [ ] 9.4 持久化面板宽度、浮动位置、展开状态与任务偏好，第二屏移除及不同 DPI 后恢复到可访问区域，满足 WL-04、WL-11。
- [ ] 9.5 将快捷键作用域适配主窗口和浮动面板，确保一次按键只触发一次；输入框、模态、冲突、关闭及忙碌状态正确处理，满足 WL-09、WL-10。
- [ ] 9.6 统一关闭、重开、图片加载、取消切图和主窗口退出生命周期，释放比较窗口与后台请求，移除临时显示覆盖并保留最新用户设置，满足 DP-17、WL-06。

## 10. 原图小地图和空间查漏

- [ ] 10.1 在复核面板增加带原图的小地图，显示当前边界、编号、浅色完成和疑难/暂跳状态，原图仍可辨认，满足 SN-03、SN-04。
- [ ] 10.2 小地图、紧凑区域列表、定位按钮和完成后前进共用区域导航，实际更新主画布视口及所有选中状态，满足 SN-03、SN-07。
- [ ] 10.3 查漏采用本任务淡矩形和原图对照预设，切区保持用户配置；全图和对象编辑往返恢复区域及显示策略，满足 SN-05、SN-06。
- [ ] 10.4 复用图像坐标计划和原覆盖身份，首次默认4×3和15%重叠，空图同样覆盖；窗口和DPI变化保持计划，满足 SN-01、SN-02。
- [ ] 10.5 收纳网格设置并明确重建影响，取消保留原计划和视口，确认生成全待查的新计划，支持现有撤销，满足 SN-10。
- [ ] 10.6 保留区域完成、疑难、暂跳、解除和复看操作，全部完成后允许定位任一区域，普通平移和缩放保持原完成状态，满足 SN-07、SN-08、SN-09。
- [ ] 10.7 验证新增、移动、删除及外部修改按旧新范围或保守规则使覆盖失效，纯改类按规则决定影响；补框后完成区域仍保留新框待审，满足 SN-11、SN-12、SN-13。
- [ ] 10.8 保存重开后实际恢复区域与画布位置，混合图分别显示矩形、点及查漏状态，满足 SN-14、SN-15。

## 11. 审核范围、撤销、保存与交接

- [x] 11.1 `4af3c92f`；`test_display_consistency.py::test_temporary_show_lifts_visibility_not_eligibility`
- [ ] 11.2 批次按钮展示候选、排除和屏外/策略收起人数，成员列表准确；区分临时弱化、显式隐藏、疑难、暂跳与失败，满足 PC-05、PC-06、PC-07。
- [ ] 11.3 保留类别/几何维度、稳定成员和内容指纹，确认时范围变化则重新呈现，重复确认幂等且整批可撤销，满足 PC-08、PC-09。
- [ ] 11.4 接入矩形编辑的确认与覆盖失效，点编辑刷新关联和图块，并对无法可靠定位的覆盖影响保守处理；点编辑沿用原数据命令，满足 PC-10、PC-11。
- [ ] 11.5 验证确认、编辑、删除、重建区域、撤销及重做的完整顺序，卡片和当前对象反映同一恢复数据，满足 PC-12、PC-13。
- [ ] 11.6 验证旧v1进度、缺失和重复身份、未知扩展、损坏版本、图像替换及输出目录切换，合法矩形确认保留、过期记录失效，满足 PC-14、PC-15。
- [ ] 11.7 验证外部文件冲突、失败保存、自动保存与取消切图，内存进度和dirty保留、原文件可读，满足 PC-16。
- [ ] 11.8 修整 Inspector 交接的同步入口，跨批次双对象、关联点、无框区域和过期请求均同步或准确拒绝，返回保持原问题位置，满足 PC-17、PC-18、PC-19。
- [ ] 11.9 全部框确认、查漏完成与关键点待支持分别显示，混合图保留部分复核状态，Inspector清空和浏览不影响正式验收，满足 PC-04、PC-20。

## 12. 设置、翻译和可访问性

- [ ] 12.1 将复核显示、任务、图像高度等偏好接入默认配置、schema和runtime applier，旧配置使用默认值，非法值归一化，验证重启恢复与普通画布偏好隔离。
- [ ] 12.2 为偏好保存失败保留当前可用视图和明确提示，测试配置只写 `.tmp/`，验证无真实用户配置或注册表副作用，满足 WL-11。
- [ ] 12.3 为新增动作接入快捷键设置、冲突检测和真实绑定提示，复用既有动作名，新增默认绑定依据冲突结果选择或留空，满足 WL-09、WL-10。
- [ ] 12.4 补齐中英日韩任务、状态、按钮和动态计数文本，运行项目翻译与资源编译流程，分别验证源码磁盘和打包资源入口，满足 WL-13。
- [ ] 12.5 为控件提供无障碍名称、可见焦点和合理Tab顺序，状态同时用文字与颜色表达；验证长类名、窄窗口和高缩放下主要操作可达。

## 13. 自动化集成与行为回归

- [ ] 13.1 补显示纯规则优先级及渲染/命中专项，覆盖 DP-01至DP-18 的自动化可验证部分，重点验证弱化点、标签底板、隐藏例外和当前目标。
- [ ] 13.2 补正常应用入口的启用、滚轮、dock、任务切换和快捷键回归，覆盖 WL-01至WL-12，并检查反复打开关闭的资源释放。
- [ ] 13.3 补混合卡片、group歧义、尺寸DPI、裁切、冷暖缓存和真实异步生命周期回归，覆盖 OC-01至OC-20。
- [ ] 13.4 补小地图、真实画布区域定位、计划重建、失效和保存恢复回归，覆盖 SN-01至SN-15。
- [ ] 13.5 补实际编辑、确认、撤销、导出往返、外部变化和Inspector交接回归，覆盖 PC-01至PC-20。
- [ ] 13.6 运行受影响的 `tests/test_dense_review`、`tests/test_canvas`、`tests/test_labeling`、`tests/test_settings`、`tests/test_inspection`，若碰到历史崩溃或失败则同基线定向对照，记录完整通过/失败/跳过/未完成及退出码。
- [x] 13.7 运行相关 Python 格式和静态检查、文档链接检查及本变更 OpenSpec strict，翻译修改核对生成来源；在报告明确工具栏布局和Windows不适用点云套件的运行情况。[FIX_IMPLEMENTATION.md](../../../reports/dense_review_redesign/2026-11-17/FIX_IMPLEMENTATION.md)、[FIX_VALIDATION.md](../../../reports/dense_review_redesign/2026-11-17/FIX_VALIDATION.md)：Black/OpenSpec/链接通过，flake8 11 项既有告警与基线一致；四语言编译入口 `scripts/compile_languages.py`、磁盘/嵌入资源由 `test_translations.py::TestDenseReviewTranslations::test_literal_messages_in_all_runtime_contexts_and_resources` 验证；工具栏布局和 Windows 点云均明确未运行。本条不等于 12.4 四语言全界面已完成。

## 14. 性能与真实屏幕验收

- [ ] 14.1 用相同机器、分辨率、DPI及授权样本比较基线和新修订，至少三轮记录冷/暖卡片导航、画布可编辑首帧、GUI心跳和拖框延迟，执行 acceptance.md 的计量口径。
- [ ] 14.2 在大卡片、300框和1000点场景遍历、切图和关闭，记录源图、图块、QIcon/QPixmap、在途任务、结果队列及进程峰值与稳定阶段，核对预算和无持续增长。
- [ ] 14.3 执行 M1–M4 真实屏幕步骤，验证滚轮、人物可辨性、类别文字、重叠点/框编辑和隐藏策略，保存设备参数及用户操作证据。
- [ ] 14.4 执行 M5–M8 的查漏、单/双屏与DPI恢复、键盘/四语言及确认保存场景，记录失败、分歧和修订，保留原有未完成验收边界。
- [ ] 14.5 用匹配图片组比较缩放、拖动、重复访问、窗口切换、确认次数、耗时与疲劳，两位用户各至少两轮，独立复核错误和返工；满足约定质量与减负条件后才记录减负已验证。

## 15. 文档、最小批次提交与交付

- [ ] 15.1 根据实际功能更新操作说明和真实截图，讲清三个任务、人物卡范围、原图对照、隐藏例外及查漏与正式验收区别；更新 CUSTOM-121 的实际状态。
- [ ] 15.2 将每项规格场景关联实际测试node ID或人工证据，逐项填写结果及修订号；历史测试记录只作参考，遗留未完成项目逐项保留。
- [x] 15.3 按可独立验证最小批次核对暂存区并本地提交，用 `feat|fix|docs|test|perf(scope): 中文说明` 记录，更新功能记录与仓库操作记录的提交和验证范围。已实施批次依赖保存 `5d2d3002`、独立修复 `a4efb042`、独立复核 `1c148da5`；CUSTOM-121、操作台账和暂存范围均有记录，详见 [本次勾选核对](../../../reports/dense_review_redesign/2026-11-17/TASK_STATUS_SYNC.md)。后续新批次继续执行本条规则。
- [ ] 15.4 演练定向回退及依赖检查，使用测试副本重开标注验证对象身份、标签、旧审核字段、扩展元数据及显示恢复，登记恢复点和结果。
- [x] 15.5 汇总本地提交、实际验证范围和未决项，重新核对集成目标。按用户已有授权执行推送/PR/合入并核验目标提交号；缺少相应授权时交付本地结果和待授权状态。截至当前阶段的提交、验证、全部未决条目和目标节点见 [TASK_STATUS_SYNC.md](../../../reports/dense_review_redesign/2026-11-17/TASK_STATUS_SYNC.md)；当前仅本地交付，未推送/PR/合入，目标仍为 `codex/4.2.1-baseline-organization`。此条不代表其余任务和整体发布完成。

后续完整关键点审核另建变更，先定义类别、位置、人物归属、遮挡与缺点规则、关系签名和历史进度兼容。本任务清单的完成条件以本次五份规格为准。
