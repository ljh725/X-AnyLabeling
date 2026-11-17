# 维护候选验证 · 2026-11-17

状态：维护整理已实施，完整回归已结束但未通过；候选未达稳定基线。候选源码为 `aebb1804`；前两批维护文档
提交不改变代码，实际运行 HEAD、源码树、命令、解释器、版本、超时和退出码
保存在每批 JSON；完整 stdout/stderr 为同名 log，成功生成的 JUnit 为 xml。

使用 `C:\Users\20441\.conda\envs\x-anylabeling-cu12\python.exe`，
`QT_QPA_PLATFORM=offscreen`；不放宽 tests/conftest 的真实配置和 QSettings 写保护，
`-vv -o faulthandler_timeout=30` 加外层进程树硬超时。
原始日志保留失败及模态堆栈；单跑通过不替代合跑通过。

历史证据见[候选说明](../../docs/version-management/2026-11-17-maintenance-baseline.md)，
与本目录本轮实测分别记录。真实屏幕/字体/DPI、双人试用、性能和回退演练
不能由 offscreen 替代；工具栏布局及 Windows 点云另列覆盖情况。

## 分批实测记录（同一生产源码树）

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
工作台合跑后另行执行全 Windows 回归，主命令为 JSON 中全范围 `tests`，
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
第三批证据提交时仅换行新启动参数，AST 相同；之后重新执行完整 Windows 范围。
首轮记录时源任务 3.4 未勾选，等待真正完整运行；其余独立整理按交接继续。

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

## 未完成尾部的补核

修正后的同一测试树 `77f9ced5` 上，updates/utils/widgets 合跑为
**2 failed / 188 passed / 29 skipped / 30 subtests，9.86s，退出码 1**。
见[元数据](tail.json)、[日志](tail.log)、[JUnit](tail.xml)。这不是完整合跑的替代。
两项分别为 `test_canvas_adjustment::TestCanvasAdjustmentWidget::test_brightness_contrast_updates_are_throttled`
的 `0 != 1`（未定责时序问题），以及 `test_defaults_and_tooltips_describe_adjustment_targets`
要求英文包含 shapes 而现文案使用 annotation fills（断言与当前文案不一致）。
未将这些失败删除或改成跳过；第二轮完整结果已在下节单独统计。

规格归档及历史证据完整性已单独通过，不代表这些回归失败已解决；见
[归档审计](ARCHIVES.md)。第二轮完整 Windows 回归以 77f9ced5 为测试起点，
后续仅文档提交，生产/测试树均不变；该阶段 3.4 保持未勾，最终执行结果见下节。

## 最终完整回归与交付结论

第二轮完整 Windows 范围已结束，**不是通过**：

> 20 failed, 2632 passed, 29 skipped, 1015 subtests passed in 1511.58s (0:25:11)

这 20 项失败包括 **18 个主用例和 2 个失败子测试**；2679 个主用例的对应为
2632 通过 + 29 跳过 + 18 失败，不把子测试计成额外主用例。
完整[命令/环境/退出码](full-recheck.json)、[原始日志](full-recheck.log)、
[JUnit](full-recheck.xml)、[逐项失败清单](full-recheck-summary.json)均保留。
总超时 2400s、无输出超时 180s 均未触发，外层 1515.69s，pytest 退出码 1。
没有本轮完整运行的原生退出，不追认为全部历史 native 问题已定责或消失。

测试起点 `77f9ced5369729313ef10060d9c68459149785b2`，
生产树 `01efe6fe526f49a44353ffcbc5efc5e089a1e77f`，
测试树 `b33383b8fba80fbbcd2648507a0bde66a212d0c2`，runtime diff 为空。
后续只有维护文档/规格/归档提交，以上两树与最终交付相同。
工具栏布局与点云均未运行；29 个 skip 的具体理由在 JUnit，未将它们视为通过。

全部失败均落在前述已记录范围：Windows 文件共享/路径断言、旧测试桩缺接口、
停止快照交接、训练停止时序及两个画布调整断言；不以测试失败数直接等同产品缺陷数。
本轮只修正三个旧测试文件的真实输入/配置会话/清理，生产代码未修改，配置写保护未放宽，
失败没有删除、skip 或 xfail。原密集复核、成本统计、关键点暂停和 P2 契约不一致的
状态继续保留，不启动功能扩展或恢复停止任务。

四步维护成果可交付，**候选不能标为已验证稳定版**。任务 3.4 的勾选表示完整
执行与记录已经完成，不表示 20 个失败解决；基础产品验收和人工缺口仍按原任务管理。
11 目录分批归档、21 主规格和历史证据保全的实际结果见[归档审计](ARCHIVES.md)。
本地提交及固定备份已保存；未推送、未开 PR、未合入约定目标。

## 收尾前的本地提交

```text
0e5472cb docs(maintenance): 固定候选基线与本地备份
cdd25660 docs(maintenance): 重算任务状态并修复当前导航
efb172b9 test(maintenance): 补齐拟合集成用例真实按键事件
6c9af4dc docs(maintenance): 更正静态检查并补全原始日志
8d9ab779 test(maintenance): 修正旧窗口测试启动与清理
77f9ced5 docs(maintenance): 建立当前验证证据与失败分类
4a2f7cce docs(maintenance): 核实归档资格与场景语义映射
ffd1a047 docs(openspec): 同步并归档平滑拖动变更
15153e76 docs(openspec): 修正分批归档导航时序
8678f3eb docs(openspec): 同步并归档分阶段标注加载
2267cc6c docs(openspec): 同步并归档用户设置持久化
5453c11f docs(openspec): 同步并归档数字矩形类别保存
9caa239e docs(openspec): 同步并归档矩形拖边调整
57dc5979 docs(openspec): 同步并归档矩形预览显示
89e3785e docs(openspec): 发布并归档画布能力恢复契约
4ec0a3cd docs(openspec): 按依赖同步并归档单点拟合契约
a5486ba7 docs(openspec): 核对重复契约并归档迁移脚手架
414e079b docs(maintenance): 汇总归档与证据完整性核对
```

收尾提交以本报告后的最终 HEAD 为准；以上均为本地提交，无推送、PR 或合入。

维护清单最终 **18/18**，活动目录 **5**、合计 **148/180**、原产品未勾 **32**；
这是维护整理完成，候选仍有上述失败，未达到稳定交付。
