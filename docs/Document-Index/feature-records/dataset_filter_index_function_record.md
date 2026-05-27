# Dataset Filter Index 功能记录

```text
功能名称：
Dataset Filter Index / DatasetFilterIndex / DatasetIndexWorker / Rebuild Dataset Index（视图菜单显示名称）

修改目的：
解决标签筛选在大数据集（数千张图片）上的性能瓶颈。
原始实现需要逐文件解析 JSON 进行筛选，随着数据量增长会越来越慢。
本功能引入基于 SQLite 的派生索引缓存，实现毫秒级筛选查询，
同时保证 JSON 文件仍是唯一真实数据源，SQLite 可随时重建。

影响流程：
1. 用户打开数据集文件夹时，LabelWidget 根据数据集根目录生成稳定的数据库路径。
2. 后台启动 DatasetIndexWorker 线程，增量构建或刷新 SQLite 索引。
3. 索引建立后，筛选操作（FilterEngine）优先使用 DatasetFilterIndex.query() 替代逐文件扫描。
4. 用户在当前图片修改并保存标注后，调用 refresh_file() 单条更新索引，避免全量重建。
5. 用户可手动触发重建（Rebuild Dataset Index），清除旧缓存并从头构建。
6. 关闭文件夹时释放数据库连接，索引文件保留在 ~/.cache/xanylabeling/dataset_index/。

依赖锚点：
1. `anylabeling/views/labeling/dataset_filter_index.py`（核心索引逻辑）
2. `anylabeling/views/labeling/dataset_filter_index_worker.py`（后台线程封装）
3. `anylabeling/views/labeling/filter_engine.py`（筛选引擎集成）
4. `anylabeling/views/labeling/filter_state.py`（筛选条件对象）
5. `anylabeling/views/labeling/label_widget.py`（生命周期管理与 UI 集成）
6. `anylabeling/views/labeling/label_file.py`（JSON 路径推导规则）

改动文件：
1. `anylabeling/views/labeling/dataset_filter_index.py`（新建）
2. `anylabeling/views/labeling/dataset_filter_index_worker.py`（新建）
3. `anylabeling/views/labeling/filter_engine.py`（集成索引查询路径）
4. `anylabeling/views/labeling/label_widget.py`（集成后台线程与进度回调）

验证步骤：
1. 打开包含 1000+ 张图片的数据集，确认后台索引构建完成且无阻塞 UI。
2. 执行标签筛选，对比使用索引前后的响应时间（应显著降低）。
3. 修改当前图片的标注并保存，确认筛选结果实时反映变更。
4. 手动删除 JSON 文件后刷新索引，确认该图片从筛选结果中移除。
5. 切换不同数据集，确认各自使用独立的缓存文件（SHA256 哈希隔离）。
6. 断开索引（模拟数据库损坏），确认筛选回退到逐文件扫描模式。

已知副作用：
1. 首次打开大数据集时，后台索引构建可能短暂占用 CPU/IO。
2. 索引缓存占用磁盘空间（约为 JSON 文件总大小的 10%-20%）。
3. 若用户直接修改 JSON 文件而未通过软件保存，索引可能过期，需手动重建。
4. 多进程同时访问同一缓存文件可能产生 SQLite 锁冲突。

后续注意：
1. 若新增更多筛选维度（如属性、分数阈值），需同步扩展 shapes 表字段和查询 SQL。
2. Schema 版本变更时需确保自动迁移或重建逻辑正确。
3. 可考虑在索引中缓存更多 shape 字段，支持更复杂的筛选条件。
4. 定期清理 ~/.cache/xanylabeling/dataset_index/ 中长时间未使用的旧缓存。
```
