# 设计评审问题清单 — `manual-person-annotation-refinement`（v2 修订版）

> **版本说明**：本文件为第二轮评审结果。初版 15 个问题 + 3 处实现层留白已全部在
> `proposal.md` / `design.md` / `tasks.md` 中收敛。本次更新记录解决情况，
> 并补充修订后产生的 3 处微观问题。
>
> **结论**：spec 已达可实现状态。下方"待实现时验证"项均为编码决策，不阻塞动工。

---

## 一、初版 15 问题解决总览

| # | 问题摘要 | 解决方式 | spec 落点 |
|---|----------|----------|-----------|
| Q1 | 功能 1 漏 auto-labeling 分支 | 选 Non-Goal | proposal:11、Non-Goals:43、Decision 1:54、task 2.7、test 7.16 |
| Q2 | 互斥模式无显式 mode 变量 | 持久配置 `digit_shortcut_mode` + 瞬时 pending context | Decision 4:81、task 1.2/1.6 |
| Q3 | pending context 容器与清理边界 | 延迟提交 + 事务化回填 + 清理点枚举 | Decision 6:99、task 1.6/1.7/3.7/3.14、Risk:285、test 7.15 |
| Q4 | 同组同 label 拒绝的窗口与口径 | 三元组口径 + 双校验（digit 键 + 消费时） | Decision 7:107、task 3.8/3.11 |
| Q5 | 回填原子性（两次写拆 undo） | 同一 undo 快照提交 | Decision 6、Proposed:244、task 3.13、test 7.14 |
| Q6 | 提示通道与去抖 | bind_draw 模式才提示选中变化 + 200ms 去抖 + 固定 context | Decision 8:122、task 4.3/4.7/4.8 |
| Q7 | `prev_point` 漂移 ⚠️ | 虚拟光标累计 `virtual_prev_pos += precision_delta` | Decision 9:149-155、task 5.3/5.4、Risk:287、test 7.17 |
| Q8 | 精修触发方式 | 修饰键临时 + 可选锁定开关 | Decision 9:147、task 5.5 |
| Q9 | 键盘微调与 `MOVE_SPEED=5.0` 冲突 | 默认 1px / Shift 5px + 键盘选边状态 + undo 合并 | Decision 11:169-182、Migration:298、task 5.7-5.16 |
| Q10 | 吸附数据源/评分口径/阈值 | 灰度+梯度缓存、法线方向、median 聚合、内部固定阈值 | Decision 10:150-163、task 6.1-6.8 |
| Q11 | reject vs clamp 语义冲突 | 先 validate（clamp 即失败）再 apply | Decision 10:165、Proposed:275、task 6.10、test 7.19 |
| Q12 | `precision_factor` 作用范围 | 只影响鼠标 delta，键盘/吸附独立 | Decision 12:186 |
| Q13 | 选中边 vs 来源对象语义冲突 | 模式互斥表 | Decision 12:184-188、test 7.18 |
| Q14 | 配置 key 命名与 schema | 扁平 key + schema allow-list 登记 | Decision 13:192-201、task 1.5 |
| Q15 | 测试漏回归路径 | 补 test 7.14-7.19（6 条） | tasks.md:100-105 |

**全部解决。** 6 处文档（proposal/design/tasks 的决策、行为、任务、测试、风险、迁移）内部一致。

---

## 二、3 处实现层留白解决总览

| 原留白 | 已选方案 | spec 落点 |
|--------|----------|-----------|
| **Q2 架构**：新增 manager vs 合并 dispatcher | 新增 `DigitBindDrawManager`，与 `DigitRenameManager` 对称分离；`create_digit_mode` 按 `digit_shortcut_mode` 分流（伪码已给出） | Decision 4:93-104、task 3.2/3.3 |
| **Q9-B 键盘选边**：Tab 交互细节 | 进入（选中单 rectangle + Tab）、循环（L→T→R→B→L）、视觉（复用 active edge 样式）、退出（Esc/切选/切图/绘制/点空白） | Decision 11:171-178、task 5.9-5.12 |
| **Q10-B 评分聚合**：mean/median/p90 | median（抗角点噪声与孤立强响应） | Decision 10:163、task 6.6 |

**全部补齐。** task 列表同步扩展 +7 条（3.2/3.3、5.9-5.12、6.6）。

---

## 三、修订后新增的 3 处微观问题（非阻塞）

以下为第二轮评审在核对 Decision 4/10/11 更新时发现的新微观问题。
均不阻塞动工，可在实现阶段定，或现在补一句即可。

### N1. 键盘选边与鼠标 hover 边的共存

**位置**：Decision 11:177 退出条件枚举。

**现状**：键盘选边退出条件含 Esc、切换选中对象、切换图片、进入绘制模式、点击空白取消选择，但**不含"鼠标 hover 到另一条边"**。

**问题**：现在存在两套"active edge"来源：
- 鼠标 hover：`rect_edge_active_edge`（`canvas.py:1374`，现有）；
- 键盘 Tab：新的键盘选边状态。

