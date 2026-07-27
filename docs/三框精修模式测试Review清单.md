# 三框精修模式 · 测试 Review 清单

> **用途**：交付给测试人员的手工 + 自动化验收依据。
> **对象**：`feature/selection-optimization` 分支上的三框精修模式（View 菜单"三框精修模式"）。
> **状态**：6 个开发阶段 + 1 轮自审已完成，140 个自动化测试全绿。
> **日期**：2026-07-27

---

## 0. 如何启动测试

### 0.1 自动化测试（建议先跑，作为回归基线）

```powershell
$ErrorActionPreference = 'Stop'
$py = "$env:USERPROFILE\.conda\envs\x-anylabeling-cu12\python.exe"

# 三框精修全套（140 用例，约 1.5 分钟）
& $py -m pytest tests/test_rect_refine_grouping.py tests/test_rect_refine_visibility.py tests/test_rect_refine_workflow.py tests/test_rect_refine_canvas_gates.py tests/test_rect_refine_label_widget_integration.py tests/test_rect_refine_ui.py tests/test_rect_refine_settings.py tests/test_rect_refine_undo.py tests/test_rect_refine_boundary.py tests/test_rect_refine_edit_gates.py -q

# 既有回归（189 用例，应零失败）
& $py -m pytest tests/test_rect_edge_alignment.py tests/test_rect_edge_canvas_semantics.py tests/test_rect_edge_state_models.py tests/test_quality_geometry.py tests/test_quality_matching.py tests/test_size_overlay.py tests/test_settings/ -q
```

**预期**：`140 passed` + `189 passed`。任何失败请记录测试名 + 报告。

### 0.2 手工测试环境

- 启动应用：`xanylabeling`（或 `& $py -m anylabeling.app`）
- 准备一张含 person / head / face 矩形标注的图片（JSON + 图片）
- 入口：**视图 → 三框精修模式**（菜单可勾选）

---

## 1. 功能边界（测试人员必读）

### 1.1 第一版**做**了什么

| 能力 | 说明 |
|---|---|
| 模式入口 | 视图菜单勾选开启 / 取消关闭；连续模式（通过/Esc/切图不自动关闭） |
| 建组 | 鼠标点 person/head/face → 自动按几何 + GID 推导临时工作组 |
| 主画布隔离 | ACTIVE 时主画布只显示工作组成员，其他 Shape 不可见/不可交互 |
| 导航器分离 | 导航器始终显示用户基础层，不受任务层影响 |
| 边拖精修 | ACTIVE 时只能拖工作组成员的矩形边（整体/顶点/旋转/方向键被禁） |
| 实时对齐提示 | 拖边时若水平边差值严格 < 3px，显示绿色"上沿/下沿已接近" |
| 通过保存 | `Ctrl+Enter` 通过当前工作组 → 真实写盘 → 释放组 → 回 SELECTING |
| Esc 四级仲裁 | drag → pending → 工作组回滚 → Canvas 原有 Esc |
| Ctrl+Z 受限 | 工作组内单步撤销，不越过建组前历史 |
| 切图/关闭/互斥 | 自动安全回滚工作组；进入绘制模式自动关闭精修 |
| 配置/快捷键 | yaml `rect_refine` 块调阈值；设置对话框改 `Ctrl+Enter` |
| 国际化 | UI 文案 4 语言（zh/en/ja/ko） |

### 1.2 第一版**不做**（不要当作 bug 报）

- ❌ 不自动修改/补齐/重新分配正式 `group_id`
- ❌ 不显示成员列表/候选分数/像素差/"更换成员"面板
- ❌ 不自动吸附矩形边，不自动通过工作组
- ❌ 不支持 rotation / polygon / quadrilateral 等非水平矩形
- ❌ 不用模型推理替代几何匹配
- ❌ 不改变现有 Rectangle Edge Editing 的命中和拖动算法
- ❌ 不修复无关的全局保存/过滤历史问题
- ❌ `.qm`/`resources.py` 需在有 Qt6 RCC 工具链的环境单独重建（见 §6 已知限制）

---

## 2. 手工验收用例（按 §33 AC 编号）

> 每个 AC 给：**前置 / 操作 / 预期**。标记 ✅=已有自动化覆盖，📝=仅手工。

### 2.1 功能入口与连续模式（AC-001 ~ AC-007）

