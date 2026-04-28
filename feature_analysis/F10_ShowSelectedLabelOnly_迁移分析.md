# 功能10：  — 迁移分析报告（4.0.0 最终版）

- **难度**: ⭐ | **影响级别**: 🟢 极小改动
- **源文件**: 无独立文件，嵌入 `canvas.py` + `label_widget.py` (~15行)
- **实际耗时**: ~10分钟

---

## 1. 原分析文档的问题

旧文档提到"需适配 QGraphicsView"，但实际上 **4.0.0-beta.4 仍使用 QWidget-based Canvas**（3678行），未迁移到 QGraphicsView。因此 F10 的实现方式与旧版完全一致：在 `paintEvent` 中通过条件判断跳过非选中 shape 的标签绘制。

---

## 2. 4.0.0 实现详情

### `canvas.py`
- `__init__` 中新增属性：`self.show_selected_label_only = False`
- `paintEvent` 的标签绘制循环中（第 2618 行附近）插入条件：
  ```python
  if self.show_selected_label_only and not shape.selected:
      continue
  ```
  当开启时，只有 `shape.selected == True` 的标签才会被收集到 `labels` 列表中并绘制。

### `label_widget.py`
- Action 定义（复用现有 `set_canvas_params` 机制）：
  ```python
  show_selected_label_only = action(
      self.tr("Show Selected Label Only"),
      lambda x: self.set_canvas_params("show_selected_label_only", x),
      tip=self.tr("Show labels only for selected shapes"),
      checkable=True,
      checked=self._config.get("show_selected_label_only", False),
      auto_trigger=True,
  )
  ```
- `set_canvas_params(key, value)` 会自动将属性设置到 Canvas 并调用 `canvas.update()`，无需额外连接 selection 信号。

### 配置
- `xanylabeling_config.yaml` 新增：`show_selected_label_only: false`

---

## 3. 与 3.3.8 设想的差异

| 项目 | 3.3.8 文档设想 | 4.0.0 实际 |
|------|---------------|-----------|
| Canvas 架构 | QGraphicsView + LabelItem.setVisible() | QWidget-based paintEvent |
| 实现方式 | ShapeManager 控制 LabelItem 可见性 | `paintEvent` 循环中 `continue` 跳过 |
| 文件数 | 3 个（adapter + shape_manager + label_widget） | 2 个（canvas + label_widget） |
| 代码量 | ~30行 | ~15行 |

---

## 4. 测试验证

1. 打开一张有多个 shape 的图片
2. View 菜单 → 勾选 "Show Selected Label Only"
3. 未选中任何 shape 时，画布上不应显示任何标签
4. 选中某个 shape 后，只有该 shape 的标签显示
5. 选中多个 shape 时，这些 shape 的标签都显示
6. 取消勾选后，所有标签恢复正常显示
