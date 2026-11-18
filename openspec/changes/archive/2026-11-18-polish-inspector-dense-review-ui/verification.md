# P2 界面打磨实施与验证

2026-11-03，分支 `feat/ui-polish-p2`，基线 `9673d3b9`（P0 收口快照），
备份标签 `backup/pre-p2-20261103`。依据
[UI-IMPROVEMENT-PLAN.md](../../../reports/ui_review_20261103/UI-IMPROVEMENT-PLAN.md)
的 P2 清单与 §6.7 核查结论。

## 实际改动

### 1. 空间查漏网格（P2-1）

- `dense_review/workspace.py` 新增 `_CoverageGrid`：按 `CoveragePlan` 的
  `image_width/height` 等比映射 `region.rect`，四态配色（已完成 success /
  疑难 warning / 暂跳 primary / 待查 surface+background 混合），当前区域 2px
  primary 描边，悬停描边与 tooltip，无计划时画空状态文案。
- 查漏页改为 `QSplitter`：网格（stretch 3）+ 区域列表（stretch 2），列表键盘
  操作不变。
- 点击映射复用现有选择链路：`region_clicked → setCurrentItem →
  _on_region_selected → set_current_region + host 定位`；列表不可用时直接写
  会话并定位，避免两套状态。
- 新增 `tests/test_dense_review/test_coverage_grid.py`（7 项）与
  `test_workspace.py::test_coverage_grid_click_selects_matching_region`。

### 2. Inspector 详情分节（P2-2）

- `inspector/dialog.py` 重写 `_show_selected_details()`：
  概要（标题/说明）、规则命中（规则名/说明/指标两列表）、位置（文件/对象/
  区域）、建议、状态（人工判断/动作/机器）、备注六节。
- 新增 `_section()` / `_kv_table()` / `_format_metric()`；删除 `#86868b`
  硬编码，全部取 `get_theme()`；空证据显示「本轮没有规则证据。」。
- 新增 `test_detail_sections_follow_theme`：断言六节存在，并把 `get_theme`
  替换为 `DARK` 后验证 HTML 使用深色 token。

### 3. 快捷键与提示（P2-3）

- Inspector：`F5` 开始检查（仅在按钮可用时触发）、`Enter` 在问题表内定位
  （`WidgetShortcut`）、`Esc` 保持 Qt 原生；开始按钮/问题表 tooltip 标注真实
  按键。`Ctrl+F` 搜索**未实现**：Inspector 目前没有搜索框，搜索属于计划中的
  P1（表格排序/搜索/大数据模型），P2 不越界，见「未完成」。
- Dense：5 个 `QShortcut` 由 `ApplicationShortcut` 改为 `WindowShortcut`；
  `_apply_shortcut_hints()` 按实际配置给按钮写 tooltip（`Ctrl+Return` /
  `Alt+Return` / `Alt+N` / `Alt+X` / `Alt+V`）。
- 新增 `test_inspector_shortcuts_scope_and_start`、
  `test_dense_shortcuts_are_window_scoped`。

### 4. 本地化（P2-4）

- Inspector：模块级标签字典改为 `QT_TRANSLATE_NOOP` + `_translate_label()`
  运行时翻译；模块内 118 处中文字面量用脚本包进 `self.tr()`（跳过 docstring、
  f-string、比较表达式、字典键、`setProperty/setObjectName/setData`）。
- 四语言 `.ts` 用 `pylupdate6 anylabeling` 重生成（新增 413 条消息，工作台相关
  291 条），`en_US` 与 `zh_CN` 全部补齐（2500/2500），`lrelease` 重编译
  `.qm`，`rcc -g python` 重生成 `resources.py` 并保持 PyQt6 导入。
- 新增 `test_english_translations_cover_workbench`：加载
  `:/languages/translations/en_US.qm` 后打开 Inspector，断言按钮与表头为英文。

### 5. 主操作图标（P2-5）

