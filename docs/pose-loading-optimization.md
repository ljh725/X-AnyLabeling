# Pose 标注数据加载性能优化方案

## 1. 现状与瓶颈

### 1.1 数据源架构

X-AnyLabeling 以 **JSON 文件为唯一真实数据源**。每张图片对应一个 `.json` 标注文件，编辑时通过 `LabelFile.load()` / `save()` 进行完整读写。

项目内虽已存在 `DatasetFilterIndex`（SQLite 派生索引），但其设计定位为：

> JSON 标注文件是唯一真实数据源。SQLite 仅作为可丢弃、可重建的索引缓存，不保存不可从 JSON 恢复的信息。

因此，当前 SQLite **仅用于筛选导航**，并未承担目录级元数据缓存职责。

### 1.2 已定位瓶颈

按代码阅读结果，慢点集中在：

| 阶段 | 文件/函数 | 问题描述 | 影响 |
|---|---|---|---|
| **目录打开** | `label_widget.py:import_image_folder` | 遍历全部图片，为每个文件推导 JSON 路径并创建列表项 | O(N) 文件系统操作 |
| **目录打开** | `label_widget.py:_create_file_list_item` → `_label_file_checked` | **逐个打开 JSON 分块读取，查找 `checked` 字段** | O(N) IO + 字符串匹配 |
| **单图加载** | `label_file.py:LabelFile.load()` | 完整 `json.load` 整张标注并反序列化 | 内存 + 解析时间 |
| **单图加载** | `label_widget.py:load_shapes()` → `add_label()` | 为每个 Shape 创建 `LabelListWidgetItem` | UI 对象爆炸 |
| **单图加载** | `canvas.py:load_shapes()` → `store_shapes()` | 初次加载即深拷贝所有 Shape 做 undo 备份 | 内存 + CPU 双倍消耗 |
| **绘制** | `canvas.py:paintEvent()` | 每次 paint 遍历全量 shape，逐 shape 创建 `QPainterPath` | 帧率下降 |

> **核心结论**：对于 Pose 场景（单人 1 框 + 17 关键点，多人倍数放大），瓶颈主要在 **UI 对象构建** 和 **绘制开销**，而非单纯 JSON 解析速度。直接引入数据库替代 JSON 主存储**并不能解决 UI 层面的成本**。

### 1.3 审核结论

引入数据库适合作为**目录级元数据索引**，不适合作为第一步替换 JSON 主存储。当前最值得优先处理的是同步 IO、初次 undo 深拷贝、左侧列表 item 数量和绘制全量遍历。

需要注意：Phase 1 中如果直接依赖 SQLite 的 `checked` 字段，会形成对 Phase 2 的前置依赖。因此 Phase 1 的实现应先采用“默认状态 + 后台校正”方案，Phase 2 再把 `checked` 纳入 SQLite 缓存。

---

## 2. 落地路线

### Phase 1：不改数据格式（快速见效）

目标：在不改动 JSON 主存储、不引入新依赖的前提下，消除最明显的同步阻塞和 UI 冗余。

#### 2.1 文件列表 `checked` 状态懒加载（高收益）

- **文件**：`anylabeling/views/labeling/label_widget.py`
- **函数**：`_label_file_checked()`、`_create_file_list_item()`、`import_image_folder()`
- **改动**：
  1. `_create_file_list_item()` **不再同步调用** `_label_file_checked()` 读 JSON。
  2. Phase 1 不依赖 SQLite 新字段，首次打开目录时默认显示 `Unchecked` 或“未知”状态，**不读取 JSON**。
  3. 当前图片加载完成后，只校正当前文件的 checked 状态。
  4. 如需校正全列表状态，使用低优先级后台任务分批读取，每批处理少量文件，避免阻塞 UI。
  5. Phase 2 完成后，再把优先级改为：SQLite 命中直接取值；缓存缺失时后台校正。
- **预期收益**：打开含 10k 张图的目录时，避免 10k 次 JSON 读取，目录加载时间从数秒/数十秒降至亚秒级。
- **审核建议**：这是最优先的改动点。当前 `_label_file_checked()` 虽然是分块读，不是完整 `json.load`，但对大目录仍是 N 次文件打开和磁盘读取，收益确定性高。

