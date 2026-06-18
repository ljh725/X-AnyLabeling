## 1. 实现左右前缀方向规则

- [ ] 1.1 在 `pose_layout.py` 新增 `_is_lateral_prefix(label)` 辅助函数，支持 `l_`/`r_`/`left_`/`right_` 大小写不敏感匹配
- [ ] 1.2 在 `pose_layout.py` 新增 `_apply_lateral_prefix_rule(direction, label, mid_x, anchor_x)` 函数，将方向修正到左侧族/右侧族/正中
- [ ] 1.3 修改 `compute_direction()`，在返回前调用 `_apply_lateral_prefix_rule()`
- [ ] 1.4 确保 `nose` 标签返回 `up` 方向（正中）

## 2. 实现躯干与下肢分层排列

- [ ] 2.1 在 `pose_layout.py` 新增 `_body_part_group(label)` 函数，将 COCO 标签映射到 `head`/`la`/`ra`/`ll`/`rl`
- [ ] 2.2 在 `apply_layout()` 中，对 `anti` 模式按身体部位分组，并在组内按 Y 轴排序
- [ ] 2.3 在 `layout_column()` 中，按身体部位分组后分别进入左/右/顶列，并保持 Y 轴顺序
- [ ] 2.4 在 `layout_direct()` 中保持现有直接放置，但方向已被前缀规则修正

## 3. 实现中线不交叉约束

- [ ] 3.1 在 `layout_anti()` 中，对前缀强制方向后的候选矩形检查是否越过 midline
- [ ] 3.2 若候选位置越过中线，沿方向继续外推直到不越界或达到 `search_max`
- [ ] 3.3 在 `layout_column()` 分栏时，对 `l_xxx` 强制左列、`r_xxx` 强制右列，无视默认方向
- [ ] 3.4 在 `layout_direct()` 中，直接按前缀方向放置，不额外检查中线

## 4. 实现头部关键点横向排列

- [ ] 4.1 在 `pose_renderer.py` 的 `_build_label_items()` 中，对头部标签使用较小的 `leader_length` 缩放系数
- [ ] 4.2 在 `layout_column()` 的 `top_items` 处理中，按 `l_eye`/`nose`/`r_eye` 顺序横向排列
- [ ] 4.3 确保头部标签的左右偏移量小于躯干标签

## 5. 单元测试

- [ ] 5.1 测试 `l_sho` 默认方向为左侧族
- [ ] 5.2 测试 `r_kne` 默认方向为右侧族
- [ ] 5.3 测试 `Left_elb` 大小写不敏感匹配
- [ ] 5.4 测试 `nose` 方向为 `up`
- [ ] 5.5 测试 `anti` 布局下 `l_xxx` 矩形不越过中线
- [ ] 5.6 测试 `column` 布局下 `r_xxx` 分到右列
- [ ] 5.7 测试躯干标签按 Y 轴从上至下排列
- [ ] 5.8 测试头部标签横向排列顺序
- [ ] 5.9 测试无前缀自定义标签回退默认方向
- [ ] 5.10 测试空间不足时向同侧外推

## 6. 验证与文档

- [ ] 6.1 运行 `pytest tests/test_pose_layout.py tests/test_pose_renderer.py` 并全部通过
- [ ] 6.2 在本地打开 pose 图片，目视检查躯干/下肢/头部标签分布
- [ ] 6.3 更新 `pose_layout.py` 和 `pose_renderer.py` 相关函数 docstring
- [ ] 6.4 运行 `flake8 anylabeling/views/labeling/widgets/pose_label/`
- [ ] 6.5 标记所有任务完成，准备归档