- `utils/qt.py` 新增 `themed_icon(icon, color)`：用 SourceIn 合成把
  `currentColor` 的 SVG 图标着色为主题色，避免深色底不可见。
- Inspector：开始（play/白）、定位（scan-search/次色）、复查（rotate-cw/次色）。
- Dense：开始（play/白）、完成本批（check/白）、完成对象（circle-check/次色）、
  看全图（eye/次色）；图标尺寸 15px。

### 6. 测试基础设施

- 新增 `tests/conftest.py` 会话级 `QApplication`，修复跨测试模块运行时
  `QTranslator` 被销毁导致的 `RuntimeError` / 解释器 abort（原先分目录跑正常，
  合并跑必现）。
- `render_ui.py` / `render_dark.py` 的输出目录支持 `UI_REVIEW_OUT` 环境变量，
  便于在只允许工作区根目录写入的环境下出图。

## 实际命令与结果

```powershell
$env:QT_QPA_PLATFORM="offscreen"
$env:PYTHONPATH="D:/X-AnyLabeling-4.2.1/.tooling/pytest-shim"
python -m pytest -q -p no:cacheprovider --basetemp=.pytest-shim-run `
  tests/test_inspection tests/test_dense_review
```

结果：**170 passed**（Inspection 83、Dense Review 87），0 失败。

```powershell
python -m pytest -q -p no:cacheprovider --basetemp=.pytest-shim-run tests/test_canvas
```

结果：**578 passed, 1 failed**；失败项
`test_groups::test_shape_label_keeps_fixed_screen_size_while_zooming`
（179 != 139）是 P0 实施记录中已存在的基线失败，与本次改动无关。

```powershell
python -m flake8 <改动文件>
python -m black --check --line-length 79 <改动文件>
```

结果：通过（black 26.5.1；与 pre-commit 固定的 23.3.0 可能存在格式差异，
建议合并前用 pre-commit 再跑一次）。

离屏渲染（`UI_REVIEW_OUT=.p2-render`）：

| 文件 | 尺寸 | 平均 RGB | 说明 |
| --- | --- | --- | --- |
| `01_inspector_empty.png` | 1200×820 | 251,251,252 | 浅色空状态 |
| `03_inspector_selected.png` | 1200×820 | 247,248,249 | 六节详情 |
| `05_dense_coverage.png` | 1280×860 | 244,245,246 | 网格 + 列表 |
| `06_inspector_dark.png` | 1200×820 | 35,36,39 | 深色详情 |
| `08_dense_dark.png` | 1280×860 | 56,57,60 | 深色查漏 |

翻译覆盖：

| 语言 | 消息总数 | 未翻译 |
| --- | --- | --- |
| en_US | 2500 | 0 |
| zh_CN | 2500 | 0 |
| ja_JP | 2500 | 413 |
| ko_KR | 2500 | 413 |

## 未完成与边界

- **Ctrl+F / 表格搜索**：Inspector 无搜索框，属 P1 的「排序/搜索/大数据模型」，
  本次不实现，快捷键提示也未宣称该按键。
- **ja_JP / ko_KR**：413 条新增文案未翻译，运行时回退中文；需要时另开翻译任务。
- **真实屏幕人工验收**：所有截图来自 `QT_QPA_PLATFORM=offscreen`，未在真实
  显示器与真实数据集上验收；与 P0 相同的遗留项。
- **表格排序/三态页/按钮菜单化**：P1 范围，未做。

## 回退

- 代码：`git revert` 本次提交即可；网格为新增控件，删除 `_CoverageGrid` 与
  查漏页 splitter 改动可单独撤销该项；图标删除 `_apply_icons()` 调用即恢复纯文字。
- 翻译：`.ts`/`.qm`/`resources.py` 属生成物，回退到上一提交后重新运行
  `pylupdate6` / `lrelease` / `rcc` 即可。
- 数据：无变化，不涉及标注 JSON、`.xanylabeling/` 或检查报告格式。
