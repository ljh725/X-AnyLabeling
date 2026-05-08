# 更改输出目录 + 点击画面卡顿分析

> 日期: 2026-05-07 | 分析范围: `anylabeling/views/labeling/`

---

## 概述

用户操作流程：更改输出目录 → 点击画面。该流程会产生**两段卡顿**，分布在 UI 主线程上的两个不同位置。

| 卡顿 | 触发时机 | 根因 | 严重程度 |
|------|----------|------|----------|
| 第一段 | 选择输出目录后 | `import_image_folder()` 全量目录扫描 + 逐文件 JSON 存在性/状态检查 | 高（必然触发） |
| 第二段 | 点击画面时 | `Canvas.mousePressEvent` 内 `repaint() × 2` 同步重绘，叠加 `update_attributes()` / inspector 表格刷新 | 中（shape 越多越卡） |

---

## 第一段卡顿：更改输出目录

### 调用链

```
用户选择输出目录
│
└─► LabelWidget.change_output_dir_dialog  (label_widget.py:6895)
    │
    ├─► self.output_dir = output_dir              # 更新输出目录
    │
    └─► self.import_image_folder(dirpath, load=False)  (label_widget.py:7339)
        │
        ├─► utils.scan_all_images(dirpath)        # ★ os.walk 递归全量扫描
        │   (utils/qt.py:13)
        │   └─► for root, _, files in os.walk(folder_path):
        │       └─► 过滤图片扩展名 + natsort 排序
        │
        ├─► for filename in image_files:          # 逐文件构建列表项
        │   │
        │   └─► self._create_file_list_item(filename, label_file)
        │       (label_widget.py:3955)
        │       │
        │       ├─► QtCore.QFile.exists(label_file)         # 文件存在检查
        │       ├─► LabelFile.is_label_file(label_file)      # ★ 打开 JSON 验证格式
        │       └─► self._label_file_checked(label_file)     # ★ 打开 JSON 扫描 checked 字段
        │           (label_widget.py:3928)
        │           └─► open(label_file).chunk_read(8192) + 正则搜索
        │
        └─► self._update_inspector_file_list()    # 更新 Inspector 文件列表
            (label_widget.py:4738)
```

### 耗时热点（按权重排序）

1. **`scan_all_images()`** — `os.walk` 递归遍历整个图片目录，无缓存、无增量。文件越多越慢。
   - 位置：`anylabeling/views/labeling/utils/qt.py:13`
2. **`LabelFile.is_label_file()`** — 对每个 label_file 打开文件判断是否为合法 JSON 标注。shapes 越多的 JSON 越慢。
   - 位置：`anylabeling/views/labeling/label_file.py:23`
3. **`_label_file_checked()`** — 再次打开每个 JSON，分块读取并正则搜索 `"checked"` 字段。**即使 `checkstate` 已通过 `is_label_file` 确定，仍进行二次文件读取。**
   - 位置：`label_widget.py:3928`

---

## 第二段卡顿：点击画面

### 调用链

```
用户点击 Canvas
│
├─► Canvas.mousePressEvent                      (canvas.py:1070)
│   │
│   └─► if editing() and click on shape:
│       │
│       └─► Canvas.select_shape_point            (canvas.py:1406)
│           │
│           ├─► set_hiding()                     # 隐藏背景 shapes
│           │
│           ├─► selection_changed.emit([shape])  # ★ 信号发射
│           │   │
│           │   └─► LabelWidget.shape_selection_changed  (label_widget.py:5230)
│           │       │
│           │       ├─► label_list.clearSelection()
│           │       ├─► label_list.find_item_by_shape(shape)  # O(n) 线性扫描
│           │       ├─► label_list.select_item(item)
│           │       ├─► label_list.scroll_to_item(item)
│           │       ├─► set_text_editing(True)
│           │       │
│           │       ├─► if selected_count == 1:
│           │       │   └─► update_attributes(i)        # ★ 完全重建属性面板
│           │       │       (label_widget.py:4835)
│           │       │       # 创建 QGridLayout/QRadioButton/QComboBox
│           │       │       # 嵌套循环截断文本(width 逐字符测量)
│           │       │
│           │       └─► _schedule_inspector_table_refresh()  # 150ms 防抖
│           │           └─► [150ms 后]
│           │               _refresh_inspector_table      (label_widget.py:4723)
│           │               └─► refresh_table_from_shapes (inspector_panel.py:308)
│           │                   └─► EditableTableWidget.populate (editable_table_widget.py:236)
│           │                       ├─► set_records()     # 重置 model
│           │                       └─► resizeColumnsToContents()  # ★ 遍历 cell 测量宽度
│           │
│           └─► calculate_offsets(point)
│
├─► repaint()                                    # ★ 同步完整重绘 #1
│   └─► paintEvent                              (canvas.py:2125)
│       # 遍历所有 shape：画 group 边界、逐个绘制、高亮选中、十字线等
│
└─► repaint()                                    # ★ 同步完整重绘 #2
    └─► paintEvent                              # 同上，再次遍历所有 shape
```

