# 缩放中心飘逸问题分析：600×800（竖图）vs 800×600（横图）

> 状态：**待确认**。本文档仅记录分析结论，未修改任何代码。确认后再决定是否修复。

## 一、现象描述

用户在使用中观察到：

- **600×800（宽600高800，竖图 portrait）**：Ctrl+滚轮缩放时，**缩放中心不在鼠标位置**，画面会"飘逸"（鼠标下的点在缩放后偏离了原位置）。
- **800×600（宽800高600，横图 landscape）**：缩放中心基本正常，鼠标下的点能保持稳定。

两张图只是宽高互换（面积相同），为何缩放稳定性不同？

## 二、涉及代码

| 位置 | 作用 |
|------|------|
| `anylabeling/views/labeling/label_widget.py:6942-6963` | `zoom_request` —— Ctrl+滚轮缩放的核心，**问题所在** |
| `anylabeling/views/labeling/widgets/canvas.py:3676-3679` | `wheelEvent` 把 Ctrl+Wheel 转成 `zoom_request` 信号 |
| `anylabeling/views/labeling/widgets/canvas.py:3622-3626` | `minimumSizeHint` —— canvas widget 逻辑尺寸 = `scale × pixmap` |
| `anylabeling/views/labeling/label_widget.py:548` | `scroll_area.setWidgetResizable(True)` —— 关键的尺寸钳制开关 |
| `anylabeling/views/labeling/widgets/canvas.py:3433-3443` | `offset_to_center` —— 居中偏移（缩放后图像小于视口时生效） |
| `anylabeling/views/labeling/widgets/canvas.py:3429-3431` | `transform_pos` —— 屏幕→图像坐标换算 |

## 三、问题代码（`zoom_request`）

```python
# anylabeling/views/labeling/label_widget.py:6942-6963
def zoom_request(self, delta, pos):
    canvas_width_old = self.canvas.width()          # ← 只取 width
    units = 1.1
    if delta < 0:
        units = 0.9
    self.add_zoom(units)

    canvas_width_new = self.canvas.width()          # ← 只取 width
    if canvas_width_old != canvas_width_new:        # ← 用 width 变化判断"是否真的缩放了"
        canvas_scale_factor = canvas_width_new / canvas_width_old

        x_shift = round(pos.x() * canvas_scale_factor - pos.x())
        y_shift = round(pos.y() * canvas_scale_factor - pos.y())  # ← y 复用了 x 的因子

        self.set_scroll(Qt.Orientation.Horizontal,
            self.scroll_bars[Qt.Orientation.Horizontal].value() + x_shift)
        self.set_scroll(Qt.Orientation.Vertical,
            self.scroll_bars[Qt.Orientation.Vertical].value() + y_shift)
```

## 四、根因分析（三个层面）

### 层面 1（主因）：`canvas.width()` 被 `setWidgetResizable(True)` 钳制 → 补偿被整体跳过

`label_widget.py:548` 启用了 `scroll_area.setWidgetResizable(True)`。Qt 的该行为是：**当子 widget 的 sizeHint 小于视口时，强制把它拉伸到视口尺寸**。

canvas 的 `minimumSizeHint`（`canvas.py:3622-3626`）返回 `self.scale * self.pixmap.size()`：

- **600×800（竖图）**：在 1920×1080 视口下 fit_window 约 135%，缩放后逻辑尺寸 ≈ 810×1080。**宽度 810 < 视口宽 1920**，于是 canvas widget 的实际 `width()` 被钳制成 ≈视口宽 1920，而非 `scale×600`。
  - 缩放（如 135% → 150%）后逻辑宽 = 600×1.5 = 900，仍 < 1920，**仍被钳制**。
  - `canvas_width_old(≈1920) == canvas_width_new(≈1920)` → **`if` 判断为假，整个滚动条补偿被跳过**。
  - 但 scale 实际从 1.35 → 1.50 变了，图像视觉放大，鼠标下的图像点屏幕位置已移动，滚动条却不补偿 → **飘逸**。

