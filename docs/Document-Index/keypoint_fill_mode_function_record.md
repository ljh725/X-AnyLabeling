# Keypoint Fill Mode 功能记录

```text
功能名称：
Keypoint Fill Mode / 关键点补标模式

修改目的：
基于 person 的 group_id 自动推进关键点补全，减少关键点标注时的重复操作。

影响流程：
1. 用户选择一个带 group_id 的 person 框。
2. 模式计算该 group 中缺失的关键点。
3. 新建点时自动继承当前 label 和 group_id。
4. 每完成一个点，自动推进到下一个缺失关键点。
5. 全部关键点完成后自动退出模式。
6. 可根据当前图形变化刷新缺失列表。

依赖锚点：
1. `anylabeling/views/labeling/widgets/keypoint_fill_mode.py`
2. `anylabeling/views/labeling/label_widget.py`

改动文件：
1. `anylabeling/views/labeling/widgets/keypoint_fill_mode.py`
2. `anylabeling/views/labeling/label_widget.py`

验证步骤：
1. 选中一个带 `group_id` 的 person 矩形框。
2. 进入关键点补标模式。
3. 新建关键点，确认 label 和 group_id 自动写入。
4. 连续补点，确认补标顺序正确。
5. 补完后确认模式自动退出。

已知副作用：
1. 模式依赖当前 group 的关键点状态，外部改动可能导致补标序列变化。
2. 激活后会接管点标注流程，用户需要关注当前模式状态。

后续注意：
1. 若关键点顺序变化，需要同步更新 `KEYPOINT_ORDER`。
2. 若自动激活策略变化，需要同步检查 `label_widget.py` 的调用点。
```