#### 2.2 取消初次加载的 Undo 快照（中高收益）

- **文件**：`anylabeling/views/labeling/widgets/canvas.py`
- **函数**：`load_shapes()`、`store_shapes()`
- **改动**：
  1. `load_shapes()` 增加可选参数 `store_backup=True`。
  2. `label_widget.py:load_file()` 在调用 `canvas.load_shapes()` 时传入 `store_backup=False`。
  3. 用户进行第一次编辑操作前（如移动点、改标签），`Canvas` 自动补一次 `store_shapes()`。
- **预期收益**：Pose 大文件初次加载时减少一次全量 Shape 深拷贝，内存峰值和加载延迟降低约 30%~50%。
- **审核建议**：该项收益确定，但需要增加“首次编辑前补快照”的保护逻辑。不能简单删除 `store_shapes()`，否则初次编辑后的撤销栈语义会改变。

#### 2.3 延迟启动 Dataset Index Worker（中收益）

- **文件**：`anylabeling/views/labeling/label_widget.py`
- **函数**：`import_image_folder()`、`_start_dataset_index_worker()`
- **改动**：
  1. 当前代码在 `import_image_folder()` 末尾直接启动 `DatasetIndexWorker`（后台线程）。
  2. 改为：当前图片加载完成且主线程 `QEventLoop` 进入空闲后（`QTimer.singleShot(500, ...)`），再启动 Worker。
  3. 或增加配置项：仅当用户启用了“筛选导航”或“Inspector”面板时才构建全量索引。
- **预期收益**：避免打开目录瞬间后台线程与当前图片加载争抢磁盘 IO 和 CPU。
- **审核建议**：不要完全关闭索引构建，否则筛选导航会回退到全量 JSON 扫描。建议默认延迟启动，并在用户主动启用筛选导航前优先提示“索引构建中/请构建索引”。

#### 2.4 Label List 批量/条件化添加（中收益）

- **文件**：`anylabeling/views/labeling/label_widget.py`
- **函数**：`load_shapes()`、`add_label()`
- **改动**：
  1. `load_shapes()` 中虽然已使用 `label_list.setUpdatesEnabled(False)`，但每个 shape 仍创建了独立的 `LabelListWidgetItem`。
  2. 对于 `shape_type == "point"` 的 Pose 关键点，提供两种策略（可选实现）：
     - **策略 A**：不单独创建左侧列表项，仅在 Canvas 绘制；左侧只保留 person 矩形框条目。
     - **策略 B**：按 `group_id` 聚合显示，一个 person 对应一个可展开的列表项，内部折叠关键点。
  3. 若短期内不改 UI 结构，至少减少加载过程中的信号和刷新次数；`QListWidget.addItems()` 只能添加字符串，不能直接批量添加现有 `LabelListWidgetItem`，因此不能作为自定义 item 的直接替代方案。
  4. 更长期的正确方案是改为 `QListView + QAbstractListModel`，让左侧列表虚拟化，避免为每个关键点创建重型 widget item。
- **预期收益**：单人 17 关键点场景，左侧列表项从 18 个降至 1 个，UI 布局计算大幅减少。
- **审核建议**：这是 Pose 场景的核心优化。若产品允许，优先采用“person/group 聚合显示”，收益大于单纯微调 `QListWidget`。

#### 2.5 绘制阶段 Viewport Culling / Path 缓存（中收益）

- **文件**：`anylabeling/views/labeling/widgets/canvas.py`、`shape.py`
- **函数**：`paintEvent()`、`Shape.paint()`
- **改动**：
  1. **Viewport Culling**：在 `paintEvent()` 中，先计算当前 viewport 的 QRectF，只绘制与之相交的 shape。
  2. **Path 缓存**：`Shape` 增加 `_cached_path` 属性。当 `points` 未改变时，`paint()` 直接复用缓存的 `QPainterPath`，避免每次重新 `moveTo/lineTo`。
  3. **Group 批量绘制**：Pose 的 skeleton 连线可预先缓存为一个人的整体 path，减少 painter state switch。
