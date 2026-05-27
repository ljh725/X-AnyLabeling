# Filter State Persistence 功能记录

```text
功能名称：
Filter State Persistence / FilterState

修改目的：
提供一种统一、不可变的筛选条件表示方式，支持序列化/反序列化，
使筛选状态可以在组件间传递、持久化到配置文件、并在程序重启后恢复。
原始实现中筛选条件分散在多个变量中，缺乏统一抽象，导致状态同步困难。

影响流程：
1. 用户通过 FilterLabelWidget 设置筛选条件（标签、GID、Shape Type）。
2. 条件被封装为 FilterState 对象，经过规范化处理（空 gid → "-1"，空 labels → set()）。
3. FilterEngine 使用 FilterState 执行查询（逐文件扫描或索引查询）。
4. FilterNavigationEngine 使用 FilterState 维护筛选结果列表和当前位置。
5. 筛选状态通过 to_dict() / from_dict() 保存到配置文件，实现持久化。
6. 程序启动时从配置恢复上次的筛选条件（如果用户启用了保存筛选）。

依赖锚点：
1. `anylabeling/views/labeling/filter_state.py`（核心类）
2. `anylabeling/views/labeling/filter_engine.py`（筛选引擎，接收 FilterState）
3. `anylabeling/views/labeling/filter_navigation_engine.py`（导航引擎，使用 FilterState）
4. `anylabeling/views/labeling/widgets/filter_label_widget.py`（UI 与状态的绑定）
5. `anylabeling/views/labeling/label_widget.py`（状态持久化与恢复）
6. `anylabeling/views/labeling/settings/schema.py`（配置项定义）

改动文件：
1. `anylabeling/views/labeling/filter_state.py`（新建）
2. `anylabeling/views/labeling/filter_engine.py`（适配 FilterState 接口）
3. `anylabeling/views/labeling/filter_navigation_engine.py`（适配 FilterState 接口）
4. `anylabeling/views/labeling/label_widget.py`（集成状态持久化）
5. `tests/test_filter_persistence.py`（新增测试）

验证步骤：
1. 设置一组筛选条件（多个标签 + 特定 GID + shape_type），确认 FilterState 正确封装。
2. 调用 to_dict() 和 from_dict()，确认序列化/反序列化前后状态一致。
3. 关闭程序后重新打开，确认筛选条件自动恢复。
4. 验证空条件（无筛选）时 has_active_filter() 返回 False。
5. 验证 copy() 返回深拷贝，修改副本不影响原对象。
6. 运行 test_filter_persistence.py，确认所有测试通过。

已知副作用：
1. 使用 set() 存储 labels 在序列化时可能丢失顺序（若需保持顺序可改用 list）。
2. gid 统一规范化为字符串 "-1"，与数值型 gid 混用时需注意类型转换。
3. 持久化到 YAML/JSON 时，set 类型需先转为 list。

后续注意：
1. 若新增筛选维度（如属性、创建时间），需扩展 FilterState 字段。
2. 若支持筛选条件的历史记录/撤销，可考虑引入不可变快照机制。
3. 可考虑与 DatasetFilterIndex 的查询参数统一，避免重复转换。
4. 配置持久化时应考虑版本兼容，旧版配置缺少新字段时需给出默认值。
```
