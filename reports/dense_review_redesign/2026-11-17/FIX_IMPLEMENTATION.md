# FIX_RECHECK 四项遗留修复 · 2026-11-17

本轮落实 F1–F4，专项 18 项通过。目录回归最终结果见下表；不将整个密集复核重设计标为已完成。

## 实现

| 发现 | 修复 | 持久验证 |
| --- | --- | --- |
| F1 | 任务视口复用原图对照的完整恢复路径，保留精确小数比例、FIT_WINDOW/FIT_WIDTH/MANUAL，同步缩放控件、画布几何、导航器和视图记忆 | 原小数/适应窗口往返 + 控件/画布大小往返 + FIT_WIDTH 往返 |
| F2 | 查漏任务对 point 清零全部绘制组件；drawable/hittable 同源失效，矩形轮廓保留 | 真实 QImage 像素无变化 + Canvas 命中不包含隐藏点 |
| F3 | 重开只恢复当前任务显示策略，不再重放上次任务切换的目标快照 | rect1 → 查漏 → 类别 → rect2 → 关闭/重开仍为 rect2 |
| F4 | 普通 hide 在下一事件循环确认持续隐藏后清理；同步浮动/停靠 hide/show 不退出复核；close 继续立即清理 | 下拉 original → 浮动 → 停靠，模式、编辑暂停和目标均保持；真正 hide/close 仍释放覆盖层 |

另将 `test_explicit_region_navigation_still_moves_the_canvas` 的 `or True` 恒真断言改为比较实际缩放/平移。六个补充实验全部提升为持久测试。

## 验证和限制

使用 conda `x-anylabeling-cu12`、PyQt6 offscreen。沙箱内 Qt DLL 被拒绝加载，实际测试在沙箱外运行，未放宽配置隔离和 `.tmp` 写保护。归档日志仅移除 ANSI 颜色与行末空白，原始输出保留在 `.tmp/dense-review-fix-20261117/raw-logs/`。使用真实 get_config 配置会话、`-vv -o faulthandler_timeout=30`、独立 basetemp 和外层 1000 秒硬超时。

| 验证 | 结果 | 证据 |
| --- | --- | --- |
| 专项 | 18 passed，51.77s | [fix-targeted.txt](fix-targeted.txt) |
| 密集复核独立全目录 | 282 passed, 698 subtests passed in 454.38s | [fix-dense.txt](fix-dense.txt) |
| 画布目录（排除原生退出的旧文件） | 691 passed、83 subtests passed；1 failed，16.44s | [fix-canvas-other.txt](fix-canvas-other.txt) |
| 上述失败的开工快照对照 | 同样缺少 update_user_preference；1 failed | [fix-baseline-size.txt](fix-baseline-size.txt) |
| 合并目录/完整画布目录 | 在 test_rectangle_preview_overlap.py 原生退出，码 3221226505（0xC0000409），不能宣称目录全通过 | [合并](fix-regression.txt)、[独立画布](fix-canvas.txt) |
| 原生退出单用例对照 | 当前与开工三个模块快照均以相同异常码退出；`test_nudge_preview_preserves_host_dirty[16777234-False-False]` | [当前](fix-crash-probe.txt)、[开工快照](fix-baseline.txt) |
| 去掉该参数化函数继续运行 | 同文件后续 test_fit_commit_marks_host_dirty 仍原生退出，未改动此旧测试文件 | [fix-canvas-rest.txt](fix-canvas-rest.txt) |
| Black（三个业务文件） | 通过 | [fix-black.txt](fix-black.txt) |
| flake8（三个业务文件及修复测试） | 无新增；11 项既有 C901/F841/F541 与开工快照一致 | [当前](fix-flake8.txt)、[开工快照](fix-flake8-baseline.txt) |
| OpenSpec strict、git diff --check | 通过 | [OpenSpec](fix-openspec.txt)；diff 空白检查通过 |

基线对照使用 `.tmp/dense-review-fix-20261117/before/` 开工源码，通过临时 import loader 替换本轮修改的三个业务模块；未恢复或覆盖工作区。对应依赖保存提交 `5d2d3002`。本轮没有修正其他功能的既有测试桩或对上述原生异常作根因结论。

未运行全仓、完整标注/设置/Inspector、CI 排除的工具栏布局/Windows 点云、真实屏幕/双屏/DPI、性能与减负人工验收。

## 保存与交付

- 起点 `aabbbf63`，沿用 `codex/4.2.1/dense-review-redesign-plan`；该起点含已保存复核报告，工作区已有前轮实现。
- `5d2d3002` 先保存同任务前轮源码、翻译生成物和测试依赖；验证状态按原报告保留，未将前轮失败项当成完成。
- 随后单独提交本轮 F1–F4 三模块修复、回归和记录。`.gitignore`、开发资料不纳入提交。
- 未推送、未开 PR、未合入；合入目标仍为 `codex/4.2.1-baseline-organization`。
- 功能说明：[CUSTOM-121 后续修复](../../../docs/custom_changes/2026-11-17-dense-review-followup-fixes.md)。仅撤销本轮修复时 revert 后续 fix 提交，保留前轮依赖保存点。
