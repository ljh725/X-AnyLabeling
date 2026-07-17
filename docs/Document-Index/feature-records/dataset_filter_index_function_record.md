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
2. 若存在与当前数据集身份匹配的完整缓存，立即挂载并恢复标签状态；约 1.5 秒后在后台自动 Refresh 校验增量变化。
3. 若不存在缓存，只在后台检查标签文件是否存在，不再使用应用级模态进度框，也不自动触发首次全量索引。
4. 索引建立后，筛选操作（FilterEngine）优先使用 DatasetFilterIndex.query() 替代逐文件扫描。
5. 用户在当前图片修改并保存标注后，先原子保存 JSON，再调用 refresh_file() 单条更新索引；索引失败只进入待同步状态，不会把成功的 JSON 保存判为失败。
6. Refresh 在现有数据库上执行增量事务；Rebuild 在独立临时数据库中完成并通过完整性检查后，才原子替换正式缓存。
7. Rebuild 期间旧索引持续可读；取消、异常或临时数据库安装失败时保留旧索引。
8. 关闭或切换文件夹时取消旧数据集任务并释放连接，索引文件继续保留在 ~/.cache/xanylabeling/dataset_index/。

三个实施优先级：
1. P0 可用性：已有缓存立即挂载、后台自动 Refresh、首次加载非模态化、明确区分 missing/cached/syncing/ready/stale/failed 状态。
2. P1 安全与性能：Rebuild 临时库 + 完整性检查 + 原子切换；批量并发读取 JSON、单线程批量写 SQLite；取消时事务回滚。
3. P2 一致性与诊断：JSON 同目录临时文件 + fsync + os.replace 原子保存；保存后单文件同步失败可重试；记录数据集身份、完成时间、文件数、shape 数和耗时。

依赖锚点：
1. `anylabeling/views/labeling/dataset_filter_index.py`（核心索引逻辑）
2. `anylabeling/views/labeling/dataset_filter_index_worker.py`（后台线程封装）
3. `anylabeling/views/labeling/filter_engine.py`（筛选引擎集成）
4. `anylabeling/views/labeling/filter_state.py`（筛选条件对象）
5. `anylabeling/views/labeling/label_widget.py`（状态机、缓存挂载、生命周期管理与 UI 集成）
6. `anylabeling/views/labeling/label_file.py`（JSON 路径推导与原子保存）

改动文件：
1. `anylabeling/views/labeling/dataset_filter_index.py`（新建）
2. `anylabeling/views/labeling/dataset_filter_index_worker.py`（新建）
3. `anylabeling/views/labeling/filter_engine.py`（集成索引查询路径）
4. `anylabeling/views/labeling/label_widget.py`（集成后台线程、缓存状态机与进度回调）
5. `anylabeling/views/labeling/label_file.py`（JSON 原子保存）
6. `scripts/compile_languages.py` / `scripts/generate_languages.py`（兼容 Qt5/Qt6 资源编译器输出）

验证步骤：
1. 首次打开包含 1000+ 张图片且没有缓存的数据集，确认标签检查在后台进行、标注界面可以立即操作。
2. 手动 Refresh 或 Rebuild 后关闭并重新打开软件，确认缓存立即挂载，随后后台只做增量 Refresh。
3. Rebuild 期间执行筛选，确认旧索引仍可查询；取消或制造解析异常后确认旧缓存未被覆盖。
4. 执行标签筛选，对比使用索引前后的响应时间（应显著降低）。
5. 修改当前图片的标注并保存，确认 JSON 完整且筛选结果实时反映变更；模拟 SQLite 写入失败时 JSON 仍保存成功。
6. 手动删除或外部修改 JSON 文件后 Refresh，确认纳秒级 mtime/size 检测能更新对应记录。
7. 切换不同数据集，确认各自使用独立的缓存文件（规范化根目录的 SHA256 哈希隔离）。
8. 断开索引（模拟数据库损坏），确认筛选回退到逐文件扫描模式。

已知副作用：
1. 首次打开没有缓存的大数据集时不会自动全量构建；需手动 Refresh/Rebuild 才能获得索引加速。
2. 索引缓存占用磁盘空间（约为 JSON 文件总大小的 10%-20%）。
3. 已有缓存每次打开后会自动后台 Refresh，期间可能产生受限的 CPU/IO 占用，但不会强制锁住界面。
4. 若用户在软件运行期间从外部修改 JSON，变化会在下一次 Refresh 时同步，不保证瞬时感知。
5. 多进程同时访问同一缓存文件仍可能产生 SQLite 锁等待；当前设置 30 秒 busy timeout，并将同步失败隔离为 stale 状态。

后续注意：
1. 若新增更多筛选维度（如属性、分数阈值），需同步扩展 shapes 表字段和查询 SQL。
2. Schema 版本变更时需确保自动迁移或重建逻辑正确。
3. 可考虑在索引中缓存更多 shape 字段，支持更复杂的筛选条件。
4. 当前不迁移缓存目录，也不自动清理旧缓存；后续若实现迁移或清理，必须保留可回滚路径并避免误删仍在使用的数据集缓存。
```
