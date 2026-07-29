# Pose 加载性能优化代码改造记录

> 记录 Task 1 ~ Task 6 及 Task 8 的实际代码变更，供后续 Canvas 结构拆解参考。

---

## 1. 通用改造：性能日志开关（Task 1 + Task F）

### 文件
- `anylabeling/views/labeling/label_widget.py`
- `anylabeling/views/labeling/label_file.py`
- `anylabeling/views/labeling/widgets/canvas.py`

### 新增内容

每个文件顶部新增统一的性能日志开关：

```python
import os

PERF_LOG_ENABLED = os.getenv("XANYLABELING_PERF_LOG") == "1"


def _perf_log(message, *args):
    """Emit performance logs only when enabled by env var."""
    if PERF_LOG_ENABLED:
        logger.info(message, *args)
```

### 使用方式

所有性能埋点从 `logger.info(...)` 替换为 `_perf_log(...)`。默认关闭，设置环境变量 `XANYLABELING_PERF_LOG=1` 后输出。

---

## 2. 性能埋点（Task 1）

### 2.1 `label_widget.py` — `import_image_folder()`

```python
_t0 = time.perf_counter()
# ... 目录扫描和列表构建 ...
_perf_log(
    "import_image_folder: %d files in %.3fs",
    len(image_files),
    time.perf_counter() - _t0,
)
```

### 2.2 `label_widget.py` — `load_file()`

在 `load_file()` 内部插入多个阶段计时：

| 阶段 | 计时变量 | 日志内容 |
|------|----------|----------|
| Label JSON 读取 | `_t_label` | `load_file label json: %.3fs` |
| Image decode | `_t_image` | `load_file image decode: %.3fs` |
| Canvas load_pixmap | `_t_pixmap` | `load_file canvas.load_pixmap: %.3fs` |
| Load shapes | `_t_shapes` | `load_file load_shapes: %.3fs, count=%d` |
| Paint canvas | `_t_canvas` | `load_file paint_canvas: %.3fs` |
| 总计 | `_t_load` | `load_file total: %.3fs` |

### 2.3 `label_widget.py` — `open_next_image()`

```python
_t_next = time.perf_counter()
_perf_log("open_next_image enter: current=%s", self.filename)
# ... 翻页逻辑 ...
_perf_log(
    "open_next_image exit: %.3fs, next=%s",
    time.perf_counter() - _t_next,
    self.filename,
)
```

### 2.4 `label_widget.py` — `_label_file_checked()`

对慢于 50ms 的 checked 字段扫描输出警告：

```python
_dt = time.perf_counter() - _t0
if _dt > 0.05:
    _perf_log("_label_file_checked slow: %.3fs for %s", _dt, label_file)
```

### 2.5 `label_file.py` — `load_image_file()`

```python
_t0 = time.perf_counter()
try:
    with open(filename, "rb") as f:
        data = f.read()
    elapsed = time.perf_counter() - _t0
    if elapsed > 0.05:
        _perf_log("LabelFile.load_image_file slow: %.3fs, file=%s", elapsed, filename)
    return data
```

### 2.6 `label_file.py` — `load()`

```python
# imageData base64 解码计时
_t_image = time.perf_counter()
image_data = base64.b64decode(data["imageData"])
_perf_log("LabelFile.load imageData decode: %.3fs, file=%s", ...)

# 外部图片文件读取计时
_t_image = time.perf_counter()
image_data = self.load_image_file(image_path)
_perf_log("LabelFile.load image bytes: %.3fs, file=%s", ...)

# 整体耗时（>100ms 才输出）
_t_shape_build = time.perf_counter()
shapes = [Shape().load_from_dict(s) for s in data["shapes"]]
_t_shapes = time.perf_counter()
total_time = _t_shapes - _t0
if total_time > 0.1:
    _perf_log("LabelFile.load slow: json=%.3fs, pre_shapes=%.3fs, shape_build=%.3fs, total=%.3fs, file=%s", ...)
```

### 2.7 `label_widget.py` — `load_shapes()`

```python
_t_filter = time.perf_counter()
total_time = _t_filter - _t0
if total_time > 0.1:
    _perf_log(
        "load_shapes slow: %d shapes, list=%.3fs, canvas=%.3fs, filter=%.3fs, total=%.3fs",
        len(shapes), _t_list - _t0, _t_canvas - _t_list, _t_filter - _t_canvas, total_time
    )
```

### 2.8 `canvas.py` — `paintEvent()`

