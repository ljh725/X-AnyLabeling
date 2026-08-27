# 行为分析遥测噪声审计报告（2026-08-25）

- **数据来源**：
  - 导出 bundle：`logs/log-20260825-001/`（18 个文件，v2.0，导出于 2026-08-25 08:37 本地时间）
  - 本机记录库：`~/.xanylabeling/behavior_analytics/`（403,200 行 / 约 275 MB）
- **分析对象 session**：`project-session-75daaf8726a0b995fb05f4af4b3611c0`（65,431 个 v3 事件，2026-08-24 16:00 至 2026-08-25 08:37 本地时间）
- **核心结论**：本机记录条目需要更新。40.3 万条记录中约 **96% 无分析价值**（31.5% 为 v3 事件风暴噪声，64.4% 为废弃的 v1/v2 遗留 schema），另有 4 类字段级缺失/失真导致质量门失败。

---

## 1. 总体量化

| 类别 | 条目数 | 占比 | 判定 |
|------|--------|------|------|
| v3 `action_span:attribute_edit` 风暴 | 127,311 | 31.5% | 纯噪声（跨全部会话仅 3 条带 shape_id，**99.998% 无效**） |
| v1/v2 遗留 schema | 259,594 | 64.4% | 已废弃（`shape_edited` 130,071 + 旧 `action_span` 99,175 + 其余 3 万余），仅 legacy 诊断可用 |
| v3 有效事件（几何/选择/翻页/保存等） | 约 16,300 | 约 4% | 信号质量好，应保留 |

本机库按 schema 版本分布：v1 = 152,175 行，v2 = 107,419 行，v3 = 143,606 行。v3 条目中约 88.5% 是 attribute_edit 风暴。

## 2. 发现一：`attribute_edit` 事件风暴（最严重）

### 2.1 现象（本次 session 数据）

- 55,590 条 `attribute_edit`（占全部 60,961 个动作的 91%），其中 **55,587 条无 shape_id**，`attribute_category` 全部为 `visibility`；
- 事件间隔 **94.4% ≤ 1ms**（最密 1 秒 264 条，非人类操作节奏）；
- 按 200ms 间隔聚类为 **1,800 个爆发**：中位每爆 27 条、持续 15ms；其中 **1,693 个紧跟 `image_navigate`**，其余紧跟 `pan`/`zoom`（即图片加载/重绘触发）；
- 一张仅 13 个对象的图片被记为 396 次"编辑"（`image_metrics.edited_count` 被污染）；
- 单张图片最多风暴 264+ 条（`image-2f4364982e69cdffbbf508bc6ff69790`，object_count=13）。

### 2.2 受污染的统计表

`action_counts`、`transitions`（`attribute_edit→attribute_edit` 53,633 次）、`common_sequences`、`repetition_diagnostics`（same_action_loop 89.4%）、`rework_metrics.no_change` 分母、`image_metrics.edited_count`。**凡是动作占比类指标在该 bug 修复前均不可信。**

### 2.3 根因定位（代码）

| 位置 | 问题 |
|------|------|
| `anylabeling/views/labeling/label_widget.py:509` | `label_list.item_changed` 连接到 `label_item_changed` |
| `anylabeling/views/labeling/widgets/label_list_widget.py:154-155` | `item_changed` 直接暴露 `model().itemChanged` —— Qt 该信号**不区分用户点击复选框与程序化 `setItemCheckState`** |
| `anylabeling/views/labeling/label_widget.py:7359-7375` | `label_item_changed` 无条件发射 `_behavior_action("attribute_edit", visibility)`；且 `shape` 就在作用域内（7360 行）却未传 shape_id |

**机制**：加载图片 → label 列表重建 → 程序化 `setItemCheckState` 逐 shape 触发 `itemChanged` → 每次重建按 shape 数量成批发射"用户 visibility 编辑"。pan/zoom 后的可见性刷新同理。

### 2.4 修复方向

1. 列表重建/程序化刷新期间用 guard flag 或 `blockSignals` 屏蔽发射（可挡掉约 89% 的 v3 写入量）；
2. 仅在真实用户交互入口（鼠标点击复选框的事件路径）记录；
3. 发射时附带 `shape.shape_id`，否则对象级归属永远缺失。

## 3. 发现二：v1/v2 遗留 schema 堆积（64% 库体积）

259,594 行 v1/v2 条目已被 v3 取代，当前 session 的 `legacy_version_share = 0` 说明新数据不再产生，但旧数据仍占 263MB 库的主体。建议按 retention 策略压缩归档或清除，仅保留 legacy 诊断所需的最小样本。

