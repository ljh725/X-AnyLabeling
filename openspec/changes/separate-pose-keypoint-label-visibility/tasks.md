## 1. 拆分 Pose 几何与文本标签渲染

- [ ] 1.1 调整 Pose View 渲染入口，使姿态几何在 Pose View 开启且存在 pose 数据时即可渲染
- [ ] 1.2 在 `pose_renderer.py` 中区分“几何绘制”与“关键点文本绘制”两层策略
- [ ] 1.3 确保无 group 聚焦时只显示姿态几何，不显示关键点文本

## 2. 收紧 Pose 聚焦状态边界

- [ ] 2.1 梳理 `label_widget.py` 与 `canvas.py` 中 pose 聚焦状态的来源
- [ ] 2.2 让只有 pose group 聚焦相关状态才会触发关键点文本显示
- [ ] 2.3 去除或显式隔离与 Pose 标签策略无关的 `label_on_selection` 传递语义

## 3. 清理 Pose View 下的普通标签干扰

- [ ] 3.1 在 Pose View 中 suppress COCO 关键点的原生普通标签
- [ ] 3.2 在 Pose View 中默认 suppress `person` 矩形框的原生标签文本
- [ ] 3.3 保留 person 框线和 pose 几何本身，不影响空间定位

## 4. 补充回归测试

- [ ] 4.1 为“无过滤也渲染 Pose 几何”补充测试
- [ ] 4.2 为“无 group 聚焦不显示关键点文本”补充测试
- [ ] 4.3 为“聚焦 group 后仅显示该组关键点文本”补充测试
- [ ] 4.4 为“Pose View 中隐藏 person 矩形框标签文本”补充测试
- [ ] 4.5 为“普通 Label on Selection 开关不驱动 Pose 关键点文本”补充测试

## 5. 验证

- [ ] 5.1 运行 `pytest tests/test_canvas_interaction.py tests/test_pose_renderer.py -q`
- [ ] 5.2 运行针对修改文件的静态检查或语法校验
- [ ] 5.3 手动验证 Pose View 下无聚焦、聚焦单组、切换过滤三类场景