```python
_t0 = time.perf_counter()
# ... 绘制逻辑 ...
_dt = time.perf_counter() - _t0
if _dt > 0.05:
    _perf_log("Canvas.paintEvent slow: %.3fs, shapes=%d", _dt, len(self.shapes))
```

### 2.9 `canvas.py` — `load_shapes()`

```python
_t_total = time.perf_counter()
total_time = _t_total - _t0
if total_time > 0.1:
    _perf_log(
        "Canvas.load_shapes slow: store_shapes=%.3fs, total=%.3fs, count=%d",
        _t_after_store - _t_before_store, total_time, len(self.shapes)
    )
```

### 2.10 `label_widget.py` — `update_thumbnail_display()`

```python
_t_thumbnail = time.perf_counter()
# ... 缩略图加载 ...
_perf_log("update_thumbnail_display: %.3fs, %s", time.perf_counter() - _t_thumbnail, self.filename)
```

---

## 3. 跳过同步 checked 扫描（Task 2）

### 文件
- `anylabeling/views/labeling/label_widget.py`

### 改造点

#### 3.1 `_create_file_list_item()` 新增 `load_checked` 参数

```python
def _create_file_list_item(self, file, label_file, load_checked=False):
    item = QtWidgets.QListWidgetItem(file)
    # ... flags 设置 ...
    if QtCore.QFile.exists(label_file) and LabelFile.is_label_file(label_file):
        item.setCheckState(Qt.CheckState.Checked)
    else:
        item.setCheckState(Qt.CheckState.Unchecked)
    
    if load_checked:
        self._set_file_item_checked(
            item, self._label_file_checked(label_file)
        )
    else:
        self._set_file_item_checked(item, False)  # 默认不读取 JSON
    return item
```

#### 3.2 `import_image_folder()` 传 `load_checked=False`

```python
item = self._create_file_list_item(
    filename, label_file, load_checked=False
)
```

#### 3.3 `import_dropped_image_files()` 传 `load_checked=False`

```python
item = self._create_file_list_item(
    file, label_file, load_checked=False
)
```

#### 3.4 `_label_file_checked()` 保留

继续保留，供后续手动触发或后台校正复用：

```python
def _label_file_checked(self, label_file):
    _t0 = time.perf_counter()
    try:
        with open(label_file, "rb") as f:
            buffer = b""
            while True:
                chunk = f.read(8192)
                if not chunk:
                    break
                buffer = buffer[-32:] + chunk
                match = CHECKED_FIELD_PATTERN.search(buffer)
                if match:
                    _dt = time.perf_counter() - _t0
                    if _dt > 0.05:
                        _perf_log("_label_file_checked slow: %.3fs for %s", _dt, label_file)
                    return match.group(1) == "true"
    except Exception:
        return False
    return False
```

#### 3.5 `_update_current_file_checked_item()`

`load_file()` 加载完成后调用，用已加载数据校正当前项：

```python
def _update_current_file_checked_item(self):
    if not self.filename:
        return
    item = self._current_file_item()
    if item is None:
        return
    checked = self.other_data.get(CHECKED_FIELD, False) is True
    self._set_file_item_checked(item, checked)
```

---

## 4. 初次加载跳过 Undo 深拷贝（Task 3）

### 文件
- `anylabeling/views/labeling/widgets/canvas.py`
- `anylabeling/views/labeling/label_widget.py`

### 改造点

#### 4.1 `Canvas.load_shapes()` 新增 `store_backup` 参数

```python
def load_shapes(self, shapes, replace=True, store_backup=True):
    _t0 = time.perf_counter()
    # ...
    if store_backup:
        self.store_shapes()
    # ...
```

#### 4.2 `Canvas.store_shapes()` 深拷贝 undo 快照

```python
def store_shapes(self):
    shapes_backup = []
    for shape in self.shapes:
        shape.copy()
        shapes_backup.append(shape)
    self.shapes_backups.append(shapes_backup)
```

**注意**：`Shape.copy()` 内部使用 `copy.deepcopy()`，而 `Shape` 中缓存了 `QPainterPath` 对象不可 pickle。解决方案见 Task 6 的 `__getstate__`。

#### 4.3 `LabelWidget.load_shapes()` 透传参数

```python
def load_shapes(self, shapes, replace=True, update_last_label=True, store_backup=True):
    # ...
    self.canvas.load_shapes(shapes, replace=replace, store_backup=store_backup)
    # ...
```

#### 4.4 `load_file()` 初次加载传 `store_backup=False`

```python
self.load_shapes(
    self.label_file.shapes,
    update_last_label=False,
    store_backup=False,
)
```