## 4. 发现三：同一动作新旧命名并存（跨代双计风险）

| 旧路径条目（本机库） | 现行 v3 对应 | 风险 |
|----------------------|--------------|------|
| `action_span:rectangle_edge_drag`（128） | `action_span:rectangle_adjust`（247） | 同类动作双命名 |
| 顶层 `geometry_edit`（2,118） | `action_span:geometry_adjust`（3,617） | 顶层事件与 span 并存 |
| `shape_saved`（2,106） | `labels_saved`（5,303 + span 3,457） | 语义重复 |
| 顶层 `shape_edited`（130,071，v1/v2） | 已由 span 卷积替代 | 遗留 |

跨代合并分析时会双计或漏计，建议统一到 v3 命名并移除旧发射路径。

## 5. 发现四：字段缺失与失真（该记没记好）

| 问题 | 证据 | 后果 |
|------|------|------|
| `context_version` / `correlation_id` 恒 None | `context_coverage = 0/60,961` | 质量门恒 fail（`quality_gate: false`） |
| `attribute_edit` 不带 shape_id | 对象活跃时间 `unattributed_active_time = 100%` | 对象级归属完全失效 |
| zoom/pan 全部无 `object_episode_id`；1,640 次保存中 931 次无归属 | `action_spans` 归属统计 | 流程内时间分解只能事后推算（验证时仅 7.7s zoom/pan 落在 episode 窗口内） |
| 会话级 active = focused = wall = 16.45h | `time_metrics` | 隔夜挂机约 11 小时被记为"活跃聚焦"，时长指标失真 |
| `summary.json` 118MB（manifest 声明 `max_bundle_bytes: 5MB`） | 同一批事件以 `action_spans`/`semantic_actions`/`dimension_counts` 多份近似副本内嵌 | 导出体积膨胀，限制仅作用于 CSV 表 |

## 6. 有效信号清单（应保留，勿动）

以下条目结构完整、区分度好，本次行为分析的全部有效结论均来自它们：

- `action_span:geometry_adjust` / `rectangle_adjust`：带 `duration_ms`、`edit_target`（vertex/move/left/right/top/bottom）、`result`（success/no_change）——支撑"顶点拖拽占流程内 41% 耗时"等结论；
- `shape_selected`（含 object_episode 生命周期，924 个 episode 中 923 个正常闭合，闭合率 99.9%）；
- `image_visit_started` / `image_visit_ended`；
- `shape_created` / `shape_deleted` / `labels_saved` / `mode_changed`；
- `action_span:zoom` / `pan`（时长统计有效，仅缺 episode 归属）。

## 7. 修复优先级建议

| 优先级 | 事项 | 预期收益 |
|--------|------|----------|
| P0 | 堵 attribute_edit 风暴（guard + 用户交互入口 + shape_id） | 消除约 89% 的 v3 写入量，动作占比类指标恢复可信 |
| P1 | 清理/归档 v1/v2 遗留数据 | 释放约 64% 库体积 |
| P1 | 补 context 采集，使 `context_coverage` 过阈值 | 质量门可转绿 |
| P2 | zoom/pan/labels_saved 挂接当前 object_episode | 流程内时间分解无需推算 |
| P2 | 统一动作命名，删除旧发射路径 | 消除跨代双计 |
| P3 | 会话级 active/focused 接窗口聚焦信号与 wall 分离 | 时长指标去挂机污染 |
| P3 | 导出去掉 `summary.json` 冗余副本 | bundle 回到 MB 量级 |

## 8. 附：本次 session 真实行为基线（剔除风暴后，供修复后对比）

- 工作时段（本地）：08-24 16:00–18:00（高峰）、19:00–21:00、08-25 08:00–08:37（收尾）；隔夜为挂机；
- 过图：1,770 次访问 / 1,392 张图（约 1.27 次/图，线性单遍）；
- 编辑：843 次几何调整（59% no_change）+ 62 次矩形边缘调整；删除 483 / 创建 65（净 -418，清理型会话）；
- 保存：1,640 次（≈每次过图一存，瞬时无耗时）；
- 耗时结构：顶点拖拽 273s（41.1%）≈ 动作间空隙 270s（40.6%）> move 83s（12.4%）> 矩形边缘 39s（5.7%）；
- 返工：72 个对象 100% 回访重编，`saved_then_reedited` 79%。

> 建议在 P0 修复落地后重新导出一次 bundle，与本基线对照验证风暴消失、`edited_count` 恢复正常量级。
