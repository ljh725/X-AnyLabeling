## Why

CUSTOM-109 Inspector 与 CUSTOM-110 Dense Review 的 P0 界面重构已完成（见
`reports/ui_review_20261103/UI-IMPLEMENTATION.md`），但
`UI-IMPROVEMENT-PLAN.md` 的 P2 仍留下四处可见缺口：

- 空间查漏页只有区域列表，看不出「哪些区域已查」，与网格语义脱节。
- Inspector 详情是一整段 HTML 文本墙，规则、证据、建议混在一起，且带三处写死
  灰色，深色模式下对比不足。
- Inspector 没有任何业务快捷键；Dense 的快捷键是应用级作用域，窗口失焦后仍会
  抢 `Alt+Return` 等按键；界面提示文案与实际绑定（`Ctrl+Return`）不一致。
- Inspector 的 253 个中文字面量中有 188 个未包 `tr()`，英文界面下这些文案不会
  被翻译；两窗口标题在四套 `.ts` 中均为 0 条。

P2 不改业务判定、数据结构与保存格式，只补交互与呈现，因此可以独立成一次变更，
不影响 P0 已验收的行为。

## What Changes

- 空间查漏页新增网格示意图：按 `CoveragePlan` 的行列与 `image_width/height`
  等比绘制，已查/疑难/暂跳/待查四态着色，当前区域描边；点击方块等同在列表选中
  并定位；无计划时显示空状态而不是空白网格。
- Inspector 详情改为分节呈现：概要、规则命中（含指标）、位置、建议、状态、
  备注；颜色全部取 `get_theme()`，不再写死 `#86868b`。
- 快捷键：Inspector 增加 `F5` 开始检查、`Enter` 定位、`Ctrl+F` 聚焦搜索；
  Dense 的五个快捷键从 `ApplicationShortcut` 改为 `WindowShortcut`；两窗口的
  提示文案改为真实绑定（`Ctrl+Return` / `Alt+Return`）。
- 本地化：Inspector 面向界面的中文串包 `self.tr()`（配置键、枚举值、数据键
  不改），重生成 `zh_CN / en_US / ja_JP / ko_KR` 的 `.ts` 与 `.qm`。
- 主操作补图标：两个窗口各 2–4 个主/常用按钮接入 `new_icon_path`。
- 不做：表格排序/搜索/大数据模型、三态页、按钮菜单化、qtbase 标准按钮翻译
  （均为 P1 或需要独立依赖，另立变更）。

## Capabilities

### New Capabilities

- `workbench-ui-polish`: 定义两个工作台的核查网格、详情分节、快捷键作用域与
  本地化要求。

### Modified Capabilities

无。`openspec/specs/` 目前没有这两个工作台的已发布规范。

## Impact

涉及 `anylabeling/views/labeling/dense_review/workspace.py`、
`anylabeling/views/labeling/inspector/dialog.py`、`utils/style.py`（仅追加
作用域样式）、`utils/theme.py`（若需补 token）、
`anylabeling/resources/translations/*.ts|.qm`，以及对应测试与
`docs/custom_changes/2026-11-02-*.md` 的「后续修订」表。

无新增依赖、无数据结构或保存格式变更；不改 `inspection` / `dense_review`
服务层。回退按文件撤销即可。
