# 验证记录：restore-v430-canvas-controls

> 最新代码实施（2026-11-05）：见 [implementation-20261105.md](implementation-20261105.md)。本轮修复工具栏横向滚轮、成组重载丢失未保存标注及设置窗口关闭后的延迟回调异常；最终专项 **127 passed（250.20s）**，受影响回归 **403 passed / 1 项既有字体失败（194.77s）**。下文旧复核中的 T1 未修复、生命周期/16 位灰度未测试等描述均已被本轮证据更新，性能及真实系统缩放仍保留限制；当前状态以任务清单为准。

> 最新复核（2026-11-05）：[review-20261105.md](review-20261105.md) 记录本轮 **73 passed（114.08s）**、R1/R2 修复核验和四语言磁盘缺失时的应用级翻译回退核验。当前源码已修复此前视图/保持按钮问题，`resources.py` 也已更新；下文涉及“缺陷未修复”“资源未重生成”及 52 项测试数的内容均为 2026-11-04 历史记录。新增未修复 T1 为工具栏横向滚轮方向相反，恢复 6.2 已撤回勾选。7.3 的 pending 生命周期、完整回归、性能、真实屏幕及独立交付仍未验收；当前状态见 [tasks.md](tasks.md)。本轮只修改复核文档，未实施代码修复。

> 2026-11-04 联合复核补充：下文为此前恢复实施的验证记录，不是本轮全部重跑结果。最新缺陷、证据边界及两变更的任务合并见 [joint-review-20261104.md](joint-review-20261104.md)，当前状态以 [tasks.md](tasks.md) 为准。现有 52 项专项本轮重跑通过（100.62s），额外探针仍复现传统模式首次平移跳动及保持按钮保存失败后状态分叉，相关完成勾选已撤回；本轮未实施代码修复。
>
> 历史编号更正：本文末尾“未执行”中的性能基准应对应恢复 8.3，真实屏幕/主题/系统缩放验收对应 8.4，配置交错保存对应 8.5；7.4 为视图边界矩阵。源码磁盘翻译通过不代表嵌入资源或打包验收通过，8.1 现保持未完成。配置持久化实现已经存在，需补本画布集成联测，不能继续视作“尚未实施”。

## 环境与基线

- 日期：2026-11-04
- 系统：Windows（DSH workspace-write 沙箱；`backups/`、`reports/`、`.git` 的普通写入被 ACL 拒绝）
- Python：3.12（`x-anylabeling-cu12` conda 环境），`QT_QPA_PLATFORM=offscreen`，PyQt6
- 代码基线：`67c98a80171318f6ced1070c49fc82b2120a22c9`（`codex/4.2.1-baseline-organization`）
- 实施前工作区差异：35 个已跟踪修改、20 项未跟踪条目（Inspector / Dense Review / 配置持久化等先前成果）；本次只叠加五项画布能力、恢复来源证据与专项测试，不回退既有改动。

## 恢复来源与保全

实施前在 `backups/restore-v430-20261104/` 保存：

| 内容 | 路径 | 结果 |
| --- | --- | --- |
| 已提交历史 bundle | `backups/restore-v430-20261104.bundle` | `git bundle verify`：`records a complete history`，HEAD `67c98a80`，SHA-256 `7168ea70…97c21` |
| 未暂存二进制补丁 | `backups/restore-v430-20261104/diff-unstaged.binary.patch` | `git apply --reverse --check` 通过 |
| 已暂存补丁 | `.../diff-staged.binary.patch` | 空（实施前无暂存内容） |
| 未跟踪源码/文档副本 | `.../untracked/` | 26 项完整复制 |
| 文件哈希清单 | `.../hashes.txt` | 65 项（已跟踪修改 + 未跟踪） |
| 交付回执 | `.../receipt.json` | 分支、HEAD、bundle/补丁哈希、blob 指纹 |

三份可恢复 blob 按原始字节导出并复核，与历史 P2 复验报告一致：

| 文件 | Git blob | SHA-256 |
| --- | --- | --- |
| `anylabeling/views/labeling/label_widget.py` | `63aca7d717b200fbc27e2f14b8dba7e1765ec2e6` | `eee49005…0ca909c` |
| `anylabeling/views/labeling/widgets/canvas.py` | `6adda41acf330a0378e43fb1ee650e6bf5548fc2` | `e9880c23…126abf8` |
| `tests/test_labeling/test_canvas_display_retention.py` | `ad4dcfbee35f144dc769a951e063a7a76d95be04` | `d8069aba…678a9428` |

