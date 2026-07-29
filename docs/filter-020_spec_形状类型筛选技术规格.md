# Shape Type 分类筛选功能 — 技术说明文档

## 1. 功能概述

在现有 Label / Group ID 筛选基础上，新增 **Shape Type**（标注形状类型）筛选维度。三个筛选条件可任意组合（AND 逻辑），并支持跨图片保持筛选状态。

### 1.1 筛选维度

| 维度 | 空值标记 | 含义 |
|------|---------|------|
| Label | `""` | 显示所有标签 |
| Group ID | `"-1"` | 显示所有组 |
| Shape Type | `""` | 显示所有形状类型 |

### 1.2 Shape Type 可选值

```
rectangle, polygon, point, linestrip, circle, rotation, cuboid, quadrilateral, line
```

---

## 2. 涉及文件一览

| 文件 | 角色 |
|------|------|
| `anylabeling/views/labeling/widgets/filter_label_widget.py` | `ShapeTypeFilterComboBox` 控件定义 |
| `anylabeling/views/labeling/widgets/__init__.py` | 导出 `ShapeTypeFilterComboBox` |
| `anylabeling/views/labeling/label_widget.py` | 全部业务逻辑：初始化、筛选方法、菜单、跨页保持、性能优化 |

---

## 3. 核心架构

### 3.1 数据流

```
用户操作（菜单 / 下拉框）
    │
    ▼
set_label_filter_value()  ──→  QComboBox.currentIndexChanged
set_gid_filter_value()    ──→  QComboBox.currentIndexChanged
set_shape_type_filter_value() ──→  QComboBox.currentIndexChanged
    │                              │
    │                              ▼
    │              text_selection_changed(index)
    │              gid_selection_changed(index)
    │              shape_type_selection_changed(index)
    │                     │
    │                     ▼
    │              _sticky_filter_state["xxx"] = combobox.currentText()
    │                     │
    │                     ▼
    │              _apply_combined_shape_filters()
    │                     │
    │         读取 _sticky_filter_state
    │         ┌───────────┼───────────┐
    │         ▼           ▼           ▼
    │       label       gid       shape_type
    │         └───────────┼───────────┘
    │                     ▼
    │              AND 组合 is_visible()
    │                     │
    │                     ▼
    │         _sync_label_list_visibility(is_visible)
    │             单次遍历完成:
    │             ┌─ 判断可见性
    │             ├─ 更新 item.checkState()
    │             ├─ 更新 shape.visible / canvas.visible[shape]
    │             ├─ 累计 visible_count
    │             └─ 记录 changed 标志
    │                     │
    │             返回 (visible_count, changed)
    │                     │
    │         ┌───────────┴───────────┐
    │         ▼                       ▼
    │   changed=True 时            visible_count==0
    │   canvas.update()           且 has_active_filter
    │   navigator 刷新                │
    │                                ▼
    │                           status("No items
    │                               match the filter
    │                               criteria")
    └─────────────────────┘
```

### 3.2 Sticky Filter State（跨页保持核心）

**问题**：翻页时 `reset_state()` 清空 combobox，`update_*_box()` 根据新图片 shape 重建下拉项，旧筛选值可能不在新图中，被回退为默认值，导致筛选状态丢失。

**方案**：引入 `_sticky_filter_state`（dict），作为独立于 UI 控件的权威筛选状态。

```python
# 初始化（label_widget.py:293）
self._sticky_filter_state = {
    "label": "",
    "gid": "-1",
    "shape_type": "",
}
```

**状态流转**：

```
              用户操作
                 │
    ┌────────────┼────────────┐
    ▼            ▼            ▼
label改变    gid改变    shape_type改变
    │            │            │
    └────────────┼────────────┘
                 ▼
          sticky_state 更新
                 │
    ┌────────────┼────────────┐
    ▼                          ▼
当前图片应用              翻页保存到
_apply_combined_      _pending_filter_restore
shape_filters()               │
                 ┌────────────┘
                 ▼
         新图片 _refresh_shape_filters()
                 │
         从 pending 恢复 sticky
                 │
         update_*_box() 将 sticky 值
         强制加入下拉项（即使本图没有）
                 │
                 ▼
         _apply_combined_shape_filters()
```

**关键机制**：
- `update_combo_box/gid_box/type_box()` 优先使用 sticky 值；若 sticky 值不在当前图片候选项中，**强制加入下拉列表**（不自动回退）。
- `_apply_combined_shape_filters()` **只从 sticky_state 读取**，不依赖 combobox 当前文本。
- 用户主动改筛选时才更新 sticky（`*_selection_changed` → sticky update）。

