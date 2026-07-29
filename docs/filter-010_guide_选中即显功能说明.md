# Label on Selection 功能技术文档

## 功能概述

`Label on Selection`（选中即显）是 Canvas 标签绘制模式。启用后，画布只绘制当前已选中对象的标签文字，未选中对象的标签文字不绘制。

该功能只影响“标签文字绘制”，不改变对象本身的可见性。

---

## 一、与筛选系统的关系

当前对象可见性和标签绘制分属两个层级：

| 层级 | 控制内容 | 主要实现 |
|------|----------|----------|
| Shape visibility | 对象是否可见、是否可被绘制/选中 | `FilterState` + `ShapeFilterEngine` + `shape.visible` |
| Label drawing | 可见对象的标签文字是否绘制 | `Canvas.label_on_selection` + `shape.selected` |

关系规则：

1. 如果 `shape.visible == False`，对象和标签都不会绘制。
2. 如果 `shape.visible == True` 且 `show_labels == False`，对象绘制但标签不绘制。
3. 如果 `shape.visible == True`、`show_labels == True`、`label_on_selection == False`，绘制所有可见对象的标签。
4. 如果 `shape.visible == True`、`show_labels == True`、`label_on_selection == True`，只绘制已选中对象的标签。

因此，`Label on Selection` 不替代 label/gid/shape_type 筛选，也不修改 `FilterState`。

---

## 二、状态管理

### 2.1 配置层

文件：`anylabeling/configs/xanylabeling_config.yaml`

```yaml
label_on_selection: false
```

配置会随应用配置保存到用户配置文件。

### 2.2 UI 层

文件：`anylabeling/views/labeling/label_widget.py`

```python
label_on_selection = action(
    self.tr("Label on Selection"),
    lambda x: self.set_canvas_params("label_on_selection", x),
    tip=self.tr("Show labels only for selected shapes"),
    icon=None,
    checkable=True,
    checked=self._config.get("label_on_selection", False),
    enabled=True,
    auto_trigger=True,
)
```

### 2.3 Canvas 层

文件：`anylabeling/views/labeling/widgets/canvas.py`

```python
self.label_on_selection = False
```

运行时通过 `set_canvas_params()` 同步到 Canvas：

```python
def set_canvas_params(self, key, value):
    self._config[key] = value
    assert hasattr(self.canvas, key), f"Canvas has no attribute {key}"
    setattr(self.canvas, key, value)
    self.canvas.update()
```

---

## 三、绘制逻辑

标签绘制阶段的核心判断：

```python
for shape in self.shapes:
    if not shape.visible:
        continue
    if self.label_on_selection and not shape.selected:
        continue
    # draw label text
```

行为矩阵：

| `shape.visible` | `show_labels` | `label_on_selection` | `shape.selected` | 标签绘制 |
|-----------------|---------------|----------------------|------------------|----------|
| `False` | 任意 | 任意 | 任意 | 否 |
| `True` | `False` | 任意 | 任意 | 否 |
| `True` | `True` | `False` | 任意 | 是 |
| `True` | `True` | `True` | `False` | 否 |
| `True` | `True` | `True` | `True` | 是 |

---

## 四、选择行为

`Label on Selection` 依赖 `shape.selected`，所以它对选择状态敏感。

当前行为：

| 用户操作 | 普通模式 | label_on_selection 模式 |
|----------|----------|-------------------------|
| 点击未选中对象 | 选中该对象 | 选中该对象并显示其标签 |
| 点击空白区域 | 取消选中 | 取消选中，标签随之隐藏 |
| Ctrl/多选操作 | 添加到选中集 | 添加到选中集，显示所有选中对象标签 |
| 切换编辑/绘制模式 | 可能清空选中 | 可能清空选中，标签随之隐藏 |

重复点击已选中对象的细节依赖命中路径：

- 普通形状内部命中时，`label_on_selection=True` 会避免把 `h_shape_is_selected` 置为取消选择状态。
- 顶点、cuboid 等特殊命中路径仍按各自选择逻辑处理。
- 空白点击最终进入 `deselect_shape()`，会取消选中。

这意味着该功能不是“锁定选中对象”，而是“只为当前选中对象绘制标签”。

---

## 五、调用链

```text
用户点击对象
  |
  v
Canvas.mousePressEvent() / select_shape_point()
  |
  v
Canvas.selection_changed.emit([...])
  |
  v
LabelingWidget.shape_selection_changed()
  |
  v
shape.selected 更新
  |
  v
Canvas.update()
  |
  v
Canvas.paintEvent()
  |
  v
根据 show_labels / label_on_selection / shape.selected 决定是否绘制标签文字
```

---

## 六、关键文件

| 文件 | 职责 |
|------|------|
| `anylabeling/configs/xanylabeling_config.yaml` | 默认配置 |
| `anylabeling/views/labeling/label_widget.py` | 菜单 Action、配置同步、Canvas 参数更新 |
| `anylabeling/views/labeling/widgets/canvas.py` | 选择逻辑、标签绘制逻辑 |

---

## 七、验证清单

1. 启用 `Label on Selection`，选中一个对象，只显示该对象标签。
2. 多选多个对象，显示所有选中对象标签。
3. 点击空白区域取消选中后，不显示对象标签。
4. 关闭 `Label on Selection` 后，恢复显示所有可见对象标签。
5. 开启 label/gid/shape_type 筛选后，只在筛选后仍可见的对象中应用选中即显。
6. 隐藏某个 label 后，即使对象被选中，也不绘制该对象标签。
7. `show_labels=False` 时，无论 `label_on_selection` 是否开启，都不绘制标签。

---

## 八、维护注意事项

1. 不要在 `Label on Selection` 中修改 `shape.visible` 或 `FilterState`。
2. 不要把该功能和筛选保持逻辑混在一起；筛选决定对象是否可见，本功能只决定标签文字是否绘制。
3. 修改选择逻辑时，需要同时验证普通形状、点、线、polygon、rectangle、cuboid 的点击命中路径。
4. 如果未来需要“锁定选中对象不被空白点击取消”，应作为独立模式实现，不应混入 `label_on_selection`。

---

文档版本：4.1  
更新日期：2026-05-09  
适用版本：X-AnyLabeling 4.0.0-beta.4
