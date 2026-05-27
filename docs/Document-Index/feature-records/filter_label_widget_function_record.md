# Filter Label Widget 功能记录

```text
功能名称：
Filter Label Widget / 标签筛选控件

修改目的：
为标注界面提供 label、group_id、shape_type 三维筛选入口，并驱动当前画布的可见性过滤。

影响流程：
1. 用户在筛选控件中选择标签、组号或形状类型。
2. `LabelFilterComboBox`、`GroupIDFilterComboBox`、`ShapeTypeFilterComboBox` 触发回调。
3. `label_widget.py` 更新内部 `FilterState`。
4. 过滤引擎重新计算当前可见对象。
5. 画布、列表和导航视图同步刷新。

依赖锚点：
1. `anylabeling/views/labeling/widgets/filter_label_widget.py`
2. `anylabeling/views/labeling/label_widget.py`
3. `anylabeling/views/labeling/filter_state.py`
4. `anylabeling/views/labeling/filter_engine.py`

改动文件：
1. `anylabeling/views/labeling/widgets/filter_label_widget.py`
2. `anylabeling/views/labeling/label_widget.py`

验证步骤：
1. 打开标注界面并加载带多个 label / group / shape_type 的数据。
2. 逐个切换筛选项，确认可见对象随之变化。
3. 清空筛选项，确认恢复完整显示。
4. 检查筛选菜单和下拉框是否与当前数据同步。

已知副作用：
1. 筛选会影响可见性，可能让当前对象暂时不可见。
2. 筛选项依赖当前数据集，跨图像时会动态更新。

后续注意：
1. 若新增筛选维度，需要同步扩展 `FilterState` 与 `ShapeFilterEngine`。
2. 若筛选状态持久化策略变化，需要确认下拉框回填逻辑仍然正确。
```