### 耗时热点（按权重排序）

1. **`repaint() × 2` — 两次同步 paintEvent**
   - 位置：`canvas.py:1268-1269`
   - 原因：`repaint()` 是 Qt 同步调用，立即执行 `paintEvent()`。`paintEvent` 会遍历 canvas 上所有 shape 进行绘制（group 边界、顶点、填充、描边、选中高亮、十字线）。**一次点击触发两遍完整绘制。**
   - 影响因子：当前图片的 shape 数量。几百个 shape 时明显卡顿。

2. **`update_attributes()` — 完全重建属性面板**
   - 位置：`label_widget.py:4835`
   - 触发条件：`self.attributes` 已配置 AND 选中单个 shape AND 非绘制模式
   - 原因：每次选中都重新创建 `QGridLayout`、所有 `QLabel`/`QRadioButton`/`QComboBox`，包含嵌套 while 循环的文本截断计算。是 O(属性数 × 选项数 × 文本长度) 的 CPU 消耗。
   - 如果 attributes 未配置，不会执行，可跳过。

3. **Inspector 表格刷新 — `resizeColumnsToContents()`**
   - 位置：`editable_table_widget.py:240`
   - 触发条件：Inspector 面板可见
   - 原因：遍历所有 cell 内容测量最佳列宽。shape 越多 cell 越多。
   - 150ms 防抖延迟不足以完全隐藏卡顿感。

4. **`find_item_by_shape()` — O(n) 线性扫描**
   - 位置：`label_list_widget.py:189`
   - 原因：每次选中 shape 都在 label_list 中线性查找对应 item。shape 数量大时累积耗时。

### 为什么改完输出目录后体感更明显

`change_output_dir_dialog` 末尾的 `setCurrentRow()` 会触发 `file_selection_changed` → `load_file()`，重新加载当前图片和所有 shape。

此时：
- 所有 shape 刚刚加载到 canvas，paintEvent 无任何缓存预热
- Inspector 表格被 `_update_inspector_file_list()` 清空，需要首次填充
- 属性面板需要首次构建

**"首次加载后第一次点击"** 的 paintEvent + inspector 填充 + 属性构建 叠加在一起，体感就是一记明显的停顿。后续点击不再清空 inspector，所以卡顿感减轻。

---

## 优化建议

### 立即见效（低风险）

1. **`repaint() × 2` → `update()`**
   - 文件：`canvas.py:1268-1269`
   - 将 `self.repaint()` 改为 `self.update()`（异步调度，Qt 在事件循环空闲时合并绘制）
   - 预期收益：消除点击时的同步重绘卡顿，点击响应变即时

2. **`_label_file_checked()` 去重**
   - 文件：`label_widget.py:3967`
   - 问题：`is_label_file` 已打开过 JSON 并成功解析，`_label_file_checked` 又打开一遍只为了找 `checked` 字段
   - 方案：在 `is_label_file` 判断为 True 时直接设为 checked 状态，或传递已解析的 JSON data 避免二次 IO
   - 预期收益：减少改输出目录时的文件 IO 量约 50%

### 中期优化（需验证）

3. **`import_image_folder` 增量扫描 / 后台线程**
   - 将 `os.walk` 移到后台线程，文件名列表先展示，标注文件状态异步更新
   - 用 `os.scandir` 替代 `os.walk`（减少 stat 调用）

4. **`update_attributes()` 增量更新**
   - 文件：`label_widget.py:4835`
   - 仅更新变化的控件值、标签文本，而非完全重建布局

5. **Inspector `resizeColumnsToContents()` 节流**
   - 文件：`editable_table_widget.py:240`
   - 仅在 shape 数量变化时执行列宽计算，或使用固定列宽 + 省略号截断

### 验证方法

在以下位置加 `time.perf_counter()` 打点即可量化：

| 位置 | 文件:行号 |
|------|-----------|
| `scan_all_images` 前后 | `utils/qt.py:13` |
| `import_image_folder` 内 `_create_file_list_item` 循环 | `label_widget.py:7353` |
| `_label_file_checked` 入口 | `label_widget.py:3928` |
| `Canvas.mousePressEvent` 入口/出口 | `canvas.py:1070` |
| `Canvas.repaint` → `paintEvent` 入口/出口 | `canvas.py:1268`, `canvas.py:2125` |
| `shape_selection_changed` 入口/出口 | `label_widget.py:5230` |
| `update_attributes` 入口/出口 | `label_widget.py:4835` |
| `_refresh_inspector_table` 入口/出口 | `label_widget.py:4723` |
