# 维护候选验证 · 2026-11-17

状态：执行中，尚无最终全绿结论。候选源码为 `aebb1804`；前两批维护文档
提交不改变代码，实际运行 HEAD、源码树、命令、解释器、版本、超时和退出码
保存在每批 JSON；完整 stdout/stderr 为同名 log，成功生成的 JUnit 为 xml。

使用 `C:\Users\20441\.conda\envs\x-anylabeling-cu12\python.exe`，
`QT_QPA_PLATFORM=offscreen`；不放宽 tests/conftest 的真实配置和 QSettings 写保护，
`-vv -o faulthandler_timeout=30` 加外层进程树硬超时。
原始日志保留失败及模态堆栈；单跑通过不替代合跑通过。

历史证据见[候选说明](../../docs/version-management/2026-11-17-maintenance-baseline.md)，
与本目录本轮实测分别记录。真实屏幕/字体/DPI、双人试用、性能和回退演练
不能由 offscreen 替代；工具栏布局及 Windows 点云另列覆盖情况。

## 本轮结果（同一源码树）

两批运行 HEAD `cdd256607c2e9ef71a8bd8fe78568c1cc6266d00`，
源码树 `01efe6fe526f49a44353ffcbc5efc5e089a1e77f`，与固定候选一致。
Python 3.12.12、PyQt6 6.10.2、pytest 9.0.3、onnxruntime-gpu 1.24.3。

| 批次 | 实际结果 | 外层限制 / 退出码 | 原始证据 |
| --- | --- | --- | --- |
| 历史风险最小复核 | 3 failed / 9 passed，9.91s | 180s / 1，无超时 | [命令及环境](priority.json)、[日志](priority.log)、[JUnit](priority.xml) |
| 核心合跑 | 991 passed / 1 skipped / 107 subtests，208.38s | 900s / 0 | [命令及环境](core.json)、[日志](core.log)、[JUnit](core.xml) |
| Inspector + 密集复核合跑 | 1 failed / 525 passed / 842 subtests，833.55s | 1500s / 1，无超时 | [命令及环境](review.json)、[日志](review.log)、[JUnit](review.xml) |
| Windows 全范围收集 | 2679 tests collected，4.16s | 120s / 0 | [命令及环境](collect.json)、[日志](collect.log) |
| 拟合输入测试修正 | 完整集成文件 36 passed，124.78s | 240s / 0 | [修正说明](FIT_FIX.md) |

核心合跑包含完整画布、配置、设置目录，及标注读取/保存失败保护、切图、数字
矩形 16 种组合和 0–9、保存后重载、撤销、修正成本的取消导航/事务/回退。
配置跨独立进程读写和设置窗口重开均已测试；未改变写保护或用错误弹窗替身
掩盖初始化保存失败。跳过项详见 JUnit，不合并子测试与主用例数字。

最小失败节点：

- `tests/test_dense_review/test_redesign_interactions.py::test_handoff_keeps_cross_batch_objects_and_associated_point_reachable`：首个交接断言为 False。请求未填协议所需 `snapshot_digest`；这是停止快照的已知用例，后续跨批次断言尚未到达，不能据此声称该功能已验收。
- `tests/test_labeling/test_canvas_controls_integration.py::test_pending_mode_finishes_real_edit[commit-fit]` 及 `[cancel-fit]`：尚未建立拟合手势即断言 `interaction_in_progress()` 为真失败。历史 `7c6ccff3` 也复现；本轮只确认当前仍失败，不宣称已完成产品定责。

旧原生退出相关 `test_nudge_preview_preserves_host_dirty` 的 8 个参数和
`TestLabelLocks::test_category_checkbox_controls_all_matching_shapes` 本轮均通过；
更大组合结果另列，不能从这 9 项推出全局原生问题均已解决。
不为修复停止任务的用例或行为扩大维护范围。

拟合失败已用最小测试修正闭环：只补真实 Shift 按下/释放，全部原断言保留，
生产代码无改动。提交 `efb172b9`，静态检查结论与原始日志补充于 `6c9af4dc`。
整文件通过还包含分组撤销/重做、保存重开与真实进程重启。
flake8 基线与修正后各 14 条既有 F811，退出码 1，不宣称静态全绿。

工作台合跑的唯一失败为上述停止快照交接用例；Inspector 主用例全部通过。
本次合跑未出现原生退出，不等于所有系统、测试顺序或真实屏幕都已验证。
全 Windows 回归正在另跑，主命令为 JSON 中全范围 `tests`，
显式排除 `tests/test_widgets/test_toolbar_layout.py` 与 `tests/test_pointcloud`；
工具栏布局本轮未执行，点云不适用于本机 Windows，均不计为通过。

## 本轮失败分类与范围

除拟合输入测试已修正外，下列问题保留，不删除失败、不添加 skip/xfail：

