# Digit Rename Manager 功能记录

```text
功能名称：
Digit Relabel Manager / DigitRenameManager

修改目的：
在编辑模式下，为已选中的图形提供 0-9 数字键批量重命名能力，并提供独立的快捷键映射配置界面。

影响流程：
1. 用户在标注界面进入编辑状态并选中一个或多个图形。
2. 用户按下数字键 0-9。
3. `label_widget.py` 先判断当前是否处于重命名模式。
4. 若存在选中对象，则由 `DigitRenameManager.trigger_rename()` 接管按键。
5. 管理器根据 `rename_shortcuts` 查找目标标签并批量修改选中图形的 label。
6. 同步刷新图形列表、唯一标签列表、属性面板和脏状态。
7. 用户可通过 “Digit Relabel Manager” 对话框配置 0-9 的映射并保存到配置文件。

依赖锚点：
1. `anylabeling/views/labeling/widgets/digit_rename_manager.py`
2. `anylabeling/views/labeling/label_widget.py`
3. `anylabeling/configs/xanylabeling_config.yaml`
4. `anylabeling/views/labeling/widgets/__init__.py`
5. `anylabeling/views/labeling/settings/schema.py`

改动文件：
1. `anylabeling/views/labeling/widgets/digit_rename_manager.py`
2. `anylabeling/views/labeling/label_widget.py`
3. `anylabeling/configs/xanylabeling_config.yaml`
4. `anylabeling/views/labeling/widgets/__init__.py`

验证步骤：
1. 打开标注界面并进入编辑模式。
2. 选中一个或多个图形。
3. 配置数字键映射，例如 `1 -> person`。
4. 按下数字键 `1`，确认选中图形标签被批量更新。
5. 检查图形列表、唯一标签列表和属性显示是否同步刷新。
6. 重新打开对话框，确认映射已成功保存并可再次读取。

已知副作用：
1. 仅在编辑模式且存在选中图形时，数字键会被重命名逻辑接管。
2. 如果某个数字键未配置映射，会提示用户先配置快捷映射。
3. 选中多个图形时会统一改成同一个标签，可能覆盖原有分类差异。
4. 若新标签不在唯一标签列表中，系统会自动补入该标签。

后续注意：
1. 后续若修改数字键快捷逻辑，需要同步检查“绘制模式”和“重命名模式”的优先级。
2. 若扩展到更多快捷键范围，需要同时更新配置读取、对话框页数和校验逻辑。
3. 若上游调整 `label_widget.py` 的按键入口，需重新核对 `create_digit_mode()` 的接管条件。
4. 若新增标签验证规则，需同步确认批量重命名时的校验提示是否仍然准确。
```
