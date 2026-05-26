# 四个功能总结

## 1. `file_dialog_preview.py`

```text
功能名称：
文件选择预览窗口

功能作用：
在打开文件对话框时，实时预览当前选中的 JSON 或图片文件，提升文件选择效率。

核心流程：
1. `FileDialogPreview` 替换默认文件对话框。
2. 当用户切换选中文件时触发 `currentChanged`。
3. 若是 JSON，则读取并格式化显示内容。
4. 若是图片，则加载并缩放显示预览图。
5. 不能解析的文件则隐藏预览区域。

依赖锚点：
`anylabeling/views/labeling/widgets/file_dialog_preview.py`
`anylabeling/views/labeling/label_widget.py`

注意点：
只负责预览，不修改文件内容。
```

## 2. `filter_label_widget.py`

```text
功能名称：
标签 / Group ID / 形状类型筛选控件

功能作用：
提供三个下拉筛选器，用于按 label、group_id 和 shape_type 过滤当前标注数据。

核心流程：
1. 三个 `QComboBox` 分别展示标签、组号和形状类型。
2. 用户切换选项后回调 `label_widget.py` 的筛选处理函数。
3. `label_widget.py` 更新内部过滤状态并刷新可见形状。
4. 筛选项会根据当前数据集动态更新。

依赖锚点：
`anylabeling/views/labeling/widgets/filter_label_widget.py`
`anylabeling/views/labeling/label_widget.py`

注意点：
它是筛选入口，本身不执行过滤逻辑。
```

## 3. `keypoint_fill_mode.py`

```text
功能名称：
关键点补标模式

功能作用：
基于 `group_id` 自动推进 COCO 关键点补全流程，并在新建点时自动分配 label 和 group_id。

核心流程：
1. 激活时读取当前 group 中已存在的关键点。
2. 计算缺失关键点列表并进入循环补标状态。
3. 新建点时自动写入当前 label 和 group_id。
4. 每补一个点就推进到下一个缺失关键点。
5. 组内关键点补完后自动退出模式。

依赖锚点：
`anylabeling/views/labeling/widgets/keypoint_fill_mode.py`
`anylabeling/views/labeling/label_widget.py`

注意点：
它负责“补标状态机”，不负责窗口展示。
```

## 4. `keypoint_tool_window.py`

```text
功能名称：
关键点补标工具窗口

功能作用：
提供独立浮动窗口，展示 person 列表、关键点进度和当前补标状态，支持切换目标组并进入补标模式。

核心流程：
1. 扫描当前图像中的 person group。
2. 统计每个 group 的完成度并展示列表。
3. 单击切换目标，双击进入补标模式。
4. 选中关键点可快速跳转到对应标签。
5. 新建形状或撤销后可刷新进度显示。

依赖锚点：
`anylabeling/views/labeling/widgets/keypoint_tool_window.py`
`anylabeling/views/labeling/widgets/keypoint_fill_mode.py`
`anylabeling/views/labeling/label_widget.py`

注意点：
它是 UI 容器和操作面板，实际补标逻辑仍由 `KeypointFillMode` 执行。
```

## 总结

这四个模块分别覆盖了“文件选择预览”“数据筛选”“关键点补标状态机”“关键点补标工具窗口”，共同构成标注界面里的辅助工作流。