- **800×600（横图）**：fit_window 约 180%，逻辑宽 = 800×1.8 = 1440，更接近视口宽；继续放大后逻辑宽（如 800×2.0=1600）会真实增长并接近/超过视口宽边界 → `canvas_width_old != canvas_width_new` 成立 → **进入补偿分支** → 大致正常。

**结论**：竖图因缩放后宽度小于视口，canvas width 被钳制、不随 scale 变化，导致缩放检测失效、补偿被跳过——这是飘逸的主因。

### 层面 2：即便进入补偿，y 方向错用了宽度因子

`canvas_scale_factor = canvas_width_new / canvas_width_old` 只反映**宽度**变化率，但 y 方向的滚动条补偿也用了它。对竖图（高度方向是限制维度、像素多），y 方向的真实位移需要 height 因子，错用 width 因子会算偏。

### 层面 3：`pos` 坐标语义在缩放前后已变

`pos` 来自 canvas 的 `wheelEvent`（`ev.position().toPoint()`），是相对 canvas widget 的坐标。canvas 尺寸随 scale 变化时，同一屏幕位置的 `pos` 值在缩放前后语义不同，直接用旧 pos 参与新位移计算会引入误差。

## 五、数值推导（600×800，视口 1920×1080，135% → 150%）

设鼠标位于图像中部（图像坐标 300,400）：

| 时刻 | scale | canvas 逻辑尺寸 | canvas.width()（被钳制后） | 是否进入补偿 |
|------|-------|-----------------|---------------------------|-------------|
| 缩放前 | 1.35 | 810 × 1080 | ≈1920（被视口钳制，因 810<1920） | — |
| 缩放后 | 1.50 | 900 × 1080 | ≈1920（仍被钳制，因 900<1920） | **否**（width 未变） |

- `canvas_width_old == canvas_width_new` → 跳过 `set_scroll` 补偿。
- 但 scale 变了 1.35→1.50，图像点 300,400 的屏幕位置从 `300×1.35 + offset` 变成 `300×1.50 + offset`，移动了 `300×0.15 = 45px`，无人补偿 → 鼠标下的点飘走 45px。

对照 800×600 在 180%→200%：逻辑宽 1440→1600，width 会真实变化 → 进入补偿 → 基本稳定。

## 六、为什么两张图表现不同（一句话）

竖图(600×800)缩放后宽度小于视口宽，`setWidgetResizable(True)` 把 canvas width 钳成视口宽，导致 `zoom_request` 的"width 变化"检测失效、滚动条补偿被整体跳过；横图(800×600)缩放后宽度接近/超过视口宽，width 能真实变化，补偿正常触发。

## 七、修复方案（按推荐度排序）

### 方案 A（推荐）：用 scale 比作因子，按"保持鼠标下图像点不动"重算滚动条

核心思想：缩放前后，让鼠标光标下的那个**图像坐标点**保持在同一**屏幕位置**。

数学：
- 设鼠标图像坐标 `ip = transform_pos(pos_screen)`（缩放前算）。
- 缩放后新的滚动条值应满足：`screen_pos(ip, new_scale, new_scroll) == pos_screen`。
- 推导得：`scroll_new = scroll_old + (new_scale - old_scale) * ip`（图像坐标系下的位移）。

改动范围：仅 `zoom_request` 一个函数。不依赖 `canvas.width()`，绕开 widgetResizable 钳制问题，对所有图方向都准确。

### 方案 B：用 canvas.height() 单独算 y 因子

在 `zoom_request` 增加 height 变化检测，y 方向用 height 因子。部分缓解层面 2，但层面 1（width 钳制导致跳过）仍在，竖图依旧飘逸。不推荐单独用。

### 方案 C：关闭 `setWidgetResizable(True)`

改 layout 策略，让 canvas 严格按 `scale×pixmap` 尺寸。副作用大：会影响 fit_window 下的居中布局（`offset_to_center` 依赖 widget 尺寸行为）。不推荐。

## 八、验证方法

