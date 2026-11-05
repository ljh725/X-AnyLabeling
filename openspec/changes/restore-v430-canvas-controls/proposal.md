## Why

此前从 v4.3.0 选择性迁入的五项画布能力已从当前工作区丢失，但原迁移任务仍标记为已实施，导致实际按钮和操作行为与记录不符。已找到与历史复验指纹一致的源码对象，需要在保留当前密集审核等成果的基础上恢复，并补齐可恢复交付证据。

## What Changes

- 恢复可视化工具栏、两种滚轮导航模式、面板三态审核入口、仅填充透明度、三项显示参数保持，共五项既定能力。
- 实施前保存当前完整工作区与未跟踪文件；将可恢复 Git 对象导出并校验，按功能差异合并到当前代码。
- 恢复对应配置、专项测试、图标和四语言资源；验证 Inspector、密集审核、本地矩形编辑、共享视图及分阶段加载兼容。
- 建立功能—源码—测试—提交对照，修正历史迁移状态与当前实现不一致的问题。
- 范围沿用 `migrate-canvas-controls-from-v430`，不整版升级，不引入四种显示模式、MultiTask、OCR、测量、旋转或跳图步长改造。

## Capabilities

### New Capabilities

以下五个名称沿用原迁移的待归档 delta；当前主规格目录没有对应已发布规格。本变更承接恢复交付，实施时须统一两份变更的证据与状态，不能重复导入主规格。

- `canvas-visualization-toolbar`: 恢复既有显示动作的工具栏入口与窄窗口可达性。
- `canvas-wheel-navigation`: 恢复 direct/traditional 模式、滚轮优先级和视图一致性。
- `canvas-review-status-controls`: 恢复面板三态图片审核及既有状态同步。
- `annotation-fill-opacity`: 恢复仅作用于填充的透明度行为。
- `canvas-display-value-retention`: 恢复透明度、亮度、对比度独立跨图保持。
- `canvas-controls-recovery`: 可验证的恢复来源、既有定制保留和交付完整性。

### Modified Capabilities

无。此处的 New 表示尚未形成主规格，不表示本轮扩大原迁移功能。

## Impact

- 主要涉及 `label_widget.py`、`widgets/canvas.py`、`widgets/canvas_adjustment.py`、`widgets/toolbar.py`、`shape.py`、配置与 settings schema/runtime、资源和受影响测试。
- 原迁移来源固定为上游 v4.3.0 `74407f633b61a8ff6adc0e7eafbafa6856825759`；优先使用本地适配后且指纹可核验的源码，不整体检出上游版本。
- 不改变标注 JSON 格式或训练导出语义，不回滚当前 Inspector / Dense Review UI 与未提交实现，不新增运行时依赖。
- 配置保存缺陷由独立变更 `fix-user-settings-persistence` 负责；共享文件按差异衔接，最终配置保持验收以该修复完成后的集成结果为准。
- 本轮仅创建方案；备份、源码恢复、历史状态修正与提交均为后续实施任务。
