## Context

参见 `proposal.md` 的动机。本设计建立在以下现状与约束上：

- 画布坐标模型为 `image_delta = screen_delta / canvas.scale`。现有 `zoom` 精修模式使用 `min(canvas.scale, max_factor)` 作为额外除数，导致低于 100% 时不降速、高缩放时反而继续降速，与低倍视图最难精修的实际问题相反。
- `Canvas` 已有选中矩形单边命中、拖动、几何约束、滚轮矩形编辑、方向键整框移动、precision virtual cursor 和 undo 通知路径，应复用而不是创建第二套 shape 编辑器。
- `canvas.py` 与 `label_widget.py` 是高成本文件。新算法和状态必须尽量放在小型纯 Python helper 中，Canvas/LabelWidget 只承担 Qt 事件适配、绘制和信号转发。
- 历史 `manual-person-annotation-refinement` change 描述了 fixed/zoom 精修、Tab 选边和局部边缘吸附，但主规格尚未归档相关 capability，且历史任务勾选状态不能替代当前代码验证。本变更的 6 份 spec 是新的行为来源。
- 指标采集必须与正式标注严格隔离：不能改变 shape、dirty、undo、自动保存或 JSON；即使采集失败，审核仍必须继续。

## Goals / Non-Goals

**Goals:**

- 用纯函数定义并测试缩放无关的目标精修增益。
- 让鼠标、滚轮和键盘共享一个活动边状态和同一几何验证入口。
- 将持久审核会话、瞬态边交互和统计 episode 分为三套明确生命周期。
- 在实现 P0 前获得 baseline 指标，并让每个阶段自动带上可比较的 feature-stage 标记。
- 通过 feature flags 分阶段落地，任何阶段都能独立关闭或回滚。

**Non-Goals:**

- 不改变矩形或其他 shape 的 JSON 表示。
- 不改变 auto-labeling 结果落地流程。
- 不统计鼠标绝对位置、图像内容、标签文本、group_id 或矩形坐标。
- 不引入联网遥测、外部分析服务或新的运行时依赖。
- 不在 P2 中实现实时自动吸附、自动接受候选或语义边界模型。
- 不借本变更重构 Canvas 的全部事件系统。

## Decisions

### Decision 1: 六个组件作为一个变更，五个用户阶段顺序交付

用户功能严格按以下阶段推进，每阶段都以前序阶段自动化测试和人工指标门禁通过为开始条件：

| 阶段 | 优先级 | capability | 主要结果 |
| --- | --- | --- | --- |
| 1 | P0-1 | `review-edge-precision-gain` | 低倍视图稳定的默认边精修增益 |
| 2 | P0-2 | `review-edge-discrete-nudging` | 活动边 1px/5px 滚轮与键盘收尾 |
| 3 | P1-1 | `review-edge-adjustment-feedback` | 原边、位移、坐标、尺寸和结果反馈 |
| 4 | P1-2 | `review-refinement-session-continuity` | 跨矩形/切图的低疲劳连续审核 |
| 5 | P2 | `review-edge-assistance` | 可选局部放大和确认式候选 |

`review-refinement-telemetry` 是横切前置组件，不增加第六个用户阶段：先实现 collector/writer 和 baseline 采集，然后在阶段 1–5 逐步接入新增事件。

**Alternatives considered:** 六个独立 OpenSpec changes。放弃原因是活动边、配置迁移、undo 和指标阶段标记存在强依赖，拆分会产生重复状态和难以比较的验收口径。

### Decision 2: 精修参数使用目标增益而不是降速倍率

纯逻辑函数接收 `canvas_scale` 与 `target_gain`：

```text
normal_gain = 1 / max(canvas_scale, epsilon)
effective_gain = min(normal_gain, target_gain)
effective_image_delta = screen_delta * effective_gain
```

默认 `target_gain = 0.5`。等价的额外除数为：

```text
precision_factor = max(1, 1 / (canvas_scale * target_gain))
```