### 快速验证根因（层面 1）

在 `zoom_request` 临时加日志：

```python
def zoom_request(self, delta, pos):
    canvas_width_old = self.canvas.width()
    ...
    canvas_width_new = self.canvas.width()
    print(f"[zoom] old={canvas_width_old} new={canvas_width_new} "
          f"changed={canvas_width_old != canvas_width_new} "
          f"scale={self.canvas.scale}")
    ...
```

在 600×800 上 Ctrl+滚轮缩放：若看到 `changed=False` 且 `scale` 确实变化，则证实层面 1 的钳制问题。
在 800×600 上同样操作对照：应看到 `changed=True`。

### 修复后验证

- 600×800 与 800×600 在任意位置 Ctrl+滚轮缩放，鼠标下的图像点保持屏幕位置不变。
- 缩放到边界（1%、1000%）行为正常。
- 切图后 fit_window 仍正确居中。

## 九、待确认事项

1. 根因分析（尤其层面 1 的 widgetResizable 钳制假设）是否符合你对现象的观察？
2. 是否采纳方案 A？确认后我会进入计划模式给出精确的代码改动（仅改 `zoom_request` 一个函数）。
3. 是否需要补充针对 `keep_prev_viewport` / navigator 等相关路径的检查？

---

## 十、对实现文档（canvas-080_task_缩放中心飘移修复计划.md）的评审反馈

> 本节是对配套实现文档的技术评审。认可整体思路（image-anchor 模型 + 纳入 `offset_to_center`），但发现 **1 个致命符号问题 + 2 个隐患 + 1 个边界一致性问题**，必须在编码前澄清。

### 背景：坐标模型的核实结论

实现文档第 2 节声称的坐标模型：

```text
widget_pos = (image_pos + offset_to_center) * scale
image_pos  = widget_pos / scale - offset_to_center
```

经核实 `canvas.py:2365-2367`（paint 顺序 `scale → translate`）与 `canvas.py:3431`（`transform_pos`）、`canvas.py:3441`（offset 已除以 scale）后确认：**正向公式数值上成立**，且 `transform_pos` 是权威反函数（`image_pos = widget_pos / scale - offset`，注意 `offset` 不再除 scale，因为 `offset_to_center()` 内部已除过 `s`）。这一节文档写对了。

### 问题 1（🚨 致命）：helper 里 `scroll_new = old_scroll + delta` 的符号存疑

实现文档第 76 行写：

```text
new_scroll = old_scroll + scroll_delta   # 文档写 +
```

helper 伪代码（文档 124-145 行）：

```python
delta = new_pos - old_pos                  # = 同一图像点在 canvas widget 坐标系下的位移
self.set_scroll(H, old_h + delta.x())      # 文档用 +
```

**符号推导**：

- `delta = new_pos - old_pos` 表示"鼠标下的图像点在 canvas widget 坐标系中、缩放后比缩放前多走了多少像素"。
- 滚动条 `old_h` 表示"视口左上角在 canvas widget 坐标系中的位置"。
- 要让鼠标下的图像点**屏幕位置不变**（即视口看到的内容跟着图像点走），视口必须**与图像点同向移动 `delta`**。
- 视口移动 `delta` ⟺ 滚动条值移动 `delta`？

  这里需要区分"滚动条值增大 = 视口向内容下方/右方移动"（Qt 默认语义）。图像点 widget 坐标增大 `delta`，要让它在视口内的相对位置不变，视口也需向右下移动 `delta`，即滚动条值增大 `delta`。

  **按此推导符号应为 `+`，与文档一致。**

**但是**：直觉上"以鼠标为中心放大"时，放大后图像点会向远离原点的方向移动（图像变大了），若不补偿，鼠标下的点会朝远离原点方向漂走；补偿方向应是"把视口也朝那个方向拉"——这与 `+` 自洽。