- **预期收益**：缩放、平移时的帧率提升，大文件场景从卡顿变为流畅。
- **审核建议**：Viewport Culling 前需要缓存 shape 的 bounding rect。否则每次 paint 为了判断可见性仍调用 `bounding_rect()`，可能只是把成本从绘制转移到裁剪判断。

---

### Phase 2：扩展 SQLite 派生索引（结构性提升）

目标：把 SQLite 从“仅用于筛选导航的临时缓存”升级为“目录级元数据中心”，但仍**不替代 JSON 主存储**。

#### 2.6 Schema 扩展

- **文件**：`anylabeling/views/labeling/dataset_filter_index.py`
- **函数**：`_ensure_schema()`、`_insert_files()`、`_read_shapes()`
- **改动**：
  1. `files` 表新增字段：
     - `checked INTEGER`（布尔值）
     - `json_exists INTEGER`（标注文件是否存在）
     - `index_error TEXT` 或复用当前 `error_message`（记录解析失败原因）
     - `image_path TEXT`（当前已有，需确保与 `json_path` 稳定关联）
     - 已有 `json_mtime`、`json_size`、`shape_count` 继续保留
  2. `_read_shapes()` 建议拆分为 `_read_index_fields()`，同时提取 `checked`、`shape_count`、`label/group_id/shape_type`。
  3. `_ensure_schema()` 增加 schema 版本号升级逻辑（`SCHEMA_VERSION` 从 `"2"` 升至 `"3"`），旧缓存自动重建。
  4. SQLite 查询 API 增加 `get_file_meta(image_path)` 或批量 `get_file_meta_map(image_files)`，避免 UI 层逐文件查询造成 N 次 SQL 往返。

#### 2.7 目录打开时从 SQLite 直接恢复元数据

- **文件**：`anylabeling/views/labeling/label_widget.py`
- **函数**：`import_image_folder()`、`_create_file_list_item()`、`_label_file_checked()`
- **改动**：
  1. `import_image_folder()` 扫描完图片列表后，先 `open()` 对应的 `DatasetFilterIndex`。
  2. 构建文件列表项前，批量读取当前 image list 的缓存元数据；checked 状态直接从内存 map 获取。
  3. 若缓存缺失或 `json_mtime`/`size` 不匹配，不在 UI 线程立即读 JSON；先显示默认状态，再交给后台索引任务刷新。
  3. 目录**二次打开**时，只要 JSON 未变动，**零 JSON 读取**即可完成目录加载和文件列表渲染。
- **审核建议**：避免在 `_create_file_list_item()` 内部逐项查询 SQLite。数据库比 JSON 快，但 N 次 SQL 查询仍会拖慢大目录，应先批量查询。

#### 2.8 单文件保存后增量刷新索引

- **文件**：`anylabeling/views/labeling/label_widget.py`
- **函数**：`save_attributes()` / 保存逻辑
- **改动**：
  1. 当前保存后已调用 `self._dataset_filter_index.refresh_file(self.image_path, self.output_dir)`。
  2. 在 Phase 2 中，确保 `refresh_file()` 在 `files` 表中同步更新 `checked`、`shape_count`、`json_mtime`、`json_size`。
  3. 保证缓存与磁盘 JSON 的弱一致性（以 mtime/size 为校验依据）。

#### 2.9 筛选导航回退路径优化

- **文件**：`anylabeling/views/labeling/label_widget.py`、`filter_navigation_engine.py`
- **函数**：`enable_filter_navigation()`、`FilterNavigationEngine.collect_matched_files()`
- **改动**：
  1. 当前逻辑：如果 SQLite 索引未就绪，会回退到 `FilterNavigationEngine.collect_matched_files()`，该函数会**遍历所有图片并逐个 `json.load`**。
  2. 回退路径改为：仅对当前内存中已加载的图片做过滤；若用户需要全量筛选导航，强制提示“请先构建索引”。
  3. 或者，把 `FilterNavigationEngine` 也接在 `DatasetFilterIndex` 上，回退时只读 SQLite，不再读 JSON。