---

## 4. 关键方法说明

### 4.1 ShapeTypeFilterComboBox（filter_label_widget.py:46）

```python
class ShapeTypeFilterComboBox(QWidget):
    type_box: QComboBox          # 下拉控件
    items: List[str]             # 当前下拉项列表
    update_items(items)          # 重建下拉项
    # 信号连接: type_box.currentIndexChanged → parent.shape_type_selection_changed
```

### 4.2 筛选值设置（label_widget.py）

| 方法 | 行号 | 作用 |
|------|------|------|
| `set_label_filter_value(label, block_signal)` | `:4100` | 设置 label combobox 选中项 |
| `set_gid_filter_value(gid, block_signal)` | `:4115` | 设置 gid combobox 选中项 |
| `set_shape_type_filter_value(type, block_signal)` | `:4127` | 设置 shape_type combobox 选中项 |

### 4.3 用户交互响应（label_widget.py）

| 方法 | 行号 | 作用 |
|------|------|------|
| `text_selection_changed(index)` | `:5521` | 更新 sticky.label → 应用组合筛选 |
| `gid_selection_changed(index)` | `:5527` | 更新 sticky.gid → 应用组合筛选 |
| `shape_type_selection_changed(index)` | `:4189` | 更新 sticky.shape_type → 应用组合筛选 |

### 4.4 组合筛选核心（label_widget.py:4204）

```python
def _apply_combined_shape_filters(self):
    # 从 sticky_state 读取（非 combobox）
    label = self._sticky_filter_state["label"]
    gid = self._sticky_filter_state["gid"]
    shape_type = self._sticky_filter_state["shape_type"]

    has_active_filter = (
        label != "" or gid != "-1" or shape_type != ""
    )

    def is_visible(item):
        shape = item.shape()
        label_ok      = (label == "" or shape.label == label)
        gid_ok        = (gid == "-1" or str(shape.group_id) == gid)
        type_ok       = (shape_type == "" or shape.shape_type == shape_type)
        label_info_ok = self.label_info[shape.label].get("visible", True)
        return label_ok and gid_ok and type_ok and label_info_ok

    # 单次遍历：设置可见性 + 计数 + 变化检测
    visible_count, changed = self._sync_label_list_visibility(is_visible)

    # 只在可见性实际变化时才刷新画布
    if changed:
        self.canvas.update()
        if navigator可见:
            self.update_navigator_shapes()

    # 无命中提示
    if visible_count == 0 and has_active_filter:
        self.status("No items match the filter criteria")
    else:
        self.status("")
```

### 4.5 `_sync_label_list_visibility()`（label_widget.py:5298）

改造为返回 `(visible_count, changed)` 的单次遍历方法：

- 在循环中同时完成：
  - 判断 `is_visible`
  - 累计 `visible_count`
  - 检测 `item.checkState()` 是否变化 → 设置 `changed`
  - 检测 `shape.visible` 是否变化 → 设置 `changed`
  - 更新 `item.checkState()`、`shape.visible`、`canvas.visible[shape]`
- 不再在方法内部触发 `canvas.update()` / navigator 刷新
- 调用方根据 `changed` 决定是否刷新

### 4.6 `_collect_filter_options()`（label_widget.py:5340）

**新增** 单次遍历收集方法：

```python
def _collect_filter_options(self):
    labels_set = set()
    gids_set = set()
    types_set = set()
    for item in self.label_list:
        shape = item.shape()
        labels_set.add(str(shape.label))
        if shape.group_id is not None:
            gids_set.add(str(shape.group_id))
        if shape.shape_type:
            types_set.add(str(shape.shape_type))
    return labels_set, gids_set, types_set
```

### 4.7 下拉项更新（label_widget.py）

| 方法 | 行号 | 作用 |
|------|------|------|
| `update_combo_box(block_signal, precomputed)` | `:5344` | 从 label_list 或预计算结果提取唯一标签 |
| `update_gid_box(block_signal, precomputed)` | `:5377` | 从 label_list 或预计算结果提取唯一 gid |
| `update_shape_type_box(block_signal, precomputed)` | `:4162` | 从 label_list 或预计算结果提取唯一 shape_type |

