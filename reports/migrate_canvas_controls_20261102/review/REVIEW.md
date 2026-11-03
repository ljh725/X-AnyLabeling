# migrate-canvas-controls-from-v430 复核

> 后续状态：原问题及评级已重新复核，见 [P2 复验报告](P2-RECHECK.md)。本页保留初次发现及失败证据；原第二项仅证明与方案延迟策略不一致，不据此证明四极值功能回退，也不代表新增迁移需求。

日期：2026-11-02（Asia/Shanghai）。对象：本地 HEAD `5767933892cb1d0bc37049bdd2e26f5a71418518` 上当前未提交实现及 OpenSpec 文档。复核不修改生产代码、原任务勾选或实施报告，补充用例和结果独立保存在本目录。

结论：发现两项 P2 级规格未兑现，暂不满足完成/归档条件。四种显示模式未发现被加入本轮生产差异；五项能力的总体范围与用户选择一致。

## P2：快速切图保持的是旧缓存而非最新滑块值

- 位置：`anylabeling/views/labeling/label_widget.py:7392-7399`；面板 `set_brightness_contrast` 在目标图加载完成时停止待处理定时器并覆盖滑块。
- 场景：图片 A 亮度/对比度已应用为 70；开启对应保持按钮，将滑块设为 90，在 33ms 节流刷新触发前切换到 B。
- 预期：B 沿用最新设置 90，A 的单图缓存亦不丢失最新输入。
- 实际：B 恢复为 70；最新值尚未写入 `brightness_contrast_values`，随后被目标图同步丢弃。亮度、对比度各一个复现用例均失败（断言 `70 == 90`）。
- 相关规格：`canvas-display-value-retention` 中 Successful image switches / Resets and asynchronous display updates；任务 4.2–4.4。
- 修复建议：离开原图前快照/提交待处理的滑块值到原图显示状态，目标图只使用该稳定快照；不要让旧图延迟渲染在目标图上执行。现有“不保持时防旧事件串图”测试不足以验证开启保持的路径。
- 注意：缓存路径沿用旧实现，本复核不声称这是本轮首次引入的历史回归；这里是本轮明确承诺的保持/快速切图行为未兑现。

## P2：四极值草稿不计入正在进行的交互

- 位置：`anylabeling/views/labeling/widgets/canvas.py:5564-5577`，以及 `label_widget.py::apply_wheel_navigation_mode` 的调用。
- 场景：开始四极值绘制，已接受第一个边界后应用 traditional 模式。
- 预期：草稿仍在进行，继续使用 direct，暂存 traditional 请求，到草稿提交或取消后应用。
- 实际：四极值将未提交状态放在 `rectangle_creation.draft`，而 `canvas.current` 为 None；`interaction_in_progress` 没有检查该草稿，立即切到 traditional 并改变滚动条/视图。补充用例失败（实际 traditional，预期 direct）。
- 相关规格：`canvas-wheel-navigation` 中 Change mode during an active edit；任务 7.1 已勾选，但此路径未满足。
- 修复建议：把本地四极值草稿纳入交互检测；同时核对提交、取消、切工具和换图后 pending 请求的收尾，增加真实结束事件测试，不能只手动调用 pending 方法证明恢复正常。

## 本次验证

- `openspec validate migrate-canvas-controls-from-v430 --strict`：通过；只说明规格结构合法。
- `git diff --check`：通过。
- 现有新增测试六个文件：44 passed（42.90s）。
- 本目录补充用例：7 个，4 passed / 3 failed；两个参数化失败属于同一保持值问题，另一个为四极值草稿问题。
- 补充通过：traditional 适应宽度横向范围检查；大图、小图、长图在实际处理布局事件后的模式往返中心检查。
- 初次沙箱内执行因 Qt/Pillow DLL 拒绝访问而未能收集测试；相同 Conda 环境在获准的沙箱外离屏执行完成。该收集失败未计入产品失败数。
- 环境：`C:/Users/20441/.conda/envs/x-anylabeling-cu12/python.exe`、`QT_QPA_PLATFORM=offscreen`。临时图片/config/QSettings 均位于项目复核临时目录。

现有新增测试命令：

```powershell
$env:QT_QPA_PLATFORM='offscreen'
& 'C:/Users/20441/.conda/envs/x-anylabeling-cu12/python.exe' -m pytest tests/test_canvas/test_fill_opacity.py tests/test_canvas/test_wheel_navigation.py tests/test_labeling/test_canvas_display_retention.py tests/test_labeling/test_review_status_panel.py tests/test_labeling/test_toolbar_display_actions.py tests/test_config/test_wheel_navigation_config.py -q -p no:cacheprovider --basetemp reports/migrate_canvas_controls_20261102/review-pytest-elevated
```

补充复现命令（换一个未占用的 basetemp，避免覆盖既有证据）：

```powershell
$env:QT_QPA_PLATFORM='offscreen'
& 'C:/Users/20441/.conda/envs/x-anylabeling-cu12/python.exe' -m pytest reports/migrate_canvas_controls_20261102/review/test_review_gaps.py -q -p no:cacheprovider --basetemp reports/migrate_canvas_controls_20261102/review-rerun-pytest
```

结果：`review-gaps.xml`（首次六项，2 failed/4 passed）与 `review-extreme.xml`（单独四极值项，1 failed）。

## 完成状态与限制

- 当前任务为 27/31 勾选；7.3、7.4、8.4、8.5 仍未完成，分别涉及视图边界验证、窗口布局/主题/系统缩放、同环境性能复测和人工验收。
- 本复核未执行完整历史回归、真实性能复测或可见窗口人工验收，不将此前报告的 718 项通过冒充本次重跑。
- 规格提案/设计仍有“只生成规划”“尚未实施”的历史描述，实施已发生；后续修订文档时应标注这是提案创建时状态，并链接实施与复核报告。
- 建议在修复上述两项、补齐相应反例回归及剩余验收后再关闭变更；本轮未自行修改任务状态或归档。