| AC | 前置 | 操作 | 预期 | 自动化 |
|---|---|---|---|---|
| AC-001 | 功能关闭 | 点视图菜单"三框精修模式" | 菜单勾选，状态栏提示"已开启"，无二次确认弹窗 | ✅ |
| AC-002 | 模式开启无工作组 | 再次点菜单 | 取消勾选，状态栏提示"已关闭"，恢复基础可见状态 | ✅ |
| AC-003 | 模式开启 | 通过(Ctrl+Enter)或 Esc 结束一组 | 模式仍开启，菜单仍勾选，可立即点下一个锚点 | ✅ |
| AC-004 | 模式开启 | 进入绘制模式（点"创建矩形"等） | 先安全回滚并关闭三框精修，菜单取消勾选 | ✅ |
| AC-005 | 应用无已加载图片 | 开启模式后加载图片 | 新图直接进入待选状态 | 📝 |
| AC-006 | 功能关闭 | 开启模式成功 | 画布/状态栏显示非模态开启提示 | 📝（仅 status 调用） |
| AC-007 | 模式开启 | 退出模式成功 | 显示非模态结束提示 | 📝（仅 status 调用） |

### 2.2 锚点与非对称推导（AC-010 ~ AC-017）

| AC | 操作 | 预期 | 自动化 |
|---|---|---|---|
| AC-010 | 点 person | 向下查 head，再从每个 head 查 face | ✅ |
| AC-011 | 点 head | 只向上查 person，不向下展开 face | ✅ |
| AC-012 | 点 face | 先查 head，再查 person，到 person 停止 | ✅ |
| AC-013 | 嵌套框重叠处点击 | 锚点 = Canvas hit-test 最终选中对象 | ✅ |
| AC-014 | head 向上有多个近分 person | 不任选父级，形成仅 head 不完整组 | ✅ |
| AC-015 | face 向上缺 head | 仅 face 进入组，不跨级找 person | ✅ |
| AC-016 | 点无效 bbox 锚点 | 不崩溃，锚点保留，形成不完整组 | ✅ |
| AC-017 | 锚点可见但关联对象被基础筛选隐藏 | 锚点可建组，推导仍扫描全图把合理关联加入工作组 | ✅ |

### 2.3 GID 与几何合并（AC-020 ~ AC-032）

> 这些主要由纯 Python 单测覆盖（grouping 模块）。手工抽样验证即可。

| AC | 场景 | 预期 | 自动化 |
|---|---|---|---|
| AC-020 | 三框统一有效 GID 且几何一致 | 三者进组，来源 GID+geometry | ✅ |
| AC-021 | person/head 同 GID，face 无 GID | head 合并证据加入，face 几何加入 | ✅ |
| AC-022 | person/face 同 GID，head 无 GID | 先几何找 head，再验证加入 face | ✅ |
| AC-023 | 只有 person 有 GID | 等价纯几何推导 | ✅ |
| AC-024 | person 无有效 GID | 跳过 GID 路径 | ✅ |
| AC-025 | 同 GID 两个 head | 返回 `DUPLICATE_GID_HEAD`，不建组 | ✅ |
| AC-026 | 同 GID 两个 face | 返回 `DUPLICATE_GID_FACE`，不建组 | ✅ |
| AC-027 | 同 GID head 几何硬不合理 | 返回 `GID_HEAD_GEOMETRY_INVALID` | ✅ |
| AC-028 | 几何 top1 明显优于同 GID head ≥0.12 | 返回 GID/几何冲突 | ✅ |
| AC-029 | 几何 top1 与同 GID head 分差 <0.12 | 视为歧义，保留合理候选，不判冲突 | ✅ |
| AC-030 | 同 GID face 与所有已接受 head 不合理 | 返回 `GID_FACE_GEOMETRY_INVALID` | ✅ |
| AC-031 | 同 GID face 但无可验证 head | face 不绕过几何进组，不改 GID | ✅ |
| AC-032 | GID 值为 bool/字符串/非法值 | 只视为无可用 GID 证据 | ✅ |

### 2.4 几何候选（AC-040 ~ AC-048）

| AC | 场景 | 预期 | 自动化 |
|---|---|---|---|
| AC-040 | 无 GID 且多个合理 head | 全部进入 person 工作组 | ✅ |
| AC-041 | 每个 head 有多个合理 face | 合理 face 取并集去重 | ✅ |
| AC-042 | 缺 head | person 锚点仍可建立不完整组 | ✅ |
| AC-043 | 有 head 缺 face | person+head 可建立不完整组 | ✅ |
| AC-044 | 内框完全包含但普通 IoU 低 | 不得仅因 IoU 低排除 | ✅ |
| AC-045 | 候选分数 0.5499 | 不进入合理候选 | ✅ |
| AC-046 | 候选分数 0.55 | 进入合理候选 | ✅ |
| AC-047 | 同一输入重复推导 | 成员和关系顺序完全一致 | ✅ |
| AC-048 | 几何多候选超过 3 个 | 不被 QA 的 top_n=3 截断 | ✅ |

