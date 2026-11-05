# CUSTOM-110：密集标注复核工作流

- 状态：实施中（自动化验证通过；人工试用、性能门槛、翻译与训练导出往返未完成）
- 功能分类：新增本地能力
- 创建日期、最后更新日期：2026-11-02（Asia/Shanghai）
- 原始版本与基线提交：X-AnyLabeling 4.2.1；实现基线 `9a37c5474c390e93243e33a88e8232a19c833280`
- 实现提交 / PR：尚未提交；当前实现位于工作区
- OpenSpec：`openspec/changes/add-dense-annotation-review-workflow/`
- 验证记录：[verification.md](../../openspec/changes/add-dense-annotation-review-workflow/verification.md) · [实施报告](../../reports/dense_review_workflow_20261102/REPORT.md)

## 问题与目标

密集课堂图片通常有约 30 个重叠矩形和 6 类动作。颜色、普通对象列表和反复缩放不足以支持类别判断与精确调框；逐对象强制打勾又会抵消收益。目标是默认自由编辑、批次结束一次确认正确/已修正对象，同时把类别与框确认、疑难/暂跳、空间查漏和内容失效分开记录。

不在本项中：新模型推理、自动按置信度通过、自动补全遮挡框、多用户合并、跨图重识别、首版非矩形编辑。

## 基线、备份与依赖

- 实施基线：`9a37c547`；工作区在本功能前已有 Inspector 等未提交改动，本功能只追加密集复核相关文件与精确差异。
- 现有远端备份：分支/标签 `backup/refactor-data-inspector-workflow-20261102` 指向 `9a37c547`。
- 本功能本地基线标签：`backup/add-dense-annotation-review-workflow-20261102`，已核验指向 `9a37c5474c390e93243e33a88e8232a19c833280`；尚未推送远端。
- 当前实现尚未提交；提交前应先按台账保存并核对远端 SHA。
- 依赖：现有持久 Shape 身份、编辑命令、撤销、dirty/自动保存、手动隐藏、锁定、形状筛选和分阶段加载。

## 实际修改

| 文件 / 目录 | 原行为 | 改后行为 |
| --- | --- | --- |
| `anylabeling/services/dense_review/` | 不存在 | 纯 Python 状态、签名、账本、批次、覆盖、配置、存储与会话 |
| `anylabeling/views/labeling/dense_review/` | 不存在 | 非模态工作区、配置编辑器、卡片懒缩略图、比较、查漏页 |
| `label_widget.py` | 无入口/进度 | Workflow 菜单入口、会话生命周期、保存注入、外部冲突、聚焦/全图、排除项、撤销 |
| `widgets/canvas.py` | 无查漏覆盖 | 临时虚线区域，仅显示，不改标注 |
| `configs/xanylabeling_config.yaml` | 无本功能快捷键 | 6 个可配置快捷键 |
| `settings/schema.py` | 无本功能快捷字段 | 新增 Dense Review 分组与标签 |
| `services/inspection/handoff.py` | 声明密集复核不可用 | 改为可用，协议 `dense-review.v1` |
| `tests/test_dense_review/` | 不存在 | 70 项服务与 GUI 集成测试 |

## 数据契约与兼容

- 顶层可选字段：`xanylabeling_dense_review`，版本 1。
- 内容：图像指纹/尺寸、规则签名、对象确认签名、批次成员与游标、新增待处理、查漏计划/区域基线、当前维度。
- 不写入 shape；不改变旧 `checked`、`review_status`、图片级验收或其他扩展字段。
- 旧文件无该字段按尚未开展处理；未知版本/损坏内容保留原内容并显示不可恢复，用户显式重建前不覆盖。
- 图像像素变化重置对象确认与查漏覆盖；规则变化保守失效；仅几何/类别内容变化按对象和区域失效。
- 矩形使用规范化边界，等价点序/整数浮点不误失效；真实微坐标变化仍失效。
- 保存沿用现有原子写入；保存失败保留内存进度与 dirty；外部文件变化保存前要求明确选择。

## 验证

实际运行（2026-11-02，`C:/Users/20441/.conda/envs/x-anylabeling-cu12/python.exe`，Python 3.12.12 / PyQt6 6.10.2 / Qt 6.10.0，`QT_QPA_PLATFORM=offscreen`）：

| 检查 | 结果 |
| --- | --- |
| `tests/test_dense_review` | **70 passed** |
| `tests/test_inspection` | **80 passed** |
| 定向 labeling | **72 passed, 15 subtests** |
| labeling 全量 | **192 passed, 8 failed**, 45 subtests |
| canvas | **578 passed, 1 failed**, 83 subtests |
| widgets | **29 passed, 3 failed**, 2 subtests |
| settings 单文件 | schema 7；controller 13；dialog/runtime/shape 21 passed, 1 skipped, 9 subtests |
| utils/config | **85 passed, 8 skipped**, 28 subtests |
| OpenSpec strict | 通过 |
| flake8/Black/compileall/`git diff --check` | 通过 |

既有失败与 Inspector 基线记录一致：canvas 固定标签宽度、widgets 亮度/工具栏、labeling 的 `SimpleNamespace`、Windows 路径/标题和临时文件权限。`tests/test_settings` 整目录一次运行出现原生访问冲突，各文件单独通过，未记为通过。

