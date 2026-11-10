## Why

当前 Inspector 已能检查、定位和复查，但日常界面同时展示大量判定与高级操作，上一个／下一个只切换表格选择，用户仍需反复定位。用户已确认以“检查出不符合规则的数据 → 在原主画布修改或删除 → 保存复查 → 下一个问题”为主流程，并明确要求第二屏独立窗口及 F1／F2 导航。

## What Changes

- 精简 Inspector 默认界面，保留规则与范围、开始／取消检查、问题队列、简短原因、对象选择、忽略和保存并复查；历史、导入导出、外部候选、密集复核等既有能力移到“更多”，详细证据按需展开。
- 保持独立、非模态、可移动和缩放的 Inspector 窗口，可放在第二屏；不嵌入主窗口、不占用主画布，不新增图片预览、缩略图或第二套标注画布。
- 显式选中问题即调用原主窗口导航，切换到对应图片并定位已有对象或问题区域；修改、改类和删除沿用现有主画布及保存／撤销链路。
- 一组“上一个问题／下一个问题”按钮及默认 **F1／F2** 快捷键，按当前筛选结果跨图片、跨分页导航；在原主窗口编辑和 Inspector 激活时均生效。
- 提供“待处理／已解决／已忽略”简洁视图；保留底层人工判断、动作和机器验证状态，不能把声明修改或忽略视作复查成功。
- 将“保存并复查”串联为一次明确操作，提供“通过后进入下一个问题”选项；保存失败、复查失败或问题仍命中时不自动推进。
- 补齐导航取消、窗口焦点、快捷键配置、双屏及小窗口验收，更新中文操作说明与相关翻译。

## Capabilities

### New Capabilities

- `inspector-focused-review`: 独立检查窗口的精简界面、单主画布处理、问题状态及保存复查流程。
- `inspection-result-navigation`: 显式选择问题、F1／F2 双窗口导航、筛选分页边界、焦点与取消保护。

### Modified Capabilities

无。当前 `openspec/specs/` 无已发布主规格；本变更增补当前代码行为契约，依托既有 `refactor-data-inspector-workflow` 与 `polish-inspector-dense-review-ui` 的实现，不重新创建检查引擎，也不改写这些变更的未完成验收项。

## Impact

- 主要涉及 `anylabeling/views/labeling/inspector/dialog.py`、`label_widget.py` 中的 Inspector 桥接，及必要的窗口内导航协调代码。
- 快捷键涉及 `anylabeling/configs/xanylabeling_config.yaml`、`settings/schema.py`、`settings/runtime_applier.py`；新键沿用配置、冲突检测和即时更新机制。
- 相关测试位于 `tests/test_inspection/` 及现有设置／主窗口导航测试；同步 `docs/zh_cn/inspector.md`、本地化资源及本变更验收记录。
- 不新增依赖，不修改规则算法、标注格式或既有报告／反馈语义；不自动删标注、图片或标注文件，不改变图片正式审核状态。
- 本次交付仅为规划文档与已确认效果图，实施任务全部保持未完成。