#### 4.5 首次编辑前补 undo 快照

在 `Canvas` 中维护 `_pending_initial_backup` 标志：

```python
# 在需要触发 undo 的编辑操作入口处检查
if getattr(self, '_pending_initial_backup', False):
    self.store_shapes()
    self._pending_initial_backup = False
```

---

## 5. 禁用自动 Dataset Index Worker（Task 4 + 后台扫描手动化）

### 文件
- `anylabeling/views/labeling/label_widget.py`

### 改造点

#### 5.1 移除 `import_image_folder()` 中的自动索引启动

原代码（已移除）：
```python
# 原自动启动逻辑（已删除）
if self._dataset_index_timer is not None:
    self._dataset_index_timer.stop()
    self._dataset_index_timer = None
self._dataset_index_timer = QtCore.QTimer(self)
self._dataset_index_timer.singleShot(3000, lambda: ...)
```

当前状态：切换目录时仅取消 pending timer，不再自动启动新 timer：

```python
# Cancel any pending dataset index timer from a previous directory.
if self._dataset_index_timer is not None:
    self._dataset_index_timer.stop()
    self._dataset_index_timer = None
```

#### 5.2 保留手动入口

```python
def refresh_dataset_index(self):
    self._start_dataset_index_worker(
        "refresh", list(self.image_list), self.output_dir
    )

def rebuild_dataset_index(self):
    self._start_dataset_index_worker(
        "rebuild", list(self.image_list), self.output_dir
    )

def cancel_dataset_index_build(self):
    if self._dataset_index_worker is not None:
        self._dataset_index_worker.cancel()
```

#### 5.3 菜单和工具栏注册

View 菜单和工具栏已注册以下 action：
- `Refresh Dataset Index`
- `Rebuild Dataset Index`
- `Cancel Dataset Index Build`
- `Scan EXIF Orientation`（Task C 新增）

---

## 6. Pose 关键点列表逐项显示（Task 5）

### 文件
- `anylabeling/views/labeling/label_widget.py`

### 改造点

#### 6.1 移除跳过 point 的降载逻辑

原试验代码（已回滚）：
```python
# 曾尝试跳过 point 以加速列表构建，但会导致保存丢失关键点
# if shape.shape_type == "point":
#     continue
```

当前策略：**保持 point 逐项显示**，因为 `save_labels()` 从 `label_list` 保存，跳过 point 会导致数据丢失。

#### 6.2 保留 `add_label()` 逐个添加

```python
def add_label(self, shape):
    item = LabelListWidgetItem(shape.label, shape)
    self.label_list.addItem(item)
    # ...
```

不使用 `QListWidget.addItems()`，因为该接口只能添加字符串，无法携带 `Shape` 对象。

---

## 7. 绘制裁剪和路径缓存（Task 6）

### 文件
- `anylabeling/views/labeling/shape.py`
- `anylabeling/views/labeling/widgets/canvas.py`

### 改造点

#### 7.1 `Shape` 类 — bounding rect 缓存

```python
class Shape:
    def __init__(self, ...):
        # ...
        self._cached_bbox = None
    
    def bounding_rect(self):
        if self._cached_bbox is None:
            # 计算 bounding rect
            if self.points:
                xs = [p.x() for p in self.points]
                ys = [p.y() for p in self.points]
                # 对 point 类型扩展半径避免空 rect
                if self.shape_type == "point":
                    r = self.point_size
                    self._cached_bbox = QtCore.QRectF(
                        min(xs) - r, min(ys) - r,
                        max(xs) - min(xs) + 2 * r,
                        max(ys) - min(ys) + 2 * r
                    )
                else:
                    self._cached_bbox = QtCore.QRectF(
                        min(xs), min(ys),
                        max(xs) - min(xs), max(ys) - min(ys)
                    )
            else:
                self._cached_bbox = QtCore.QRectF()
        return self._cached_bbox
    
    def invalidate_bbox(self):
        self._cached_bbox = None
```

**失效点**：所有修改 `points` 的位置调用 `self.invalidate_bbox()`：
- `add_point()`
- `pop_point()`
- `insert_point()`
- `remove_point()`
- `set_point()`
- `offset()`
- `scale()`
- `rotate()`
- `load_from_dict()`

#### 7.2 `Shape` 类 — `QPainterPath` 缓存

