# docs/ 文件分类清单

> 生成日期：2026-07-07
> 范围：`docs/` 目录下全部文件（含子目录）
> 用途：本清单**只做分类建议，不移动任何文件**。后续若要落地整理，按此清单执行 `git mv` 即可。

---

## 一、现状

`docs/` 根目录平铺 **67 个 markdown**，主题混杂（质检 / 姿态 / 选择筛选 / Canvas / 矩形边对齐……）。
此外有若干语义不一致的子目录与杂物：

| 现存项 | 性质 | 问题 |
|--------|------|------|
| `en/` `zh_cn/` | X-AnyLabeling 官方用户文档（多语言） | 与二次开发文档混在一起 |
| `Document-Index/` | 自整理的二次开发文档索引 | 本身结构良好，但未涵盖根目录 67 篇 |
| `superpowers/` + `superpowers-readme.md` + `openspec-README.md` | **第三方**方法论工具的 README | 非本项目内容 |
| `arch-020_note_文件名差异报告.txt` | 一次性文件名比对报告 | 历史归档 |
| `__pycache__/` | Python 字节码缓存 | **不该出现在 docs/**，应删除并加 `.gitignore` |
| `dataset_filter_index.py` | **源码**（SQLite 索引缓存） | 不应放在文档目录 |

---

## 二、推荐目录结构

```
docs/
├── 00_index/                      ← 原 Document-Index/ 改名（放最前，做总目录）
├── user_guide/                    ← 原 en/ + zh_cn/（官方用户文档）
│
├── external/                      ← 第三方工具/方法论（非本项目内容）
│   ├── openspec-README.md
│   ├── superpowers-readme.md
│   └── superpowers/
│
├── features/                      ← 按功能模块分组（本项目二次开发文档）
│   ├── quality_check/             ← L1/L2 质检（13 篇）
│   ├── rect_edge_align/           ← 矩形边对齐/编辑（7 篇）
│   ├── pose/                      ← 姿态视图相关（12 篇）
│   ├── selection_filter/          ← 选择/筛选系统（12 篇）
│   ├── canvas/                    ← Canvas 分析与重构（4 篇）
│   ├── inspector/                 ← Inspector 面板（3 篇）
│   └── misc_fixes/                ← 零散修复/优化（4 篇）
│
├── methodology/                   ← 问题建模/prompt/上下文净化等方法论（7 篇）
├── testing/                       ← 测试矩阵（1 篇）
└── _archive/                      ← DEVELOPMENT_LOG、filename_compare_reports 等历史产物
```

---

## 三、逐文件归属

### 1. `user_guide/`（官方用户文档，原 `en/` + `zh_cn/`）

| 文件 | 说明 |
|------|------|
| `en/`（目录，9 篇） | 英文用户手册：get_started / user_guide / cli / custom_model / model_zoo / image_classifier / paddle_ocr / vqa / chatbot |
| `zh_cn/`（目录，10 篇） | 中文用户手册（比英文多一篇 faq） |

### 2. `external/`（第三方工具/方法论，非本项目）

| 文件 | 说明 |
|------|------|
| `openspec-README.md` | OpenSpec 工具的 README（Fission-AI/OpenSpec） |
| `superpowers-readme.md` | Superpowers 方法论工具的 README |
| `superpowers/`（目录） | Superpowers 的 plans/specs，含 pose-view、rename-pred-jsons 两项 |

### 3. `00_index/`（原 `Document-Index/`，自整理索引）

| 文件 | 说明 |
|------|------|
| `Document-Index/` 全部 | README + ai_prompt_template / labeling_keyword_guide / custom_extension_prompt_guide / canvas_extension_sync_guide / canvas_refactor_workflow / github_sync_checklist / custom_project_maintenance_strategy / development_habits_checklist / four_widget_summary + feature-records/（11 篇功能记录） |

> 建议改名为 `00_index/` 以排在最前；内部结构保持不动。

### 4. `features/quality_check/`（L1/L2 质检，13 篇）

| 文件 | 说明 |
|------|------|
| `qc-010_des_三阶段目标框质量校验方案.md` | 三阶段校验总体方案 |
| `qc-020_note_目标框准确度治理建模.md` | person/head/face + pose 质量治理建模 |
| `qc-030_spec_l1_l2目标框质量校验规则规格表.md` | L1/L2 规则规格表 |
| `qc-040_spec_v0_阶段一l1_l2质检规则阈值与输出规格.md` | 阈值与输出规格（对应 `configs/quality/l1_l2_threshold_profile_v0.yaml`） |
| `qc-050_des_阶段一l1_l2质检方案_问题建模.md` | 问题建模初版 |
| `qc-051_des_v1_阶段一l1_l2质检方案_问题建模.md` | 问题建模 v1 |
| `qc-060_task_阶段一l1_l2质检实现任务文档.md` | 实现任务拆解 |
| `qc-070_impl_阶段一l1l2质检系统_代码构建说明.md` | 代码构建说明 |
| `qc-080_task_l1_l2质检复核队列功能实现任务文档.md` | 复核队列实现任务 |
| `qc-090_guide_inspector_l1_l2质检复核队列使用说明.md` | 复核队列使用说明 |
| `qc-100_spec_group_id解耦质检规则体系_0703.md` | group_id 解耦后的规则体系调整 |
| `qc-110_note_vitpose模型分歧排序qc方法.md` | 基于 ViTPose 的模型分歧排序质检法 |
| `qc-111_note_v1_vitpose分歧排序质检.md` | ViTPose 分歧排序质检 V1 |

### 5. `features/rect_edge_align/`（矩形框类别：边对齐、边编辑、三框精修，11 篇）

| 文件 | 说明 |
|------|------|
| `cls3-010_task_矩形边对齐功能实现任务文档.md` | 实现任务总文档 |
| `cls3-020_impl_矩形边对齐功能实现报告.md` | 实现报告 |
| `cls3-030_fix_v1_矩形边对齐功能修复报告.md` | 修复报告 v1 |
| `cls3-040_review_v1_矩形边对齐功能审核结论.md` | 审核结论 v1 |
| `cls3-050_summary_矩形边对齐功能说明总结.md` | 功能边界、交互、结构总结 |
| `cls3-060_guide_矩形边级编辑功能说明.md` | 边级编辑功能说明 |
| `cls3-070_guide_矩形边编辑功能说明.md` | 单边编辑能力说明 |
| `cls3-080_des_矩形边编辑暂停恢复设计.md` | 编辑模式暂停与恢复设计 |
| `cls3-090_des_三框精修模式交互与状态机设计.md` | person/head/face 三框精修设计 |
| `cls3-100_review_三框精修模式代码落点审计表.md` | 代码落点审计结论 |
| `cls3-110_review_三框精修模式测试review清单.md` | 测试与验收 review 清单 |

### 6. `features/pose/`（姿态视图，12 篇）

| 文件 | 说明 |
|------|------|
| `pose-010_summary_pose关键点标签显示功能总结.md` | Pose 关键点标签显示功能开发总结 |
| `pose-020_des_pose视图标签解耦方案.md` | Pose View 与原生标签系统解耦方案 |
| `pose-030_des_pose视图标签布局优化方案.md` | 姿态标签布局优化方案 |
| `pose-040_des_pose视图标签拖曳方案.md` | 标签框拖拽功能方案 |
| `pose-050_des_pose视图标签布局表格模型.md` | 姿态标签布局表格化建模 |
| `pose-060_task_pose标签防遮挡html转pyqt6.md` | Pose 标签防遮挡原型 HTML→PyQt6 转换 |
| `pose-070_review_pose标签设计对比建议.md` | Pose 标签设计文档对比与建议 |
| `pose-080_des_pose标签隐藏与自动聚合方案.md` | 标签隐藏与自动聚合模式修改说明 |
| `pose-090_summary_2026-06-16_姿态视图自动聚焦实现.md` | 上述功能实现总结 |
| `pose-100_des_pose标注数据加载优化.md` | Pose 标注数据加载性能优化方案 |
| `pose-110_task_pose加载优化清单.md` | 加载优化任务拆解 |
| `pose-120_impl_pose加载优化代码改造.md` | 加载优化代码改造记录 |

### 7. `features/selection_filter/`（选择/筛选系统，12 篇）

| 文件 | 说明 |
|------|------|
| `filter-010_guide_选中即显功能说明.md` | "选中即显"功能技术文档 |
| `filter-020_spec_形状类型筛选技术规格.md` | Shape Type 分类筛选技术说明 |
| `filter-030_des_筛选状态引擎模式.md` | Filter State + Engine 架构模板 |
| `filter-040_task_筛选结果导航实现计划.md` | 筛选结果导航实现计划 |
| `filter-050_des_json筛选规则检查蓝图.md` | JSON 筛选与规则检查实施蓝图 |
| `filter-060_des_数据集筛选索引设计.md` | 数据集筛选索引（SQLite）设计 |
| `filter-070_guide_exif与筛选索引说明.md` | EXIF 扫描 / 数据集索引 / 全局过滤菜单说明 |
| `filter-080_task_后台扫描手动化清单.md` | 后台扫描手动化任务书 |
| `filter-090_summary_后台扫描手动化总结.md` | 后台扫描手动化功能总结 |
| `filter-100_des_优先级排序拾取模式.md` | 优先级排序拾取模式（选择交互设计模式） |
| `filter-110_spec_优先级元组规范.md` | 优先级元组规范表征 |
| `filter-120_task_复杂对象选择优化迁移计划.md` | 功能 C「复杂对象选择优化」迁移计划 |

### 8. `features/canvas/`（Canvas 分析、重构、事件与视口，8 篇）

| 文件 | 说明 |
|------|------|
| `canvas-010_note_canvas分析报告.md` | Canvas.py 详细分析报告（2026/04/25） |
| `canvas-020_des_canvas重构方案.md` | Canvas.py 拆分重构方案 |
| `canvas-030_note_claudecode_ds_canvas分析.md` | ClaudeCode-DS 对 Canvas.py 的完整分析 |
| `canvas-040_note_opencode_kimi_canvas分析.md` | opencode-kimi 对 Canvas.py 的架构深度分析 |
| `canvas-050_note_鼠标事件处理顺序.md` | Canvas 鼠标事件处理顺序 |
| `canvas-060_des_视口状态管理.md` | Viewport 状态管理设计 |
| `canvas-070_note_缩放中心飘移分析.md` | 缩放中心飘移问题分析 |
| `canvas-080_task_缩放中心飘移修复计划.md` | 缩放中心飘移修复计划 |

### 9. `features/inspector/`（Inspector 面板，3 篇）

| 文件 | 说明 |
|------|------|
| `inspect-010_des_数据检查面板设计.md` | 数据检查面板分阶段实现方案 |
| `inspect-020_guide_inspector面板参考手册.md` | Inspector Panel Reference Manual |
| `inspect-030_spec_inspector外部结果格式.md` | Inspector 外部检测结果导入格式 |

### 10. `features/misc_fixes/`（零散修复/优化，3 篇）

| 文件 | 说明 |
|------|------|
| `keypoint_fill_call_chain.md` | Keypoint Fill Tool 调用链文档 |
| `output_dir_click_lag_analysis.md` | 更改输出目录 + 点击画面卡顿分析 |
| `fix_rect_label_visibility_after_creation.md` | 矩形标注后可见性被筛选刷新影响的修复 |

### 11. `methodology/`（问题建模/prompt/方法论，7 篇）

| 文件 | 说明 |
|------|------|
| `meth-010_guide_问题建模prompt指南.md` | 让大模型成为问题建模伙伴 |
| `meth-011_guide_问题建模prompt指南_重构.md` | 上文的重构版 |
| `meth-020_guide_标注质量方法论prompt指南.md` | 标注质量方法论 prompt 指南 |
| `meth-030_spec_问题重表征通用模板.md` | 问题重表征通用模板 |
| `meth-040_des_问题重表征多目标选择.md` | 问题重表征：多目标选择（与 selection_filter 交叉） |
| `meth-050_note_模式卡片001_决策转排序.md` | 模式卡片 #001：决策转排序 |
| `meth-060_summary_上下文净化摘要.md` | 上下文净化（AI 对话聚焦）摘要模板 |

### 12. `testing/`（测试，1 篇）

| 文件 | 说明 |
|------|------|
| `feature_interaction_test_matrix.md` | 功能交互测试矩阵 |

### 13. `_archive/`（历史产物）

| 文件 | 说明 |
|------|------|
| `arch-010_note_选中即显早期开发记录.md` | Label on Selection 功能早期开发记录（已被各功能文档取代） |
| `arch-020_note_文件名差异报告.txt` | 一次性文件名比对报告 |

---

## 四、待清理项（建议单独处理）

| 项 | 建议 | 理由 |
|----|------|------|
| `__pycache__/`（含 3 个 `.pyc`） | **删除**，并把 `__pycache__/` 加入 `.gitignore` | Python 字节码缓存不属于文档 |
| `dataset_filter_index.py` | **移出 docs/**：确认是否即 `anylabeling/` 中实际使用的源码；若是则移到源码树并删此副本，若仅是参考实现则移到 `_archive/` 或 `tools/` | 文档目录不应放 `.py` 源码 |

> 注：`dataset_filter_index.py` 头部 docstring 表明它是实际功能代码（SQLite 派生索引缓存），需确认与源码树中版本的关系后再处置。

---

## 五、数量统计

| 目标目录 | 文件数 |
|----------|--------|
| `user_guide/` | 2 目录（19 篇） |
| `external/` | 2 md + 1 目录 |
| `00_index/` | 1 目录（原样） |
| `features/quality_check/` | 13 |
| `features/rect_edge_align/` | 11 |
| `features/pose/` | 12 |
| `features/selection_filter/` | 12 |
| `features/canvas/` | 8 |
| `features/inspector/` | 3 |
| `features/misc_fixes/` | 3 |
| `methodology/` | 7 |
| `testing/` | 1 |
| `_archive/` | 2 |
| 待清理 | 1 目录（`__pycache__`） + 1 py |

根目录 67 篇 markdown 全部归位，无遗漏。

---

## 六、落地步骤（确认后再执行）

1. **先清理垃圾**（低风险）：
   ```bash
   rm -rf docs/__pycache__
   echo "__pycache__/" >> .gitignore
   ```
2. **处置 `dataset_filter_index.py`**：先 `git log` 确认其与源码树关系，再决定移走或删除。
3. **按本清单 `git mv`**：保留 git 历史。建议按目录分批提交（一次提交一个目标目录）。
4. **更新链接**：`00_index/README.md` 与各文档内的相对链接（如 `docs/pose-060_task_pose标签防遮挡html转pyqt6.md` 这类引用）需同步更新。
5. **更新本清单**：落地完成后把本文档顶部"不移动任何文件"声明改为"已完成"。