## 未完成 / 未验证

- 真实屏幕与授权密集样本的人工验收；offscreen 截图不能替代真实字体度量与观感检查。
- 性能（10.2）：暖缓存切换与 GUI 心跳在 30/300 对象均达标；拖框回退在 300 对象达标（+8.7%/+8.2%），30 对象未达标（+18.9%/+24.8%，绝对 p95 5.5–5.8ms），需真实屏幕与更高样本复核。
- 两位实际使用者对照试用、独立质量复核和减负结论（10.4/10.5）。
- ja_JP/ko_KR 仍有 413 条历史未翻译；打包产物的 `resources.py` 仍嵌入旧 `.qm`，需在具备兼容 rcc 的机器重生成。
- 完整虚拟列表、小窗口专用收起控件（不属于本变更验收门槛）。

## 迁移与回退

- 进入：Workflow → Dense Review；默认关闭，不影响普通画布。
- 配置：数据集或输出目录下 `.xanylabeling/dense_review/config.json`；未配置时全部进入“其他待处理”，未知框规则保守失效。
- 回退代码：删除两个新增包与测试，还原主窗口/画布/设置/配置/Inspector handoff 的本功能差异。
- 回退数据：保留 `xanylabeling_dense_review` 原内容，不解释为旧审核通过；需要清理时先备份并显式删除。

## 后续修订

| 日期 | 原因 | 实际改动 | 验证结果 |
| --- | --- | --- | --- |
| 2026-11-02 | 首版实施 | 新增服务、工作区、主窗口接入、配置/快捷键、Inspector handoff 与 70 项测试 | 自动化通过；人工/性能/翻译未完成 |
| 2026-11-02 | 评审补强 | 批次确认无画布编辑时也可撤销；快捷疑难留空；默聚焦；缩略图失败文案；无效边界可持久化；外部移动/删除覆盖失效 | `tests/test_dense_review` 70 passed |
| 2026-11-02 | 修复评审 F1-F4 | 缩略图缓存按边界/上下文/源版本键控并丢弃同 ID 旧请求；连续审核撤销按剩余动作顺序；全图返回保留用户倍率；统一历史按真实顺序记录审核与内容变更 | 新增 7 项探针，`tests/test_dense_review` 70 passed；见 [评审响应](../../reports/dense_review_workflow_20261102/REVIEW-RESPONSE-20261102.md) |
| 2026-11-02 | 修复第二轮 R2-1/R2-2 | 每条事务持有完整审核快照，重复内容不再覆盖早期确认；审核/编辑事务与快照统一保留最近100条 | 密集复核与三轮独立探针合跑 **85 passed in 44.80s**；见 [修复记录](../../reports/dense_review_workflow_20261102/ROUND2-UNDO-FIX-20261102.md) |
| 2026-11-03 | UI 重构（P0） | 接入 `get_dialog_style()` + `get_workbench_qss()`；顶部进度条 + 单行工具条；批次改卡片；卡片流加状态色条/底板/角标并按宽度自适应列数；操作条单行化；查漏区域行渲染器 | `tests/test_dense_review` 78 passed；截图见 `reports/ui_review_20261103/`；详见 [实施记录](../../reports/ui_review_20261103/UI-IMPLEMENTATION.md) |
| 2026-11-03 | UI 打磨（P2，`feat/ui-polish-p2`） | 查漏页新增网格示意图并与列表联动；五个快捷键改 `WindowShortcut`，按钮 tooltip 按实际绑定生成；主操作图标 | `tests/test_dense_review` 87 passed；见 [验证](../../openspec/changes/polish-inspector-dense-review-ui/verification.md) 与 [P2 实施记录](../../reports/ui_review_20261103/UI-P2-IMPLEMENTATION.md) |
| 2026-11-03 | 补齐剩余验收项 | 重做栈与统一 LIFO 历史（`Ctrl+Shift+Z`）；四语言翻译与 `load_translator` 磁盘回退；自制 7 场景样本与生成器；延迟注入、训练导出往返、翻译覆盖测试；性能基准与拖框让路（worker 解码、按 tick 限量、指针按下暂停卡片后台）；用户手册与截图 | `tests/test_dense_review` **123 passed**；`tests/test_canvas` 578 passed/1 基线失败；`tests/test_labeling` 192 passed/10 failed（8 基线+2 沙箱临时目录）；性能见 `perf_reports/dense_review/performance-20261103/`；10.2 部分达标，10.4/10.5 未做 |
| 2026-11-05 | 按 11-04 复核补齐代码 | 在已有未提交的导航、虚拟卡片和异步比较实现上补齐逐框/暂跳跨批及保存游标顺序、查漏重开定位、图块任务/结果共同容量限制与取消、比较重试与清理；补四语言主体/动态提示及内嵌资源，修正性能终点和真实切图测量 | 完整结果与原始证据见 [实施记录](../../openspec/changes/add-dense-annotation-review-workflow/implementation-20261105.md)。当前 61/66 项勾选；最终离屏性能门槛通过，人工屏幕/质量试用和大范围 Qt 合跑问题仍保留，未归档 |