| 类型 | 节点 / 当前事实 | 处理边界 |
| --- | --- | --- |
| 停止快照的测试协议缺口 | `test_redesign_interactions::test_handoff_keeps_cross_batch_objects_and_associated_point_reachable` 未提供 snapshot digest，返回拒绝 | 不恢复原重设计；后续跨批/关联点行为仍未获该用例验收 |
| Windows 临时文件共享 | `test_remote_server::TestRemoteServerClassFilter::{test_prediction_forwards_selected_classes,test_selecting_all_classes_sends_empty_filter_override}` 打开仍由 NamedTemporaryFile 占用的 JPEG 时 PermissionError | [标准库独立探针](windows-probes.txt)在仓库 .tmp 同样复现，不归为维护回归 |
| Windows 测试路径断言 | `test_dataset::test_dataset_preparation_reports_invalid_yaml_path` 将反斜线路径直接作正则，报 bad escape `\X` | 测试平台适配缺口，本轮未改训练测试 |
| Windows home 规则 | `test_environment::test_expand_training_path_supports_tilde_and_unicode` 只覆盖 HOME，但 Windows expanduser 采用 USERPROFILE | 同上；[探针](windows-probes.txt)独立确认行为 |
| 可复现、尚未定责 | `test_trainer::test_stop_training_terminates_silent_process_immediately` 在 stop 后 join(3) 仍存活 | 保留停止延迟风险；服务和测试相对集成分支未变化，未运行旧保存点复验，不能据此宣称根因或归属已确定 |

五项 Windows 失败独立合跑为 **5 failed / 6.38s，退出码 1**；
范围仅上述五项，详见[命令](windows-failures.json)、[日志](windows-failures.log)、
[JUnit](windows-failures.xml)。被测提交 `6c9af4dc`，runtime diff 为空。
相对本地集成分支，相关 remote_server、auto_training 服务和上述测试文件均无差异；
此为静态来源对照，不冒充在历史保存点执行过测试。

真实屏幕/字体/DPI/读屏、双人试用、收益与质量对照，以及统计功能的性能/回退
缺口仍按原任务保留。Inspector 用户声明通过和历史 restore 的系统缩放验收
不扩展为整个候选的人工通过。OpenSpec strict 只验证规格结构。

## 首次完整运行与后续修正

完整命令和源码身份：[full.json](full.json)，原始输出：[full.log](full.log)。
运行 HEAD `6c9af4dc`，2679 项收集成功，总上限 1800s、无输出上限 180s。
实际 1720.41s 后因无输出超时结束进程树，退出码 1，**没有完整 JUnit**。
最后节点为 `tests/test_staged_output_window.py::test_output_switch_reads_current_then_background`，
堆栈 `LabelingWidget.error_message → persist_user_preferences → set_canvas_params → MainWindow`。
最小复现保留原始 No active configuration session 错误，不屏蔽弹窗，见
[启动修正](STARTUP_FIX.md)。修正已提交 `8d9ab779`，两个文件最终 15 passed。
本报告提交同时仅换行新启动参数，AST 相同；之后重新执行完整 Windows 范围。
源任务 3.4 暂不勾选，等待真正完整运行；本轮其余独立整理按交接继续。

首轮日志能观察到 2429 个 PASSED 和 16 个 FAILED 主节点，另有子测试失败；
这是中断日志提取，**不是最终 pytest 总计**，不能以 2679 减去这些数字断言跳过数。
从挂起节点起的未完成范围及后续更新/工具/控件等未完成尾部，等待第二轮完整结果。
工具栏布局及点云继续显式排除，不计为通过。

另五个标注文件的最小合跑为 **12 failed / 42 passed / 19 subtests**，4.69s、退出码 1；
见[元数据](additional-failures.json)、[日志](additional-failures.log)、[JUnit](additional-failures.xml)。
这些不属于恢复停止任务的理由，本轮仅记录：

- 属性测试桩缺少 `Shape.copy()` 或 `_metadata_generation`；过滤测试桩缺 `dense_review_active()`。
- 标题测试硬编码 POSIX 路径，Windows 实际为规范化盘符/反斜线。
- 属性 JSON 上传及两个视频流测试同样在占用中的 NamedTemporaryFile 上触发 Windows PermissionError；上传的两个子测试也失败。

除上述两个初始化夹具修正和拟合输入测试修正外，本轮不改这些服务或桩、不加 skip/xfail、
不重启停止任务。回归异常与环境/夹具缺口如实保留，人工缺口继续受原任务约束。

## 检查的实际边界

本轮产品源码未改；两份新修正窗口测试 flake8 退出 0，拟合文件有 14 条既有 F811。
代码与文档 diff 空白检查通过；原始 pytest 日志/XML 则含 pytest 输出的行尾空白，
保留原字节，不将整批 `git diff --check` 冒称为零告警；检查时将原始 .log/.xml 单列。
未为纯文档归档重跑 Qt，后续完整复验的测试树和源码树均单独记录。
