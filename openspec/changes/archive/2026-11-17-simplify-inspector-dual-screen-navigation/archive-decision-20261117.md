# Inspector 双屏导航简化归档决定

日期：2026-11-17（Asia/Shanghai）。

变更：`simplify-inspector-dual-screen-navigation`。

## 用户授权

用户在看到本变更“25/26，唯一剩余项为 6.3 实际双屏人工验收”的状态后，明确表示：

> “1 已经通过人工验证 勾选通过  2 讲任务归档”

据此勾选 6.3 并将本变更归档，任务状态 26/26。

## 关闭前的真实状态

- 代码与自动化：1.1–5.5、6.1、6.2、6.4 均为既有勾选，证据见 [verification.md](verification.md) 及其 JUnit 原件；最终完整 Inspector 与设置为 308 passed + 9 subtests，`openspec validate --strict` 通过。
- 6.3 实际双屏验收：2026-11-06 实施时保持未勾选。2026-11-07 在真实双屏（Q27G2S 2560×1440 + 2490W1 1920×1080）上创建独立验收实例，Computer Use 截图与点击通道超时（`FrameArrived timed out`、`coordinate input geometry is unavailable`），未记为通过。
- 本轮（2026-11-17）**没有新增截图、没有逐条操作记录**，也没有重跑双屏会话。

## 勾选依据与边界

6.3 的勾选依据是**用户的人工实测声明**，不是本仓库可复现的屏幕证据。本决定不追认 2026-11-07 那轮失败的自动化或截图尝试，也不把离屏渲染截图当作双屏证据。上述边界已同步写入 [tasks.md](tasks.md) 的 6.3 行和 [verification.md](verification.md) 的 2026-11-17 小节。

## 归档处理

- 归档位置：`openspec/changes/archive/2026-11-17-simplify-inspector-dual-screen-navigation/`。
- 两份新增规格同步到主规格：`openspec/specs/inspector-focused-review/`、`openspec/specs/inspection-result-navigation/`。规格中的验收要求保留，发布为正式契约不表示已取得全部人工证据。
- 更新 `openspec/PENDING_TASKS.md`，从活跃变更中移除本项。
- 同步 `docs/custom_changes/` 的 CUSTOM-123 记录与索引、`docs/version-management/操作记录.md`。

本次仅变更 OpenSpec 文档、定制台账与归档位置，不修改生产代码，不重跑功能测试。Inspector 重构（`refactor-data-inspector-workflow`，已归档）与其他变更的验收状态不受影响。