独立重建核验：将 bundle 克隆到 `.local/restore-v430-20261104/verify-clone`，应用未暂存补丁后按 `hashes.txt` 比对，**60/62 项逐字节一致**；`.gitignore`、`dense_review/workspace.py` 两项仅行尾归一化不同（应用补丁时的 CRLF/LF 规范化，备份时已出现同类警告）。三份 blob 的哈希另行直接核对一致。

说明：沙箱内首次 `git bundle` 因进程管道被拒，bundle 与备份目录创建使用了经批准的单次更宽权限；其上所有源码与测试验证仍在 workspace-write 沙箱内完成。

## 变更落点

| 能力 | 文件与函数 |
| --- | --- |
| 仅填充透明度 | `shape.py::Shape.paint(fill_opacity)` 只缩放临时填充 alpha；`widgets/canvas.py` 掩码/普通填充/选中与创建预览各乘一次，移除全局 `p.setOpacity` |
| 三态图片审核 | `widgets/canvas_adjustment.py::_build_status_row`、`status_changed`、`set_status`、`set_status_enabled`；`label_widget.py::set_annotation_checked`、`_sync_annotation_checked_state`、`reset_state`、`load_file` |
| 显示参数保持 | `canvas_adjustment.py` 三行 `opacity_pin`/`brightness_pin`/`contrast_pin` 与既有重置按钮；`label_widget.py::_flush_pending_brightness_contrast`、`load_file` 跨图策略、keep 动作双向同步 |
| 可视化工具栏 | `label_widget.py` 八类显示动作补齐图标并接入 `actions.tool`，成组/解组随行；`widgets/toolbar.py::ToolBarScrollArea` 横向滚动且吞掉滚轮；`toolbar_scroll_area` 使用新控件 |
| 滚轮导航 | `widgets/canvas.py::wheelEvent` 优先级重写、`interaction_in_progress`；`label_widget.py::apply_wheel_navigation_mode`、延迟应用、`constrain_canvas_pan`；`config.py` 归一化、`xanylabeling_config.yaml` 默认值、settings schema 与 runtime applier |

## 行为—测试—结果

| 行为 | 测试 | 结果 |
| --- | --- | --- |
| 填充 100/50/0/100% 像素往返，边框不受影响，颜色对象不被改写 | `test_fill_opacity.py::test_shape_fill_alpha_is_scaled_without_touching_outlines` | 通过 |
| 掩码填充只乘一次，边框仍可读 | `test_mask_fill_is_scaled_once_and_border_stays_readable` | 通过 |
| 选中/创建预览填充使用同一乘数 | `test_selected_preview_fill_uses_the_same_multiplier` | 通过 |
| 可视化导出保留自身填充规则 | `test_visualization_export_keeps_its_own_fill_rules` | 通过 |
| 无效滚轮模式回退 direct | `test_wheel_navigation.py::test_invalid_mode_falls_back_to_direct` | 通过 |
| direct 裸滚轮只缩放、traditional 只滚动 | `test_direct_bare_wheel_zooms_without_scrolling`、`test_traditional_bare_wheel_scrolls_without_zooming` | 通过 |
| Ctrl 在两种模式均缩放，Shift 均滚动 | `test_ctrl_wheel_always_zooms`、`test_shift_wheel_always_scrolls`（各 2 参数） | 通过 |
| 横向/像素增量与空增量不误触发 | `test_horizontal_*`、`test_unmatched_modifiers_and_empty_delta_do_nothing` | 通过 |
| Alt 调笔刷、Alt 调框、Alt+Shift 调对比，单次事件仅一个行为 | `test_alt_wheel_*`、`test_alt_shift_wheel_adjusts_compare_split` | 通过 |
| 导航不新增几何撤销；无图滚轮无副作用 | `test_navigation_does_not_create_geometry_backups`、`test_no_image_wheel_event_is_harmless` | 通过 |
| 交互中（含四极值草稿）延迟模式切换 | `test_interaction_in_progress_tracks_drawing_state`、`test_canvas_display_retention.py::test_wheel_mode_waits_for_extreme_draft_*` | 通过 |
| 缺省/有效/无效 `canvas.wheel_navigation_mode` 配置 | `test_wheel_navigation_config.py`（5 项） | 通过 |
| 设置项注册与 runtime 应用 | `test_setting_field_is_registered_with_both_options`、`test_runtime_applier_forwards_the_mode` | 通过 |
| runtime applier 实际切换画布模式并同步配置 | `test_canvas_display_retention.py::test_runtime_applier_switches_wheel_mode` | 通过 |
| 无图禁用审核面板、不建标注文件 | `test_review_status_panel.py::test_panel_is_disabled_until_an_image_is_loaded` | 通过 |
| 面板三态保存并同步菜单/文件列表/JSON | `test_panel_review_selection_saves_and_syncs` | 通过 |
| 切图跟随目标图状态 | `test_panel_follows_target_image_status` | 通过 |
| 后台旧审核元数据不得覆盖人工状态 | `test_stale_metadata_cannot_override_manual_status` | 通过 |
| 程序同步不保存、重复选择不重写 | `test_programmatic_sync_does_not_save`、`test_repeated_selection_does_not_rewrite` | 通过 |
| 保存失败保留可重试 dirty 状态 | `test_failed_save_keeps_retryable_dirty_state` | 通过 |
| 工具栏复用既有动作且有可读图标/提示 | `test_toolbar_display_actions.py::test_toolbar_reuses_existing_display_actions` | 通过 |
| 工具栏与菜单共享显示状态 | `test_toolbar_and_menu_share_display_state` | 通过 |
| 未引入四种显示模式选择器 | `test_toolbar_does_not_add_display_mode_selector` | 通过 |
| 工具栏横向滚动吞掉滚轮 | `test_toolbar_scroll_area_consumes_wheel` | 通过 |
| 透明度跨图保持/关闭恢复 100%/同图与失败/取消不重置 | `test_canvas_display_retention.py`（14 项） | 通过 |
| 亮度/对比度缓存、keep 动作双向同步、节流内切图取最新值 | 同上 | 通过 |
| 模式切换保持图像中心与倍率 | `test_wheel_navigation_mode_switch_preserves_the_view`、`test_mode_roundtrip_*`（既有复核用例） | 通过 |

