## 1. 现状基线与分阶段开关

- [ ] 1.1 为当前 precision factor、virtual cursor、矩形边拖动、wheel rectangle editing、方向键和 undo 行为补充或确认回归测试，记录历史 change 勾选项与当前代码的差异
- [x] 1.2 在 `xanylabeling_config.yaml` 中新增 `rectangle_review_refinement` 配置树和 baseline/P0/P1/P2 rollout flags，所有新用户功能与 telemetry 默认关闭
- [x] 1.3 在 settings schema/runtime applier 中增加新配置的类型、范围和依赖校验，并为无效 target gain、步长和时间阈值提供安全默认值
- [x] 1.4 建立旧 fixed/zoom precision 配置迁移 fixture，验证新 key 优先、旧 key 只读兼容和用户保存时写入新结构

## 2. 横切组件：单框精修指标基础

- [x] 2.1 新增不依赖 PyQt 的 episode 数据模型、end-reason/feature-stage 枚举和可注入 monotonic/wall clock 接口
- [x] 2.2 实现 sole-rectangle episode 生命周期及 wall/focused/active 三类耗时计算，覆盖切换目标、切图、失焦、空闲阈值、会话结束和应用关闭
- [x] 2.3 实现 300ms zoom burst counter，同时记录 `zoom_action_count` 和规范化 `zoom_step_count`
- [x] 2.4 实现轴向 drag reversal detector，使用 0.5px deadband、1.0px direction confirmation，并在每次新拖动重置
- [x] 2.5 实现当前目标 geometry fingerprint 的内存比较协议，使 undo 仅在实际改变当前矩形时计数
- [x] 2.6 实现 schema-versioned JSONL writer，使用不透明 session/episode/target token，默认排除路径、label、group_id 和坐标
- [x] 2.7 实现 fail-open 写入策略：写盘/序列化失败不抛入 UI 事件循环，只产生一次非阻塞告警
- [x] 2.8 实现 JSONL reader/aggregator 和 `scripts/export_rectangle_review_metrics.py`，输出逐 episode CSV、按 feature stage 的 count/median/p75/mean 以及损坏行数量
- [x] 2.9 为 collector、计时、zoom burst、reversal、undo 归因、隐私字段、损坏行和不可写目录添加纯 Python 单元测试
- [x] 2.10 在 LabelWidget 的 sole-selection、切图、zoom applied、undo result、窗口激活和关闭生命周期接入 telemetry 领域事件
- [x] 2.11 在 Canvas 矩形边拖动路径只上报几何层已接受的轴向 delta、drag start 和 committed/canceled end，不在 mouse-move 写盘
- [x] 2.12 添加 PyQt 集成测试，验证 telemetry 关闭时零文件写入，开启时 episode 正确结束，采集故障不影响保存、undo、dirty 或切图
- [ ] 2.13 在五阶段功能全部关闭时执行试点 baseline 采集并导出首份阶段对比表，确认字段口径和匿名化结果符合规格

## 3. 阶段 1（P0-1）：缩放无关的矩形边精修增益

- [x] 3.1 新增纯 Python gain helper，实现 `effective_gain = min(1 / canvas_scale, target_gain)`、默认 target gain 0.5 和非法 scale 防护
- [x] 3.2 将 Canvas 精修 virtual cursor 改为消费 gain helper 的有效 delta，并保证普通拖动与 feature flag 关闭路径保持现状
- [x] 3.3 仅对单个已选矩形的正式边拖动默认应用精修增益，验证整框、顶点、其他 shape 和绘制路径不受影响
- [x] 3.4 实现 Shift 临时粗调以及拖动中按下/松开 Shift 时的 raw/virtual 基准重置，确保坐标不跳变
- [x] 3.5 保留会话关闭时的 Ctrl 旧临时精修入口，并添加 Ctrl/Shift/无修饰键组合的互斥测试
- [x] 3.6 实现旧 fixed factor 与 zoom max factor 到 target gain 的运行时迁移和一次性用户提示
- [x] 3.7 添加 50%、100%、200%、400% zoom 的 gain 单测与 Canvas 拖动测试，覆盖 5–8 屏幕像素映射、高倍不加速和连续事件无漂移
- [x] 3.8 将 telemetry feature stage 标记为 `p0_gain`，确认 edge drag 只贡献已接受位移和 reversal 事件
- [ ] 3.9 完成阶段 1 人工 A/B：相同样本比较单框耗时、缩放、反向修正、撤销和最终框质量，未通过门禁时保持 flag 关闭