**存疑点**：我的第一反应是 `-`，但仔细推导又得到 `+`。这种符号问题极易在 QPainter 矩阵手算时出错。**强烈建议**：在动手前用一段独立的数值验证（不接 UI，纯算 `old_pos / old_scale - old_offset` → `new_pos` → 看符号），或写一个最小测试在 offscreen canvas 上跑一次，确认 `+` 正确。这是修复成败的开关。

### 问题 2（⚠️ 隐患）：`old_offset` 计算时机与 pending layout

helper 流程：

```python
old_offset = self.canvas.offset_to_center()   # ①
apply_zoom()                                    # ② set_zoom → paint_canvas → adjustSize
new_offset = self.canvas.offset_to_center()    # ③
```

`offset_to_center()`（`canvas.py:3438`）依赖 `super().size()`，而 `paint_canvas()`（`label_widget.py:7476`）调 `self.canvas.adjustSize()` 会触发 Qt layout 重算，改变 canvas widget size。

- ③ 用的是 adjustSize 后的新 size ✓（正确）
- 但 ① 的 `old_offset` 用的 size 是否可靠？

如果上一次 paint 之后有未处理的 layout 事件（例如刚切换图像、刚 fit_window），`super().size()` 可能仍是旧值，导致 `old_offset` 偏。

**建议**：在 ① 之前强制一次同步布局，例如 `self.canvas.update()` 或直接读 `self.canvas.size()`（已 layout 完成的值）。实现文档未提及这一点，需补充。

### 问题 3（⚠️ 隐患）：maximum==0 方向的 clamp 行为

实现文档第 78 行自承认：

> 如果某个方向的图像小于视口，滚动条最大值为 0，则该方向无法通过滚动条保持任意鼠标点稳定。

但 helper（文档 144-145 行）无条件 `set_scroll(H, old_h + delta.x())`。Qt 的 `setValue` 会自动 clamp 到 `[minimum, maximum]`。当 maximum==0（如 600×800 宽度方向小于视口）时：

- 水平 delta 被 clamp 吃掉（水平靠 `offset_to_center` 居中保持稳定）✓
- 但 **vertical delta 仍按公式算出并应用** → 可能出现"水平不动、垂直漂移"的不一致

实现文档第 337 行手工验证只说"无滚动条方向允许有受限漂移"，没说要不要主动处理。

**建议**：在 helper 里检测某方向 `maximum == 0` 时跳过该方向 `set_scroll`（让居中 offset 负责稳定），避免与有滚动条方向的补偿产生不一致。需在实现中明确决策。

### 问题 4（边界一致性）：改 4.3 但不改第 5 节的 navigator 一致性

实现文档第 4.3 节建议把 `_convert_navigator_pos_to_canvas`（`label_widget.py:6880-6881`）从 `x_ratio * canvas.width()` 改为基于 pixmap/offset/scale 的新公式。但第 5 节又把 `_center_on_shape`、`update_navigator_viewport` 列为"第二阶段不改"。

风险：若只改 4.3（navigator 点击定位用新模型）而不改 `update_navigator_viewport`（viewport 框绘制仍用旧 canvas.size 比例模型），会出现 **navigator 点击位置与 viewport 框显示位置模型不一致**，可能产生新的视觉偏差。

**需确认**：是否接受这种"半新半旧"状态作为第一阶段交付？还是建议把 `update_navigator_viewport` 也纳入第一阶段同步改？

### 反馈小结

| # | 问题 | 严重度 | 阻塞编码？ |
|---|------|--------|-----------|
| 1 | helper 符号 `+` vs `-` | 致命 | **是**，需先验证 |
| 2 | old_offset 计算前是否需强制 layout 刷新 | 中 | 否，但建议补 |
| 3 | maximum==0 方向是否主动跳过补偿 | 中 | 否，但建议明确 |
| 4 | navigator 4.3 与第 5 节模型不一致 | 低 | 否，但建议决策 |

**建议先解决问题 1**：用一段独立数值验证 `+`/`-` 符号（或写一个 offscreen 最小测试），再进入编码。其余 3 点可在编码时一并处理，但实现文档应补充相应说明。
