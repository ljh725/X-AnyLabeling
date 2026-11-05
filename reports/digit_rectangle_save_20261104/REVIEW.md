# 数字快捷键矩形保存复核

日期：2026-11-04。范围：当前工作区代码；仅新增复核测试和报告，未修改业务逻辑。

## 结论

已配置数字键对应矩形模式及类别时，正常流程可以完成画框、写入 JSON，并在重新打开图片后恢复矩形及坐标。发现一个类别赋值缺陷，不能认为所有配置下都正确保存。

## 发现：[P2] 关闭标签弹窗后，预选类别覆盖数字键绑定类别

位置：`anylabeling/views/labeling/label_widget.py:7437–7452`，`new_shape()`。

复现步骤：

1. 将数字键 3 配置为 `rectangle`，绑定类别“车辆”。
2. 关闭 `display_label_popup`（标签弹窗）。
3. 在类别列表 `unique_label_list` 中选中“其他类别”，画布中不选中任何矩形。
4. 按 3，用两次鼠标点击完成矩形。
5. 自动保存或按 Ctrl+S，然后检查 JSON。

实际：文件存在、矩形四个顶点正确，但 `shapes[0].label` 为“其他类别”。

预期：`shapes[0].label` 应为数字键绑定的“车辆”。

原因：`new_shape()` 先读取类别列表的选中值。关闭弹窗且已有选中类别时，不进入包含 `digit_to_label` 消费逻辑的分支，所以预选类别被写入，数字键绑定值也未被清除。

影响：自动保存、手动保存，以及图片同目录、独立输出目录的四种组合均复现。默认 `display_label_popup: true` 下未复现。临时可启用标签弹窗，或取消类别列表中的预选类别。

建议：完成普通绘制时优先消费待应用的数字键绑定类别，再处理类别列表选中值或弹窗设置；保留自动标注特殊标记的处理顺序。

## 验证

环境：Windows，Python 3.12.12，PyQt6 6.10.2，Qt offscreen。使用真实主窗口、数字键事件、两次鼠标点击和 Ctrl+S，检查实际写入的 JSON，并通过 `load_file()` 重新打开。配置、QSettings、图片和标签文件均隔离在项目测试临时目录。

新增测试：`tests/test_labeling/test_digit_rectangle_save.py`。

- 16 种组合：自动/手动保存 × 同目录/输出目录 × 弹窗开/关 × 类别列表有/无预选。
- 分别验证 0–9 十个数字键。
- 保存后核对类别、矩形类型、四个顶点、图片尺寸，重新加载核对类别和坐标。
- 联合运行现有 13 个数字键行为测试。

首次完整结果：**35 passed，4 failed**。四项失败全部是上述错存类别问题，详见 `results.xml`。

已将这四种已知缺陷场景标记为严格 `xfail`，保留断言和复现能力；修复后测试会变为 XPASS 并提示移除此标记。这不表示业务缺陷已修复。

复现命令（PowerShell）：

```powershell
& 'C:/Users/20441/.conda/envs/x-anylabeling-cu12/python.exe' -m pytest tests/test_labeling/test_digit_rectangle_save.py tests/test_labeling/test_digit_label_actions.py -q --tb=short --color=no -p no:cacheprovider --basetemp .tmp/digit-rectangle-save-review-new
```

另对四项严格 xfail 及已有 `test_label_file_save.py` 的写入/失败保护测试做了复核，结果见 `known_issue.xml`。
