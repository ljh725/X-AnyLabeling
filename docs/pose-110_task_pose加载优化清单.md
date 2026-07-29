# Pose 标注加载性能优化开发任务拆解

## 0. 执行原则

- JSON 仍是唯一真实数据源，不改标注文件格式。
- SQLite 只做可删除、可重建的派生缓存。
- 先做埋点和 Phase 1，确认收益后再做 SQLite schema 扩展。
- 每个任务完成后都要保留原有标注、保存、撤销、筛选导航行为。

---

## Task 1：增加性能埋点（P0）

### 目标

确认加载慢点到底落在目录扫描、JSON 读取、Shape 构建、列表构建、Undo 快照还是绘制阶段。

### 改动文件

- `anylabeling/views/labeling/label_widget.py`
- `anylabeling/views/labeling/label_file.py`
- `anylabeling/views/labeling/widgets/canvas.py`
- `anylabeling/views/labeling/shape.py`

### Checklist

- [x] 在 `import_image_folder()` 增加总耗时日志。
- [x] 在 `_create_file_list_item()` / `_label_file_checked()` 增加累计耗时日志。
- [x] 在 `LabelFile.load()` 增加 JSON 读取和 `Shape.load_from_dict()` 构建耗时日志。
- [x] 在 `label_widget.py:load_shapes()` 增加 `add_label()` / label list 构建耗时日志。
- [x] 在 `canvas.py:load_shapes()` 增加 `store_shapes()` 耗时日志。
- [x] 在 `canvas.py:paintEvent()` 增加首帧或慢帧日志，避免每帧刷屏。
- [x] 使用 `time.perf_counter()`，不要使用低精度时间。
- [x] 日志默认走现有 logger，不使用 `print()`。

### 验收

- [ ] 打开大目录后，日志能拆出各阶段耗时。
- [ ] 打开单张 Pose 大标注后，日志能看到 JSON 解析、Shape 构建、列表构建、Undo 快照、首帧绘制耗时。
- [ ] 埋点不会明显拖慢正常操作。

---

## Task 2：目录打开时跳过同步 checked 扫描（P0）

### 目标

打开目录时不再逐个读取 JSON 查找 `checked` 字段，先让文件列表和首张图片尽快显示。

### 改动文件

- `anylabeling/views/labeling/label_widget.py`

### 涉及函数

- `import_image_folder()`
- `_create_file_list_item()`
- `_label_file_checked()`
- `_set_file_item_checked()`
- `_update_current_file_checked_item()`

### Checklist

- [x] 修改 `_create_file_list_item()`，增加参数控制是否同步读取 checked，例如 `load_checked=False`。
- [x] `import_image_folder()` 调用 `_create_file_list_item()` 时传 `load_checked=False`。
- [x] 首次创建列表项时默认使用 `Unchecked` 或“未知”状态，不读取 JSON。
- [x] 当前文件被 `load_file()` 成功加载后，用已加载的 `self.other_data[CHECKED_FIELD]` 校正当前列表项。
- [x] 保留 `_label_file_checked()`，供后续后台校正或兼容逻辑使用。
- [x] 不在 UI 线程批量遍历 JSON 校正 checked。

### 验收

- [ ] 打开 5000+ 图片目录时，UI 线程不逐个读取 JSON。
- [ ] 当前图片加载后，当前文件的 checked 图标状态正确。
- [ ] 用户切换图片后，对应文件项 checked 状态能被正确校正。
- [ ] 标记 checked / unchecked 后，保存和文件列表图标仍正确。

---

## Task 3：初次加载跳过 Undo 深拷贝（P0）

### 目标

初次加载标注时不立即深拷贝全量 shapes，降低 Pose 大文件加载延迟和内存峰值。

### 改动文件

- `anylabeling/views/labeling/widgets/canvas.py`
- `anylabeling/views/labeling/label_widget.py`

### 涉及函数

- `Canvas.load_shapes()`
- `Canvas.store_shapes()`
- `LabelWidget.load_shapes()`
- `LabelWidget.load_file()`

### Checklist