```python
class Shape:
    def __init__(self, ...):
        # ...
        self._cached_path = None
        self._path_geometry_key = None
    
    def _geometry_cache_key(self):
        return (self.shape_type, self._closed, tuple((p.x(), p.y()) for p in self.points))
    
    def paint(self, painter):
        # ...
        path = self.get_path()
        # ...
    
    def get_path(self):
        key = self._geometry_cache_key()
        if self._cached_path is None or self._path_geometry_key != key:
            self._cached_path = self._build_path()
            self._path_geometry_key = key
        return self._cached_path
    
    def _build_path(self):
        path = QtGui.QPainterPath()
        # 根据 shape_type 构建 path
        if self.shape_type == "rectangle":
            # ...
        elif self.shape_type == "polygon":
            # ...
        # ...
        return path
```

#### 7.3 `Shape` 类 — `__getstate__` 处理不可 pickle 对象

`QPainterPath` 不可 pickle，`copy.deepcopy()` 在 undo 快照时会崩溃：

```python
def __getstate__(self):
    state = self.__dict__.copy()
    # QPainterPath 不可序列化，undo 快照时跳过
    state['_cached_path'] = None
    state['_path_geometry_key'] = None
    return state
```

#### 7.4 `Canvas.paintEvent()` — viewport 裁剪

```python
def paintEvent(self, event):
    _t0 = time.perf_counter()
    
    p = self._painter
    p.begin(self)
    
    # 计算当前 viewport 对应的 scene 范围
    viewport_rect = self._get_viewport_scene_rect()
    
    # 绘制 shapes
    for shape in self.shapes:
        if not self.visible.get(shape, True):
            continue
        
        # viewport 裁剪：不在可见区域的 shape 跳过绘制
        bbox = shape.bounding_rect()
        if not viewport_rect.intersects(bbox):
            continue
        
        shape.paint(p)
    
    # ... 其他绘制 ...
    p.end()
    
    _dt = time.perf_counter() - _t0
    if _dt > 0.05:
        _perf_log("Canvas.paintEvent slow: %.3fs, shapes=%d", _dt, len(self.shapes))
```

#### 7.5 `_get_viewport_scene_rect()`

```python
def _get_viewport_scene_rect(self):
    """将当前 widget 的 viewport 转换为 scene 坐标系的 QRectF。"""
    # 取 widget 的可见区域
    view_rect = self.rect()
    # 转换为 scene 坐标
    tl = self.transform().inverted()[0].map(view_rect.topLeft())
    br = self.transform().inverted()[0].map(view_rect.bottomRight())
    return QtCore.QRectF(tl, br).normalized()
```

---

## 8. 禁止筛选导航回退全量 JSON 扫描（Task 8）

### 文件
- `anylabeling/views/labeling/label_widget.py`

### 改造点

#### 8.1 `enable_filter_navigation()` — 安全路径

```python
def enable_filter_navigation(self, status_prefix=None):
    if not self._filter_state.has_active_filter():
        self.status(self.tr("No active filter for result navigation"), 3000)
        self._set_filter_navigation_action_checked(False)
        return False
    
    state = self._copy_filter_state()
    if (
        self._dataset_filter_index is not None
        and self._dataset_filter_index.is_ready()
    ):
        # Fast path: query derived SQLite index
        all_matched = self._dataset_filter_index.query(state)
        image_set = set(self.image_list)
        matched = [p for p in all_matched if p in image_set]
    else:
        # 如果索引未就绪，提示用户而不是全量 JSON 扫描
        self.status(
            self.tr("Dataset index not ready. Please wait or rebuild index."),
            5000,
        )
        self._set_filter_navigation_action_checked(False)
        return False
    
    self._filter_navigation_files = matched
    self._filter_navigation_initial_count = len(matched)
    self._filter_navigation_state = state
    self._filter_navigation_active = bool(matched)
    
    if not matched:
        self.status(self.tr("No files match the current filter"), 3000)
        self._set_filter_navigation_action_checked(False)
        return False
    
    self._show_filter_navigation_status(
        status_prefix or self.tr("Filter result navigation enabled")
    )
    self._set_filter_navigation_action_checked(True)
    return True
```

#### 8.2 关键行为

- SQLite 索引未 ready 时：**不调用** `FilterNavigationEngine.collect_matched_files()`
- 只显示状态栏提示，要求用户先手动构建索引
- 返回 `False`，阻止筛选导航启用
- 构建完成后可重新启用

---

## 9. 手动 EXIF 扫描入口（后台扫描手动化 Task C）

### 文件
- `anylabeling/views/labeling/label_widget.py`

### 新增 Action