## 4. 阶段 2（P0-2）：活动边 1px/5px 离散微调

- [x] 4.1 扩展 rectangle-edge interaction controller，使 hover 与正式 active 分离，并让 click/键盘循环建立唯一 active edge
- [x] 4.2 实现鼠标点击边、Tab/反向 Tab 循环边和角点优先级，确保活动边在几何变化后从当前 rectangle 刷新
- [x] 4.3 新增纯 Python wheel accumulator，分别规范化 angleDelta/pixelDelta，只有完整刻度才产生 nudge command
- [x] 4.4 新增共享 nudge helper，在修改前验证图像边界、最小宽高和反翻转，拒绝需要隐式 clamp 的候选
- [x] 4.5 在审核会话内将 active-edge wheel 映射为 1px、Shift+wheel 映射为 5px；无 active edge 时将事件交还原画布逻辑
- [x] 4.6 将 active-edge 方向键映射为轴向 1px、Shift+方向键映射为 5px，并忽略非轴向按键而不移动整框
- [x] 4.7 以 target/edge/direction/source/500ms 作为 nudge burst key 实现 undo 合并，方向或目标变化时结束旧批次
- [ ] 4.8 添加标准滚轮、高分辨率滚轮、键盘、方向映射、几何拒绝、无活动边、跨目标和 undo 合并测试
- [ ] 4.9 将 telemetry feature stage 标记为 `p0_nudge`，验证滚轮微调不误计为主画布 zoom，undo 只归因当前矩形
- [ ] 4.10 完成阶段 2 人工 A/B：统计无需放大的 1–5px 收尾比例及四项核心指标，未通过门禁时保留 P0-1 并关闭 nudge flag

## 5. 阶段 3（P1-1）：矩形边调整反馈

- [x] 5.1 新增不可变 feedback snapshot/view model，统一计算原坐标、当前坐标、有符号累计 delta、当前 W×H、phase 和 rejection reason
- [x] 5.2 在 drag 与 nudge burst 开始/更新/提交/取消时维护同一 feedback model，目标变化时可靠清除
- [x] 5.3 在 Canvas 绘制固定屏幕像素的 hover/active/drag 状态、原边虚线和数值 HUD，并完整保存/恢复 painter state
- [ ] 5.4 实现 HUD 避让策略，优先放到鼠标和活动边对侧，空间不足时降级到状态栏而不遮挡目标
- [x] 5.5 让状态栏消费同一 view model，显示提交、Esc 回滚、窗口中断和边界/最小尺寸/反翻转拒绝原因
- [ ] 5.6 添加不同 zoom、不同边、连续 nudge、取消、拒绝、切图清理和 overlay 不影响 JSON/dirty/undo 的测试
- [ ] 5.7 将 telemetry feature stage 标记为 `p1_feedback`，确认反馈绘制与局部 HUD 更新不产生 zoom、reversal 或 undo 计数
- [ ] 5.8 完成阶段 3 人工 A/B：检查误选边、反向修正、撤销和 active time 是否改善，未通过门禁时可独立关闭 feedback flag

## 6. 阶段 4（P1-2）：连续审核精修会话

