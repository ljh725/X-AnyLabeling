# 行为分析语义接入覆盖矩阵

机器事实来源：`anylabeling/services/behavior_analytics/action_catalog.py` 的 `ACTION_CATALOG`，当前动作目录版本：`1.0`。本表中的语义动作名称由自动化漂移测试校验。

| 用户动作 | 主要入口 | 语义动作 | 终态 | 必需上下文 |
|---|---|---|---|---|
| 整体移动 | Canvas drag | `geometry_adjust` | success/cancelled/no_change | shape_type, edit_target=body |
| 矩形边调整 | Canvas edge drag | `rectangle_adjust` | success/cancelled/no_change | edge, size bucket |
| 矩形角调整 | Canvas corner drag | `rectangle_adjust` | success/cancelled/no_change | corner, size bucket |
| 关键点移动 | Canvas vertex drag | `keypoint_adjust` | success/cancelled/no_change | point bucket |
| 键盘连续微调 | Labeling keyboard handler | `keyboard_nudge` | success/no_change | input source, net change |
| 滚轮缩放 | Canvas wheel | `zoom` burst | success/interrupted | input count |
| 视图平移 | Canvas pan | `pan` burst | success/interrupted | input count |
| 标签修改 | Label editor commit | `label_edit` | success/cancelled/no_change | safe label key |
| 属性修改 | Attribute editor commit | `attribute_edit` | success/cancelled/no_change | attribute category |
| 新建/导入/AI | Shape creation adapters | `shape_created` | success/failed | initial source |
| 删除/撤销恢复 | Delete/undo handlers | `shape_deleted` / `shape_restored` | success/failed | object identity |
| 保存 | Save entry | `labels_saved` | success/failed | changed/saved facts |

每一行都必须能够映射到唯一的动作关联 ID，并且在固定回放中验证一次用户操作只产生一个最终可计数动作。