三个方法统一模式：
1. 检查 `_sticky_filter_state` 中的对应值
2. 若 sticky 值非默认且不在当前图片候选项中，**强制追加到列表**
3. 按 sticky 值设置 combobox 选中项

新增 `precomputed` 参数：传入预计算结果集时跳过自身遍历；未传入时回退到原有遍历（兼容 `refresh_filter_menus` 等独立调用）。

### 4.8 筛选刷新入口（label_widget.py:5358）

```python
def _refresh_shape_filters(self):
    # 1. 从 pending 恢复 sticky（跨页保持）
    if self._pending_filter_restore:
        self._sticky_filter_state.update(saved)
        self._pending_filter_restore = None

    # 2. 单次遍历收集三个下拉选项
    labels_set, gids_set, types_set = self._collect_filter_options()

    # 3. 传入预计算结果更新三个下拉（无额外遍历）
    self.update_combo_box(block_signal=True, precomputed=labels_set)
    self.update_gid_box(block_signal=True, precomputed=gids_set)
    self.update_shape_type_box(block_signal=True, precomputed=types_set)

    # 4. 应用组合筛选
    self._apply_combined_shape_filters()
```

调用时机：每次 `load_shapes()` 末尾、`add_label()`、`edit_label()`、`batch_edit_labels()` 等操作后。

---

## 5. 跨页保持机制

### 5.1 Enable Global Filter 开关

- 位置：`View` 菜单 → `Enable Global Filter`（默认开启）
- 存储：`QSettings("anylabeling", "anylabeling", "filter/global_keep_enabled")`
- 方法：`toggle_global_filter_keep(enabled)` (`label_widget.py:4249`)

### 5.2 翻页流程

**开关 ON（默认）**：

```
load_file(filename)
    │
    ├─ 保存: _pending_filter_restore = dict(_sticky_filter_state)
    │
    ├─ reset_state() → 清空 combobox
    │
    ├─ load_shapes(...) → _refresh_shape_filters()
    │      │
    │      ├─ 恢复: _sticky_filter_state.update(_pending_filter_restore)
    │      ├─ _collect_filter_options() → 单次扫描收集
    │      ├─ update_*_box(precomputed=...) → 零额外扫描
    │      └─ _apply_combined_shape_filters() → 单次遍历应用筛选
    │
    └─ 渲染（仅在 changed 时触发 canvas.update）
```

**开关 OFF**：

```
load_file(filename)
    │
    ├─ _pending_filter_restore = None
    │
    ├─ reset_state() → 清空 combobox
    │
    ├─ load_shapes(...) → _refresh_shape_filters()
    │      │
    │      ├─ _pending_filter_restore 为 None，sticky 不更新
    │      ├─ update_*_box() → sticky 为默认，回退到 ""
    │      └─ _apply_combined_shape_filters() → 显示全部
    │
    └─ 渲染
```

### 5.3 开关切换行为

**开→关**：清空 `_sticky_filter_state` + 重置三个 combobox + 重新应用筛选（显示全部）。

---

## 6. 菜单体系

### 6.1 右键菜单

三个菜单各含三个筛选子菜单：

| 菜单 | 变量前缀 | 初始化位置 |
|------|---------|-----------|
| 右侧 Label List 右键 | `label_filter_menu`, `gid_filter_menu`, `shape_type_filter_menu` | `:2122` |
| Canvas 左键右键 | `canvas_*_filter_menu_0` | `:2344` |
| Canvas 编辑模式右键 | `canvas_*_filter_menu_1` | `:2990` |

### 6.2 菜单刷新

`refresh_filter_menus()` (`label_widget.py:4068`) — 在菜单 `aboutToShow` 信号触发时更新所有筛选菜单项并勾选当前值。

---

## 7. 与其他模块的交互

### 7.1 与 Inspector Panel 的关系

无直接交互。筛选影响的是画布可见性 + 对象列表 check state，Inspector Panel 的表格数据源仍为全部 shape。

### 7.2 与 Keypoint Fill Mode 的关系

Keypoint fill 模式会直接操作 `gid_filter_combobox`：
- 激活时设置 gid 值为目标 person 的 group_id
- 退出时设置 gid 为 "-1"（全部）

这些操作会触发 `gid_selection_changed` → sticky 更新 → 组合筛选应用，行为正确。

### 7.3 与 Label Visibility 的关系

`apply_label_visibility()` 保持独立，在 Labels 面板中切换某类标签显隐时不经过组合筛选，直接覆盖可见性。同样仅在 `changed=True` 时才触发画布刷新。