这一定义在 50% 和 100% 下把 5–8px 鼠标位移映射为 2.5–4px 图像位移；在 200% 以上不对已经较精细的自然增益做反向加速。

边拖动默认走目标增益；整框和其他 shape 保持原路径。Shift 粗调在拖动中按事件实时判断，修饰键状态切换时重置 raw/virtual 基准，但保留已应用坐标，避免跳变。Ctrl 兼容入口只在新审核会话关闭时继续代表旧临时精修；会话开启后 Ctrl 不改变默认边精修语义。

**Alternatives considered:** 固定除以 2/4，无法在不同 zoom 下保持一致手感；基于鼠标速度的动态加速度，虽然可自动粗细切换，但不可预测且不利于形成肌肉记忆。

### Decision 3: 一个活动边状态服务所有输入设备

扩展现有 rectangle-edge interaction state，而不是为滚轮、键盘再建独立选边状态。状态分为：

```text
idle → hover → active → dragging → active
                  └→ nudge-burst → active
任意状态 -- target/image/session change --> idle
```

- hover 仅提供候选视觉反馈，不能让滚轮隐式修改矩形。
- click 或键盘循环把候选提升为正式 active。
- mouse drag、wheel nudge、arrow nudge 和 P2 candidate 都读取同一 active edge。
- 点击另一边是显式接管；角点仍保留原生顶点优先级。
- 活动边在几何更新后从当前 rectangle geometry 刷新，禁止持有失效坐标副本。

Canvas 只把 Qt 输入转换为领域命令；边坐标候选由共享纯逻辑 helper 验证，验证成功后才进入现有 shape mutation/notify/store 流程。

### Decision 4: 滚轮微调不再使用“框内缩放、框外最近边”隐式语义

新审核会话开启且存在正式 active edge 时：

- 一个标准 wheel step 对应 1px，Shift 对应 5px。
- pixelDelta/angleDelta 先进入 accumulator；达到一个标准刻度才产生一次领域命令。
- 无 active edge 时不消费事件，交还原有画布滚动/缩放逻辑。
- 键盘只接受与边轴向匹配的方向；正负方向映射由边坐标轴决定。

连续微调用 `target_id + edge_name + direction + input_source` 作为 burst key，500ms 内相同 key 合并 undo；key 或方向变化立即结束旧 burst。该规则同时便于准确统计反向修正和撤销归因。

**Alternatives considered:** 根据鼠标在矩形内外决定 wheel 行为。放弃原因是用户无法从视觉状态预测“缩放整框”还是“调整某边”，且容易产生不可逆误操作感。

### Decision 5: 反馈由不可变快照驱动

拖动或 nudge burst 开始时创建只读 feedback snapshot：目标边名、原边坐标、原矩形 bbox 和开始时间。当前几何每次变化后通过 snapshot 计算累计 delta 与 W×H；Canvas renderer 只消费 view model：

```text
edge_name, original_coord, current_coord, signed_delta,
current_width, current_height, phase, rejection_reason
```

原边以固定屏幕像素虚线绘制；活动边、提示背景和文字均使用保存/恢复 painter state。Overlay 不进入 shape/undo/dirty。LabelWidget status bar 复用同一 view model，避免画布和状态栏显示不同数值。

### Decision 6: 会话、边交互、统计 episode 三层状态分离

三层生命周期如下：

1. `RefinementSession`：用户显式启用，可按配置跨矩形和切图保持。
2. `EdgeInteraction`：绑定当前 image token + shape identity，目标变化立即清除。
3. `ReviewEpisode`：当一个 rectangle 成为 sole selection 时开始，到目标/图片/会话变化或关闭时结束。

切图时的顺序固定为：结束旧 episode → 取消/提交输入批次 → 清除 edge state → 装载新图 → 如 sole-selection 建立则开始新 episode。窗口失焦先回滚未提交 drag，再暂停 episode focused timer。这样不会把旧图活动边或虚拟光标带到新对象，同时会话开关无需重复操作。

