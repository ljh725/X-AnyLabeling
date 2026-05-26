# Keypoint Tool Window 功能记录

```text
功能名称：
Keypoint Tool Window / 关键点补标工具窗口

修改目的：
为关键点补标提供独立窗口，集中展示 person 列表、补标进度和快速切换入口。

影响流程：
1. 主界面打开关键点工具窗口。
2. 窗口扫描当前图像中的 person group。
3. 列表展示各 group 的完成度。
4. 单击切换目标，双击进入补标模式。
5. 选中关键点可跳转到对应补标标签。
6. 新建形状或切图后刷新进度显示。

依赖锚点：
1. `anylabeling/views/labeling/widgets/keypoint_tool_window.py`
2. `anylabeling/views/labeling/widgets/keypoint_fill_mode.py`
3. `anylabeling/views/labeling/label_widget.py`

改动文件：
1. `anylabeling/views/labeling/widgets/keypoint_tool_window.py`
2. `anylabeling/views/labeling/widgets/keypoint_fill_mode.py`
3. `anylabeling/views/labeling/label_widget.py`

验证步骤：
1. 打开关键点工具窗口。
2. 确认 person 列表和进度统计正常显示。
3. 单击和双击不同 group，确认目标切换和补标模式切换正常。
4. 新建关键点后确认窗口刷新。
5. 关闭窗口后再打开，确认窗口可恢复使用。

已知副作用：
1. 窗口刷新依赖当前图像中的 shape 状态，数据变化后需要及时刷新。
2. 自动锁定目标开启时，切换图片可能自动进入补标流程。

后续注意：
1. 若窗口布局变化，需要同步检查 group 列表和关键点状态联动。
2. 若补标模式逻辑变化，需要同步核对窗口中的切换行为。
```
