# 2026-11-06 当前项目改动核对

本次核对当前工作区、Git 历史、定制台账及各项最新实施记录，没有重新验收所有历史功能。

## 比较范围与保存状态

- 官方基线：`v4.2.1^{commit}`，`6d250499d2dd81f78723b9217c7a9abf0443ca25`。
- 当前分支：`codex/4.2.1-baseline-organization`。
- 本次交付整理起点：`b27f122a`（2026-11-06），此前的 `834e494e` 保存单点拟合修复，`b27f122a` 保存该修复的交付补记；两个提交均已同步工作分支及版本入口。
- 相对官方基线，当前 `anylabeling/` 下有 91 个差异文件：新增 59、修改 32。该口径包含配置、翻译及生成资源，不能解释成 91 个功能或 91 个手工编写的 Python 文件。
- [逐文件清单](inventory/source-files-20261106.tsv) 来自 `git diff --name-status v4.2.1 -- anylabeling`，包括本次交付的 Canvas 框选和已提交的单点拟合修复；A/M 是文件状态，不是功能分类。
- 11-05 的 `e4421908` 保存此前设置、画布、Inspector、Dense Review 等工作区成果；`f083a534` 合并版本首页；`1ef860fa` 保存操作说明与同步证据。[历史同步记录](../../reports/workspace_sync_20261105/README.md) 记录当时情况。11-06 已联网核对远端，交付前两个目标分支均为 `b27f122a`。
- 今天剩余的框选源码、测试、实现记录及总览/索引更新已由 `c58e16b6` 保存，并同步至个人仓库 `origin/codex/4.2.1-baseline-organization` 与 `origin/versions/4.2.1`；交付补记随后的文档提交同步，详见 [框选交付记录](2026-11-06-marquee-selection.md)。

## 已进入当前源码的原功能修改与增强

| 编号 / 主题 | 已有行为变化 | 主要源码落点 | 记录与当前边界 |
| --- | --- | --- | --- |
| CUSTOM-010 批量编辑 | 仅应用明确修改字段，保留其他字段并兼容撤销 | `editing_commands.py`、`label_widget.py`、`widgets/label_dialog.py` | [历史台账](CATALOG-20261030.md)；已提交，不在本轮重新全面验收 |
| CUSTOM-011 数字键与模式 | 数字绘制/改标顺序、多选改标、创建/编辑状态衔接 | `label_widget.py`、settings 配置和动作 | [历史台账](CATALOG-20261030.md)；特定错存类别问题仍有未实施任务，见下 |
| CUSTOM-012 选择一致性 | 命中优先级、隐藏/聚焦及锁定行为 | `widgets/canvas.py`、`widgets/rectangle_edge.py` | [历史台账](CATALOG-20261030.md) |
| CUSTOM-013 标签显示 | 仅显示选中对象标签，悬停可预览 | `widgets/canvas.py`、配置与菜单 | [历史台账](CATALOG-20261030.md) |
| CUSTOM-014 窗口密度 | 按外层窗口尺寸判断；四极值提交/取消回归修复 | `label_widget.py`、矩形创建控制器 | [历史台账](CATALOG-20261030.md) |
| CUSTOM-002 标注加载 | 目录扫描与搜索后台化，分阶段列表/标注/审核回填，导航保存并发和 EXIF 生命周期 | `label_widget.py`、`utils/staged_annotation_loading.py`、`utils/file_search.py`、`utils/async_exif.py` | [实现归档](2026-10-30-staged-loading.md) |
| CUSTOM-003 拖动性能 | 状态栏取消全数据集遍历，合并拖框/顶点/立方体拖动绘制 | `label_widget.py::show_shape`、`widgets/canvas.py::mouseMoveEvent` | [修复与验收](2026-10-30-canvas-dragging.md)；已有历史测试及用户体验确认 |
| 用户配置持久化 | 按字段提交、冲突/失败恢复、临时预览回滚、数字绑定与运行时同步、重启恢复、测试配置隔离 | `user_config.py`、`config.py`、`settings/`、`label_widget.py`、模型管理入口 | [验证](../../openspec/changes/fix-user-settings-persistence/verification.md)；代码已保存，真实终端原启动方式人工验收未完成 |

上表省略统一前缀 `anylabeling/views/labeling/`；`user_config.py`、`config.py` 位于 `anylabeling/`。

## 已进入当前源码的扩展与迁移能力

