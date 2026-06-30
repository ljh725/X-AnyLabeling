# 功能 C「复杂对象选择优化」迁移到 beta.4 —— 执行计划

> 归档文档。本文件随迁移进度更新，已完成项打勾。
>
> 创建时间：2026-06-29
> 目标项目：`D:/xinjiegou-X-AnyLabeling-4.0.0-beta.4`
> 参考来源：`D:/X-AnyLabeling-4.0.0-beta.11`

---

## 一、目标与范围

### 目标
把 beta.11 的选择优化（`_shape_hit_candidates` 多级优先级排序）迁移到 beta.4，解决重叠 / 嵌套 / 近邻对象的误选、难选问题。

### 本次范围（已确认）
- ✅ **只迁移功能 C**（选择优化），不迁移功能 A（锁定）/ 功能 B（组）。
- ✅ 对 `_shape_hit_candidates` 内的 `locked` 守卫做**轻量适配**：仅在 `Shape.__init__` 加 `self.locked = False` 默认值，让守卫永远 no-op；不带锁定的任何 UI / 持久化 / 删除保护。
- ✅ 迁移分支独立验收，**不合并**回 `feature/label-display-mode`。

### 核心改进原理
beta.4：`reversed(shapes) + 首次 contains_point 命中即 return`（栈序 + 区域包含）。
beta.11：统一 `_shape_hit_candidates`，按 **`(级别, 主排序值, 次排序值, -栈序)`** 优先级排序 —— 级别 0=顶点、1=可编辑边/点线近邻、2=整体命中；顶点/边的主排序值是距离，整体命中的主排序值是面积。

---

## 二、安全网（备份 / 分支 / 回退）

| 机制 | 值 | 状态 |
|------|----|----|
| 备份 tag（本地） | `selection-migration/baseline-2026-06-29` | ✅ 已创建 |
| 备份 tag（异地 GitHub） | `origin/selection-migration/baseline-2026-06-29` | ✅ 已推送 |
| 迁移分支 | `feature/selection-optimization`（基于 `feature/label-display-mode @ a2d7f9d`） | ✅ 已创建并切换 |
| 迁移分支（异地 GitHub） | `origin/feature/selection-optimization` | ✅ 已推送 |
| 基线 HEAD | `a2d7f9d 260629_移走无关信息` | ✅ |

### 三级回退兜底
| 场景 | 命令 |
|------|------|
| 单步改错 | `git reset --hard HEAD~1` |
| 整体回退（本地） | `git reset --hard selection-migration/baseline-2026-06-29` |
| 本地 `.git` 损坏 | `git fetch origin && git reset --hard selection-migration/baseline-2026-06-29` |

---

## 三、执行阶段

### 阶段 0：备份与分支 — ✅ 已完成
- [x] 确认工作区干净
- [x] 打本地 tag `selection-migration/baseline-2026-06-29`
- [x] 推 tag 到 GitHub origin（异地容灾）
- [x] 建迁移分支 `feature/selection-optimization`
- [x] 写本文档

### 阶段 1：轻量适配 locked 字段
- [x] `shape.py` `__init__` 在 `self.visible = True` 后加 `self.locked = False`
- [x] 语法检查通过 (commit `68e30f5`)
- **回归测试**：打开任意带标注图，无报错、shape 正常显示 — ⏳ 待人工验证

### 阶段 2：新增核心方法 `_shape_hit_candidates`
- [x] `canvas.py` 在 `is_shape_interactive` 后插入新方法（92 行含注释，移植自 beta.11）
- [x] 语法检查通过 (commit `83adef6`)
- **依赖已确认**：`self.epsilon`、`self.scale`、`is_shape_interactive`、`utils.distance`、`utils.distance_to_line`、`nearest_cuboid_control`、`cuboid_face_path`、`cuboid_face_hit_test`、`cuboid_control_point`、`CUBOID_FACE_FRONT` — 全部存在

### 阶段 3：重写调用点① —— 悬停高亮 `mouseMoveEvent`
- [x] 循环头改为 `for shape in self._shape_hit_candidates(pos):` (commit `b7d3222`)
- [x] `else` 分支保持 beta.4 原样 `self.un_highlight()`（不引入 group）
- [x] 保持 `self.h_hape` 命名不变
- **回归测试点**：⏳ 待人工验证（见下方清单）

### 阶段 4：重写调用点② —— 点击选择 `select_shape_point`
- [x] `else` 分支改为 `for shape in self._shape_hit_candidates(point):` (commit `0b4dea3`)
- [x] 末尾保持 beta.4 原样 `self.deselect_shape()`（不引入 group）
- [x] 消除重复判定逻辑（净减 20 行）
- **回归测试点**：⏳ 待人工验证（见下方清单）

### 阶段 5：重写调用点③ —— 双击编辑 `mouseDoubleClickEvent`
- [x] `double_click_edit_label` 分支改为 `for shape in self._shape_hit_candidates(pos):` (commit `38d6cb1`)
- [x] 消除重复判定逻辑（净减 12 行）
- **回归测试点**：⏳ 待人工验证（见下方清单）

