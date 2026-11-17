## Why

数字快捷键绘制矩形后，若关闭标签弹窗且类别列表预选了其他类别，JSON 会写入预选类别，而非数字键绑定类别；矩形坐标和文件写入虽正常，标注语义却已错误。2026-11-04 的复核在自动/手动保存及两种输出位置组合中均复现，需要记录为独立修复任务。

## What Changes

- 让普通矩形绘制完成时，数字键绑定类别优先于类别列表预选值、复用上次类别及标签弹窗设置。
- 正确消费本次绘制的待应用类别，避免成功提交后仍保留旧绑定。
- 验证自动保存、Ctrl+S 和保存重开均保持绑定类别及矩形坐标。
- 保留数字键选中对象改类、自动标注特殊标记和普通非数字绘制的既有行为。
- 本轮仅生成 OpenSpec 文档和待实施任务，不修改业务代码、测试代码或配置，不执行修复。

## Capabilities

### New Capabilities

- `digit-rectangle-label-save`: 定义数字键绘制矩形的类别优先级、绑定消费及保存重载一致性要求。此处为现有功能补充规格，不新增用户操作入口。

### Modified Capabilities

无。当前 `openspec/specs/` 中没有可直接修改的对应能力规格。

## Impact

- 计划修复入口：`anylabeling/views/labeling/label_widget.py` 的 `create_digit_mode()` / `new_shape()`；优先在普通绘制的类别解析阶段解决。
- 回归范围：`tests/test_labeling/test_digit_rectangle_save.py`、`test_digit_label_actions.py`、`test_label_file_save.py`，按实际改动补充相邻行为用例。
- 不变更 JSON 格式、数字键配置格式或依赖，不批量改写既有标注；历史错存类别无法仅凭现有 JSON 可靠推断，不自动修复。
- 依据：`reports/digit_rectangle_save_20261104/REVIEW.md`、`results.xml` 和 `known_issue.xml`。首次完整复核为 35 passed、4 failed；四项已知缺陷目前以严格 xfail 保留，并非已修复。
