# v4.3.0 画布控件迁移与恢复联合复核

日期：2026-11-04（Asia/Shanghai）。范围：`migrate-canvas-controls-from-v430` 与 `restore-v430-canvas-controls` 的五项画布能力、共享文件及验收证据。用户要求本轮只改任务文档，不实施代码。本轮未修改生产源码、测试源码、翻译、配置模板或 Git 历史；运行测试与探针只在项目 `.tmp` 下生成隔离配置、自制图片及结果。

## 结论与执行归属

当前五项能力的实现和六个专项测试模块均存在，不能再称“当前仍全部丢失”；也不能凭文件存在或既有勾选认定恢复完成。52 项现有专项本轮全部通过，额外探针仍复现两个行为缺陷，另有键位说明与资源交付缺口。当前不满足整体验收条件。

以 [恢复 tasks.md](tasks.md) 为唯一当前执行清单；[迁移 tasks.md](../migrate-canvas-controls-from-v430/tasks.md) 保留原 31 项文字、27 项历史已勾选和 4 项历史未勾选，并逐项映射至恢复任务，不再并行维护可执行勾选框。未归档、删除或发布任何规格；五项同名 delta 未来只同步一次。

调查时实现缺失及后续恢复是历史事实；现有证据不能确认具体 agent、工具或某条 reset 命令导致丢失。当前 HEAD 为 `67c98a80171318f6ced1070c49fc82b2120a22c9`，相关实现大量未提交，HEAD 本身不代表本次所测代码，后续交付仍须完成恢复任务 9.2。

## R1｜P2：切入传统模式时未完成 pan 折算，下一次操作才突跳

- 源码：`label_widget.py::_apply_wheel_navigation_mode_now` 调用 `_apply_shared_view`；后者直接生成 `canvas.pan_offset` 并将滚动条居中，未按传统模式折算/夹紧。`constrain_canvas_pan` 直到下一次 `_apply_zoom` 或 `pan_canvas` 才清除偏移并夹紧滚动条。
- 实际探针：自制 1600×1200 RGB 图，150% 放大，在 direct 中平移，再切换 traditional，处理布局事件后进行 1px 水平平移。
- 结果：切换后图像中心约为 `(199.920, 199.254)`，仍留有 `pan_offset=(900.619, 600.619)`；仅平移 1px 后中心变为 `(364.333, 267.667)`，pan 清零、滚动条夹紧至零。可达边界应在切换时即生效，不应延迟到下一次交互。
- 测试遗漏：既有往返测试只对比切换前后中心；传统平移测试手工将 `pan_offset` 置零，掩盖了切换遗留的偏移。不能因这些测试通过而关闭此问题。
- 后续：恢复 7.3 修复并补正式反例，7.4 扩展边界/导航器/共享视图矩阵，8.2 执行回归。本轮仅记录，未修复。

## R2｜P2：保持按钮保存失败后，配置与两处界面状态分叉

- 源码：亮度/对比度 pin 的 `clicked` 直接连接对应 QAction 的 `trigger`，QAction 的回调调用 `update_user_preference`。失败时该函数恢复 `_config`，但没有同步恢复已经翻转的 QAction/pin。
- 故障注入：使用隔离 MainWindow，将 `persist_user_preferences` 临时替换为返回 `False` 的函数，从关闭状态点击亮度 pin；探针结束恢复原函数。该注入验证失败返回后的界面处理，不代表已经分别完成真实磁盘满/冲突/锁忙测试。
- 结果：`keep_prev_brightness=False`，而 QAction 与 pin 均为 `True`。用户看到“保持”，切图逻辑却仍读取关闭的配置。
- 后续：恢复 5.1 在既有保存链路修复失败状态同步，并对两种保持分别验证失败、重试及重启；8.5 覆盖交错保存。不得新增平行 writer。本轮未改保存代码。

## R3｜P2：实际手势与设置/用户说明不一致

