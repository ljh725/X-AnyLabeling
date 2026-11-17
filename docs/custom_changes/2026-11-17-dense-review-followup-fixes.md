# CUSTOM-121：密集复核 F1–F4 遗留修复

- 状态：已验证（F1–F4 自动化；真实屏幕与整个重设计验收未完成）
- 功能分类：原功能修改
- 创建日期、最后更新日期：2026-11-17（Asia/Shanghai）
- 原始版本与基线提交：4.2.1；`aabbbf63` + 前轮同任务未提交实现。
- 实现提交：前轮依赖保存为 `5d2d3002`；本轮独立修复为 `a4efb042`。
- 工作区已有修改、前置依赖：显示/画布/停靠实现、翻译生成物、密集复核测试及画布配置隔离修复一并保存于依赖提交；`.gitignore` 和开发资料保留未提交。开工快照保存在 `.tmp/dense-review-fix-20261117/`。

## 问题与目标

修复 [FIX_RECHECK.md](../../reports/dense_review_redesign/2026-11-17/FIX_RECHECK.md) 的 F1–F4。此次仅闭环这四项，不将工作区重设计的其余任务、真实屏幕和性能验收标为完成。

## 修改位置与方法

| 文件 / 函数 | 原行为 | 改后行为 | 迁移注意事项 |
| --- | --- | --- | --- |
| label_widget.py / dense_review_restore_view | 仅恢复 scale，FIT_WIDTH 丢失 | 复用完整原图对照视口恢复，同步控件、画布尺寸、滚动/平移、导航器和图像视图记忆，保留三种模式与小数比例 | 保留同图像校验；任务快照 scale 转为精确百分比 |
| display.py / _resolve | 查漏点仅隐藏符号和文字 | 清零点的全部可绘制组件，绘制和命中共同失效 | 只针对点，矩形轮廓不变；不改标注内容 |
| workspace.py / showEvent | 重开恢复旧任务对象快照 | 仅重装任务策略，沿用当前会话对象和当前视口 | 显式任务切换仍恢复各任务快照 |
| workspace.py / hideEvent | 浮动/停靠临时 hide 立即退出 | 下一事件循环确认仍隐藏才清理；close 仍同步清理 | 瞬时 hide/show 保留原图模式、编辑暂停和对象；真正隐藏释放覆盖层 |
| test_workspace_review_fixes.py | 缺少六个行为检查，区域导航有恒真断言 | 固化六个独立复现，浮动与重新停靠双向验证；区域导航比较实际视口变化 | 复用真实 MainWindow 与 get_config 隔离，不放宽写保护 |

## 兼容与数据影响

仅改变显示与窗口生命周期；不迁移配置、标注文件、快捷键或审核数据。保留任务显式切换的目标恢复语义。普通 hide 的覆盖层清理延后到下一事件循环；close 当场清理。

## 验证

- 环境：conda `x-anylabeling-cu12`、Python 3.12、PyQt6 offscreen；沙箱内 Qt DLL 加载拒绝访问，实际窗口测试在沙箱外运行，保留 tests/conftest.py 全部配置隔离。
- 专项：18 passed，51.77s；包含报告中全部六项失败复现。日志：[fix-targeted.txt](../../reports/dense_review_redesign/2026-11-17/fix-targeted.txt)。
- 目录回归：密集复核独立全目录 282 passed, 698 subtests passed in 454.38s；画布排除原生退出旧文件后 691 passed、83 subtests passed、1 failed（该失败和原生退出均在开工快照复现），详情见 [实现报告](../../reports/dense_review_redesign/2026-11-17/FIX_IMPLEMENTATION.md)。合并运行日志见 [fix-regression.txt](../../reports/dense_review_redesign/2026-11-17/fix-regression.txt)。使用 `-vv -o faulthandler_timeout=30`、独立 `.tmp` basetemp、外层 subprocess 1000 秒硬超时。
- Black：本轮三个业务文件 check 通过。flake8：这三个文件与修复测试无新增告警；label_widget.py 有 11 项既有 C901/F841/F541，已对开工副本核实一致，未借本轮重构其他功能。
- OpenSpec strict、git diff --check：通过。
- 未覆盖：全仓、完整标注/设置/Inspector、CI 排除的工具栏布局及 Windows 点云、真实屏幕/双屏/DPI、性能与减负人工验收。

## 迁移与回退

先移植依赖保存提交，再移植本轮 fix 提交。仅回退四项修复时 revert 本轮 fix 提交，保留依赖保存提交和其他功能；本轮 fix 以 F1–F4 专项和受影响目录回归验证。

## 后续修订

| 日期 | 原因 | 实际改动 / 提交 | 验证结果 |
| --- | --- | --- | --- |
| 2026-11-17 | 独立复核 `a4efb042` 的 F1–F4 修复 | 不改业务代码或测试；原样复跑前两轮十四项复现，核对持久回归和修复调用链 | 原复现 14 passed；密集复核 282 passed / 698 subtests；受影响画布十文件 286 passed / 6 subtests；Black/OpenSpec 通过，flake8 无新增；[独立复核报告](../../reports/dense_review_redesign/2026-11-17/FIX_VALIDATION.md) |
| 2026-11-17 | 修复复核剩余四项 P2 | 三处业务模块修复、六个持久行为回归、移除恒真断言 | 专项 18 passed；密集复核 282 passed, 698 subtests passed in 454.38s；画布既有失败见报告 |
