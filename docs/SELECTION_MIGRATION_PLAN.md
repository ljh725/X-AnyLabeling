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
beta.11：统一 `_shape_hit_candidates`，按 **`(级别, 距离, 面积, -栈序)`** 优先级排序 —— 级别 0=顶点、1=可编辑边、2=整体命中。

---

## 二、安全网（备份 / 分支 / 回退）

| 机制 | 值 | 状态 |
|------|----|----|
| 备份 tag（本地） | `selection-migration/baseline-2026-06-29` | ✅ 已创建 |
| 备份 tag（异地 GitHub） | `origin/selection-migration/baseline-2026-06-29` | ✅ 已推送 |
| 迁移分支 | `feature/selection-optimization`（基于 `feature/label-display-mode @ a2d7f9d`） | ✅ 已创建并切换 |
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
- [ ] `shape.py` `__init__` 在 `self.visible = True` 后加 `self.locked = False`
- **回归测试**：打开任意带标注图，无报错、shape 正常显示

### 阶段 2：新增核心方法 `_shape_hit_candidates`
- [ ] `canvas.py` 在 `is_shape_interactive`（:488）后插入新方法（~75 行，移植自 beta.11 :497-571）
- [ ] 语法检查通过
- **依赖已确认**：`self.epsilon`(:97)、`self.scale`(:155)、`is_visible`、`utils.distance`、`utils.distance_to_line`、`nearest_cuboid_control`(:1731)、`cuboid_face_path`(:1756)、`cuboid_face_hit_test`(:1770)、`CUBOID_FACE_FRONT`(:54)

### 阶段 3：重写调用点① —— 悬停高亮 `mouseMoveEvent`（:591）
- [ ] `for shape in reversed([s for s in self.shapes if self.is_shape_interactive(s)]):`（:868-1050）→ `for shape in self._shape_hit_candidates(pos):`
- [ ] `else` 分支还原为 beta.4 原样 `self.un_highlight()`（不引入 group）
- [ ] 保持 `self.h_hape` 命名不变（不连锁改名）
- **回归测试点**：
  - [ ] 顶点附近 → 顶点高亮 + 手指 cursor
  - [ ] 边附近 → 边高亮 + "加点"提示
  - [ ] shape 内部 → 整体高亮 + 抓手 cursor
  - [ ] 重叠时移到最近顶点 → 优先高亮该顶点所属对象

### 阶段 4：重写调用点② —— 点击选择 `select_shape_point`（:1473）
- [ ] `else` 分支 `for shape in reversed(self.shapes):`（:1520-1560）→ `for shape in self._shape_hit_candidates(point):`
- [ ] 末尾保留 beta.4 原样 `self.deselect_shape()`（:1561，不引入 group）
- **回归测试点**：
  - [ ] 单击未选中对象 → 选中
  - [ ] Ctrl+单击 → 多选累加
  - [ ] 单击空白 → 取消选中
  - [ ] 重叠时点击交叠区 → 选到最近顶点/边所属对象（核心改进）
  - [ ] 嵌套时点击内层 → 内层（面积小）优先选中（核心改进）

### 阶段 5：重写调用点③ —— 双击编辑 `mouseDoubleClickEvent`（:1414）
- [ ] `if self.editing() and self.double_click_edit_label:` 下 `for shape in reversed(self.shapes):`（:1430-1450）→ `for shape in self._shape_hit_candidates(pos):`
- **回归测试点**：
  - [ ] 双击对象 → 弹出标签编辑框
  - [ ] 双击嵌套对象内层 → 编辑内层而非外层（核心改进）

### 阶段 6：收尾与提交
- [ ] `shape.py` / `canvas.py` 语法检查
- [ ] 端到端冒烟测试（上述全部回归点）
- [ ] 分步 commit（每阶段一个）+ push 到 GitHub `feature/selection-optimization`
- [ ] 更新本文档勾选

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