- [x] 6.1 新增 refinement session controller，将持久 session enabled 与瞬态 edge interaction/feedback/nudge burst 分离
- [x] 6.2 将 selection change、image change、shape deletion、mode change、focus loss 和 app close 统一路由到 teardown 协议
- [x] 6.3 按“结束 episode→回滚未提交拖动/结束批次→清 edge state→切图→建立新 episode”的顺序接入 LabelWidget 生命周期
- [x] 6.4 实现 `persist_across_images`：会话可跨图保持，但活动边、virtual cursor、feedback 和 wheel accumulator 不跨目标/图片
- [x] 6.5 实现鼠标 click、键盘循环、方向键和滚轮围绕同一 active edge 的无歧义设备交接
- [ ] 6.6 增加审核精修主开关、当前会话状态和安全退出提示；用户退出时只清瞬态状态，不撤销已提交标注
- [x] 6.7 添加 session state machine 测试，覆盖连续矩形、跨图、失焦回滚、删除目标、退出会话和旧模式兼容
- [ ] 6.8 将 telemetry feature stage 标记为 `p1_continuity`，验证 episode end reason、focused pause 和跨图目标 token 隔离
- [ ] 6.9 完成阶段 4 连续批量审核试点，比较重复开关/修饰键使用、四项核心指标和主观疲劳评分，未通过门禁时关闭 persistence

## 7. 阶段 5（P2）：可选局部观察与确认式边缘候选

- [x] 7.1 实现只读 loupe view model，从活动边附近采样 ROI，且不修改 Canvas scale、transform、hit-test、gain 或 geometry
- [x] 7.2 绘制固定屏幕尺寸的局部放大 overlay，并实现对侧放置、边界内约束和遮挡时隐藏策略
- [x] 7.3 将现有局部边缘评分封装为显式 request-only candidate service，禁止 hover、drag 和切图自动触发
- [x] 7.4 实现 candidate preview 状态，显示位置、偏移和可靠性，但在用户接受前不修改 shape/dirty/undo
- [x] 7.5 实现 accept/reject/cancel 两步事务：accept 先验证几何并产生一个 undo 单元，reject/cancel 保持原位
- [x] 7.6 为 loupe 和 candidate 分别增加默认关闭的配置与设置项，并确保功能关闭时不执行 ROI/梯度计算
- [ ] 7.7 添加局部观察坐标不变、overlay 避让、候选显式触发、低可靠性、约束拒绝、接受撤销和取消零副作用测试
- [ ] 7.8 将 telemetry feature stage 标记为 `p2_assistance`，确认 loupe 不计主画布 zoom，并在阶段报告中增加候选请求/接受/拒绝的非核心诊断字段
- [ ] 7.9 完成阶段 5 受控试点；只有 active time 或质量改善且候选拒绝率可接受时才考虑扩大启用范围

## 8. 跨阶段质量门禁与交付

- [x] 8.1 为新增设置、状态栏、HUD、告警和迁移提示补充翻译源字符串，更新 `.ts` 并运行 `scripts/compile_languages.py`
- [x] 8.2 使用 Black 79 列格式化受影响 Python 文件，运行 flake8，并确认所有新增函数/类具有类型提示和 Google-style docstring
- [x] 8.3 分别运行 telemetry/gain/nudge/feedback/session/assistance 的纯 Python 测试和最窄 PyQt offscreen 交互测试
- [x] 8.4 运行现有矩形边、precision、wheel、size overlay、viewport、undo 和设置迁移回归测试，确认 feature flags 关闭时旧行为不回退
- [x] 8.5 执行跨模块 release gate（完整 pytest 与 pre-commit），记录因环境限制跳过或需审批的项目
- [ ] 8.6 为五阶段分别归档 baseline/阶段指标报告、样本规模、median/p75、质量抽检和是否通过门禁的结论
- [x] 8.7 更新用户文档，说明默认精修、Shift 粗调、活动边滚轮/键盘微调、会话保持、P2 确认流程、指标启用/导出/清除和本地隐私边界
- [ ] 8.8 对照 6 份 capability specs 逐项验收，确认不改变标注 JSON、auto-labeling、dirty/undo 语义且 telemetry 失败不阻塞审核
