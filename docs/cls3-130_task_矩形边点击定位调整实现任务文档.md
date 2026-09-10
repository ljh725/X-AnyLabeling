# 矩形边点击定位调整实现任务文档（cls3-130 · r3）

日期：2026-09-09。r3 将 r2 伪代码落实为代码分层，修正生命周期、双击和最小尺寸边界。配套设计为 cls3-120 r4。

## 1. 文件与职责

| 文件 | 职责 |
|---|---|
| anylabeling/views/labeling/rect_edge_click.py | 无 Qt 的四区域算法、外围范围、死区半宽、单坐标提案 |
| anylabeling/views/labeling/widgets/rect_edge_click_controller.py | Qt 输入适配、点击锁、预览、提交、提示和双击防护 |
| anylabeling/views/labeling/widgets/canvas.py | 在现有鼠标、键盘、清理、绘制入口调用控制器 |
| anylabeling/views/labeling/widgets/rectangle_workflow.py | 工作台入口提示更新；沿用现有微调按钮和反馈 |
| anylabeling/resources/translations/{en_US,zh_CN,ja_JP,ko_KR}.ts | 四语言消息与引导；编译生成 qm/resources.py |
| tests/test_rect_edge_click.py | 无 Qt 几何用例和固定种子性质检验 |
| tests/test_rect_edge_click_canvas.py | 真实 Qt 事件、预览、提交、拖动和取消 |
| tests/test_rectangle_workflow.py | 完整窗口中的 dirty、反馈、撤销与微调分组 |

采用独立 Qt 控制器，避免继续扩大 Canvas；不修改 RectEdgeInteractionController 的阶段定义。

## 2. 纯几何接口

- classify(box, point, scale) → ClickDecision：退化/非有限几何 → 有限范围 → 对角线窄带 → 四区域。
- effective_box(box)：宽高各 2 倍的同中心外围矩形。
- dead_band_half_width(box, scale)：min(6/scale, 0.05×短边)，原图单位。
- proposed_box(box, edge, point)：只替换一个原始坐标，不 clamp、不取整。
- box 顺序为 (left, top, right, bottom)，point 为 (x, y)。

反例：box=(100,100,200,300)、point=(120,20) 判上边；不会因距左边所在直线更近而误判。

## 3. 事件接线

### 悬停

在原有边悬停循环之前调用控制器。激活且落于操作范围内时独占候选提示；死区清候选边和虚线。每次鼠标移动都更新预览，即使候选边名称未变。普通状态、原顶点手柄或操作范围外回落原有逻辑。

### 按下与晋级

在原边命中分支前分类。有效点击创建 ClickLock，保存 RectEdgeRef、原框、原始顶点快照、按下位置，并调用已有 begin_pending。

move 前复核锁定对象与顶点快照；通过后沿用现有 pending 晋级为拖动。_start_rect_edge_drag 交接锁并撤掉点击预览。原有阈值、精修增益和拖动恢复不复制实现。

### 松开与撤销

先处理点击锁，再进入原拖动释放路径。若释放位置已移动但没有收到 move 事件，补做拖动晋级与最终坐标更新。

静止点击以按下位置生成提案，严格验证完整框，再执行已有 apply_edge_coord。仅有实际变化时发 started、几何通知、一次 store_shapes、shape_moved、delta、committed feedback 和 finished。反馈使用刷新后的边坐标，提交后不保留活动边；微调 burst 重置，避免跨点击合并撤销。

### 清理与双击

- clear_rect_edge_alignment 是公共取消入口，清除锁、预览、源对象、指针和双击记录。
- 取消中的 press 对应 release 必须被消费，不能穿透到旧选择/编辑流程。
- 成功提交后再记录双击时间，避免先写记录又被公共清理擦除。
- 双击使用同对象、Qt 双击时间、屏幕位置邻近三个条件，也覆盖原生 MouseButtonDblClick。
- Alt 按下/释放刷新提示，不必再移动一次鼠标；离开画布撤掉参照线。

## 4. 对 r2 模板的必要修正

1. 最小尺寸不是不可达分支：窄框缩小仍可能不足 1px，须在 mutation 前拒绝，预览同样拒绝。
2. 不用“同对象短时间内全部点击无效”的全局节流，否则快速修两条不同边会被拦截。
3. source geometry 需快照复核，不能仅判断 shape 仍在列表内。
4. 死区拒绝必须消费后续 move/release，避免静默触发整框移动或选中切换。
5. 旧顶点拖动保留优先权；贴边非顶点位置按区域提交。
6. 反馈使用更新后边坐标，提交后工作台按钮不残留“已武装”状态。

## 5. 执行与验证

- [x] 实现纯几何模块与测试。
- [x] 实现 Canvas 最小接线、独立 Qt 控制器、单次撤销和状态清理。
- [x] 补齐预览、图像边界、最小尺寸、双击和普通模式回落。
- [x] 同步四语言文案、编译资源、同步设计和使用说明。
- [x] 完成最终集成回归、格式/lint 检查并记录结果。

验证记录（2026-09-09）：

- 新增定向用例：63 passed（纯几何 33、画布事件 26、完整工作台点击 4）。
- 原有回归：124 passed，范围为 test_rect_edge_canvas_semantics、test_rectangle_workflow 原有用例、test_rect_edge_alignment、test_rect_edge_state_models；8 条已有 NumPy cross 弃用警告，无失败。
- 本次受影响的 7 个 Python 文件 Black 检查及 Flake8 通过；git diff --check 通过。
- OpenSpec 严格校验通过；四语言编译资源均可从 Qt 资源路径加载，并包含新增提示。
- 离屏画布预览几何已渲染检查；真实窗口测试覆盖 dirty、单次撤销、微调分组、浮点空操作与保存重载。
- Qt 测试使用项目指定 conda 解释器；因沙箱内 Qt DLL 访问受限，经授权在沙箱外执行。

本次代码任务 4/4 完成；所属 OpenSpec 变更共 30 项，完成 27 项，剩余为原有 3 项人工试点。

人工速度和质量试点仍在 OpenSpec 变更第 6 节中待执行，不以自动化通过代替人工收益结论。
