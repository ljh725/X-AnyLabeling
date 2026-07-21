# 10 · 局部边缘吸附（实验性）

> **已退役（2026-07-20）**：产品验证确认该能力不好用，运行时代码、菜单入口、快捷键、配置和测试均已删除。本文仅保留为历史决策记录。

#### Local Edge Snap

> 一次性命令（Ctrl+Alt+E），对当前 Tab 选中的矩形边，在附近 ±4 图像像素内用 Sobel 梯度搜索最强边缘并尝试吸附。**纯像素梯度分析，非模型/非语义**。当前定位为实验性可选命令，**非精修主流程**——因为「图像强边缘 ≠ 标注规则上的正确边界」。
>
> [← 返回作品集主页](../PORTFOLIO.md)

---

## 解决的痛点（与设计反思）

最初设想：人工用 [精修模式（09）](09-precision-mode.md) 把边拖到目标附近后，算法根据图像边缘**自动补齐最后 1-3 像素**：

```
人工精修到附近 → 算法读图像梯度 → 自动吸附到强边缘
```

但实现并讨论后发现一个**根本性的方向问题**：在当前人物标注任务中，**「图像强边缘」不等于「标注规则上的正确边界」**：

```
人物边界可能模糊 ───┐
衣服纹理强于人体轮廓 ─┼─→ 梯度最强的位置 ≠ 应该贴的边界
头发/遮挡/光照干扰  ──┤
person 框需留白规范 ──┘   （数据规范可能要求留白，而非贴紧图像）
head/face/person 框间关系 ── 比"贴图像边缘"更重要
```

**当前结论**（诚实记录）：功能 4 不作为精修主流程继续强化，保留为**实验性、可选的一次性命令**。后续不扩大，除非重新立项明确它到底是：(1) 图像边缘吸附 / (2) 框间几何对齐 / (3) 实例内规则约束 / (4) 人工确认式候选建议——这四个方向不能混为一个功能。

> 这个「做了之后发现方向有偏、主动叫停」的过程，我如实写进了 [docs/feature_summary.md](../feature_summary.md)。

---

## 方案：Sobel 梯度 + 双重阈值

尽管定位为实验，算法本身是完整且可单测的。流程：

```
框边附近像素 → 灰度 → Sobel 梯度 → 沿边中段取梯度中位数打分 → 通过双重阈值则吸附
```

### 1. 纯 Python 评分模块（零 PyQt）

[`edge_snap.py`](../../anylabeling/views/labeling/edge_snap.py)（212 行）**零 PyQt6 依赖**，完全可独立单测。核心：

- **`EdgeSnapCache`**：按图像 `cacheKey` 懒构建灰度 + Sobel x/y 梯度（`cv2.Sobel(..., ksize=3)`），图像不变则复用
- **`score_edge`**：对候选坐标，取**垂直于边方向**的梯度分量，沿边**中段 60%**（丢两端各 20%）取**绝对值中位数**作为该坐标的边缘强度
- **`best_snap_candidate`**：在 `±search_range`（默认 ±4）窗口内找最强候选

```python
# edge_snap.py:155-212（best_snap_candidate 节选）
base = int(round(current_coord))
window = list(range(base - search_range, base + search_range + 1))  # ±4 → 9 候选
# 排除当前坐标本身（无操作吸附应报失败而非成功）
scored = [(c, s) for c, s in window_scored if c != base]
best_coord, best_score = max(scored, key=lambda cs: cs[1])

# 双重阈值（N3）：自适应 + 绝对下限，同时满足才吸附
if best_score >= k * local_max and best_score >= abs_floor:
    return best_coord, best_score
return None
```

### 2. 双重阈值：自适应 + 绝对下限

单一阈值在不同对比度图像上表现不稳。用**两条同时满足**才吸附：

| 阈值 | 默认 | 作用 |
|------|------|------|
| `k * local_max`（自适应） | k=0.6 | 候选强度需达到窗口局部最大值的 60%——跨对比度稳定 |
| `abs_floor`（绝对下限） | 10.0 | 梯度绝对值不够 10 直接拒——防低纹理图像误吸 |

测试 `test_7_22_*` / `test_7_23_*` 分别钉死两条阈值非空：弱边缘（Sobel≈8 < 10）即便过了自适应也被绝对下限拦；候选 40 虽 >10 但 < `0.6×100` 被自适应拦。

### 3. validate-before-apply：clamp 即失败

吸附候选若会被反翻转/最小尺寸 clamp 修正（即 `geometry_with_edge_coord` 返回的坐标 ≠ 候选），**视为失败而非部分应用**——边保持原位，避免「吸附到一个被截断的位置」的误导：

