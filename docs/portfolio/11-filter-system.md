# 11 · 筛选系统（保持 + 引擎 + 索引 + 导航）
#### Filter System: Persistence · Engine · Index · Navigation

> 一套 4 层的筛选子系统，解决 upstream 仅有两个裸 `QComboBox` 的痛点：**切图保留筛选态**、**JSON/属性筛选引擎**、**SQLite 索引缓存**（5000 图加速）、**筛选结果跨文件导航**。核心是 `filter_state_engine_pattern` 单字段驱动状态机，把 upstream 直连控件的耦合拆成 State/Engine/UI 三层。
>
> [← 返回作品集主页](../PORTFOLIO.md)

---

## 解决的痛点

upstream beta.4 的筛选能力只有两个直接连 handler 的 `QComboBox`（`GroupIDFilterComboBox` / `LabelFilterComboBox`）——`currentIndexChanged` 直接调 `parent.gid_selection_changed`。痛点：

```
痛点1：切一张图，筛选就丢了 —— 每张图要重新勾选 label/group_id
痛点2：想"只在含 head 标签的文件间跳转"？没有 —— upstream 没有"筛选结果导航"
痛点3：5000 图 / 18000 shape，每次筛选全量扫 JSON，卡到无法用
痛点4：筛选逻辑和 UI 控件耦合，无法单测，无法复用到 Inspector
```

---

## 方案：4 层子系统

| 层 | 文件 | 行数 | 职责 |
|----|------|------|------|
| **State** | `filter_state.py` | 86 | 归一化的筛选态（label 集合 / gid / shape_type），快照+恢复 |
| **Engine** | `filter_engine.py` | 137 | 计算匹配 + 同步可见性，**不碰 UI 控件** |
| **Index** | `dataset_filter_index.py` | 1015 | SQLite 派生索引缓存（可丢弃、可重建） |
| **Navigation** | `filter_navigation_engine.py` | 105 | 纯逻辑计算哪些文件/shape 满足快照，跨文件导航 |
| **Worker** | `dataset_filter_index_worker.py` | 83 | 后台索引构建线程 |

---

## 技术亮点

### 1. 筛选保持：切图不丢筛选态（核心诉求）

`filter_state.py` 用**快照/恢复**模式：`load_file()` 切图时，先 `_copy_filter_state()` 存进 `_pending_filter_restore`，重置，重载 shapes，再通过 setters 恢复并重新应用。这样 label/gid/shape_type 选择在图片间**存活**。

这正是 [docs/filter_state_engine_pattern.md](../filter_state_engine_pattern.md) 里「单字段驱动状态机」模式的落地：`FilterState` 是 State 层，`ShapeFilterEngine` 是 Engine 层，UI 只负责调 setters。

### 2. SQLite 派生索引：5000 图从卡死到秒级

JSON 仍是唯一真相源，SQLite 是**可丢弃、可重建**的派生缓存（`~/.cache/xanylabeling/dataset_index`，WAL 模式，schema v2）。动机来自一个具体工作负载：5000 图 / 18000 shape，全量扫 JSON 无法用。

- 增量更新、手动刷新、后台 worker 线程构建
- schema 版本化，升级自动重建
- 因为是派生缓存，损坏了直接重建，零数据风险

### 3. 纯逻辑 Engine，零 UI 耦合

`ShapeFilterEngine`（`compute_matches` / `sync_label_list_visibility`）和 `FilterNavigationEngine`（`collect_matched_files` / `file_matches_filter` / `shapes_match_filter`）都**不依赖 PyQt**，可无 Qt 单测。筛选语义：label 集合 OR within set，再与 gid、shape_type AND。

### 4. 模式可复用：Inspector / focus-solo 的模板

`docs/filter_state_engine_pattern.md` 明确把这个 State/Engine/UI 三层架构作为**可复用模板**，计划用于未来的「属性筛选 / 文件筛选 / Inspector 筛选 / focus-solo 可见性」——一次设计，多处复用。

---

## 代码定位

| 位置 | 说明 |
|------|------|
| [`filter_state.py`](../../anylabeling/views/labeling/filter_state.py) | 86 行，归一化筛选态 + `copy()`/`reset()`/`has_active_filter()` |
| [`filter_engine.py`](../../anylabeling/views/labeling/filter_engine.py) | 137 行，`ShapeFilterEngine.compute_matches`/`sync_label_list_visibility` |
| [`dataset_filter_index.py`](../../anylabeling/views/labeling/dataset_filter_index.py) | 1015 行，SQLite 索引 + schema 版本化 |
| [`filter_navigation_engine.py`](../../anylabeling/views/labeling/filter_navigation_engine.py) | 105 行，跨文件导航纯逻辑 |
| [`dataset_filter_index_worker.py`](../../anylabeling/views/labeling/dataset_filter_index_worker.py) | 83 行，后台索引 worker |

---

## 测试覆盖

| 文件 | 覆盖点 |
|------|--------|
| [`tests/test_filter_persistence.py`](../../tests/test_filter_persistence.py) | 切图保留筛选态、快照/恢复链 |
| [`tests/test_filter_navigation_engine.py`](../../tests/test_filter_navigation_engine.py) | 跨文件匹配、`file_matches_filter`/`shapes_match_filter` |

---

## 设计方法论沉淀

- 📄 [**filter_state_engine_pattern.md**](../filter_state_engine_pattern.md) — 单字段驱动状态机模式（State/Engine/UI 三层），本功能是该模式的第一个落地点
- 📄 [**dataset_filter_index_design.md**](../dataset_filter_index_design.md) — SQLite 派生索引设计（可丢弃、可重建）
- 📄 [**json_filter_checker_blueprint.md**](../json_filter_checker_blueprint.md) — JSON 筛选蓝图
- 📄 [**shape_type_filter_technical_spec.md**](../shape_type_filter_technical_spec.md) — shape_type 筛选技术规格
- 📄 [**filter_result_navigation_implementation_plan.md**](../filter_result_navigation_implementation_plan.md) — 筛选结果导航实现计划

---

## 截图

> `[截图待补]` — 计划补充：切图后筛选态保留 + 筛选结果跨文件导航演示
