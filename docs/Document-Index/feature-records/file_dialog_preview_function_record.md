# File Dialog Preview 功能记录

```text
功能名称：
File Dialog Preview / 文件选择预览窗口

修改目的：
在打开文件对话框时提供 JSON 和图片的即时预览，降低找文件和确认内容的成本。

影响流程：
1. 用户在主界面触发打开文件。
2. `FileDialogPreview` 替换默认文件对话框。
3. 选中文件变化时触发预览更新。
4. JSON 文件显示格式化文本内容。
5. 图片文件显示缩放预览图。
6. 无法解析的文件自动隐藏预览区。

依赖锚点：
1. `anylabeling/views/labeling/widgets/file_dialog_preview.py`
2. `anylabeling/views/labeling/label_widget.py`

改动文件：
1. `anylabeling/views/labeling/widgets/file_dialog_preview.py`
2. `anylabeling/views/labeling/label_widget.py`

验证步骤：
1. 打开文件对话框。
2. 依次选择 JSON 文件和图片文件。
3. 确认预览区分别显示格式化文本和图片。
4. 选择不支持的文件，确认预览区隐藏。

已知副作用：
1. 预览 JSON 时会直接读取文件内容，文件异常会影响预览显示。
2. 大图会被缩放，预览内容不会保持原始尺寸。

后续注意：
1. 若后续支持更多文件类型，需要同步扩展 `on_change()` 的分支。
2. 若打开文件流程调整，需要确认 `FileDialogPreview` 仍然被正确替换。
```
