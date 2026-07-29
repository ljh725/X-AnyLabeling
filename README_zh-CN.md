<div align="center">

# X-AnyLabeling · 个人扩展版

### 数据质量检查 · 画布交互优化 · 姿态标注工作流

[![License](https://img.shields.io/badge/License-LGPL%20v3-blue.svg)](./LICENSE)
[![Python](https://img.shields.io/badge/python-3.11+-aff.svg)](https://www.python.org/)
[![PyQt6](https://img.shields.io/badge/GUI-PyQt6-green.svg)](https://www.riverbankcomputing.com/software/pyqt/)
[![Upstream](https://img.shields.io/badge/upstream-CVHub520-orange.svg)](https://github.com/CVHub520/X-AnyLabeling)

**[English](README.md)** | **[简体中文](README_zh-CN.md)**

</div>

---

> 本仓库是 [CVHub520/X-AnyLabeling](https://github.com/CVHub520/X-AnyLabeling)（beta.4）的个人 fork。
> 我在原版基础上扩展了 **6 个功能模块**，聚焦于**数据质量检查、画布交互优化、姿态标注工作流**。
> [原版 upstream README 保留在此](README_upstream_zh-CN.md)。

```
CVHub520/X-AnyLabeling (upstream, beta.4)
        │  fork
        ▼
ljh725/X-AnyLabeling  ← 本仓库（93 commits / ~1.5 万行扩展代码）
```

| 维度 | 数据 |
|------|------|
| 提交数 | **93**（相对 upstream main） |
| 新增代码 | **~15,000 行**（功能代码 + 测试） |
| 测试用例 | **230+**（功能相关） |
| 设计文档 | **116 篇**（`docs/` 目录） |
| 功能模块 | **6 个** |

---

## 功能矩阵

| # | 模块 | 代码规模 | 测试 | 核心价值 | 详述 |
|---|------|---------|------|---------|------|
| 1 | **L1/L2 质检引擎** | 4,354 行 / 12 文件 | 148 | 12 条几何/视觉关系规则 + face→head→person 跨类匹配，纯 Python（零 PyQt 依赖），CLI/UI 共享同一份逻辑 | [→ 01](docs/portfolio/01-quality-engine.md) |
| 2 | **Inspector 数据检查面板** | 3,785 行 / 10 文件 | 60+ | 5-Tab 质检工作台、插件化规则引擎、点击问题即跳转 Canvas，标注-质检闭环内化 | [→ 02](docs/portfolio/02-inspector-panel.md) |
| 3 | **优先级排序拾取模式** | ~90 行核心算法 | 6 | 「决策转排序」范式：4 维优先级元组取代 if-elif 链，解决密集/嵌套标注选错痛点 | [→ 03](docs/portfolio/03-selection-optimization.md) |
| 4 | **矩形边编辑** | 407 行几何 + ~250 行 canvas | 21 | 独立拖动矩形单条边，几何层/UI 层严格解耦，反翻转 clamp 保证矩形永不坍塌 | [→ 04](docs/portfolio/04-rect-edge-edit.md) |
| 5 | **Pose View 标签解耦** | 1,994 行 / 9 文件 | 36 | filter-driven 单字段解耦标签列表与选中焦点，4 种防遮挡布局算法，总览/选中两态显示 | [→ 05](docs/portfolio/05-pose-view.md) |
| 6 | **数据处理脚本集** | 40 个脚本（核心逾 3,000 行） | — | YOLO Pose 三步流水线 + ViTPose 预标注对比 + 质检 CLI，覆盖姿态数据生产全链路 | [→ 06](docs/portfolio/06-data-toolkit.md) |

---

## 模块亮点

### 1. L1/L2 数据质检引擎

**痛点**：姿态标注数据集通常包含 face（人脸框）、head（头部框）、person（人体框）三类对象，外加 COCO 17 关键点。人工逐张检查它们的几何关系（face 是否在 head 内、head 是否在 person 上端、关键点是否越界）成本极高，且规则难以复用。

**方案**：一套纯 Python 的双层质检引擎——L1 检查 JSON 结构合法性，L2 用 12 条几何/视觉规则评估跨类关系，配 face→head→person 跨类匹配算法（硬过滤 + 加权打分）和阈值评估系统。

**亮点**：
- 🏗️ **纯 Python / PyQt 严格分层**：`quality/` 12 个文件 **0 个 PyQt import**，可在无显示器 CI 环境直接跑批，CLI 与 UI 共享同一份逻辑
- 🎯 **12 条 L2 规则**：L2-01 face 匹配 head、L2-03 face/head 面积比、L2-06 head/person 空间位置、L2-09 关键点越界、L2-12 图级密度异常……
- 🔗 **跨类匹配**：face→head（严格，5 条硬过滤 + 4 维打分）/ head→person（宽松，4 条硬过滤 + 5 维打分），三角函数峰值衰减做平滑评分
- ⚖️ **阈值评估**：4 种 direction + `error_requires` 二次确认降级（error 命中但确认条件不满足时自动降级为 warning）
- 💡 **阈值建议**：9 级优先级触发表，基于人工复核统计产出非约束性建议（永远 pending，不自动改配置）

📊 数据：4,354 行 · 148 测试用例 · [详细文档 →](docs/portfolio/01-quality-engine.md)

---

### 2. Inspector 数据检查面板

**痛点**：原工作流是「标注 → 导出 JSON → 外部 Python 脚本检查 → 手动定位问题文件 → 逐张打开修复 → 再导出 → 再检查」，质检闭环在外部脚本，发现的问题无法直接跳转回标注位修复。

**方案**：一个 5-Tab 的 QDockWidget 工作台（数据检查 / 质检复核 / 数据表格 / 规则配置 / 导出），把外部脚本能力搬进标注工具，点击问题点直接跳转 Canvas 上的 shape。

**亮点**：
- 🧩 **插件化规则引擎**：`ValidationRule` ABC + `check`/`check_all` 双层级，新增规则零侵入
- 📋 **8 条内置规则**：标签白名单、group_id 唯一性、person 框必须有 gid、label-shape 绑定、关键点完整性……
- 🔁 **信号契约复用**：质检复核 Tab 复用既有 `issue_navigate_requested` 通路，**父级 LabelingWidget 零改动**即可接入新功能
- 🗂️ **三维内存索引**：`FlatIndex` 的 `_by_file/_by_label/_by_group` 支撑 500~1000 文件/批次扫描

📊 数据：3,785 行 · 60+ 测试用例 · [详细文档 →](docs/portfolio/02-inspector-panel.md)

---

### 3. 优先级排序拾取模式

**痛点**：密集/嵌套标注场景（多框堆叠、关键点压在矩形上、大背景框套小目标框）下，旧的 `reversed + 首次命中` 策略只能选到"最后创建且整体命中"的对象，经常选错或选不到想要的对象。

**方案**：「决策转排序（Decision → Sort）」范式——对每个候选 shape 计算 4 维优先级元组，按字典序排序，让"抓顶点 > 抓边 > 抓小对象 > 抓栈顶"在排序中自然生效。

**核心算法**：

```python
# canvas.py:515-523 — 优先级 priority = (级别, 距离, 面积, -stack_index)，升序(越小越优先)
#   级别 0: 附近顶点(可抓取编辑点)——最高优先
#   级别 1: 附近可编辑边(可双击加点)
#   级别 2: 整体命中(contains_point)——兜底
#   同级别下: 距离更近者优先；仍相同时面积更小者优先(嵌套场景下小对象优先)；
#     最后后创建者(栈顶)优先。
```

**亮点**：
- 🎯 **4 维优先级元组**：`(级别, 距离/面积, 面积, -stack_index)`，零 if 分支
- 🧠 **面积当"具体性"代理**：嵌套场景下小对象面积小自然排前面
- 🔁 **三入口统一复用**：悬停高亮、点击选择、双击编辑都取排序后的首个候选
- 🧪 **纯算法可单测**：6 个场景在无 PyQt 环境下验证

📊 数据：~90 行核心算法 · 6 场景测试 · [详细文档 →](docs/portfolio/03-selection-optimization.md)

---

### 4. 矩形边编辑

**痛点**：标注矩形时经常需要精修某条边（贴合图像边界、对齐相邻框），但原生编辑只能拖角点——拖角点会同时改变两条边，破坏另一方向的对齐。

**方案**：独立选中并拖动矩形的任意一条边（左/右/上/下），保留其他三条边不变。几何计算层与 Canvas UI 层严格解耦。

**反翻转 clamp**（矩形拖过头也不会坍塌）：

```python
# rect_edge_alignment.py:320-370
if edge_name == RECT_EDGE_LEFT:
    x_min = min(coord, x_max - min_size)      # 不会超过右边
elif edge_name == RECT_EDGE_RIGHT:
    x_max = max(coord, x_min + min_size)      # 不会低于左边
elif edge_name == RECT_EDGE_TOP:
    y_min = min(coord, y_max - min_size)
elif edge_name == RECT_EDGE_BOTTOM:
    y_max = max(coord, y_min + min_size)
```

**亮点**：
- 📐 **几何层/UI 层解耦**：`RectEdgeRef` 只是临时编辑句柄，**绝不写回 JSON/不进 Shape.other_data**
- 🛡️ **反翻转 clamp**：`min < max` 永远成立
- 🔄 **Canvas 状态机**：hover → 按下选中 → 实时改坐标 → 松开提交 → Esc 取消恢复
- 🔒 **绘制模式双向互斥**：进 create 模式自动关闭边编辑，反之亦然
- 📝 **诚实呈现**：经历了「边对齐（吸附参考边）→ 简化为边编辑」的演进，文档如实记录

📊 数据：407 行几何 + ~250 行 canvas · 21 测试用例 · [详细文档 →](docs/portfolio/04-rect-edge-edit.md)

---

### 5. Pose View 标签解耦

**痛点**：开启 Pose View 后渲染器完全接管整张图，普通矩形/多边形标签被隐藏，"分割感"强；且选中某人会污染普通标签流程的选中态。

**方案**：filter-driven 架构——用单一字段 `pose_focus_group_id` 驱动标签列表与选中焦点的解耦；按 shape 类型过滤而非模式切换，让 Pose View 与原生标签共存。

**亮点**：
- 🎛️ **filter-driven 单字段解耦**：`pose_focus_group_id` 一个字段驱动总览/选中两态切换，不污染原生选中流程
- 📐 **4 种防遮挡布局**：direct / anti（优先级排序消重叠）/ column（四象限垂直堆叠）/ category（按部位分组）
- 👁️ **总览/选中两态显示**：总览态 person 分色看全景，选中态显示骨架+标签+引线看细节
- 🧱 **纯模块优先原则**：`pose_constants`/`pose_config`/`pose_layout` 零 QWidget 依赖，可独立单测
- 🔧 **事件来源区分**：Keypoint Fill 模式的程序性空选中用 `is_active` 守卫，避免误清聚焦

📊 数据：1,994 行 / 9 文件 · 36 测试用例 · [详细文档 →](docs/portfolio/05-pose-view.md)

---

### 6. 数据处理脚本集

**痛点**：姿态数据生产是一个完整链路（标注 → 格式转换 → 数据集划分 → 可视化核验 → 模型预标注对比 → 规则质检），每一步都需要专门工具，散落各处难以维护。

**方案**：40 个统一 `argparse` CLI 风格的脚本，覆盖姿态数据生产全链路，与规格文档、Inspector 队列深度集成。

**代表脚本**：
- 🔄 **YOLO Pose 三步流水线**：`step1-convert_json_to_yolopose.py`（604 行）→ `step2-split_yolov8pose_dataset.py` → `step3-visualize_yolo_dataset.py`
- 🤖 **ViTPose 预标注对比**：按 group_id 注入预测关键点，用模型预测反查人工标注盲点
- ✅ **质检 CLI**：`run_l1l2_qc.py`（输出 review.tsv + report.json）、`gen_threshold_suggestion.py`
- 📊 **数据集统计/对比**：唯一 label 提取、stem 对比、shape 统计

📊 数据：40 个脚本（核心逾 3,000 行） · [详细文档 →](docs/portfolio/06-data-toolkit.md)

---

## 技术栈

| 层 | 技术 |
|----|------|
| GUI 框架 | PyQt6（QMainWindow / QDockWidget / QGraphicsView） |
| 质检引擎 | 纯 Python（stdlib + PyYAML），零 PyQt 依赖 |
| 配置驱动 | YAML 阈值 profile + 21 项 pose_view 配置键 |
| CLI 工具 | argparse + ProcessPoolExecutor + tqdm |
| 测试 | pytest + unittest，headless Qt（`QT_QPA_PLATFORM=offscreen`） |
| 代码质量 | black（line 79）+ flake8（max complexity 18）+ Google docstring |

---

## 完整作品集

如需架构图、带 `file:line` 可点击链接的代码片段、以及更深的技术解读：

- 📄 **[作品集主页 English](docs/PORTFOLIO_EN.md)** · **[中文](docs/PORTFOLIO.md)**
- 📁 **[6 个模块深度文档](docs/portfolio/)** — 每篇含痛点/架构图/技术亮点/代码定位/测试覆盖
- 📚 **[116 篇设计文档](docs/)** — 方法论、模式卡片、重构计划

---

## 设计方法论沉淀

实现这些功能时，我把可复用的设计决策记录成了「模式卡片」和设计文档：

- [PATTERN_CARD_001 决策转排序](docs/meth-050_note_模式卡片001_决策转排序.md)——把多重 if-elif 决策转成可比较的元组排序
- [filter-030_des_筛选状态引擎模式.md](docs/filter-030_des_筛选状态引擎模式.md)——单字段驱动状态机模式
- [canvas-020_des_canvas重构方案.md](docs/canvas-020_des_canvas重构方案.md)——Canvas 分析与重构方法论

---

## 致谢

- [CVHub520/X-AnyLabeling](https://github.com/CVHub520/X-AnyLabeling)——优秀的开源标注工具，是本 fork 的基础
- 原版 upstream README 保留在 [README_upstream_zh-CN.md](README_upstream_zh-CN.md) / [README_upstream.md](README_upstream.md)