#### 2.10 不建议直接落地的方案

- **不建议把 JSON 主存储直接替换成数据库**：改动范围会覆盖导入导出、保存、外部兼容、异常恢复和用户已有数据，风险高；同时无法解决单图 UI 构建和绘制开销。
- **不建议把完整 shape blob 存入 SQLite 作为主加载路径**：这会引入 JSON 与 DB 双写一致性问题。除非后续有明确需求，否则 SQLite 只缓存可从 JSON 恢复的轻量字段。
- **不建议优先更换 JSON 库**：`orjson` 等库能降低解析时间，但对 `QPointF` 创建、`LabelListWidgetItem` 创建、undo 深拷贝、`QPainterPath` 绘制没有帮助。

---

## 3. 优先级与验收标准

| 优先级 | 事项 | 验收标准 |
|---|---|---|
| **P0** | 性能埋点基线 | 记录目录打开、单图 JSON 解析、Shape 构建、label list 构建、undo 快照、首次 paint 的耗时 |
| **P0** | Phase 1.1 `checked` 懒加载 | 打开 5000 张图目录时，UI 线程不逐个读取 JSON |
| **P0** | Phase 1.2 取消初次 undo 快照 | 单张 Pose 大图（100+ shape）加载内存峰值下降 30%+ |
| **P1** | Phase 1.3 延迟 index worker | 打开目录后首张图片立即可交互，无明显卡顿 |
| **P1** | Phase 1.4 Label list 聚合 | Pose 关键点不在左侧列表产生独立 item，或列表改为虚拟模型 |
| **P1** | Phase 1.5 Viewport / Path 缓存 | 1000+ shape 文件缩放/平移保持 30fps |
| **P2** | Phase 2.6-2.9 SQLite 扩展 | 二次打开目录零 JSON 读取，筛选导航不回退到全量 `json.load` |

---

## 4. 风险与兼容

- **JSON 格式不变**：所有改动对外部数据格式零影响，其他工具读取标注文件无差异。
- **SQLite 缓存可丢弃**：缓存损坏或 schema 升级时自动重建（`_ensure_schema()` 已有该能力），不丢数据。
- **Undo 机制调整**：需确保 `store_backup=False` 后，用户第一次 `Ctrl+Z` 仍能正确撤销到文件加载时的状态。可在首次编辑前先 `store_shapes()`。
- **多线程**：`DatasetIndexWorker` 已在独立线程运行，Phase 2 中 `refresh_file()` 的 SQLite 写操作在主线程完成（当前已是主线程调用，无需改动）。
- **路径兼容**：`_json_path_for_image()` 的推导规则（图片目录 / `output_dir`）在 Phase 2 中仍需保持一致。

---

## 5. 建议实施顺序

1. **先做性能埋点**：用 `time.perf_counter()` 在 `import_image_folder()`、`LabelFile.load()`、`Shape.load_from_dict()`、`load_shapes()`、`canvas.load_shapes()`、`paintEvent()` 前后记录耗时。
2. **做 Phase 1.1 和 Phase 1.2**：先去掉目录打开时的同步 JSON checked 扫描，再取消初次 undo 深拷贝。
3. **做 Phase 1.3**：延迟启动索引构建，避免打开目录时抢 IO。
4. **根据埋点选择 Phase 1.4 或 Phase 1.5**：如果慢在 `load_shapes()`，优先列表聚合；如果慢在交互/缩放，优先绘制优化。
5. **最后做 Phase 2**：当确认目录二次打开、筛选导航仍然慢时，再扩展 SQLite schema。Phase 2 是结构性改造，应在 Phase 1 收益验证后实施。

---

> 本文档基于 `anylabeling/views/labeling/` 下 `label_widget.py`、`label_file.py`、`canvas.py`、`shape.py`、`dataset_filter_index.py`、`filter_navigation_engine.py` 等文件的代码阅读结果编写。
