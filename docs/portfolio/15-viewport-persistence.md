# 15 · 视口状态保持
#### Viewport State Persistence

> 切图时保留**缩放级别 + 视图中心**——「我放大到 300% 盯着的人脸，切到下一张图还是 300% 看同位置」。核心决策：把视图中心存成**图像坐标**而非滚动条像素值，这样状态能跨 widget resize、跨不同尺寸的图片存活。复用模块 12 验证过的 `transform_pos` 坐标模型。
>
> [← 返回作品集主页](../PORTFOLIO.md)

---

## 解决的痛点

逐张检查标注时，标注员会把图放大到某个级别、聚焦某个区域。原生行为切图就回到 fit-window：

```
图 A：放大到 250%，看着右上角的人脸
  → 按下一张
  → 图 B 突然 fit-window 缩小，我得重新放大、重新定位
  → 5000 张图，每张都重来 → 大量时间浪费在"找回到刚才的视角"
```

upstream 有 `keep_prev_scale`（保留缩放比例）和 `keep_prev_brightness/contrast`，但**都不保留"看哪个位置"**——缩放比例对了，看的还是左上角而不是刚才的人脸。

---

## 方案：图像坐标持久化

`ViewportController` 按 filename 缓存 `(zoom_mode, zoom_value, center_x, center_y)`，其中中心点存为**图像坐标**。

```
离开图 A（on_file_leaving）──► 捕获当前视图中心（滚动条→widget→图像坐标）
       │
       ▼
加载图 B（on_file_loaded）──► 解析最佳状态 ──► 重新计算滚动位置（图像坐标→widget→滚动条）
```

恢复时有三级解析优先级：
1. **精确历史**：这张图之前看过 → 恢复它自己的状态
2. **`keep_prev_viewport` 继承**：没看过 + 开关开启 → 继承上一张图的状态
3. **无**：第一张图 / 没有缓存 → 回退 `adjust_scale(initial=True)`

---

## 技术亮点

### 1. 图像坐标 vs 滚动条像素（核心决策）

最关键的设计：**视图中心存图像坐标，不存滚动条像素值**。

```
为什么不存滚动条像素？
  → widget resize 后像素值失效
  → 不同尺寸的图，同样的像素值指向完全不同的位置
```

捕获用 `Canvas.transform_pos` 的逆变换，恢复用正向变换——和 [模块 12（缩放中心点修复）](12-zoom-center-fix.md) **完全相同的坐标模型**：

```python
# viewport_controller.py — 捕获（screen → image）
widget_cx = h_bar.value() + viewport_w / 2.0      # 视口中心的 widget 坐标
center_x = widget_cx / scale - offset.x()          # transform_pos 的逆

# 恢复（image → screen）
widget_cx = (center_x + offset.x()) * scale        # 正向变换
target_h = int(widget_cx - viewport_w / 2.0)       # 反推滚动条值
target_h = max(min, min(max, target_h))            # clamp 到有效区间
```

因为中心是图像坐标，加载新图后用**新图的** `offset_to_center()` 和 `scale` 重新反推滚动条——即使新图尺寸不同，概念上的「看这个位置」被保留。

### 2. 复用模块 12 验证过的坐标模型

模块 12（缩放修复）证明了 `widget_pos = (image_pos + offset_to_center) * scale` 这个坐标模型在竖图、`setWidgetResizable` 钳制下都正确。本功能直接复用这对公式（捕获=逆，恢复=正），**零新坐标数学**——一次证明，两处复用。

### 3. 三级解析优先级 + stale 状态清理

- **精确历史优先**：每张图记住自己的视角，回到这张图就恢复它自己的
- **继承兜底**：`keep_prev_viewport` 开启时，新图继承上一张的视角
- **防 stale**：`clear_state` 删文件状态时，若删的是 `_last_loaded`，同时清空 `_last_loaded`，防止继承到一个已删除文件的视角

### 4. 三缩放模式全保留

`ViewportState.zoom_mode` 记录 FIT_WINDOW / FIT_WIDTH / MANUAL_ZOOM，恢复时连同模式一起还原——不只是数值，连「自动适应」还是「手动缩放」的状态都保留。

---

## 与模块 12 的关系

| | 模块 12：缩放中心点修复 | 本功能：视口状态保持 |
|---|---|---|
| **目的** | 单次缩放时鼠标下的点不漂移 | 跨图片导航保留视图 |
| **触发** | 用户滚轮缩放 | 切图生命周期（`load_file`） |
| **坐标模型** | `transform_pos` 逆变换 | **同一对公式**（捕获=逆，恢复=正） |
| **共享原语** | `canvas.scale` / `offset_to_center()` / `transform_pos` | 完全相同 |

两者独立、互不调用，但共享同一套经过验证的坐标代数。模块 12 解决「一次操作的正确性」，本功能解决「跨操作的状态延续」。

---

## 代码定位

| 位置 | 说明 |
|------|------|
| [`viewport_controller.py`](../../anylabeling/views/labeling/widgets/viewport_controller.py) | 359 行，`ViewportState` dataclass + `ViewportController` |
| [`viewport_controller.py:225-284`](../../anylabeling/views/labeling/widgets/viewport_controller.py) | `_capture` 捕获（screen→image，transform_pos 逆） |
| [`viewport_controller.py:302-359`](../../anylabeling/views/labeling/widgets/viewport_controller.py) | `_apply` 恢复（image→screen，正向变换 + clamp） |
| [`label_widget.py:2980`](../../anylabeling/views/labeling/label_widget.py) | `ViewportController()` 实例化 |
| [`label_widget.py:7440-7445`](../../anylabeling/views/labeling/label_widget.py) | `on_file_leaving` 离开图时保存（`load_file` 开头） |
| [`label_widget.py:7622-7627`](../../anylabeling/views/labeling/label_widget.py) | `on_file_loaded` 加载后恢复 + `keep_prev_viewport` 配置门 |
| [`label_widget.py:1326-1335`](../../anylabeling/views/labeling/label_widget.py) | View 菜单 action「Keep Previous Viewport」 |
| [`label_widget.py:7799-7824`](../../anylabeling/views/labeling/label_widget.py) | `_clear_view_state_for_files` 文件删除时清理 stale 状态 |
| [`xanylabeling_config.yaml:10`](../../anylabeling/configs/xanylabeling_config.yaml) | 默认 `keep_prev_viewport: false` |

---

## 边界处理

| 场景 | 处理 |
|------|------|
| 无有效 pixmap | `_capture`/`_apply` 检查后返回 None/early return |
| 找不到 QScrollArea | 沿 parent chain 查找，找不到则安全退出 |
| 滚动条越界 | `max(min, min(max, target))` clamp |
| 第一张图/无缓存 | `on_file_loaded` 返回 None → 回退 `adjust_scale(initial=True)` |
| 删除文件后继承 stale | `clear_state` 同步清空 `_last_loaded` |
| 极端不同宽高比继承 | 中心可能落到边界外 → clamp 防崩溃，但可能吸附到边缘（已知副作用） |

---

## 设计文档

- 📄 [**canvas-060_des_视口状态管理.md**](../canvas-060_des_视口状态管理.md) — 304 行完整设计文档（11 节：组件/策略/坐标转换/调用链/边界/交互/UI/调试/版本史）

---

## 截图

> `[截图待补]` — 计划补充：切图后保持 250% + 人脸位置（vs upstream 回到 fit-window）的对比