- [x] 给 `Canvas.load_shapes()` 增加参数 `store_backup=True`。
- [x] 仅当 `store_backup=True` 时调用 `self.store_shapes()`。
- [x] 给 `LabelWidget.load_shapes()` 增加透传参数 `store_backup=True`。
- [x] 在 `load_file()` 初次加载 JSON shapes 时传 `store_backup=False`。
- [x] 在首次编辑前补一次 undo 快照。
- [x] 确认移动点、删除 shape、改标签、复制粘贴、自动标注结果写入等编辑入口仍会调用或触发 `store_shapes()`。

### 验收

- [ ] 打开单张 Pose 大文件时，`store_shapes()` 不在初次加载路径执行。
- [ ] 用户第一次编辑后按 `Ctrl+Z` 能撤销到刚加载完成的状态。
- [ ] 多次撤销/重做行为和原来一致。
- [ ] 切换图片不会复用上一张图的 undo 栈。

---

## Task 4：延迟启动 Dataset Index Worker（P1）

### 目标

避免打开目录后立即启动后台索引，与首张图片加载和 UI 初始化争抢磁盘 IO / CPU。

### 改动文件

- `anylabeling/views/labeling/label_widget.py`

### 涉及函数

- `import_image_folder()`
- `_start_dataset_index_worker()`
- `_on_dataset_index_finished()`
- `enable_filter_navigation()`

### Checklist

- [x] 移除 `import_image_folder()` 末尾对 `_start_dataset_index_worker()` 的立即调用。
- [x] 使用 `QtCore.QTimer.singleShot()` 延迟启动索引，例如首图加载完成 500ms 后。
- [x] 如果用户在索引构建前启用筛选导航，提示“索引构建中”或主动触发索引构建。
- [x] 防止重复启动 worker，继续复用现有 `_dataset_index_worker is not None` 判断。
- [x] 切换目录时取消或忽略旧目录的 pending timer / worker。

### 验收

- [ ] 打开目录后首张图优先显示并可交互。
- [ ] 索引仍会自动构建或在需要时构建。
- [ ] 快速连续打开不同目录不会让旧索引结果污染新目录。
- [ ] 筛选导航不会静默回退到全量 JSON 扫描造成卡顿。

---

## Task 5：Pose 关键点列表逐项显示（P1）

### 目标

保持 Pose `point` 在左侧 label list 逐项显示，避免保存路径丢失关键点数据。

### 改动文件

- `anylabeling/views/labeling/label_widget.py`
- `anylabeling/views/labeling/widgets/label_list_widget.py`

### 涉及函数

- `LabelWidget.load_shapes()`
- `LabelWidget.add_label()`
- `LabelListWidgetItem`

### Checklist

- [x] 明确产品策略：Pose `point` 需要在左侧列表逐个显示。
- [x] 移除跳过 `shape_type == "point"` 的降载逻辑。
- [x] 保持 point 逐项显示，避免 `save_labels()` 只从 `label_list` 保存时丢失关键点。
- [x] 确保保存时仍从 `label_list` 输出完整 JSON，包含 point 关键点。
- [ ] 后续如需优化 UI，再设计按 `group_id` 聚合 person 并折叠关键点的方案。
- [x] 不使用 `QListWidget.addItems()` 作为自定义 item 的批量替代方案；该接口只能添加字符串。

### 验收

- [x] 单人 17 关键点时，左侧列表逐点显示，与当前保存逻辑兼容。
- [x] 关键点仍能在画布上正常选择和编辑。
- [ ] 删除 person 或 group 时，不遗失相关关键点数据。
- [x] 保存后的 JSON shapes 数量和字段完整。

---

## Task 6：绘制裁剪和路径缓存（P1）

### 目标

提升 Pose 大标注在缩放、拖拽、平移时的交互帧率。

### 改动文件

- `anylabeling/views/labeling/widgets/canvas.py`
- `anylabeling/views/labeling/shape.py`

### 涉及函数

- `Canvas.paintEvent()`
- `Shape.paint()`
- `Shape.bounding_rect()`
- 所有修改 points 的方法

### Checklist