```python
# canvas.py:5106-5119
clamped = rea.geometry_with_edge_coord(geom, edge, cand, min_size=1.0)
if abs(clamped.get_edge_coord(edge) - cand) > 1e-9:
    return {"status": "failed", "reason": "clamped"}   # 不应用
rea.apply_edge_coord(shape, edge, cand, min_size=1.0)
```

### 4. 状态反馈：成功/失败/未激活 三态

| 状态 | 触发 | 状态栏 |
|------|------|--------|
| `inactive` | 未 Tab 选边 | `请先选中矩形并按 Tab 选择一条边` |
| `failed` | 搜索无可靠边缘 / clamp | `未找到可靠边缘，保持当前位置` |
| `success` | 吸附成功 | `已吸附 {edge} 边：{old} -> {new}（{delta:+.1f}px）` |

成功时 `store_shapes()` 推一次 undo 快照（可撤销）。

---

## 技术亮点

### 纯算法可单测

`edge_snap.py` 不 import PyQt，11 个测试在无 Qt 环境跑通。合成 30×30 灰度图（在某 x/y 处做硬阶跃）产生强 Sobel 响应，验证左/右/上/下四条边的吸附。

### 沿边中段采样

只取边**中段 60%** 评分（`DEFAULT_MIDDLE_FRACTION = 0.6`），丢掉两端各 20%。理由：边端点附近常是拐角/与其他边交界，梯度响应不代表「这条边本身」的边缘强度，中段最能反映纯边特征。用**中位数**（而非均值）聚合，对离群拐角鲁棒。

---

## 代码定位

| 位置 | 说明 |
|------|------|
| [`edge_snap.py`](../../anylabeling/views/labeling/edge_snap.py) | 212 行纯 Python 评分模块（`EdgeSnapCache`/`score_edge`/`best_snap_candidate`） |
| [`edge_snap.py:155-212`](../../anylabeling/views/labeling/edge_snap.py) | 双重阈值搜索 |
| [`canvas.py:5062-5132`](../../anylabeling/views/labeling/widgets/canvas.py) | `snap_active_edge` 桥接 + validate-before-apply + undo |
| [`label_widget.py:7247-7275`](../../anylabeling/views/labeling/label_widget.py) | `trigger_edge_snap` 命令 handler + 三态提示 |
| [`label_widget.py:1540-1547`](../../anylabeling/views/labeling/label_widget.py) | 菜单 action + Ctrl+Alt+E 绑定 |
| [`schema.py:848-863`](../../anylabeling/views/labeling/settings/schema.py) | `canvas_edge_snap_range`（int，1-20） |
| [`xanylabeling_config.yaml:213`](../../anylabeling/configs/xanylabeling_config.yaml) | 默认快捷键 `Ctrl+Alt+E` |

---

## 测试覆盖

[`tests/test_edge_snap.py`](../../tests/test_edge_snap.py)（11 个测试，纯 Python 无 Qt）：

| 测试 | 验证点 |
|------|--------|
| `test_7_11*a-c` | 左/右/上 三条边均能吸附到合成强边缘 |
| `test_7_12_*` | 低响应区（均匀灰度）→ None |
| `test_7_12b_*` | 强边缘在搜索窗外（±4 外）→ None |
| `test_7_22_*` | 弱边缘（<abs_floor）被绝对下限拦 |
| `test_7_23_*` | 候选 < `k×local_max` 被自适应拦（用 FakeCache） |
| `test_score_edge_*` | 越界/反转线段 → 0.0 |
| `test_cache_*` | cacheKey 变则重建、不变则复用 |

---

## 当前优先级与验收

| 项 | 内容 |
|----|------|
| 优先级 | **P2** — 保留为实验命令，暂不扩展 |
| 验收标准 | 仅验证：命令可执行、可失败、可撤销；**不**作为精修主流程验收指标 |
| 主流程 | [精修控制模式（09）](09-precision-mode.md) 才是矩形框精修的主流程 |

---

## 设计反思（方法论沉淀）

这个功能最大的价值不在代码，而在**「主动识别方向偏差并叫停」**的过程：

1. **原型驱动验证假设**：先实现一个能跑的版本，用它检验「图像边缘 = 标注边界」这个隐含假设
2. **发现假设不成立**：人物边界模糊、衣服纹理干扰、规范要求留白——图像梯度不可靠
3. **诚实降级**：不强行包装成「成功功能」，而是如实记录为「实验性、方向待重新定义」

这比「硬着头皮把一个方向有偏的功能做完」更有工程价值——它把「这个问题到底该不该用这个方法解」的判断显式化了。详细的四方向重立项讨论见 [docs/feature_summary.md](../feature_summary.md)。

---

## 截图

> `[截图待补]` — 计划补充：合成强边缘图上的吸附成功 / 衣服纹理干扰导致吸附错误的对比