### 7.4 与 `_has_active_shape_filter` 的关系

该检测方法已改为读取 `_sticky_filter_state`（`:3123`），控制 toggle-shapes-visibility 按钮的可用状态。

---

## 8. 配置持久化

| 配置项 | Key | 默认值 |
|--------|-----|--------|
| 全局筛选保持开关 | `filter/global_keep_enabled` | `True` |

通过 `QSettings` 持久化，应用重启后恢复。

---

## 9. 性能优化架构

### 9.1 优化目标

解决筛选指定 `shape_type` 后翻页延迟问题，减少每次翻页的 shape 遍历次数和无效 UI 刷新。

### 9.2 关键优化点

#### 单次遍历合并（Phase 1）

**位置**：`_sync_label_list_visibility()` → `_apply_combined_shape_filters()`

- 优化前：`_sync_label_list_visibility(is_visible)` 遍历一次设置可见性，随后 `sum(... is_visible(...))` 再遍历一次计数
- 优化后：`_sync_label_list_visibility()` 在单次循环中同时完成判断、设置、计数，返回 `(visible_count, changed)`

**收益**：筛选主路径少一次全量 shape 遍历。

#### 按变化刷新（Phase 1）

**位置**：`_sync_label_list_visibility()` 返回值由调用方决策

- 优化前：每次 `_sync_label_list_visibility()` 都无条件触发 `canvas.update()` + navigator 刷新
- 优化后：仅在 `changed=True`（任一 shape 可见性实际变化）时才触发

**收益**：连续翻页经过多张"无命中"或"结果相同"图片时，跳过画布重绘。

#### 下拉选项单次扫描（Phase 2）

**位置**：`_collect_filter_options()` + `_refresh_shape_filters()`

- 优化前：`update_combo_box`、`update_gid_box`、`update_shape_type_box` 各遍历 `label_list` 一次（3 次全量扫描）
- 优化后：新增 `_collect_filter_options()` 单次遍历同时提取 `labels_set`、`gids_set`、`types_set`，通过 `precomputed` 参数传入三个方法

**收益**：翻页时下拉重建从 3 次扫描降为 1 次。

### 9.3 翻页开销对比

| 步骤 | 优化前 | 优化后 |
|------|--------|--------|
| 收集下拉选项 | 3 次全量扫描 | 1 次全量扫描 |
| 筛选判断 & 计数 | 1 次遍历设置 + 1 次遍历计数 | 1 次遍历同时完成 |
| 画布刷新 | 无条件触发 | 仅在可见性变化时 |
| navigator 刷新 | 无条件触发 | 仅在可见性变化时 |

### 9.4 保留的回退路径

三个 `update_*_box()` 方法的 `precomputed` 参数默认为 `None`：
- 当被 `refresh_filter_menus()` 等独立调用时，回退到自身遍历（保持兼容）
- 仅在 `_refresh_shape_filters()` 翻页路径中使用预计算结果

---

## 10. 添加新筛选维度的步骤（扩展指南）

如需添加第 4 个筛选维度（如 difficulty、score 范围等）：

1. **`filter_label_widget.py`** — 新建 `XxxFilterComboBox(QWidget)`，参考 `ShapeTypeFilterComboBox`
2. **`widgets/__init__.py`** — 导出新类
3. **`label_widget.py`** 初始化区 — 创建实例 + 隐藏 + 在 `_sticky_filter_state` 添加入口
4. **`label_widget.py`** 方法区 — 新增：
   - `set_xxx_filter_value()`
   - `update_xxx_box()`
   - `_populate_xxx_filter_menu()`
   - `xxx_selection_changed()`
5. **`label_widget.py`** `_collect_filter_options()` — 加对应 set 收集
6. **`label_widget.py`** `_apply_combined_shape_filters()` — 加 `xxx_ok` 条件
7. **`label_widget.py`** `refresh_filter_menus()` — 加菜单刷新
8. **`label_widget.py`** `_refresh_shape_filters()` — 加 `update_xxx_box(precomputed=...)` 调用
9. **`label_widget.py`** `_has_active_shape_filter()` — 加检测
10. **`label_widget.py`** `toggle_global_filter_keep(False)` — 加清空
11. **`label_widget.py`** `reset_state()` — 加 clear
12. **`label_widget.py`** `_append_filter_submenus()` — 加子菜单，更新返回值元组和所有调用方