| 编号 | 能力 | 主要源码落点 | 状态 / 记录 |
| --- | --- | --- | --- |
| CUSTOM-101 | Shift 单点拟合矩形、Shift+Alt 同侧角锚定 | `widgets/point_fit.py`、`rect_edge_click.py` | 11-06 按键刷新与小框防跳修复用户验收通过、132 项 Qt 回归通过，已提交并同步；[操作说明](../zh_cn/rectangle_point_fit.md) · [实施记录](2026-11-02-rectangle-preview-overlap-plan.md) |
| CUSTOM-102 | 矩形边命中与拖边调整 | `widgets/rectangle_edge.py` | 已有代码；[历史台账](CATALOG-20261030.md) |
| CUSTOM-103 | 两点矩形创建十字线、创建/拟合共边预览避让 | `widgets/rectangle_crosshair.py`、`rectangle_preview.py` | 自动化有证据，真实屏幕验收未全完成；[预览修复](2026-11-02-rectangle-preview-overlap-plan.md) |
| CUSTOM-104 | 四极值画框及创建模式管理 | `widgets/rectangle_creation.py`、`widgets/rectangle_extreme.py` | 已有代码；[历史台账](CATALOG-20261030.md) |
| CUSTOM-105 | 持久对象身份、复制新身份、加载/保存校验 | `shape_identity.py`、`shape.py`、`label_file.py` | 已有代码；涉及标注对象身份字段 |
| CUSTOM-106 | 组合对象筛选、聚焦、反选、保留手动隐藏 | `shape_filter.py`、`label_widget.py` | 已有代码；[历史台账](CATALOG-20261030.md) |
| CUSTOM-107 | 矩形实时尺寸、最小尺寸规则与提示布局 | `rectangle_size/`、`widgets/rectangle_size_overlay.py`、规则窗口 | 已有代码；[历史台账](CATALOG-20261030.md) |
| CUSTOM-108 | 同尺寸图片共享缩放和中心点、重置入口 | `shared_view_state.py`、`label_widget.py` | 已有代码；[历史台账](CATALOG-20261030.md) |
| CUSTOM-109 | Inspector：方案/规则、扫描进度、重复框与质量检查、问题队列、定位/复查/会话恢复 | `anylabeling/services/inspection/`、`inspector/`、`label_widget.py` | 已提交，代码/自动化 52/55，3 项人工验收保留；[最新验证](../../openspec/changes/refactor-data-inspector-workflow/verification.md) |
| CUSTOM-110 | Dense Review：批次/逐框复核、比较卡片、空间查漏、确认与保存恢复、虚拟化及后台缩略图 | `anylabeling/services/dense_review/`、`dense_review/`、画布集成 | 已提交，专项功能/性能有证据，真实人工试用和完整组合回归未全完成；[11-05 实施](../../openspec/changes/add-dense-annotation-review-workflow/implementation-20261105.md) |
| CUSTOM-112～116 | 可视化工具栏、滚轮导航、三态审核、仅填充透明度、透明度/亮度/对比度跨图保持 | `widgets/canvas.py`、`canvas_adjustment.py`、`toolbar.py`、`shape.py`、`label_widget.py`、settings | 已提交，专项和配置自动联测通过；[最新实施](../../openspec/changes/restore-v430-canvas-controls/implementation-20261105.md)，性能与真实屏幕验收未全完成 |
| CUSTOM-117 | Ctrl + 左键框选多目标，部分覆盖即选中，连续操作状态保护 | `widgets/canvas.py`，两份新测试及既有拖动测试调整 | 已验收，`c58e16b6` 已提交并同步；交付专项 41 项通过，历史相关回归 225 项及 6 个子测试通过、1 项旧窗口测试排除；[实现与交付记录](2026-11-06-marquee-selection.md) |

上述多数能力源于旧个人修改版迁移或已有能力增强，不表示本次新开发，也不表示各功能都已完整人工验收。

## 尚不能作为完成能力列出的项目

| 项目 | 当前事实 | 记录 |
| --- | --- | --- |
| CUSTOM-001 统计总览/标签管理器后台扫描与进度 | 诊断及方案存在，尚未实施；与已经实现的 Inspector 扫描进度是不同入口 | [方案](2026-10-29-dataset-scan-progress.md) |
| CUSTOM-111 修正成本统计 | 部分服务、计时和 hooks 已保存；控制器/面板/报告窗口与完整集成尚缺，入口有开发状态门控 | [状态记录](2026-11-03-correction-cost-statistics.md) |
| 数字矩形特定错存标签修复 | 已登记修复任务，全部实施任务尚未勾选；测试仍有严格 xfail，不能说已修复 | [任务](../../openspec/changes/fix-digit-rectangle-label-save/tasks.md) |
| 旧版双屏、SQLite 索引、完整旧质检/行为分析 | 不能因为旧项目存在就视为全部进入当前版本；Inspector 仅采用已登记算法与协议 | [历史范围说明](CATALOG-20261030.md)、[Inspector 迁移来源](2026-11-02-inspector-workflow.md) |

## 记录完整性

当前有四类记录：本目录的功能台账/实现记录、`openspec/changes/` 中的规格与任务、`tests/` 和 `reports/` 中的验证证据、Git 提交与恢复节点。11-06 本次框选已补入总索引并登记用户人工确认。

仍存在历史文档滞后：10-30 台账和部分实施记录开头保留了“尚未提交”“旧通过数”等当时状态。11-05 同步已将这些源码保存进 Git；本次更新总索引并给出最新证据入口，没有把旧验收待办统一勾成完成。部分历史功能同处混合快照，不能假定每项都存在可独立回退的提交；迁移或回退应按功能精确差异处理。

本次整理已将剩余框选改动与资料归集提交，并同步工作分支及版本入口。已补跑 41 项交付专项并保存 JUnit 证据；没有运行新的全项目测试，也没有发布安装包。