若用户 Tab 选了 left 后鼠标移到 top 边附近，`rect_edge_active_edge` 会被 hover 更新为 top，而键盘选边仍指向 left——此时按方向键做单边微调，操作的是 left（键盘）还是 top（hover）？两者视觉指示也会打架（两个高亮边）。

**建议**（任选其一，实现时定）：
- (a) 鼠标 hover 时**自动退出**键盘选边（hover 即交还控制权给鼠标）；
- (b) 键盘选边存在时**屏蔽 hover 更新**（键盘优先，直到退出）；
- (c) 两者合并为单一"active edge"，键盘 Tab 只是在 hover 基础上循环。

推荐 (a)：符合"鼠标介入即接管"的直觉，退出条件补一句"鼠标 hover 到任意边"即可。

---

### N2. undo 合并窗口的实现方式未定

**位置**：task 5.15（"为连续键盘微调增加 undo 合并窗口，建议 500ms 内合并"）。

**现状**：现有 undo = 手动全量快照列表 `shapes_backups`（`canvas.py:143`，上限 `num_backups=10`）。`store_shapes()`（`canvas.py:389`）每次调用都 append 一个完整快照，**无合并/替换机制**。

**问题**：500ms 合并窗口有两种实现路径，各有取舍：
- **timer-based**：起一个 `QTimer`，500ms 无新输入才 push 快照。风险：app 崩溃/崩溃恢复时未落盘的微调丢失（虽然 auto-save 另有路径，但 undo 栈会缺一步）。
- **timestamp-based**：每次 push 前检查上一个快照时间戳，若 `now - last < 500ms` 则**替换**而非 append。无定时器，无延迟落盘，崩溃安全。

**建议**：选 timestamp-based（替换式合并）。实现时在 `store_shapes()` 加一个 `merge_window_ms` 参数，或新增 `store_shapes_merged()` 路径。task 5.15 可补一句"采用替换式合并，不引入定时器"。

---

### N3. 边缘吸附阈值策略仍含糊

**位置**：Decision 10:163"可靠性阈值 v0 使用内部固定参数"。

**现状**：与初版 Q10-C 相同，未明示是**自适应**（`k * max_local_response`）还是**绝对阈值**。

**影响**：
- 仅绝对阈值：暗图（整体梯度低）永远不吸附；
- 仅自适应：纹理稀疏图会把弱响应当强边，误吸。

**建议**：实现时用**双判据**——自适应为主（`score >= k * local_max`）+ 绝对下限兜底（`score >= abs_floor`），两者同时满足才接受。v0 可把 `k` 和 `abs_floor` 都硬编码，保留配置 hook 即可。

此条可在编码时定，无需改 spec。

---

## 四、待实现时验证项（编码决策，不改 spec）

以下 3 项是 spec 明确后留给实现的验证，记录在此供编码时核对：

| # | 验证项 | 验证方法 |
|---|--------|----------|
| V1 | 扁平 key（`canvas_precision_factor` 等）与 `config.py` 读写兼容 | 确认 `config.py` 对扁平顶层 key（参照 `auto_use_last_label`）无歧义；若 `canvas:` 嵌套块与扁平 `canvas_*` 混用不报 schema 错即可 |
| V2 | `DigitBindDrawManager` 与 `new_shape` 的 pending context 消费顺序 | Decision 3 优先级要求 pending context 在 `new_shape`（`label_widget.py:6573` `last_gid` 计算之前）被检查；确认消费点在 digit_to_label 分支之前 |
| V3 | 阈值双判据（N3）在合成图上的表现 | test 7.11（强边缘）+ test 7.12（低响应）已覆盖两端；编码时用中等对比度图验证不误吸 |

---

## 五、与 design.md `Open Questions` 的最终对应

design.md 原 4 条 Open Questions 全部关闭：

| design.md 原 Open Question | 关闭于 | 本文对应 |
|-----------------------------|--------|----------|
| 1. 精修模式触发方式 | Decision 9:147 | Q8 ✅ |
| 2. 键盘微调 1px/5px 归属 | Decision 11:171 + Migration:298 | Q9 ✅ |
| 3. 绑定绘制 UI 放哪 | Decision 4:93（`DigitBindDrawManager`） | Q2 ✅ |
| 4. 边缘吸附阈值是否暴露配置 | Decision 10:163（v0 内部固定 + hook） | Q10 ✅ |

---

## 六、结论

- **15 个初版问题**：全部在 spec 中解决，6 份文档内部一致。
- **3 处实现层留白**：全部补齐（`DigitBindDrawManager` / 键盘选边 / median）。
- **3 处新微观问题**（N1-N3）：均非阻塞，可在实现阶段定。
  - N1（键盘/鼠标 active edge 共存）推荐方案 (a)，spec 可补一句退出条件；
  - N2（undo 合并）推荐 timestamp-based，spec 可补半句；
  - N3（阈值策略）推迟到编码，不改 spec。
- **3 项实现时验证**（V1-V3）：编码时核对，不改 spec。

**spec 已达可进入 plan/实现的状态。** 建议下一步：进入 plan mode，在实现方案里把 N1/N2 定掉，V1-V3 作为编码核对清单。
