# Pose View 布局表格化建模

> 把“姿态标签怎么摆”从 UI 参数调试，重表征为“基于锚点的约束布局”问题。
>
> 核心转换：手工摆放参数 → 元素表 → 约束表 → 代价表 → 布局阶段。

---

## 1. 问题重表征

原始问题：

```text
Pose 标签太挤、太乱、遮挡主体，应该怎么优化布局？
```

重表征：

```text
有一组绑定关键点锚点的标签元素。
这些元素需要放在人体 bbox 周围的有限空间内。
布局目标是在靠近锚点、避免重叠、避免遮挡、保持阅读稳定之间取得平衡。
```

抽象问题：

```text
Anchor-Based Constrained Layout
基于锚点的约束布局
```

---

## 2. 元素表

每一个待绘制标签都先被看作一条 `PoseLabelItem` 记录。

| 字段 | 含义 | 当前来源 / 代码映射 | 用途 |
|------|------|-------------------|------|
| `item` | 标签元素本体 | `PoseLabelItem` | 布局操作对象 |
| `label` | 标签文本 | 关键点标签名 / 分组标签 | 决定文字宽高 |
| `anchor_x` / `anchor_y` | 标签所属关键点位置 | `PoseLabelItem.anchor_x/y` | 决定所属区域、引线起点 |
| `rect.width/height` | 标签包围盒尺寸 | 字号 + padding 计算 | 碰撞检测、列宽计算 |
| `region` | 所属空间区域 | left / right / top / bottom | 决定放置策略 |
| `priority` | 信息优先级 | 可由关键点类别、选中态、可见策略推导 | 冲突或缩放时决定保留谁 |
| `leader_start` | 引线起点 | anchor 附近偏移 | 视觉关联锚点 |
| `leader_end` | 引线终点 | label rect 边缘 | 视觉关联标签 |
| `final_rect` | 最终绘制位置 | `rect.moveTo(...)` | 渲染输入 |

---

## 3. 空间表

布局不是在无限画布上随便摆，而是在人体 bbox 周围分配空间。

| 空间对象 | 含义 | 当前方案 |
|----------|------|----------|
| `bbox` | 当前人体 / 当前标签集合的空间主体 | `_compute_bbox(items)` 或传入 bbox |
| `center_x/y` | bbox 中心 | 用于计算锚点相对方向 |
| `half_w/h` | bbox 半宽 / 半高 | 用于归一化 dx/dy |
| `left_zone` | bbox 左侧标签列 | `x = bbox_x - max_w - gap` |
| `right_zone` | bbox 右侧标签列 | `x = bbox_x2 + gap` |
| `top_zone` | bbox 顶部标签区 | 围绕 bbox 顶部中心交错摆放 |
| `bottom_zone` | bbox 底部标签区 | 围绕 bbox 底部中心交错摆放 |
| `gap` | 标签间距 | `column_gap / scale` |
| `max_w` | 当前批次最大标签宽度 | 统一左右列横向位置 |

---

## 4. 约束表

这些约束解释了为什么要调字号、gap、引线和缩放阈值。

| 约束 | 含义 | 当前实现 / 参数 | 违反时的现象 |
|------|------|----------------|--------------|
| 靠近锚点 | 标签应与关键点保持视觉关联 | `leader_start/end`, `leader_length` | 标签和关键点关系不清 |
| 避免遮挡主体 | 标签尽量放在人体 bbox 外侧 | 四象限外放：left/right/top/bottom | 标签盖住人体骨架 |
| 避免标签重叠 | 同区域标签不要互相压住 | 区内排序 + `cy` 递推 + `gap` | 文本互相遮挡 |
| 保持阅读稳定 | 同样数据多次渲染位置应稳定 | `sort(key=anchor_y)` | 标签跳动、难追踪 |
| 保持空间语义 | 左侧点去左侧，右侧点去右侧 | 归一化方向 + angle 分区 | 引线穿越主体 |
| 控制信息密度 | 缩放太小时隐藏低价值信息 | `label_zoom_threshold` | 小尺度下满屏文字 |
| 保持视觉紧凑 | 尽量减少无效留白 | `font_size`, `pad_x/y`, `column_gap` | 标签散、引线长、画面脏 |
| 保持屏幕尺度一致 | 缩放时文字视觉尺寸稳定 | `font_size / scale`, `pad / scale` | 放大缩小时标签忽大忽小 |

---

## 5. 分区规则表

四象限 Column 布局的第一步是把元素分配到区域。

| 输入字段 | 计算 | 判定 | 输出区域 |
|----------|------|------|----------|
| `anchor_x/y`, `bbox.center` | `dx = anchor_x - center_x` | `abs(norm_dx) < 0.1 and abs(norm_dy) < 0.1` | `top` |
| `dx/dy`, `half_w/h` | `norm_dx = dx / half_w`, `norm_dy = dy / half_h` | `-pi/4 <= angle <= pi/4` | `right` |
| 同上 | `angle = atan2(norm_dy, norm_dx)` | `pi/4 < angle <= 3pi/4` | `bottom` |
| 同上 | 同上 | `angle > 3pi/4 or angle <= -3pi/4` | `left` |
| 同上 | 同上 | 其余情况 | `top` |

关键点：

```text
使用归一化 dx/dy，而不是直接用像素 dx/dy。
这样宽高比例不同的人体 bbox 下，区域判断更稳定。
```

---

## 6. 区内排序表

分区后，每个区域内部再排序，保证阅读顺序和放置稳定。

