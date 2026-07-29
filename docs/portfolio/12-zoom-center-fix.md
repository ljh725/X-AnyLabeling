# 12 · 缩放中心点修复
#### Zoom Center Drift Fix

> 修复 upstream beta.4 在**竖图**上 Ctrl+滚轮缩放时「鼠标下的图像点漂移」的 bug：upstream 的 `width` 检测在 `setWidgetResizable(True)` 钳制下对竖图失效（guard 判 False 跳过补偿），且 y 轴误用 width 比率。用**坐标锚点算法**重写——基于 `transform_pos` 的精确逆变换，保证缩放前后鼠标下的图像点不变。
>
> [← 返回作品集主页](../PORTFOLIO.md)

---

## 解决的痛点（upstream 的 bug）

upstream beta.4 已经*尝试*做「缩放到鼠标位置」，但**在竖图上失效**：

```
竖图 600×800，fit-window 后缩放 ~135%
  → Ctrl+滚轮放大
  → 鼠标下的图像点"飘走"了（应该不动）
  → 而同样面积的横图 800×600 正常
```

**根因三层**（详见 [docs/canvas-070_note_缩放中心飘移分析.md](../canvas-070_note_缩放中心飘移分析.md)）：

1. **主因**：`scroll_area.setWidgetResizable(True)` 让 Qt 把 canvas widget 的 `width()` 钳制到 viewport 宽度（竖图逻辑宽 600×1.35≈810 远小于 1920 viewport），于是 `canvas.width()` 在缩放前后**不变** → buggy 的 guard `if canvas_width_old != canvas_width_new` 判 **False** → 整个滚动补偿被跳过，但 `scale` 确实变了（1.35→1.50），鼠标下的点就漂了 ~45px。
2. **次因**：即使补偿运行，y 轴位移复用了 **width** 比率；竖图的高度才是约束维，y 补偿算错。
3. **第三层**：`pos` 是 canvas-widget 坐标，当 canvas 尺寸随 scale 变化时语义漂移。

---

## 方案：坐标锚点算法

抛弃 upstream 的 `width` 比率启发式，改用 `transform_pos` 的**精确逆变换**。核心不变量：**缩放前后，鼠标下的图像坐标点不变**。

```python
# label_widget.py:7082-7133
def _zoom_around_canvas_pos(self, canvas_pos, apply_zoom):
    """缩放时保持 canvas_pos 下的图像点稳定。

    用完整坐标模型 widget_pos = (image_pos + offset_to_center) * scale
    （Canvas.transform_pos 的逆），这样对 setWidgetResizable(True) 钳制
    canvas widget width 的竖图也保持正确。
    """
    self.canvas.adjustSize()           # 同步当前 scale 的尺寸
    old_scale = self.canvas.scale
    old_offset = self.canvas.offset_to_center()
    old_pos = QtCore.QPointF(canvas_pos)
    image_pos = old_pos / old_scale - old_offset   # ① 锚定图像点

    apply_zoom()                        # 触发 paint_canvas 更新 scale/adjustSize

    new_scale = self.canvas.scale
    new_offset = self.canvas.offset_to_center()
    new_pos = (image_pos + new_offset) * new_scale  # ② 反投影
    delta = new_pos - old_pos            # ③ 需要补偿的位移

    # ④ clamp 防止把不可达的滚动值写进 scroll_values
    target_h = self._clamp_scroll_value(h_bar, old_h + delta.x())
    target_v = self._clamp_scroll_value(v_bar, old_v + delta.y())
    self.set_scroll(Horizontal, target_h)
    self.set_scroll(Vertical, target_v)
```

**四步**：① 缩放前用逆变换算出鼠标下的图像点 → ② 缩放后反投影回 widget 坐标 → ③ 差值即补偿位移 → ④ clamp 后设置滚动。

```python
# label_widget.py:7074-7080
def _clamp_scroll_value(scroll_bar, value):
    """钳制到滚动条有效区间。图像小于 viewport(maximum==0) 时不持久化不可达值。"""
    return max(scroll_bar.minimum(), min(scroll_bar.maximum(), value))
```

---

## 技术亮点

### 1. 用逆变换取代 width 启发式

upstream 用 `canvas_width_new / canvas_width_old` 比率估算位移——这是**启发式**，在 `setWidgetResizable` 钳制下直接失效。修复用 `transform_pos` 的精确数学逆：`image_pos = widget_pos / scale - offset`，无启发式、无失效路径。

### 2. `_clamp_scroll_value` 防状态污染

upstream 即使算出补偿值也会把**不可达**的滚动值写进 `scroll_values`（当图像小于 viewport、`maximum==0` 时）。`_clamp_scroll_value` 在 set 前钳制到 `[min, max]`，避免残留脏状态。

### 3. 符号验证式文档

[docs/canvas-080_task_缩放中心飘移修复计划.md](../canvas-080_task_缩放中心飘移修复计划.md) 用一节专门做**符号/正负号验证**：证明 `new_scroll = old_scroll + delta` 保持 `screen_pos = widget_pos - scroll_value` 不变量。这种「数学论证写进设计文档」的做法让修复可审计。

### 4. 诚实界定范围

修复明确标注 navigator 的相关方法（`on_navigator_zoom_changed` / `_convert_navigator_pos_to_canvas` / `update_navigator_viewport` / `_center_on_shape`）仍用旧的 size-ratio 模型，**本期未改**（Phase 2 延期）。不打包票「全修了」。

---

## 诚实定位

这不是「我加了一个 zoom-center 功能」——upstream *已经有*缩放到鼠标的尝试。这是**修复 upstream 在竖图上的一个静默失效 bug**：补偿逻辑被 guard 跳过、y 轴比率用错。价值在于**用精确坐标变换替换了在特定尺寸下失效的启发式**。

---

## 代码定位

| 位置 | 说明 |
|------|------|
| [`label_widget.py:7074-7080`](../../anylabeling/views/labeling/label_widget.py) | `_clamp_scroll_value` 静态助手 |
| [`label_widget.py:7082-7133`](../../anylabeling/views/labeling/label_widget.py) | `_zoom_around_canvas_pos` 坐标锚点算法 |
| [`label_widget.py:7135-7143`](../../anylabeling/views/labeling/label_widget.py) | `zoom_request` 重写（调用助手） |
| [`canvas.py:3619`](../../anylabeling/views/labeling/widgets/canvas.py) | `transform_pos`（逆变换依据，未被改动） |
| [`canvas.py:3696`](../../anylabeling/views/labeling/widgets/canvas.py) | `offset_to_center`（未被改动） |

提交：`30d522c`（ljh725）。upstream baseline `b99efef` 含 bug 版本。

---

## 设计文档

- 📄 [**canvas-070_note_缩放中心飘移分析.md**](../canvas-070_note_缩放中心飘移分析.md) — 根因三层分析（主因/次因/第三层）
- 📄 [**canvas-080_task_缩放中心飘移修复计划.md**](../canvas-080_task_缩放中心飘移修复计划.md) — 坐标锚点方案 + 符号验证 + Phase 2 范围界定

---

## 截图

> `[截图待补]` — 计划补充：竖图缩放漂移（修复前 vs 修复后）的对比动图