### 阶段 6：收尾与提交
- [x] `shape.py` / `canvas.py` 语法检查通过
- [x] 完整性检查：已无遗留 `reversed(self.shapes)` 选择循环；`_shape_hit_candidates` 出现 5 次（1 定义 + 3 调用 + 1 文档提及）
- [x] 分步 commit 完成（6 个提交）
- [x] push 到 GitHub `feature/selection-optimization` 分支
- [x] 更新本文档
- [x] **基础回归测试已通过**（人工，2026-06-29）：渲染/悬停/顶点/边/单击/Ctrl多选/双击均正常，未破坏原有行为
- [x] **算法优先级验证已通过**（自动化，`tests/test_shape_hit_candidates.py`）：嵌套/顶点优先/近邻顶点/空白点击/元组排序 6 场景全过
- [ ] **核心改进 GUI 验证**（重叠/嵌套真实标注图）— ⏳ 待人工验证

---

## 四、风险与注意事项

| 风险 | 应对 |
|------|------|
| beta.4 `self.h_hape`（疑似笔误）vs beta.11 `self.h_shape` | **不改命名**；新方法不引用此属性（只返回候选列表），规避连锁风险 |
| 范围蔓延 | 明确不迁移：功能 A 锁定 UI/持久化、功能 B 组逻辑、brush 编辑、auto-decode |
| 几何函数 | `nearest_vertex`/`nearest_edge`/`contains_point` 两版逐字相同，**零改动** |

---

## 五、交付物

1. `docs/SELECTION_MIGRATION_PLAN.md`（本文件）
2. 代码改动：`shape.py`(+1 行)、`canvas.py`(+75 行新方法 + ~100 行重写 3 处调用点)
3. git 产物：tag `selection-migration/baseline-2026-06-29`（本地+远程）、分支 `feature/selection-optimization`（本地+远程）

---

## 六、执行日志

- **2026-06-29 阶段0**：tag + 远程推送 + 迁移分支创建完成。当前位于 `feature/selection-optimization`。
- **2026-06-29 阶段1-5**：代码迁移全部完成，6 个分步提交（`f7f0b15`→`38d6cb1`）。
- **2026-06-29 阶段6**：语法检查/完整性检查通过，分支已 push GitHub。**待人工冒烟测试。**

### 迁移总改动量（相对 baseline）
| 文件 | 增 | 删 | 净 |
|------|----|----|----|
| `anylabeling/views/labeling/shape.py` | +4 | 0 | +4 |
| `anylabeling/views/labeling/widgets/canvas.py` | +121 | -61 | +60 |
| `docs/SELECTION_MIGRATION_PLAN.md` | +117 | 0 | +117 |
| **合计** | | | **+181** |

---

## 七、人工回归测试清单 ⏳

请在 `feature/selection-optimization` 分支上启动应用，用**带重叠/嵌套标注的图**验证以下场景：

### 基础回归（确认未破坏原有行为）
- [ ] **渲染**：打开带标注图，所有 shape 正常显示，无报错
- [ ] **悬停**：鼠标移到顶点附近 → 顶点高亮、cursor 变手指
- [ ] **悬停**：鼠标移到边上 → 边高亮、提示"加点"
- [ ] **悬停**：鼠标移到 shape 内部 → 整体高亮、cursor 变抓手
- [ ] **单击**：未选中对象 → 选中
- [ ] **Ctrl+单击**：多选累加
- [ ] **单击空白**：取消选中
- [ ] **双击**：弹出标签编辑框

### 核心改进验证（功能C的价值点）
- [ ] **重叠对象**：移到/点击交叠区 → 优先选中最近顶点/边所属对象（beta.4 会选栈顶）
- [ ] **嵌套对象**：点击/双击内层 → 内层（面积小）优先选中/编辑（beta.4 会选大框）
- [ ] **cuboid**：8 点立方体的顶点/面/边高亮与拖动正常（cuboid 分支已迁移）

### 失败时回退
```bash
git reset --hard selection-migration/baseline-2026-06-29   # 整体回退
git reset --hard HEAD~N                                     # 回退 N 个提交
```

---

## 八、关键点（pose keypoint）多选说明

> 经确认（2026-06-29）：beta.4 关键点 = `shape_type == "point"` 的独立 Shape。

- **多选方式：点击式**。依次 `Ctrl+点击`不同关键点（每次点击后**松开鼠标**）即可累加多选。
  - Ctrl + 点击关键点A → 松开 → Ctrl + 点击关键点B → A、B 同选 → ...
- **注意避免**：`Ctrl` 按下后**不松手直接拖动**会被 `mouseMoveEvent` 的"已选对象拖动"分支接管（`:863 bounded_move_shapes`），导致关键点跟着鼠标跑（这是拖动，不是多选）。
- **此行为迁移前后一致**（`:863` 拖动逻辑迁移未改动，diff 为空），非迁移引入。
- **功能C对关键点的正向影响**：多个关键点紧邻时（如 COCO pose 手肘/手腕相邻），迁移后会优先选中**离光标更近**的关键点，比 beta.4 的栈序选择更准。
