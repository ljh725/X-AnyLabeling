# Fix: 按R标注矩形框后标签默认隐藏

## 日期

2026-05-08

---

## 一、问题描述

按 R 快捷键画矩形框，标注完成后标签（复选框）默认处于未勾选状态，导致画布上的矩形框和标签文字不可见。

### 复现步骤

1. 加载图片
2. 更改输出目录
3. 按 R 开始画矩形
4. 完成标注
5. 观察：对象面板中对象的复选框为取消勾选状态，矩形框隐藏

---

## 二、筛选功能完整调用链

### 2.1 核心数据结构

| 变量 | 默认值 | 定义位置 | 说明 |
|------|--------|----------|------|
| `_sticky_filter_state["labels"]` | `set()` | :295 | 标签筛选集合 |
| `_sticky_filter_state["gid"]` | `"-1"` | :295 | 组ID筛选 |
| `_sticky_filter_state["shape_type"]` | `""` | :295 | 形状类型筛选 |
| `_global_filter_keep_enabled` | `True` | :293 | 跨图片筛选保持开关 |
| `_pending_filter_restore` | `None` | :294 | 待恢复的筛选状态快照 |
| `_filter_index` | `None` | :300 | 当前图片筛选索引缓存 |
| `label_info` | `{}` | :166 | 标签元信息（含 visible 标记） |

### 2.2 标注新形状触发链

```
用户按 R → 鼠标点击两次完成矩形
  │
  ├─ canvas.py:3050  finalise()
  │     ├─ Shape(visible=True)     [shape.py:97]
  │     ├─ self.shapes.append(shape)
  │     └─ emit new_shape()
  │
  └─ label_widget.py:5736  new_shape()
        ├─ 确定标签文字（弹窗 / 数字快捷键 / 上一条标签）
        ├─ canvas.set_last_label() [canvas.py:3509]
        └─ add_label(shape)        [label_widget.py:5277]
              ├─ LabelListWidgetItem(text, shape)
              │     └─ 初始 checkState = Checked  [label_list_widget.py:84]
              │
              ├─ label_list.add_iem(item)
              │     └─ Qt 发射 itemChanged → label_item_changed()
              │           └─ shape.visible = True ✓
              │
              ├─ _refresh_shape_filters()      [label_widget.py:5322]
              │     ├─ ① 检查 _pending_filter_restore（非None则恢复到_sticky_filter_state）
              │     ├─ ② _rebuild_filter_index()  重建筛选索引
              │     ├─ ③ update_combo_box()       更新标签筛选下拉框
              │     ├─ ④ update_gid_box()         更新组ID筛选下拉框
              │     ├─ ⑤ update_shape_type_box()  更新形状类型筛选下拉框
              │     └─ ⑥ _apply_combined_shape_filters()  ← 含修复
              │
              └─ 返回 new_shape()
```

### 2.3 `_apply_combined_shape_filters()` 内部流

```
_apply_combined_shape_filters()  [label_widget.py:4264]
  │
  ├─ 读取 _sticky_filter_state 的三个筛选条件
  │
  ├─ has_active_filter = (
  │       bool(selected_labels)    # set()→False
  │    or current_gid != "-1"      # "-1"→False
  │    or current_type != ""       # ""→False
  │   )
  │
  ├─ ★ 修复点 ★  if not has_active_filter: return
  │
  ├─ _compute_matching_items()
  │     └─ 还检查 label_info[label]["visible"] 作为二级筛选
  │
  └─ _sync_label_list_visibility(is_visible)
        ├─ QSignalBlocker(model)     阻塞 itemChanged 信号
        ├─ setUpdatesEnabled(False)   禁用视觉刷新
        ├─ 遍历所有 item：
        │     ├─ is_visible = get_visible(item)
        │     ├─ item.setCheckState(Checked/Unchecked)  ← 修改复选框
        │     ├─ shape.visible = is_visible             ← 修改形状可见性
        │     └─ canvas.visible[shape] = is_visible
        ├─ setUpdatesEnabled(True)    恢复视觉刷新
        └─ del signal_blocker         恢复信号
```

---

## 三、Enable Global Filter 切换图片流程

### 3.1 开启状态（默认 `_global_filter_keep_enabled = True`）

```
用户切换图片
  │
  └─ label_widget.py:6337  load_file()
        ├─ ① 保存当前筛选到 _pending_filter_restore
        │     _pending_filter_restore = _copy_sticky_filter_state()  [:6369]
        │
        ├─ ② reset_state()  [:6374]
        │     ├─ label_list.clear()
        │     ├─ _filter_index = None
        │     └─ 清空筛选下拉框内容
        │
        ├─ ③ 加载图片像素数据
        │
        ├─ ④ 如果有标注文件 → load_shapes()  [:6492]
        │     └─ _refresh_shape_filters()  [:5407]
        │           └─ 恢复 _pending_filter_restore → _sticky_filter_state
        │           └─ _apply_combined_shape_filters()
        │
        └─ ⑤ 如果没有标注文件（新图片）
              └─ load_shapes() 不被调用
              └─ _pending_filter_restore 残留，等待下次 _refresh_shape_filters() 消费
```