### 2.5 可见层和交互权限（AC-050 ~ AC-058）

| AC | 场景 | 预期 | 自动化 |
|---|---|---|---|
| AC-050 | 进入前有 label/GID/type 过滤 | SELECTING 主画布保持进入前基础可见效果 | 📝（部分） |
| AC-051 | 工作组建立 | 主画布只显成员，其他不可 hover/选择/编辑 | ✅ |
| AC-052 | 工作组活动且导航器打开 | 导航器仍按进入前基础过滤显示 | ✅ |
| AC-053 | 工作组结束 | 清任务层，主画布回基础可见，模式保持 SELECTING | ✅ |
| AC-054 | 退出模式 | 过滤控件/标签可见/Shape 手动可见逐项恢复 | 📝 |
| AC-055 | 模式中触发过滤/隐藏动作 | 动作被拒绝，基础快照不变 | 📝（未实现拒绝 UI） |
| AC-056 | 模式前矩形边编辑关闭 | SELECTING 不可拖边，ACTIVE 组内可拖，退出后仍关闭 | ✅ |
| AC-057 | 模式前矩形边编辑开启 | SELECTING 不可拖边，ACTIVE 组内可拖，退出后仍开启 | ✅ |
| AC-058 | ACTIVE 中尝试删除/整体移动/旋转/方向键/改 GID | 操作不可执行 | ✅ |

### 2.6 Esc、回滚和撤销（AC-060 ~ AC-067）

| AC | 场景 | 预期 | 自动化 |
|---|---|---|---|
| AC-060 | 正在边拖动 | 第一次 Esc 只回滚本次拖动，工作组仍 ACTIVE | ✅ |
| AC-061 | 存在 pending | Esc 只取消 pending，工作组仍 ACTIVE | 📝（tier 逻辑测，真实 pending 路径手工） |
| AC-062 | ACTIVE 且无边交互 | Esc 恢复整组初始几何并回 SELECTING | ✅ |
| AC-063 | SELECTING 无工作组 | Esc 执行 Canvas 原有行为 | 📝 |
| AC-064 | 建组前 clean，组内多次拖边 | Esc 后 clean，points 与初始逐点相同 | ✅ |
| AC-065 | 建组前 dirty | Esc 后仍 dirty | ✅ |
| AC-066 | Esc 完整回滚后按 Ctrl+Z | 已取消几何不会重新出现 | ✅ |
| AC-067 | 工作组内多次 Ctrl+Z | 不得撤销到建组前历史 | ✅ |

### 2.7 保存与自动保存（AC-070 ~ AC-079）

| AC | 场景 | 预期 | 自动化 |
|---|---|---|---|
| AC-070 | 无工作组按 Ctrl+Enter | 不保存、不切状态 | ✅ |
| AC-071 | ACTIVE 且无 pending/drag | Ctrl+Enter 只调一次保存 | ✅ |
| AC-072 | 正在 drag/pending | Ctrl+Enter 不保存 | ✅ |
| AC-073 | 保存成功 | 保留几何、清工作组、回 SELECTING、模式保持开启 | ✅ |
| AC-074 | 用户取消保存对话框 | 工作组和几何保持 ACTIVE | ✅ |
| AC-075 | `save_labels()` 返回失败 | 工作组和几何保持 ACTIVE，显示现有错误 | 📝（语义覆盖） |
| AC-076 | 保存抛出可处理异常 | 不停留在 SAVING，可重试 | ✅ |
| AC-077 | `auto_save=true` 且组内完成拖边 | **通过前磁盘 JSON 不变化** | ✅ |
| AC-078 | `auto_save=true` 后通过 | 只在通过路径写入最终几何 | ✅ |
| AC-079 | 工作组未改几何直接通过 | 仍执行一次成功保存并回 SELECTING | ✅ |

### 2.8 切图与关闭（AC-080 ~ AC-086）