- [x] 给 `Shape` 增加 bounding rect 缓存。
- [x] 当 `points` 改变、shape 移动、插点、删点时，主动失效 bounding rect 缓存。
- [x] 在 `paintEvent()` 中计算当前可见 viewport 的 scene QRectF。
- [x] 绘制前先用 cached bounding rect 判断是否与 viewport 相交。
- [x] 给 `Shape` 增加 path 缓存，points 未变时复用 `QPainterPath`。
- [x] 对选中、hover、difficult、scale 变化等影响绘制样式的状态，不错误复用样式相关对象。

### 验收

- [ ] 1000+ shape 文件缩放和平移不卡顿或明显改善。
- [ ] 画布外 shape 不参与绘制。
- [ ] 编辑点位后，图形立即正确刷新，不出现旧 path 残留。
- [ ] 选中、高亮、隐藏、显示、缩放下样式正确。

---

## Task 7：扩展 SQLite 目录元数据缓存（P2）

### 目标

让目录二次打开时从 SQLite 恢复文件级元数据，避免再次读取所有 JSON。

### 改动文件

- `anylabeling/views/labeling/dataset_filter_index.py`
- `anylabeling/views/labeling/dataset_filter_index_worker.py`
- `anylabeling/views/labeling/label_widget.py`

### 涉及函数

- `DatasetFilterIndex._ensure_schema()`
- `DatasetFilterIndex._read_shapes()` 或新建 `_read_index_fields()`
- `DatasetFilterIndex.refresh_file()`
- `DatasetFilterIndex.load_or_build()`
- `LabelWidget.import_image_folder()`
- `LabelWidget._create_file_list_item()`

### Checklist

- [ ] 将 `SCHEMA_VERSION` 从 `"2"` 升级到 `"3"`。
- [ ] `files` 表新增 `checked INTEGER`。
- [ ] `files` 表新增或复用 `error_message` 记录解析失败。
- [ ] 新增 `_read_index_fields(json_path)`，一次读取 `checked`、`shape_count`、`label/group_id/shape_type`。
- [ ] `refresh_file()` 同步更新 `checked`、`shape_count`、`json_mtime`、`json_size`。
- [ ] 新增批量查询 API，例如 `get_file_meta_map(image_files, output_dir)`。
- [ ] `import_image_folder()` 构建列表前批量读取 meta map。
- [ ] `_create_file_list_item()` 从 meta map 获取 checked，不逐项 SQL 查询。
- [ ] 缓存缺失或 mtime/size 不匹配时，不在 UI 线程读 JSON，交给 worker 刷新。

### 验收

- [ ] 首次打开目录会后台构建 SQLite 缓存。
- [ ] 二次打开目录时，未变更 JSON 不被读取。
- [ ] checked 状态、shape_count、筛选字段与 JSON 一致。
- [ ] 删除或新增 JSON 后，缓存能正确增量更新。
- [ ] schema 旧版本缓存能自动重建，不崩溃。

---

## Task 8：禁止筛选导航回退到全量 JSON 扫描（P2）

### 目标

避免用户启用筛选导航时，因为 SQLite 未就绪而触发全目录 `json.load`。

### 改动文件

- `anylabeling/views/labeling/label_widget.py`
- `anylabeling/views/labeling/filter_navigation_engine.py`

### 涉及函数

- `LabelWidget.enable_filter_navigation()`
- `FilterNavigationEngine.collect_matched_files()`

### Checklist

- [ ] 修改 `enable_filter_navigation()`：SQLite 未就绪时不自动调用全量 JSON 扫描。
- [ ] 给用户明确提示：请先构建索引或等待索引完成。
- [ ] 如需保留回退，只允许处理当前已加载文件，不扫全目录。
- [ ] 索引构建完成后，用户可重新启用筛选导航。

### 验收

- [ ] SQLite 未就绪时启用筛选导航不会卡死 UI。
- [ ] 不再出现全目录逐个 `json.load` 的同步路径。
- [ ] SQLite 就绪后筛选导航结果正确。

---

## 建议开发顺序

1. Task 1：性能埋点。
2. Task 2：跳过同步 checked 扫描。
3. Task 3：初次加载跳过 Undo 深拷贝。
4. Task 4：延迟启动 Dataset Index Worker。
5. 根据埋点选择 Task 5 或 Task 6。
6. Task 7：扩展 SQLite 元数据缓存。
7. Task 8：禁用筛选导航全量 JSON 回退。
