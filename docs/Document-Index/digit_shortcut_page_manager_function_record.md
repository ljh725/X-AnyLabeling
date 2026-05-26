# Digit Shortcut Page Manager 功能记录

```text
功能名称：
Digit Shortcut Page Manager / DigitShortcutPageManager

修改目的：
将原本仅支持 0-9 单页映射的数字快捷键扩展为可分页管理的快捷键体系，同时保持单页模式的向后兼容。

影响流程：
1. 标注界面启动时创建 `DigitShortcutPageManager`。
2. 管理器根据配置项 `digit_shortcut_pages` 和已有快捷键数量计算总页数。
3. 用户按数字键 0-9 时，当前页码会参与计算，得到实际快捷键索引。
4. 用户按页面切换快捷键时，当前页循环切换，并更新状态提示。
5. `label_widget.py` 通过页面管理器把数字输入映射到当前页的实际快捷项。
6. 快捷键配置保存或更新时，页面数量会同步回配置文件。
7. 配置对话框和标签对话框可读取或刷新页面状态，保持 UI 与配置一致。

依赖锚点：
1. `anylabeling/views/labeling/widgets/digit_shortcut_page_manager.py`
2. `anylabeling/views/labeling/label_widget.py`
3. `anylabeling/views/labeling/widgets/label_dialog.py`
4. `anylabeling/configs/xanylabeling_config.yaml`
5. `anylabeling/views/labeling/widgets/__init__.py`
6. `anylabeling/views/labeling/settings/schema.py`
7. `anylabeling/views/labeling/settings/runtime_applier.py`

改动文件：
1. `anylabeling/views/labeling/widgets/digit_shortcut_page_manager.py`
2. `anylabeling/views/labeling/label_widget.py`
3. `anylabeling/views/labeling/widgets/label_dialog.py`
4. `anylabeling/configs/xanylabeling_config.yaml`
5. `anylabeling/views/labeling/widgets/__init__.py`

验证步骤：
1. 启动标注界面并确认数字快捷键功能可用。
2. 配置多于 10 个的数字快捷项，确认页面总数自动扩展。
3. 按下数字键 0-9，确认当前页的映射索引正确。
4. 按页面切换快捷键，确认页码循环变化并出现状态提示。
5. 保存快捷键配置后重新打开，确认页数配置可持久化。
6. 切换到单页配置，确认行为仍与旧版本一致。

已知副作用：
1. 页数变化会影响同一数字键对应的实际索引，用户需要关注当前页。
2. 如果只配置一页，行为与旧版一致，但仍保留分页逻辑入口。
3. 当当前页超出新的总页数时，会自动回退到有效页。
4. 切换页面会触发状态提示，可能在频繁切页时打断当前操作节奏。

后续注意：
1. 若新增分页快捷键显示区域，需要同步使用 `get_page_info()` 的页码信息。
2. 若修改数字快捷键配置结构，需要同步更新 `update_shortcuts()` 与 `sync_to_config()`。
3. 若上游调整 `label_widget.py` 的数字键入口或状态栏逻辑，需要重新核对页面管理器接管时机。
4. 若 `digit_shortcut_pages` 未来允许更复杂的分页策略，需同步更新配置读取与校验逻辑。
5. 若新增自动扩容规则，要确认不会破坏单页向后兼容。
```