| AC | 场景 | 预期 | 自动化 |
|---|---|---|---|
| AC-080 | ACTIVE 时切图 | 当前组回滚，新图 SELECTING，模式保持开启 | ✅ |
| AC-081 | 建组前 clean、组内有修改后切图 | **不弹"保存临时精修"提示** | ✅ |
| AC-082 | 建组前 dirty、组内有修改后切图 | 先回滚组，再由原流程询问建组前修改 | 📝 |
| AC-083 | 用户取消切图 | 当前图保持 SELECTING，已回滚组不自动重建 | 📝 |
| AC-084 | ACTIVE 时关闭模式 | 回滚并恢复基础层，状态 OFF | ✅ |
| AC-085 | ACTIVE 时关闭应用 | 临时修改不写盘，原 dirty 语义保留 | 📝 |
| AC-086 | 切图回调晚到且 token 属于旧图 | 不操作新图 Shape | ✅ |

### 2.9 Overlay（AC-090 ~ AC-097）

| AC | 场景 | 预期 | 自动化 |
|---|---|---|---|
| AC-090 | 实际差值 2.9 px | 显示绿色提示 | ✅ |
| AC-091 | 实际差值 3.0 px | 不显示 | ✅ |
| AC-092 | 实际差值 >3.0 px | 不显示 | ✅ |
| AC-093 | 改变缩放倍率 | 判断结果不变（用原图坐标） | 📝 |
| AC-094 | 拖边尚未 release | Overlay 随实时 points 出现/消失 | ✅ |
| AC-095 | 当前关系歧义 | 不显示该关系提示 | ✅ |
| AC-096 | Overlay 出现 | dirty、撤销栈、Shape 样式、JSON 均不变 | 📝 |
| AC-097 | UI 文本检查 | 不出现实际像素数字或候选分数 | ✅ |

### 2.10 持久化隔离（AC-098 区，§33.10）

| 检查 | 预期 | 自动化 |
|---|---|---|
| 序列化前后 Shape 数量/label/group_id/flags/attributes 不因建组改变 | 是 | ✅（JSON 无 rect_refine 字段断言） |
| 只有用户通过后确认的 points 可以变化 | 是 | ✅ |
| JSON 不存在 `rect_refine`/临时成员/来源/冲突/`qa_entity_id` 字段 | 是 | ✅ |
| 用户配置只含稳定参数 + 快捷键，不含运行时工作组 | 是 | ✅ |

---

## 3. 高风险路径（重点测，对应审计 10 条阻断风险）

| # | 风险 | 手工验证要点 | 自动化 |
|---|---|---|---|
| 1 | ACTIVE 几何偷偷写盘 | 开 `auto_save=true`，ACTIVE 拖边后立刻查磁盘 JSON 文件 mtime/内容应不变 | ✅ AC-077 |
| 2 | 任务层污染基础层 | ACTIVE 时改 navigator 缩放、退出模式后查 label 筛选/可见性逐项恢复 | ✅ AC-052/054 |
| 3 | 保存失败释放组 | 通过时故意让保存失败（只读目录），确认工作组仍 ACTIVE 可重试 | ✅ AC-074/076 |
| 4 | Esc 后 dirty 被清空 | 建组前先做一处普通编辑（dirty），进组拖边，Esc 后窗口标题仍有 `*` | ✅ AC-065 |
| 5 | Ctrl+Z 越 floor | 建组后连按 Ctrl+Z 多次，确认不会回到建组前的标注状态 | ✅ AC-067 |
| 6 | 切图绕过回滚 | ACTIVE 拖边未通过时切下一张，确认旧图未被写入临时几何 | ✅ AC-080/081 |
| 7 | 临时字段写 JSON | 通过一组后用文本编辑器打开 JSON，搜 `rect_refine`/`qa_entity_id` 应无 | ✅ |
| 8 | Pose overlay 绕过任务层 | 有 pose 标注的图，ACTIVE 时主画布不应出现非成员关键点 | ✅ |
| 9 | SELECTING 边拖抢占 | SELECTING 状态点矩形边附近，应触发正常选择而非边拖抢占 | ✅ |
| 10 | 用磁盘旧 JSON 推导 | 改图后立刻进精修模式，确认用的是当前画布内存 Shape 而非旧 JSON | ✅ AC-017 |

---

## 4. 探索性测试建议

测试人员在自动化之外建议重点探索：

