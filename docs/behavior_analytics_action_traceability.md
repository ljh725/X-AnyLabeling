# 行为分析动作接入追踪清单

- 动作目录版本：`1.0`
- 机器事实来源：`anylabeling/services/behavior_analytics/action_catalog.py`
- 目录契约测试：`tests/test_behavior_analytics_action_contract.py`
- 本清单的 `missing` / `partial` 行是当前实现审计结果，不把目录登记误认为已接入。

| 目录行 | 语义动作 | 实际入口/接入点 | 测试 | 状态 | 审计备注 |
|---|---|---|---|---|---|
| geometry-body-drag | geometry_adjust | `LabelingWidget._behavior_begin_edit` / `finish_edit` | `test_behavior_analytics_label_widget.py` | covered | 整体编辑已接入 |
| rectangle-edge-drag | rectangle_adjust | `LabelingWidget._behavior_begin_geometry` | `test_behavior_analytics_label_widget.py` | covered | 边调整共享 geometry span |
| rectangle-corner-drag | rectangle_adjust | `LabelingWidget._behavior_begin_geometry` | `test_behavior_analytics_label_widget.py` | partial | 角入口需由 Canvas 统一提交 |
| keypoint-drag | keypoint_adjust | Canvas vertex release | `test_behavior_analytics_action_contract.py` | missing | 目录已登记，尚无实际语义入口 |
| keyboard-nudge | keyboard_nudge | Labeling keyboard handler | `test_behavior_analytics_action_contract.py` | missing | 仍只有底层键盘路径 |
| wheel-zoom | zoom | Canvas wheel/burst | `test_behavior_analytics_burst_retention.py` | missing | 有 burst 基础，未发语义 action |
| view-pan | pan | Canvas pan/burst | `test_behavior_analytics_burst_retention.py` | missing | 有视图状态，未发语义 action |
| label-edit | label_edit | Label editor commit | `test_behavior_analytics_action_contract.py` | missing | 编辑控件入口尚未接 telemetry |
| attribute-edit | attribute_edit | `BehaviorTelemetry.attribute_changed` | `test_behavior_analytics_telemetry.py` | covered | 属性语义事件已存在 |
| creation-intent | creation_intent | `BehaviorTelemetry.begin_creation` | `test_behavior_analytics_workflow_timeline.py` | covered | 创建前 token 与 intent 独立记录 |
| creation-draw | create_draw | `BehaviorTelemetry.begin_create_draw` / `finish_create_draw` | `test_behavior_analytics_workflow_timeline.py` | covered | 绘制阶段按 token 归属 |
| creation-label | create_label | `BehaviorTelemetry.begin_create_label` / `finish_create_label` | `test_behavior_analytics_workflow_timeline.py` | covered | 仅真实标签对话框产生阶段 |
| rectangle-wheel-scale | rectangle_adjust | `Canvas.wheelEvent` body branch | `test_behavior_analytics_workflow_timeline.py` | covered | 目标固定为 `scale` |
| rectangle-wheel-edge | rectangle_adjust | `Canvas.wheelEvent` edge branch | `test_behavior_analytics_workflow_timeline.py` | covered | 目标固定为 left/right/top/bottom |
| shape-create | shape_created | Shape creation adapters | `test_behavior_analytics_label_widget.py` | partial | 手动/导入/AI 来源仍需拆分 |
| shape-delete | shape_deleted | `LabelingWidget._behavior_action` | `test_behavior_analytics_label_widget.py` | covered | 删除动作已有入口 |
| shape-restore | shape_restored | Undo/redo handler | `test_behavior_analytics_action_contract.py` | missing | 只有删除兼容事件 |
| labels-save | labels_saved | `LabelingWidget._behavior_action` | `test_behavior_analytics_label_widget.py` | covered | 成功/失败入口已有 |
| manual-shape-create | shape_created | Manual shape tool commit | `test_behavior_analytics_action_contract.py` | partial | 需补 source=manual 事实 |
| import-shape-create | shape_created | Annotation import | `test_behavior_analytics_action_contract.py` | missing | 尚无独立语义入口 |
| ai-shape-create | shape_created | Auto-labeling create | `test_behavior_analytics_action_contract.py` | missing | 尚无 AI 来源动作闭合 |
| ai-shape-correct | ai_correct | Auto-labeling correction | `test_behavior_analytics_action_contract.py` | missing | 尚无人工修正关联 |
| inspector-review | inspector_review | Inspector issue review | `test_behavior_analytics_action_contract.py` | missing | Inspector 尚未接行为语义动作 |
| quality-review | quality_review | Quality review queue | `test_behavior_analytics_action_contract.py` | missing | 质检复核尚未接行为语义动作 |
| image-navigation | image_navigate | Image list navigation | `test_behavior_analytics_action_contract.py` | missing | 需补 image visit/action 关联 |
| undo-action | undo | Undo handler | `test_behavior_analytics_action_contract.py` | missing | 需引用原 action_id |
| redo-action | redo | Redo handler | `test_behavior_analytics_action_contract.py` | missing | 需引用被恢复 action_id |
| abnormal-exit | session_interrupted | Application close/crash boundary | `test_behavior_analytics_action_contract.py` | missing | 需统一中断原因和幂等闭合 |

## 旧低粒度与重复计数审计

当前 `LabelingWidget` 仍存在 `shape_edited` 兼容路径。它只能保留为旧 schema 的读取事实，不能作为 v3 精确耗时动作；后续任务 3.5 将增加隔离规则和重复率测试。`ActionSpan` 的 begin/terminal 路径是新版精确计数的唯一候选入口。