| 区域 | 排序键 | 目的 |
|------|--------|------|
| left | `anchor_y` 升序 | 从上到下排列 |
| right | `anchor_y` 升序 | 从上到下排列 |
| top | `anchor_y` 升序 | 靠上的锚点先放 |
| bottom | `anchor_y` 升序 | 靠上的锚点先放 |

可扩展排序键：

```python
sort_key = (
    anchor_y,
    priority,
    label,
)
```

当后续要处理“重要标签优先保留”或“选中标签优先显示”时，可以把 `priority` 插入排序键。

---

## 7. 放置策略表

| 区域 | 初始位置 | 递推方式 | 引线方向 | 当前策略 |
|------|----------|----------|----------|----------|
| left | `bbox_x - max_w - gap` | `cy = rect.bottom + gap` | 从关键点左侧到标签右边 | 左侧纵向列 |
| right | `bbox_x2 + gap` | `cy = rect.bottom + gap` | 从关键点右侧到标签左边 | 右侧纵向列 |
| top | bbox 顶部中心左右交错 | `cy = rect.y` 向上推进 | 从关键点上方到标签底部 | 顶部双列交错 |
| bottom | bbox 底部中心左右交错 | `cy = rect.bottom` 向下推进 | 从关键点下方到标签顶部 | 底部双列交错 |

---

## 8. 代价表

如果未来从“规则布局”升级为“优化布局”，可以把每个候选位置打分。

| 代价项 | 含义 | 越小越好 | 可计算方式 |
|--------|------|----------|------------|
| `overlap_cost` | 标签与标签重叠 | 是 | 重叠面积总和 |
| `body_occlusion_cost` | 标签遮挡人体 bbox / 骨架 | 是 | 与 bbox 或骨架线段交叠面积 |
| `leader_length_cost` | 标签离锚点过远 | 是 | leader 线段长度 |
| `leader_cross_cost` | 引线互相穿插 | 是 | 线段相交次数 |
| `instability_cost` | 相邻帧位置跳动 | 是 | 与上次位置距离 |
| `density_cost` | 局部信息过密 | 是 | 区域内标签数量 / 空间容量 |
| `clipping_cost` | 超出视口 | 是 | 超出 viewport 的面积 |

总成本示例：

```python
cost = (
    overlap_cost * 100
    + body_occlusion_cost * 50
    + leader_length_cost * 2
    + leader_cross_cost * 20
    + instability_cost
    + density_cost * 10
    + clipping_cost * 100
)
```

当前方案暂不需要完整代价函数；它可以作为后续优化的判断框架。

---

## 9. 布局流水线表

| 阶段 | 输入 | 输出 | 当前实现 |
|------|------|------|----------|
| 1. 收集元素 | shapes / keypoints | `PoseLabelItem[]` | `_build_label_items` |
| 2. 计算尺寸 | 文本 + 字号 + padding | `item.rect` | `font_size / scale`, `pad_x/y / scale` |
| 3. 计算空间 | items / bbox | `bbox`, `center`, `zones` | `_compute_bbox`, bbox 参数 |
| 4. 分区归类 | item anchor + bbox center | left/right/top/bottom lists | `layout_column` angle 分区 |
| 5. 区内排序 | 各区域 list | 稳定顺序 | `sort(key=anchor_y)` |
| 6. 初始放置 | 区域 list + bbox + gap | `rect.moveTo` | left/right/top/bottom placement |
| 7. 引线生成 | anchor + final rect | `leader_start/end` | 每个区域单独计算 |
| 8. 密度控制 | scale / priority | show/hide labels | `label_zoom_threshold`（方案新增） |
| 9. 绘制 | final items | painter output | `_draw_labels` |

---

## 10. 当前参数的模型含义

| 参数 | 表面作用 | 模型含义 |
|------|----------|----------|
| `layout_mode = "column"` | 默认列布局 | 选择“四象限分区 + 区内列排布”的求解器 |
| `font_size = 9` | 字号变小 | 降低单元素尺寸，缓解 overlap / density |
| `leader_length = 15` | 引线变短 | 降低 leader_length_cost 和视觉噪声 |
| `border_width = 1.0` | 描边变细 | 降低标签视觉重量 |
| `column_gap = 4` | 间距变小 | 提升空间利用率，但增加重叠风险 |
| `label_zoom_threshold = 0.3` | 低缩放隐藏标签 | 信息密度控制阈值 |
| `pad_x = 4 / scale` | 横向内边距 | 降低 rect 宽度 |
| `pad_y = 1 / scale` | 纵向内边距 | 降低 rect 高度 |

---

## 11. 下一步落地建议

先不要直接做复杂优化器。建议按这条路线推进：

```text
四象限分区
→ 区内排序
→ 初始放置
→ 简单碰撞检测
→ 局部推开
→ 超出/过密时隐藏低优先级标签
```

最低成本增强：

1. 增加 `label_zoom_threshold`，低缩放时直接隐藏标签。
2. 缩小 `font_size` / `pad_x` / `pad_y` / `column_gap`，降低单元素占用。
3. 保留四象限分区，先解决大方向的遮挡问题。
4. 再加一个轻量 `resolve_overlaps(region_items, direction)`，只处理同区域内部重叠。
5. 最后再考虑代价函数和视口裁剪。

---

## 12. 一句话总结

```text
Pose View 布局优化不是“调几个 UI 参数”，而是：
把带锚点标签元素，在 bbox 周围有限空间中，按约束和代价进行分区、排序、放置。
```

