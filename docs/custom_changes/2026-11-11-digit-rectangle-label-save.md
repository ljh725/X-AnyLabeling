# CUSTOM-011 数字键矩形类别保存

- 状态：已验证（Windows 离屏专项）
- 功能分类：原功能修改
- 创建与更新日期：2026-11-11（Asia/Shanghai）
- 版本与复核基线：X-AnyLabeling 4.2.1，`f87fdfa8`
- 实现提交：类别优先级修复 `3ddee158`；绑定生命周期补修在工作区
- 前置依赖：当前工作区中的数字键提示条和现有四极点矩形工作流

## 问题与目标

原修复让有效数字键绑定优先于类别列表预选、上次类别和标签弹窗。复核时发现，若用户在完成矩形前按 Esc、切回编辑或换图，下一次普通矩形仍可能写入已放弃的数字键类别。

## 修改位置与方法

| 文件与函数 | 改动 |
| --- | --- |
| `label_widget.py` 的 `toggle_draw_mode()` 与 `create_digit_mode()` | 工具切换先清除上次待用类别。数字快捷键在切换完成后绑定本次类别。 |
| `label_widget.py` 的 `reset_state()`、`toggle_drawing_sensitive()` 与 `eventFilter()` | 换图、取消画布草稿或在第一点前按 Esc 时清除待用类别和提示条高亮。 |
| `widgets/rectangle_creation.py` 的 `reset()` 与 `continue_drawing()` | 草稿清除后通知控件恢复。继续绘制先启动新草稿，再复用上一四极点矩形的类别。 |

## 兼容与数据影响

继续使用现有数字键配置、标签校验和 JSON 保存流程。历史标注由用户依据原图核对类别，本补修没有数据迁移步骤。

## 验证

Windows conda `x-anylabeling-cu12`，Qt offscreen。修复前以真实窗口和键鼠输入复现 4 种错类路径，涉及第一点前后按 Esc、切回编辑、换图。

修复后共 **119 项通过**，另有 **72 项子测试通过**。新增回归核对四条放弃路径之后的画布类别和实际 JSON。原有用例覆盖 0–9、自动保存与 Ctrl+S、输出目录、弹窗与预选类别组合及重载。

| 测试范围 | 实际结果 |
| --- | --- |
| 数字键矩形与改类、标签文件保存、画笔模式、数字键设置与重启、四极点绘制、数字键提示条 | 112 项通过，[JUnit 结果](../../reports/digit_rectangle_save_20261111/pytest-digit-delivery-20261111.xml) |
| Ctrl+J 退出矩形模式 | 使用有效隔离配置初始化测试窗口，1 项通过，[JUnit 结果](../../reports/digit_rectangle_save_20261111/pytest-digit-edit-20261111.xml) |
| 画布绘制模式切换 | 6 项和 72 项子测试通过，[JUnit 结果](../../reports/digit_rectangle_save_20261111/pytest-digit-mode-canvas-20261111.xml) |

全目录尝试在配置保存错误弹窗处阻塞，涉及 `test_candidate_review_regressions.py` 与 `test_navigation.py` 的旧窗口夹具。画布扩展回归还发现 `test_groups.py` 的缩放标签宽度断言失败（179 与 139），以及 `test_rectangle_preview_overlap.py` 的 `test_nudge_preview_preserves_host_dirty` 进程提前退出。这些用例未通过本轮验证。未运行真实屏幕人工验收及 CI 排除的工具栏布局、点云用例。

## 迁移与回退

同步移植工具切换、取消和图片重置三个清理入口，以及四极点继续绘制的绑定顺序。局部回退时保留 `3ddee158` 中的类别优先级处理。