### Decision 7: P2 采用观察层 loupe 与两步式候选

局部放大镜读取当前 pixmap 和活动边附近 ROI，在 painter overlay 中显示，不改变 Canvas scale、transform_pos 或 hit-test。位置策略优先放在鼠标和活动边的对侧；空间不足时隐藏而不是遮挡目标。

一次性候选复用现有局部梯度计算能力，但改成两步事务：

```text
request → validate → preview(candidate, score, delta)
                      ├→ accept → one geometry commit + undo
                      └→ reject/cancel → no mutation
```

候选不得在拖动或 hover 中自动刷新。P2 两个子功能独立 flag，默认关闭。

### Decision 8: 指标核心保持纯 Python，Qt 只发送领域事件

新增纯 Python telemetry 模块，包含可注入 monotonic/wall clock 的 collector、episode model、reversal detector、zoom burst counter、JSONL writer 和 reader/aggregator。模块不得 import PyQt。

建议事件接口：

```text
target_selected(target_token, feature_stage)
target_cleared(end_reason)
focus_changed(is_active)
review_input(timestamp)
zoom_applied(normalized_steps)
edge_drag_started(edge_token)
edge_drag_sample(accepted_axis_delta)
edge_drag_finished(committed)
undo_applied(changed_target_token)
```

LabelWidget 负责 sole-selection、切图、zoom applied、undo result 和 app lifecycle；Canvas 负责已接受的 edge drag/nudge 事件。只统计“已应用”的动作，不从原始 Qt 事件推测结果。

### Decision 9: 指标时间、缩放、反向修正和撤销使用稳定算法

时间字段：

- `wall_elapsed_ms`：episode 结束 wall time 减开始 wall time，便于审计。
- `focused_elapsed_ms`：monotonic 区间中排除窗口失焦时间。
- `active_elapsed_ms`：focused 区间内，相邻有效审核输入的间隔最多计入 `idle_timeout_ms`，默认 30 秒。

缩放：相邻有效 zoom applied 事件间隔不超过 300ms 时归为一个 action；每个规范化 step 仍累加 `zoom_step_count`。

反向修正：每次 edge drag 独立维护轴向 sign。绝对 delta 小于 0.5px 不进入累计；确认一个方向后，反方向累计达到 1.0px 时计一次 reversal，将确认方向切换并清空反向累计。只有几何层接受的实际 delta 参与计数。

撤销：LabelWidget 在 undo 前后比较目标 token 的 geometry fingerprint；仅 fingerprint 改变时把一次 undo 归因给当前 episode。fingerprint 只在内存中计算，绝不写入日志。

### Decision 10: JSONL 记录最小化且版本化

每个完成 episode 追加一行 JSON：

```text
schema_version, app_version,
session_id, episode_id, target_token,
feature_stage, feature_flags,
started_at_utc, ended_at_utc, end_reason,
wall_elapsed_ms, focused_elapsed_ms, active_elapsed_ms,
edited, zoom_action_count, zoom_step_count,
drag_reversal_count, undo_count
```

`target_token` 是会话内随机/递增的不透明值，不从路径、label、group_id 或坐标派生。默认目录由上层解析后注入 writer；测试使用临时目录。单进程 append 后 flush，写入失败后 collector 继续内存计数、UI 只警告一次，不能抛异常进入输入事件循环。

提供纯 Python 汇总脚本，将 JSONL 转为逐 episode CSV 和按 `feature_stage` 聚合的 count/median/p75/mean；损坏行被计数并跳过。

### Decision 11: 配置采用新命名并支持阶段 flags

建议配置结构：

```yaml
rectangle_review_refinement:
  enabled: false
  target_gain: 0.5
  edge_drag_precision_default: true
  nudge_step_px: 1
  coarse_step_px: 5
  feedback_enabled: true
  persist_across_images: true
  assistance:
    loupe_enabled: false
    candidate_enabled: false
  telemetry:
    enabled: false
    idle_timeout_ms: 30000
    zoom_burst_ms: 300
    reversal_deadband_px: 0.5
    reversal_confirm_px: 1.0
```

