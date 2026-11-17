# F1–F4 修复独立复核 · 2026-11-17

复核 `a4efb04298f23527d3d4313c1b23e70bd00fe2da`（依赖 `5d2d3002`）。前两轮的十四个原复现已原样复跑并全部通过；本轮审阅未发现这四项修复范围内新增的 P1/P2 问题。结论仅针对本批修复，整个 `redesign-dense-review-workspace` 继续保持实施中。

本轮没有修改业务代码或测试。开工时分支为 `codex/4.2.1/dense-review-redesign-plan`，源码与上述提交一致，仅 `.gitignore` 和 `docs/development/` 有其他工作的改动，全部保留。

## 逐项结论

| 原发现 | 独立复核结果 | 核对内容 |
| --- | --- | --- |
| F1 视口恢复不同步 | 通过 | 改用完整 `_dense_review_restore_view()`；原小数缩放与 FIT_WINDOW 往返、缩放控件/画布尺寸、FIT_WIDTH 往返均通过；源码同时同步滚动、平移、导航器和视图记忆 |
| F2 查漏点残留绘制与命中 | 通过 | 按点类型清零全部组件；原点像素 QImage 比较及真实 Canvas 命中检查均通过，矩形未走该清零分支 |
| F3 重开回退当前对象 | 通过 | 重开只安装当前任务策略，沿用 live session；原 rect1 → 查漏 → 类别 → rect2 → 关闭重开流程仍为 rect2 |
| F4 浮动丢失原图对照 | 通过 | 持续隐藏延后一个事件循环判断，close 仍立即清理；原下拉 original → 浮动复现通过，持久回归还覆盖重新停靠及暂停状态/当前对象保持 |

此前 R1–R6 的八项复现同样全部通过：真正隐藏清理、查漏刷新保持视口、重开任务预设、两种缩放往返、普通文字开关和任务关联点策略未回退。`test_explicit_region_navigation_still_moves_the_canvas` 的 `or True` 已移除，改为实际缩放/平移前后比较。

## 独立运行证据

环境为 conda `x-anylabeling-cu12`、Python 3.12.12、PyQt6 offscreen。Qt DLL 需沙箱外加载，仍保留现有真实窗口 `get_config()` 配置会话、`.tmp/` 写保护与 INI QSettings；没有放宽 guard。pytest 使用 `-vv -o faulthandler_timeout=30`、独立 basetemp 和外层硬超时（原复现 240 秒、密集复核 660 秒、画布 300 秒）。

| 验证 | 结果 | 证据 |
| --- | --- | --- |
| 原八项 + 补充六项临时复现脚本原样复跑 | **14 passed**，43.03s，退出码 0 | [日志](validation-original14.txt) |
| 密集复核全目录，含 18 项持久修复回归 | **282 passed，698 subtests passed**，454.11s，退出码 0 | [日志](validation-dense.txt) |
| 上两轮相同的受影响画布十文件 | **286 passed，6 subtests passed**，14.40s，退出码 0 | [日志](validation-canvas.txt) |
| Black，三个修复业务文件 | 通过，3 files would be left unchanged | 本次命令输出 |
| flake8，三个业务文件和持久修复测试 | 11 项既有 C901/F841/F541，退出码 1；规范化行号后与先前 `fix-flake8.txt` 逐项一致，无新增 | [先前记录](fix-flake8.txt) |
| OpenSpec strict | valid，退出码 0 | 本次命令输出 |
| 修复提交 `git diff a4efb042^ a4efb042 --check` | 通过 | 本次命令输出 |

原始输出位于本机 `.tmp/dense-review-final-audit-20261117/`；归档日志只移除 ANSI 颜色和行末空白。原样复跑的两个临时脚本分别为 `.tmp/dense-review-audit-20261117/test_audit.py` 与 `.tmp/dense-review-recheck-20261117/test_followup.py`。本轮未编写新测试或改变其断言。

## 边界与保存

本次没有重复运行完整画布目录。此前完整画布在 `test_rectangle_preview_overlap.py` 原生退出，排除该文件后还有一项测试桩失败；原生退出和失败的开工快照对照见 [实施报告](FIX_IMPLEMENTATION.md)。这些是此前证据，本轮不宣称完整画布目录通过，也不作新的根因结论。

全仓、完整标注/设置/Inspector、CI 排除的工具栏布局和 Windows 点云、真实屏幕/双屏/DPI、性能及减负人工验收均未运行。自动化通过不能替代这些验收。

代码修复已本地提交为 `a4efb042`；本轮只保存独立复核报告、日志和既有 CUSTOM-121/版本管理台账。未推送、未开 PR、未合入；合入目标仍为 `codex/4.2.1-baseline-organization`。
