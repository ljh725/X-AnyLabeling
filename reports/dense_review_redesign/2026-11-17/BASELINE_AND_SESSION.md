# 基线、样本与会话生命周期 · 2026-11-17

对应 OpenSpec `redesign-dense-review-workspace` 任务 1.3、1.4、2.2。实现与测试提交为 `216e903f`（`fix(dense-review): 修复会话恢复并补齐重设计样本`）。本报告只闭环这三项，不代表整个重设计完成。

## 任务 1.3：实施前版本复现

- 基线：`052239f2cb76e2daf0d4bd506d62c648433245ac`，在 `.tmp/dense-review-baseline-052239f2/` 建立 detached worktree，未修改基线源码。
- 样本：只使用 `.tmp/dense-review-redesign-20261117/private-s1274/` 内的私有副本；原图和标注未入库。
- 图像 SHA-256：`3fbe1521817ed266c819c4704bab0aa3d3fd1fc61a0f63d31e9be428e15a8a03`。
- 标注 SHA-256：`9cde86194700dc76be42a53c02899fcb7611331b78403c5b8155776445bc2172`。
- 内容核对：600×800，98 个对象，其中 6 个矩形、92 个点、18 个类名，group 0–5。
- 操作：先建立空工作区，再通过正常 `load_file` 加载副本，最后执行真实菜单动作 `widget.actions.open_dense_review.trigger()`；没有通过 `setEnabled(True)` 绕开缺陷。

| 检查 | 实际记录 |
| --- | --- |
| 空状态 | batch/card/region 三列表均禁用 |
| 菜单打开后的有效会话 | batch 1 项、card 98 项，但三列表仍全部禁用（WL-05） |
| 滚轮 | 滚动条 maximum=4273；发送 `QWheelEvent` 前后均为 0（OC-16） |
| 图块和行高 | 图像区 108 像素、卡片网格行高 176 像素 |
| 查漏遮挡 | 工作区为独立非模态 `QDialog`；与主画布全局矩形重叠 1154×864 像素 |

原始控件状态保存在 `.tmp/dense-review-redesign-20261117/baseline-old-workspace.json`，复现脚本为 `.tmp/repro_dense_review_baseline.py`。二者是本机证据，不包含在提交中。

## 任务 1.4：可复现样本清单

公共样本均由 `scripts/generate_dense_review_samples.py` 确定性生成，清单位于 `samples/dense_review/manifest.json`。生成器保留对象稳定 ID、类别、形状和 group_id；`tests/test_dense_review/test_samples.py` 会重新生成并核对内容、计数、加载与确定性。

| 样本 | 覆盖内容 |
| --- | --- |
| 上述私有 s1274 副本 | 6 框、92 点、98 对象、18 类名、group 0–5；仅本地使用 |
| `dense_30_six_classes` | 30 框、6 类、相邻重叠 |
| `stress_300` | 300 框、6 类各 50 个，压力与缓存场景 |
| `points_1000` | 1 个 group 0 主矩形和 1000 个明确关联点，总计 1001 对象 |
| `empty` | 无标注图片及完整空间查漏 |
| `small_and_occluded` | 遮挡和小目标 |
| `mixed_navigation` | group 0、同组多框、孤立点、只有点的组、远距离离群点、长中英日韩类名和不支持多边形 |
| `mixed_shapes` / `clipped_arm` | 混合不支持形状及框外证据 |

公共生成命令：

```bash
python scripts/generate_dense_review_samples.py --force
python scripts/generate_dense_review_samples.py --check
```

## 任务 2.2：失败、重试、重开和切图

实现位于 `anylabeling/views/labeling/dense_review/workspace.py`：

- 从有效会话进入空会话时清空旧批次、卡片、区域与请求键，关闭比较窗口并推进缩略图代际，避免旧内容和迟到结果继续呈现。
- 空状态反复刷新不会重复推进代际；成功建立会话后按实际内容重新启用列表。
- `_navigate_to()` 增加无效会话保护；确认、暂跳、区域动作沿用已有会话保护。

新增持久回归 `test_workspace_lists.py::test_failed_load_retry_reopen_and_image_switch_restore_session`，实际执行：

1. 有效会话建立 8 张卡片和 12 个区域。
2. 加载损坏图片失败，核对会话清空、三列表清空且禁用、依赖动作不执行。
3. 在同一路径恢复有效图片和 5 个新对象，正常重试后恢复列表及当前目标。
4. 关闭重开保持同一会话；切换到两个新 ID 的图片后只呈现新会话内容。

修复前该用例在失败加载后仍显示 1 个旧批次，断言失败；修复后单用例及整个列表文件通过。

## 验证

使用 conda `x-anylabeling-cu12`、Python 3.12、PyQt6 offscreen，保留 `.tmp` 配置隔离、外层硬超时和 `faulthandler_timeout=30`。

| 命令 / 范围 | 结果 |
| --- | --- |
| 新失败/重试用例（修复前） | 1 failed：旧批次数量为 1，不是 0 |
| 新失败/重试用例（修复后） | 1 passed |
| `test_workspace_lists.py` | 5 passed |
| `test_samples.py` | 9 passed |
| 列表 + dock 任务 + 样本组合 | **28 passed in 54.28s，退出码 0** |
| Black：`workspace.py`、`generate_dense_review_samples.py` | 通过 |
| Flake8：同两个 Python 文件 | 无告警 |
| `git diff --check` | 通过；其他工作的 `.gitignore` 仅有既有换行提示 |

未在本批执行完整密集复核目录、完整画布/标注/设置/Inspector、真实屏幕、双屏/DPI、性能和两位用户试用；这些仍由后续任务跟踪。

## 保存与边界

- 本地提交：`216e903f`，只含上述实现、生成器、公共样本和测试。
- `.gitignore`、`docs/development/` 及 `.tmp` 私有副本/基线工作树均未纳入提交。
- 未推送、未开 PR、未合入；目标保持 `codex/4.2.1-baseline-organization`。
- 任务 1.3、1.4、2.2 完成后，清单从 30/91 更新为 **33/91**。