- 当前主画布实际规则：Ctrl+滚轮统一缩放；Alt+滚轮调笔刷或允许编辑的单个未锁定矩形；Alt+Shift+滚轮调对比；裸滚轮依 direct/traditional 决定缩放/滚动。
- `settings/schema.py` 的矩形滚轮说明仍写 `Use Ctrl+Wheel to adjust rectangle geometry while editing. Disabled by default.`。
- `docs/zh_cn/user_guide.md` 本次取样的 267、268、393、483 行仍分别描述旧矩形/笔刷 Ctrl+滚轮和旧对比 Shift+滚轮，并把裸滚轮一概说成缩放；这些说法与已恢复代码矛盾。
- 翻译 `.ts` 仍包含上述设置旧提示的对应翻译；已有笔刷提示更新不能代表所有迁移文案已同步。独立点云界面的 Ctrl+滚轮仍属自身工具规则，不能全仓替换。
- 后续：恢复 8.1 统一实际入口说明和四语言资源。本轮只修改任务文档，未改用户指南、schema 或翻译。

## R4｜交付证据缺口：磁盘翻译通过不能替代打包资源验收

`app.py::load_translator` 优先读取磁盘 `.qm`，失败后回退嵌入资源；此前恢复记录明确 `resources.py` 未重生成。已有 QTranslator 校验能证明所读磁盘文件的文案，不能证明缺少磁盘文件的打包产物会显示同样内容。本轮未构建或验证打包产物，不能断言发布版本一定损坏。

恢复 8.1 保留未完成：未来需重建兼容嵌入资源，或证明实际交付包含并加载新磁盘资源，且缺失/回退路径符合约定。不得为修复此证据缺口而直接覆盖上游整份生成文件或引入无关功能。

## 本轮验证与边界

环境：Windows，已有 Conda `x-anylabeling-cu12` 的 Python 3.12 / PyQt6，`QT_QPA_PLATFORM=offscreen`。普通沙箱首次运行在导入 QtCore 时因 DLL 访问被拒，未执行用例；随后经工具批准在较宽权限下执行离屏测试，未连接用户真实配置。使用既有本地 `pytest_tmp_mode` 插件，仅将临时目录创建权限从 `0o700` 调为可遍历形式；未加载会替换产品保存函数的 `pytest_restore_env` 插件。

本次命令（环境及工作目录均在项目内）：

```powershell
$env:QT_QPA_PLATFORM='offscreen'
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONPATH='D:\X-AnyLabeling-4.2.1\.local\restore-v430-20261104'
& 'C:/Users/20441/.conda/envs/x-anylabeling-cu12/python.exe' -m pytest tests/test_canvas/test_fill_opacity.py tests/test_canvas/test_wheel_navigation.py tests/test_config/test_wheel_navigation_config.py tests/test_labeling/test_canvas_display_retention.py tests/test_labeling/test_review_status_panel.py tests/test_labeling/test_toolbar_display_actions.py -q -p no:cacheprovider -p pytest_tmp_mode --basetemp .tmp/canvas-joint-review-20261104 --junitxml=.tmp/canvas-joint-review-20261104.xml
```

结果：**52 passed，100.62s**。JUnit 见项目 `.tmp/canvas-joint-review-20261104.xml`；隔离探针数值见 `.tmp/canvas-joint-probes-20261104/results.json`。这些临时产物是本机辅助证据，复现步骤和结论已在本文保留；它们不能取代正式回归测试或可恢复交付保存点。

附加探针：traditional 下 1000×3000 长图适应宽度时，水平滚动范围为 0，画布与 viewport 宽均为 1093，本场景未复现横向溢出；不据此宣称极大/极小图矩阵全部通过。人工设置绘制状态后暂存模式，再直接 `reset_state`，可留下 pending；该探针没有覆盖用户实际切图/取消事件链，只作为恢复 7.3 的生命周期测试缺口，不列为已证实用户缺陷。