内部 rollout flags 允许只开启到某一阶段，并形成 `feature_stage`：`baseline`、`p0_gain`、`p0_nudge`、`p1_feedback`、`p1_continuity`、`p2_assistance`。

旧配置迁移优先级：新 key > 旧 fixed/zoom key > 默认值。旧 fixed factor 映射为 `target_gain = 1/factor`；旧 zoom max factor 映射为 `target_gain = 1/max_factor`，默认 2.0 因而得到 0.5。运行时兼容读取，不自动覆盖用户文件；用户保存设置时写新结构并保留一次迁移提示。

### Decision 12: 分阶段验收以相对改善和质量不回退为门禁

先在新功能关闭、telemetry 开启时采集 baseline，再使用相同任务样本采集阶段数据。每阶段至少报告：有效 episode 数、四个核心指标的 median/p75、被丢弃/损坏记录数和标注质量抽检结果。

初始工程目标（不是 spec 硬承诺）为：

- P0-1 后缩放 action median 降低至少 40%，最终框质量不下降。
- P0-2 后 drag reversal 与 undo median 合计降低至少 25%。
- P1 阶段后 active time median 再降低至少 15%，且误操作反馈工单不增加。
- P2 只有在启用样本中证明 active time 或质量改善且候选拒绝率可接受时，才考虑扩大默认范围。

## Risks / Trade-offs

- **[Risk] 默认边精修让大幅修边感觉过慢** → Shift 粗调恢复普通增益；整框拖动不降速；阶段 1 指标验证反向修正和耗时。
- **[Risk] Shift 与既有选择/约束快捷键冲突** → 仅在 active edge drag/nudge 状态消费 Shift，其他上下文保持旧行为，并增加 shortcut 冲突测试。
- **[Risk] 高分辨率滚轮产生重复或丢步** → 使用可测试 accumulator，分别覆盖 angleDelta 和 pixelDelta，只有规范化 step 才修改几何。
- **[Risk] 三层状态清理顺序遗漏导致跨图污染** → 将切图、删除、失焦、模式切换统一路由到一个 teardown 协议并做状态机测试。
- **[Risk] telemetry hook 增加高频 mouse-move 开销** → 只传递已接受的轴向 float delta，纯内存 O(1) 计数；不在 mouse move 写盘，episode 结束才 append。
- **[Risk] 指标启用影响用户信任** → 默认关闭、明确本地保存、最小字段、无路径/标签/坐标、提供清除和导出入口。
- **[Risk] episode 选择边界与实际审核任务不一致** → 同时记录 wall/focused/active 三种时间，并保留 end_reason；试点后可调整 idle timeout，而不改变四个核心指标定义。
- **[Risk] P2 强边缘与标注语义冲突** → 仅预览、人工确认、独立 undo、默认关闭，禁止实时吸附。

## Migration Plan

1. 合入纯 Python telemetry 和 gain helper，但所有新功能默认关闭；只对自愿试点用户开启 telemetry，采集 baseline。
2. 阶段 1 开启新 target gain 与边默认精修；保留旧 precision 配置读取和 Ctrl 兼容入口。
3. 阶段 2 替换审核会话内的隐式 wheel rectangle editing；会话外保持旧行为，完成指标门禁后再决定是否废弃旧入口。
4. 阶段 3、4 依次启用反馈和连续会话；每阶段可通过 flag 独立回滚，不回滚已保存标注。
5. 阶段 5 仅对试点显式开启，候选默认预览不应用。
6. 稳定一个版本后停止写旧 precision keys；再经过一个版本移除旧 key 的设置 UI，但继续兼容读取。

回滚时关闭对应 feature flag 即可恢复旧交互；新格式指标文件可保留或由用户清除，不影响应用和标注数据。由于没有 JSON schema 变化，无需数据迁移或标注回滚。
