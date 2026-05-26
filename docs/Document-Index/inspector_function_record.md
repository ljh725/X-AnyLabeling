# Inspector 功能记录

```text
功能名称：
Inspector / 数据检查面板

修改目的：
为标注数据提供结构化检查、问题定位、表格编辑和按规则导出能力，帮助在标注过程中快速发现并修正标签、group_id、形状类型和属性一致性问题。

影响流程：
1. 用户在标注界面打开或切换数据检查面板。
2. 面板从当前 JSON 文件列表构建 FlatIndex，并执行验证规则。
3. 验证结果在问题列表中按规则分组展示。
4. 用户点击问题后，`label_widget.py` 跳转到对应文件并选中对应图形。
5. 用户也可以在数据表格中直接编辑 label、group_id 和 description。
6. 编辑后的内容回写到当前 shape，并触发画布刷新、脏状态更新和局部重扫。
7. 用户可在规则配置页调整共享标签集和规则参数。
8. 用户可将扫描结果按规则导出到子目录中，复制 JSON 与关联图片。

依赖锚点：
1. `anylabeling/views/labeling/widgets/inspector/inspector_panel.py`
2. `anylabeling/views/labeling/widgets/inspector/validation_engine.py`
3. `anylabeling/views/labeling/widgets/inspector/flat_index.py`
4. `anylabeling/views/labeling/widgets/inspector/issue_list_widget.py`
5. `anylabeling/views/labeling/widgets/inspector/editable_table_widget.py`
6. `anylabeling/views/labeling/widgets/inspector/rule_config_widget.py`
7. `anylabeling/views/labeling/widgets/inspector/export_manager.py`
8. `anylabeling/views/labeling/label_widget.py`

改动文件：
1. `anylabeling/views/labeling/widgets/inspector/inspector_panel.py`
2. `anylabeling/views/labeling/widgets/inspector/validation_engine.py`
3. `anylabeling/views/labeling/widgets/inspector/flat_index.py`
4. `anylabeling/views/labeling/widgets/inspector/issue_list_widget.py`
5. `anylabeling/views/labeling/widgets/inspector/editable_table_widget.py`
6. `anylabeling/views/labeling/widgets/inspector/rule_config_widget.py`
7. `anylabeling/views/labeling/widgets/inspector/export_manager.py`
8. `anylabeling/views/labeling/label_widget.py`

验证步骤：
1. 打开标注界面并显示 Inspector 面板。
2. 触发一次扫描，确认问题列表、摘要和统计数量正常。
3. 点击问题条目，确认可跳转到对应文件并定位到指定 shape。
4. 切换到数据表格页，修改 label、group_id 或 description，确认能回写到当前 shape。
5. 调整规则配置并重新扫描，确认结果会随配置变化。
6. 选择导出目录并执行导出，确认 JSON 和图片被复制到规则子目录。
7. 保存后重新刷新 Inspector，确认修改结果被重新索引。

已知副作用：
1. 扫描依赖当前文件列表和规则配置，规则变化后需要重新扫描才能刷新结果。
2. 表格编辑会联动当前画布对象，若当前文件未打开则不会生效。
3. 导出操作是复制而不是移动，可能产生重复的文件副本。
4. 当表格正在编辑时，刷新会被延迟，避免覆盖正在输入的内容。
5. 规则配置会影响所有后续扫描结果，属于全局检查逻辑。

后续注意：
1. 若上游调整 `label_widget.py` 的文件切换或 shape 更新逻辑，需要同步核对 Inspector 的跳转和回写链路。
2. 若新增验证规则，需要同步扩展 `RuleConfigWidget` 的规则注册和 `ValidationEngine` 的执行逻辑。
3. 若新增可编辑字段，需要同步更新 `EditableTableWidget` 和 `_on_inspector_shape_edit()` 的回写分支。
4. 若修改导出策略，需要确认是否仍保持非破坏性复制行为。
5. 若后续拆分 Inspector 子模块，优先保留 `FlatIndex -> ValidationEngine -> IssueList -> LabelWidget` 的主链路。
```