1. **边界几何**：极小框（1×1）、极大框、负坐标、NaN/Inf 坐标 → 应不崩溃
2. **多工作组连续**：连续处理 5+ 个对象，确认每组的 token/身份不串
3. **快速操作**：建组瞬间立刻 Esc / 切图 / Ctrl+Enter，确认无残留状态
4. **撤销栈边界**：建组后立刻 Ctrl+Z（无任何拖边），确认行为正确
5. **互斥模式往返**：精修 → 绘制 → 精修 → 关键点填充 → 精修，确认每次正确开关
6. **国际化**：切换 en/ja/ko 语言，确认菜单/提示/Overlay 文案正确（注意：`.qm` 需重建后才生效，见 §6）
7. **配置变更**：改 yaml `rect_refine.min_accept_score` 后重启，确认候选阈值变化
8. **快捷键改绑**：设置对话框把 `Ctrl+Enter` 改成别的键，确认生效

---

## 5. 缺陷报告模板

```
【AC 编号】AC-XXX（若无，写"探索"）
【前置】图片/标注状态、模式状态、auto_save 设置
【操作】步骤序列
【预期】见 Review 清单
【实际】观察到的现象
【自动化是否覆盖】是/否（若是，附测试名）
【复现概率】必现/偶发（附概率）
【环境】OS / 分支 commit / 是否重建 .qm
```

---

## 6. 已知限制（不是 bug）

| 限制 | 说明 | 影响 |
|---|---|---|
| `.qm`/`resources.py` 未重建 | 当前开发环境无 Qt6 RCC 工具链（pyrcc6/pyside6-rcc 缺失）。`.ts` 翻译来源已写入 4 语言，需在有完整工具链的环境跑 `scripts/compile_languages.py` | i18n 文案在重建前可能显示为 source 文本（中文硬编码仍生效） |
| AC-006/007 非模态画布提示 | 当前用状态栏 `status()` 提示，未实现画布主界面 overlay 型提示 | 提示位置在状态栏而非画布上 |
| AC-055 过滤动作拒绝 UI | 模式中触发过滤/隐藏动作时未实现"拒绝 + 提示"UI | 用户仍可能改基础层（退出时由快照恢复，但运行中不阻止） |
| AC-061 真实 pending Esc | tier-2 逻辑已接，但完整 pending→Esc 真实路径仅手工验证 | 建议手工补 |
| 翻译质量 | ja/ko 的 8 条新字符串为英文占位，待母语维护者精修 | 日韩用户看到英文文案 |

---

## 7. 自动化测试文件索引（测试人员可对照）

| 文件 | 用例数 | 覆盖重点 |
|---|---|---|
| `tests/test_rect_refine_grouping.py` | 39 | §29 推导/评分/GID 合并/冲突码（AC-010~048 纯逻辑） |
| `tests/test_rect_refine_visibility.py` | 14 | §28 三层可见性（base/task/main/navigator） |
| `tests/test_rect_refine_workflow.py` | 36 | §25 状态机 + Esc + Save + dirty + token（fake adapter） |
| `tests/test_rect_refine_canvas_gates.py` | 8 | Canvas 可见性门禁 + Esc 分层 + Overlay（PyQt） |
| `tests/test_rect_refine_label_widget_integration.py` | 5 | 真实注入 + auto-save 阻断 + selection 接线（PyQt） |
| `tests/test_rect_refine_ui.py` | 8 | 菜单 toggle + Ctrl+Enter + 互斥 + 切图回滚（PyQt） |
| `tests/test_rect_refine_settings.py` | 8 | config 注入 + schema + runtime action map |
| `tests/test_rect_refine_undo.py` | 2 | undo_floor 真实路径 + 组内单步撤销 |
| `tests/test_rect_refine_boundary.py` | 15 | 边界 AC 系统测试（连续/嵌套/auto_save/保存细分/Overlay） |
| `tests/test_rect_refine_edit_gates.py` | 5 | AC-058 编辑门禁（方向键/旋转/整体移动） |
| **合计** | **140** | |

---

## 8. 验收结论标准

Review 后给出三种结论之一（§36.5）：

- ✅ **通过**：所有 ✅ 自动化用例绿 + 📝 手工用例无阻断级缺陷
- ⚠️ **有条件通过**：存在非阻断缺陷（如 i18n 文案、AC-006 提示位置），列明修复计划后可合并
- ❌ **不通过**：存在阻断级缺陷（几何写盘、状态机不一致、JSON 污染、崩溃）

**阻断级红线**（任一触发即不通过）：
1. ACTIVE 中未通过却写盘
2. 任务层污染了 `shape.visible`/`canvas.visible`/`hidden_by_filter`
3. 保存取消/失败后释放了工作组
4. Esc 回滚后 dirty 状态错误
5. Ctrl+Z 越过 undo_floor
6. 切图/关闭/删除/auto-labeling 绕过回滚
7. 临时字段写入了 JSON
8. 任何状态下的崩溃
