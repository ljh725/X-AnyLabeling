# Inspector / Dense Review UI 改造实施记录（P2）

- 日期：2026-11-03
- 范围：CUSTOM-109 / CUSTOM-110 的 P2 界面打磨
- 依据：[UI-IMPROVEMENT-PLAN.md](UI-IMPROVEMENT-PLAN.md) §三 P2 与 §6.2.3
- 变更单：[polish-inspector-dense-review-ui](../../openspec/changes/polish-inspector-dense-review-ui/proposal.md)
- 验证：[verification.md](../../openspec/changes/polish-inspector-dense-review-ui/verification.md)
- 基线：`9673d3b9`，分支 `feat/ui-polish-p2`，备份标签 `backup/pre-p2-20261103`

## 结果

| 指标 | P0 后 | P2 后 |
| --- | --- | --- |
| 查漏页信息形态 | 仅区域列表 | 网格示意图 + 列表，点击联动 |
| Inspector 详情 | 单段 HTML，3 处硬编码灰 | 六节结构，全部走 `get_theme()` |
| Inspector 业务快捷键 | 0 | `F5` / `Enter`（表格内），`Esc` 原生 |
| Dense 快捷键作用域 | `ApplicationShortcut` | `WindowShortcut` |
| Inspector 可翻译文案 | 253 个中文字面量中 188 未包 | 界面文案全部 `tr()`/`QT_TRANSLATE_NOOP` |
| en_US 翻译 | 工作台 0 条 | 2500/2500 已翻译 |
| 主操作图标 | 0 | 两窗口各 3–4 个，主题色着色 |
| 自动化测试 | 158 | 170（新增 12 项） |

## 变更文件

| 文件 | 改动 |
| --- | --- |
| `views/labeling/dense_review/workspace.py` | 新增 `_CoverageGrid`、查漏页 splitter、网格点击联动；快捷键改 `WindowShortcut`；`_apply_shortcut_hints()`、`_apply_icons()` |
| `views/labeling/inspector/dialog.py` | 详情六节 + 主题色；`_install_shortcuts()` / `_apply_icons()`；标签字典 `QT_TRANSLATE_NOOP`；118 处文案 `tr()` |
| `views/labeling/utils/qt.py` | 新增 `themed_icon()` |
| `resources/translations/*.ts|.qm` | 四语言重生成；en_US/zh_CN 补全 |
| `resources/resources.py` | `rcc` 重生成（PyQt6 导入） |
| `tests/conftest.py` | 会话级 QApplication |
| `tests/test_dense_review/*` | 网格测试 7 项 + 点击联动 + 快捷键/图标断言 |
| `tests/test_inspection/test_inspector_dialog.py` | 详情分节、快捷键、英文界面各 1 项 |

## 验证摘要

- `tests/test_inspection tests/test_dense_review`：**170 passed**
- `tests/test_canvas`：578 passed，1 项既有基线失败（与本次无关）
- flake8 / black：改动文件通过
- 浅色与深色离屏截图：`01`/`03`/`05`/`06`/`08`（`06`、`08` 为本轮新增深色对照）

## 未完成

- Inspector 表格搜索（P1）；`Ctrl+F` 未接线。
- ja_JP / ko_KR 各 413 条新文案未翻译，运行时回退中文。
- 真实屏幕与真实数据集人工验收未做（沿用 P0 遗留项）。

## 回退

按文件还原即可；翻译与 `resources.py` 为生成物，回退后重新
`pylupdate6` / `lrelease` / `rcc`。数据格式无变化。