```python
scan_exif_orientation = action(
    self.tr("Scan EXIF Orientation"),
    self.scan_exif_orientation,
    None, None,
    self.tr("Scan EXIF orientation for all images in the list"),
    enabled=True,
)
```

### 新增方法

```python
def scan_exif_orientation(self):
    """Manually trigger EXIF orientation scan for all images."""
    image_files = list(self.image_list)
    if not image_files:
        self.status(
            self.tr("No images to scan. Open a directory first."), 3000
        )
        return
    self.async_exif_scanner.start_scan(image_files)
    self.status(
        self.tr("Scanning EXIF orientation for %d images...") % len(image_files),
        3000,
    )
```

### 菜单/工具栏注册

已加入 View 菜单和工具栏：
```python
# View 菜单
utils.add_actions(
    self.menus.view,
    (..., refresh_dataset_index, rebuild_dataset_index, cancel_dataset_index,
     scan_exif_orientation, ...)
)

# 工具栏
self.actions.tool = (..., toggle_filter_navigation,
                     refresh_dataset_index, rebuild_dataset_index, cancel_dataset_index,
                     scan_exif_orientation, ...)
```

---

## 10. 文件同步选择优化（附加）

### 文件
- `anylabeling/views/labeling/label_widget.py`

### `_sync_file_list_current_row()`

解决翻页时 `itemSelectionChanged` 触发两次 `load_file` 的问题：

```python
def _sync_file_list_current_row(self, filename):
    """Sync file list selection without re-entering load_file."""
    filename = str(filename)
    if filename not in self.fn_to_index:
        return
    row = self.fn_to_index[filename]
    if self.file_list_widget.currentRow() == row:
        return
    blocker = QtCore.QSignalBlocker(self.file_list_widget)
    self.file_list_widget.setCurrentRow(row)
    del blocker
```

使用 `QSignalBlocker` 阻止 `itemSelectionChanged` 信号在设置行时触发二次加载。

---

## 修改文件清单

| 文件 | 涉及 Task | 主要改动 |
|------|-----------|----------|
| `anylabeling/views/labeling/label_widget.py` | 1, 2, 3, 4, 5, 8, F, C | 性能埋点、跳过 checked 扫描、undo 参数透传、禁用自动索引、point 显示、筛选导航安全、日志开关、手动 EXIF 入口 |
| `anylabeling/views/labeling/label_file.py` | 1, F | 性能埋点、日志开关 |
| `anylabeling/views/labeling/widgets/canvas.py` | 1, 3, 6, F | 性能埋点、undo 参数、viewport 裁剪、日志开关 |
| `anylabeling/views/labeling/shape.py` | 6 | bbox 缓存、path 缓存、`__getstate__` |
| `docs/filter-080_task_后台扫描手动化清单.md` | — | 任务状态更新 |
| `docs/filter-090_summary_后台扫描手动化总结.md` | — | 功能总结文档 |

---

## 后续 Canvas 结构拆解参考

### 当前 Canvas 绘制链路

```
paintEvent()
  ├─ 计算 viewport_scene_rect（裁剪依据）
  ├─ 遍历 self.shapes
  │   ├─ 检查 visible[shape]
  │   ├─ 检查 bbox 与 viewport 相交（viewport 裁剪）
  │   └─ shape.paint(p)
  │       ├─ 获取 cached path（geometry key 判断缓存命中）
  │       ├─ 绘制 path
  │       └─ 绘制选中/hover 高亮
  ├─ 绘制当前编辑中的 shape
  ├─ 绘制 cross line / grid
  └─ 慢帧检测日志
```

### Shape 缓存结构

```
Shape
  ├─ points: List[QPointF]
  ├─ _cached_bbox: QRectF | None
  ├─ _cached_path: QPainterPath | None
  ├─ _path_geometry_key: tuple | None
  ├─ bounding_rect() → 返回 _cached_bbox（懒计算）
  ├─ get_path() → 返回 _cached_path（geometry key 判断）
  ├─ invalidate_bbox() → 清空 _cached_bbox
  ├─ _geometry_cache_key() → (shape_type, closed, tuple(points))
  └─ __getstate__() → 序列化时丢弃 QPainterPath
```

### Undo 快照链路

```
编辑操作
  ├─ 检查 _pending_initial_backup
  │   └─ True → store_shapes() → 深拷贝 shapes → shapes_backups.append()
  ├─ 执行编辑
  └─ update()
```

### 性能日志控制

```
环境变量 XANYLABELING_PERF_LOG=1
  └─ _perf_log() → logger.info()
默认（未设置）
  └─ _perf_log() → 无操作
```