**关键：即使选择"全部标签"（空筛选），`_pending_filter_restore` 仍然保存了空集合的筛选状态。在新图片首次标注时，`_refresh_shape_filters()` 会恢复这个空筛选，然后调用 `_apply_combined_shape_filters()`。修复前，`_sync_label_list_visibility()` 会被调用（尽管 has_active_filter=False），导致 Qt 信号阻塞期间意外重置复选框。**

### 3.2 关闭状态（`_global_filter_keep_enabled = False`）

```
用户点击 View → Enable Global Filter 取消勾选
  │
  └─ label_widget.py:4364  toggle_global_filter_keep(False)
        ├─ _global_filter_keep_enabled = False
        ├─ 清空 _sticky_filter_state 为默认值
        ├─ 重置三个筛选下拉框为默认值（block_signal=True）
        └─ _apply_combined_shape_filters()  [:4379]
              └─ has_active_filter=False → 修复后直接 return
```

```
用户切换图片
  │
  └─ load_file()
        ├─ _pending_filter_restore = None  [:6372]  ← 不保存筛选
        │
        ├─ reset_state()
        │
        └─ _refresh_shape_filters()（如有标注）
              └─ _pending_filter_restore is None → 不恢复
              └─ _sticky_filter_state 保持默认值（无筛选）
              └─ _apply_combined_shape_filters()
                    └─ has_active_filter=False → return
```

### 3.3 总结对比

| 场景 | 开启 Global Filter | 关闭 Global Filter |
|------|-------------------|-------------------|
| 切换图片时保存筛选 | ✓ `_pending_filter_restore = 快照` | ✗ `_pending_filter_restore = None` |
| 新图片标注时恢复筛选 | ✓ 恢复快照到 `_sticky_filter_state` | ✗ 保持默认无筛选 |
| 全部标签时 `has_active_filter` | `False` | `False` |
| 修复后是否执行 sync | **否（直接 return）** | **否（直接 return）** |
| 筛选下拉框是否跨图保留 | 保留（Pending→恢复） | 不保留（随图片重置） |

---

## 四、根因定位

**文件：** `anylabeling/views/labeling/label_widget.py`  
**方法：** `_apply_combined_shape_filters()` （第 4264 行）

```python
def _apply_combined_shape_filters(self):
    ...
    has_active_filter = (
        bool(selected_labels)      # set() → False
        or current_gid != "-1"     # "-1" == "-1" → False
        or current_type != ""      # "" == "" → False
    )
    # has_active_filter = False，但以下代码仍然执行 ↓

    matched_items = self._compute_matching_items(...)
    visible_count, changed = self._sync_label_list_visibility(is_visible)
    # ↑ _sync_label_list_visibility 内部执行：
    #   1. QSignalBlocker(model) 阻塞 Qt itemChanged 信号
    #   2. setUpdatesEnabled(False) 禁用视觉刷新
    #   3. 遍历所有 item，调用 setCheckState() 设置复选框状态
    #   4. setUpdatesEnabled(True) 恢复刷新
    #   5. del blocker 恢复信号
    #
    #  在信号阻塞+更新禁用的窗口期内，刚创建的 item
    #  可能因为 Qt 内部信号队列处理而意外被重置
```

---

## 五、修复方案

在 `_apply_combined_shape_filters()` 中添加提前返回：当 `has_active_filter` 为 `False` 时，跳过全部匹配计算和可见性同步。

**修改位置：** `label_widget.py:4269-4273` 之后

```diff
     has_active_filter = (
         bool(selected_labels)
         or current_gid != "-1"
         or current_type != ""
     )

+    if not has_active_filter:
+        self.status("")
+        return
+
     matched_items = self._compute_matching_items(
         selected_labels, current_gid, current_type
     )
```

### 修复逻辑

- `has_active_filter = False`：用户未使用任何筛选，所有形状应全部可见 → **直接 return，不做任何同步**
- `has_active_filter = True`：用户在筛选下拉框中有选择 → 正常执行 `_compute_matching_items + _sync_label_list_visibility`
- `label_info` 的标签可见性控制通过 `apply_label_visibility()` 独立处理，不受影响

---

## 六、影响范围

- 仅在无筛选条件时跳过可见性同步
- 有筛选条件时行为不变
- `label_info` 的标签可见性控制仍通过 `apply_label_visibility()` 独立处理
- 不影响其他标注模式（多边形、点、线等）
- 无论 Enable Global Filter 是开是关，只要"全部标签"选中，`has_active_filter` 为 False，都跳过同步

---

## 七、测试建议

1. 打开一张空白图片，按 R 画矩形，确认标签复选框为勾选状态、矩形可见
2. 在标签筛选下拉框中选择特定标签后画矩形，确认筛选仍正常工作
3. 开启 Enable Global Filter，选择筛选条件后切换图片，确认筛选跨图保持
4. 关闭 Enable Global Filter，切换图片后画矩形，确认无残留筛选
5. 使用"眼睛"按钮切换全部可见性后再画矩形，确认行为正确