本轮没有重跑此前 203 通过/1 失败的回归批次及 95 通过的 Inspector/Dense Review 子集，没有执行真实屏幕、性能基准、完整 16 位图切换、打包或配置交错保存联测。新发现不等于旧功能全部失效；历史通过也不等于新缺陷不存在。

## 勾选与文档纠正

| 恢复任务 | 本轮处理依据 |
| --- | --- |
| 2.1 | 恢复前反例当时未运行；只能独立重建补证或明确保留缺口，不能补造历史。 |
| 2.2 / 2.4 | 区分此前两批回归、本轮 52 项及额外探针；纠正“Inspector 未运行”和已有 95 项记录的矛盾。 |
| 2.3 | 现有变更落点表不能替代三方职责保留矩阵，撤回勾选。 |
| 3.3 | 现有填充测试主要覆盖矩形，未完成混合图形/独立笔刷/实际创建预览的完整验收，撤回勾选。 |
| 5.1 / 5.3 | R2 与未测 16 位灰度/传统共享视图，撤回勾选，保留已通过子场景。 |
| 6.3 | 动作存在和标签 QAction 切换不能替代八类联动及成组撤销，撤回勾选。 |
| 7.1 / 7.2 / 7.3 | 分别补设置端到端语义、锁定/多选/外侧调边历史矩阵，以及 R1 和交互结束生命周期，撤回勾选。 |
| 8.1 / 8.2 | R3/R4 与新缺陷尚无正式回归，撤回勾选；52 项通过仍如实保留。 |
| 8.3–8.5 / 9.2 | 性能、真实屏幕、配置联测和独立交付继续未完成；更新过时依赖描述。 |
| 9.1 / 9.3 | 合并映射和复核记录已更新；strict 与文档差异检查以本次实际执行结果补记。 |

原迁移清单引用的 `reports/migrate_canvas_controls_20261102/REPORT.md` 当前不存在，已改为指向现存 REVIEW/P2 复验和恢复证据。`verification.md` 的历史任务编号存在错位，本轮加更正及最新复核入口。原 proposal/design 中“仅创建方案”“当前功能缺失”等描述属于立项时点，不能据此覆盖当前状态；本轮保留其历史设计语境，最新验收状态以执行清单和本文为准。

## 文档修订验证

- `openspec validate restore-v430-canvas-controls --strict`：通过。
- `openspec validate migrate-canvas-controls-from-v430 --strict`：通过。
- `git diff --check -- openspec/changes/restore-v430-canvas-controls openspec/changes/migrate-canvas-controls-from-v430/tasks.md`：通过；仅提示迁移文档后续 Git 操作将归一化 CRLF/LF。
- 文档本地链接、当前任务编号唯一性和历史迁移完整性检查：通过。恢复清单为 31 项（15 项勾选、16 项未勾选），迁移清单完整保留 31 项历史状态，其中 4 项原未完成已移交，未把它们标成完成。

本轮收尾取样的相关源码 SHA-256 如下，仅用于识别复核现场；不能替代测试前后全量快照或未来可恢复交付点：

| 文件（均在 `anylabeling/views/labeling/` 下） | SHA-256 |
| --- | --- |
| `label_widget.py` | `76ac27da252b95b7bf73e55560c5bbecc0974ad6e35e8601e1f09fe057364290` |
| `widgets/canvas.py` | `dcf259eb575a71607a39089070aa4987a2b889cba3729a6152f5a1337064902d` |
| `widgets/canvas_adjustment.py` | `15e11dddcf098d81ff9179c99a88a7c3ce1543bc8d05bdce71a89e80c6ed529c` |
| `widgets/toolbar.py` | `8571ae3ed4e0001c246be6549e286584708e8586851237f145f2a84f6ade2321` |
| `shape.py` | `5130aa2dd3845ffcd7c8b887fafb343fa45780c69dce472d82a89819f8f17dc8` |
