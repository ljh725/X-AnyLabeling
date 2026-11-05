## Why

两点矩形创建时，后画的预览实线会盖住十字虚线；Shift / Shift+Alt 框内调整时，原框实线从候选虚线间隙露出，使新旧边界难以辨认。用户需要重合处清楚显示引导或候选边，同时保留原有标注与调整操作。

2026-11-04 代码复核补充：原框被方向键微调后，当前帧会将新原框几何与旧缓存候选组合，导致实际已无效的候选仍显示为橙色。该 P2 已在本变更内修复并补充真实 Canvas 事件与像素回归，见 `verification.md`。

## What Changes

- 创建矩形时恢复早期 beta.4 的先矩形、后十字线顺序，与十字线共线的草稿边不重复画实线；关闭创建引导时仍画完整草稿。
- Shift / Shift+Alt 有效拟合候选使用橙色虚线，原框仅在真正共边的区间临时避让，非共边维持原样。
- 遮罩轮廓与普通轮廓使用一致的避让结果；有效拟合预览期间让原生常驻十字线暂时让位。
- 取消、失效或退出预览时恢复完整原框；提交后恢复普通标注框。预览本身不修改标注、撤销和配置状态。
- 候选与其来源目标身份、原几何保持一致；悬停时原框变化则重算，已捕获手势的原几何变化则取消，避免旧候选继续避让或覆盖新的编辑结果。
- 增加共边几何、真实画布像素和取消/提交回归验证。

## Capabilities

### New Capabilities

- `rectangle-preview-rendering`: 定义两点创建与单点拟合预览的共边显示、层次、临时性及缩放一致性。这是为既有功能首次登记显示契约，不是新增操作工具。

### Modified Capabilities

无。当前 `openspec/specs/` 没有可复用的已发布对应规范。

## Impact

涉及 `widgets/canvas.py`、`widgets/rectangle_crosshair.py`、`widgets/point_fit.py`、`shape.py`，拟新增独立 `rectangle_preview.py`，以及相关画布测试和 CUSTOM-101/103 修复记录。

与工作区现有 Inspector、画布控制迁移等变更并存，实施仅归集本功能差异。无新增依赖、菜单、翻译、JSON 格式变更或破坏性 API 变更；不涉及共享盘标签扫描优化。

显示方案来源：`docs/custom_changes/2026-11-02-rectangle-preview-overlap-plan.md`；历史证据：`reports/crosshair_overlap_20261102/history_evidence.json`。