## 执行命令与结果

```text
QT_QPA_PLATFORM=offscreen TMPDIR=.tmp/v430-final \
PYTHONPATH=.local/restore-v430-20261104 \
python -m pytest tests/test_canvas/test_fill_opacity.py \
  tests/test_canvas/test_wheel_navigation.py \
  tests/test_config/test_wheel_navigation_config.py \
  tests/test_labeling/test_canvas_display_retention.py \
  tests/test_labeling/test_review_status_panel.py \
  tests/test_labeling/test_toolbar_display_actions.py \
  -q -p no:cacheprovider -p pytest_tmp_mode
52 passed in 98.71s
```

回归子集（`test_navigation`、`test_groups`、`test_label_visibility_mode`、`test_rectangle_edge_migration`、`test_check_status`、`test_image_switch`）：**203 通过 / 1 失败**；失败为既有环境问题（见下）。

Inspector / Dense Review 选择性子集（`test_dense_review` 的 session/workspace/persistence/export/thumbnails 与 `test_inspection` 的 handoff/dialog）：**95 通过 0 失败**（75.61s），覆盖调框、数字改类、统一撤销/重做、保存重开、卡片异步代际与手递接返回。

```text
lrelease {en_US,zh_CN,ja_JP,ko_KR}.ts -qm {…}.qm
zh_CN: 5 checked, ja_JP/ko_KR/en_US: 2 checked
TRANSLATIONS-OK

openspec validate restore-v430-canvas-controls --strict
Change 'restore-v430-canvas-controls' is valid
```

## 既有失败与限制

- `tests/test_canvas/test_groups.py::test_shape_label_keeps_fixed_screen_size_while_zooming` 失败（179 != 139）；在与本变更无关的 2026-11-03 基线副本中同样失败，根因是当前 Conda 环境缺少 PyQt6 字体目录（`QFontDatabase: Cannot find font directory`），属环境既有失败。
- `tests/test_canvas/test_label_visibility_mode.py` 的假窗口缺少 `update_user_preference`，是配置持久化变更引入的既有夹具缺口；本次仅补全该测试替身，使其继续验证“仅选中标签”行为。
- 既有 `MainWindow` 测试夹具未启动配置会话，配置持久化变更会弹出模态“保存失败”对话框；本次验证用本地插件（`pytest_restore_env.py`，不入库）在无会话时跳过持久化，产品代码未改。
- `resources.py` 仍嵌入旧 `.qm`；源码运行按 `app.py` 的磁盘优先路径加载新 `.qm`，打包产物需在具备兼容 `rcc` 的环境重新生成资源后回归。
- 未执行：拖框/切图性能基准（8.4）、真实屏幕/主题/系统缩放人工验收（7.4、8.5）、与配置持久化的交错保存联测（8.5 / 配置任务 7.3）。
- 沙箱普通权限禁止写 `.git`，本恢复差异尚未独立提交（9.2）；提交需在具备写权限的环境按 `verification.md` 所列文件范围完成。
