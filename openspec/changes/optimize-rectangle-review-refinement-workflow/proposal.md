## Why

矩形框审核中的主要操作瓶颈不是边界看不清，而是舒适的鼠标位移（约 5–8 屏幕像素）与实际所需修正（约 2–5 图像像素）不匹配，导致标注员必须频繁放大、平移或持续用力控制手腕。现有精修降速、矩形边拖动、滚轮编辑和键盘移动尚未形成低认知、低疲劳的统一工作流，也缺少可量化验证优化是否有效的单框级指标。

## What Changes

- 以 5 个顺序阶段交付矩形审核精修工作流：
  1. **P0-1**：用“最大图像位移/屏幕像素”替代当前随 zoom 正向增加的降速倍率，使低倍视图得到更强精修帮助；矩形边拖动默认精修，整框拖动保持普通速度。
  2. **P0-2**：对明确激活的矩形边提供滚轮和键盘 1px/5px 离散微调，统一边选择、步进、撤销和几何约束。
  3. **P1-1**：增加活动边、原始边、实时位移量、坐标和矩形尺寸反馈，明确提交、取消和约束拒绝结果。
  4. **P1-2**：让审核精修状态在连续矩形和切图流程中按可预测规则保持，减少重复开关、修饰键长按和鼠标/键盘往返。
  5. **P2**：提供可选局部放大观察和一次性边缘候选预览；候选必须由用户确认，禁止实时自动吸附。
- 新增横切的本地效率指标组件，在阶段 1 前建立采集骨架，并随 5 个阶段持续接入和验收：记录单框耗时、缩放次数、拖动反向修正次数和撤销次数。
- **BREAKING（交互默认值）**：单个已选矩形的边拖动将默认采用精修增益；`Shift` 临时切换为普通速度。旧的“按住 Ctrl 才精修”仍可作为兼容入口，但不再是审核主流程。
- **BREAKING（配置语义）**：旧 `canvas_precision_mode: zoom` 的“缩放越大、降速越多”语义将迁移为基于目标控制增益的配置；旧键仅做兼容读取并给出迁移提示。
- 所有指标仅写入独立的本地度量文件，绝不写入标注 JSON、shape、undo 快照或数据质检报告；采集失败不得阻塞画布交互。

## Capabilities

### New Capabilities

- `review-edge-precision-gain`: P0-1，定义低倍视图下稳定、可预测的矩形边精修增益和粗细速度切换。
- `review-edge-discrete-nudging`: P0-2，定义活动矩形边的滚轮/键盘 1px 与 5px 微调、撤销合并和几何约束。
- `review-edge-adjustment-feedback`: P1-1，定义边高亮、原边参照、位移/坐标/尺寸反馈以及提交、取消和拒绝提示。
- `review-refinement-session-continuity`: P1-2，定义精修状态在选框、连续审核、切图和输入设备切换时的保持与退出规则。
- `review-edge-assistance`: P2，定义可选局部放大和需确认的一次性边缘候选，明确禁止实时自动吸附。
- `review-refinement-telemetry`: 横切能力，定义单框审核 episode、耗时、缩放、拖动反向修正和撤销指标的本地采集、隐私、容错和导出契约。

### Modified Capabilities

无。当前主规格中没有矩形审核精修相关 capability；本变更以 6 个新 capability 建立正式行为契约，并在设计中说明与历史 change artifacts 的迁移关系。

## Impact

- **核心画布**：`anylabeling/views/labeling/widgets/canvas.py` 的矩形边命中、拖动、滚轮、键盘分发、绘制反馈和撤销边界。
- **标签工作流**：`anylabeling/views/labeling/label_widget.py` 的缩放、切图、选择、状态栏、设置应用和审核 episode 生命周期。
- **交互状态/几何**：`rect_edge_interaction.py`、`rect_edge_alignment.py`，以及建议新增的纯 Python 精修增益、离散微调和指标模型 helper。
- **配置与设置**：`xanylabeling_config.yaml`、settings schema/runtime applier、用户配置迁移和用户可见文案。
- **本地度量**：新增按 schema version 管理的 JSONL episode 日志及可选汇总导出；默认显式启用、本地保存、无网络发送。
- **测试**：增加纯 Python 增益/计数/episode 测试、PyQt 画布交互测试、设置迁移测试和分阶段人工 A/B 验收。
- **兼容性**：不改变标注 JSON 结构，不改变 auto-labeling 输出，不让统计数据进入 dirty/undo，不依赖图像内容上传或外部服务。
