# 矩形与十字线、拟合预览共边显示调整方案

- 日期：2026-11-02（Asia/Shanghai）；2026-11-04 追加 P2 修复（第七节）。
- 状态：已实施，自动化验证通过；真实屏幕验收未完成（2026-11-02 晚间更新，实施结果见文末第六节；2026-11-04 P2 修复见第七节）。
- 分类：CUSTOM-101 单点拟合、CUSTOM-103 创建十字线的显示修复及配套；不增加新的标注操作。
- 范围：4.2.1 两点矩形创建，以及用户已确认的 Shift / Shift+Alt 单点拟合预览。
- 来源：[beta.4 历史代码与当前定位](../../reports/crosshair_overlap_20261102/README.md)。旧版先画矩形再画十字线可复用，但完整解决共边需要增加局部轮廓避让。
- OpenSpec：`fix-rectangle-preview-overlap`；[提案](../../openspec/changes/fix-rectangle-preview-overlap/proposal.md)、[需求规范](../../openspec/changes/fix-rectangle-preview-overlap/specs/rectangle-preview-rendering/spec.md)、[设计](../../openspec/changes/fix-rectangle-preview-overlap/design.md)、[实施任务](../../openspec/changes/fix-rectangle-preview-overlap/tasks.md)已创建，[实施与验证记录](../../openspec/changes/fix-rectangle-preview-overlap/verification.md)已补充；实施进度以任务清单为准。

## 一、最终显示规则

| 操作 | 原有边框 | 十字线 / 候选框 | 重合处 |
| --- | --- | --- | --- |
| 两点创建矩形 | 预览框的两条固定边保留原有实线 | 青蓝色十字虚线，1.5 屏幕像素 | 随鼠标移动、与十字线共线的两条预览实线不重复画，由十字虚线表示 |
| Shift / Shift+Alt 预览调整 | 原框非共边部分保留原有实线样式 | 新候选框改为 beta.4 的橙色虚线，2 屏幕像素；保留固定角圆点 | 原框与候选框真正共边的线段暂不画原实线，只显示候选虚线 |
| 调整取消 | 完整恢复原框 | 清除候选框和定位点 | 不留缺边和残影 |
| 新建完成 / 调整提交 | 使用现有普通标注框样式 | 清除临时预览 | 正式矩形始终四边完整 |

“十字线最后画”指在创建预览线之后、标签等文字层之前绘制；不把十字线无条件放在所有界面元素之上。已有其他标注对象不因十字线经过而自动缺边。

候选框建议采用 RGBA `(220, 130, 0, 255)`（beta.4 既有值）、DashLine、cosmetic 线宽 2.0；使用完整矩形路径一次描边，避免拆段后每条边的虚线节奏随意变化。新增预览不铺大面积填充。无效候选保留当前红色反馈，不隐藏原框。

若候选几何与原框相同，显示完整原框，抑制多余的候选轮廓；可以保留定位点。不能让“没有发生变化”的悬停把整个原框替换成虚线。

## 二、拟修改文件

| 文件 | 修改职责 |
| --- | --- |
| `anylabeling/views/labeling/rectangle_preview.py`（新增，拟名） | 不依赖 Canvas/Shape 的矩形边段计算与 QPainterPath 构建；统一共边区间、剩余线段和屏幕线宽换算 |
| `anylabeling/views/labeling/shape.py::Shape.paint` | 增加仅本次绘制有效的可选轮廓路径覆盖参数；其他调用继续原样运行 |
| `anylabeling/views/labeling/widgets/canvas.py::paintEvent` | 在绘制开始时获取预览快照；将局部轮廓传给目标原框/创建草稿；调整十字线绘制位置；处理遮罩轮廓的重复绘制入口 |
| `anylabeling/views/labeling/widgets/rectangle_crosshair.py` | 提供当前有效创建引导的轴线信息；拟合有效预览期间抑制原生常驻十字线，避免第三套线混入 |
| `anylabeling/views/labeling/widgets/point_fit.py` | 提供本帧有效目标和候选几何；候选轮廓改橙色；保持既有提交/取消逻辑 |
| `tests/test_canvas/test_rectangle_preview_overlap.py`（新增，拟名） | 共边几何、真实画布像素、预览恢复及数据不变的测试 |
| 现有十字线/单点拟合测试 | 按新显示约定补充场景，保留原有交互语义回归 |

不为此重构整个 `paintEvent()`，不整包复制 beta.4 Canvas。新增模块是显示修复的配套扩展代码，接入点属于现有源码修改。此项无需新增设置、翻译或重新编译资源。

## 三、实现方式

### 1. 统一计算“哪些线段不重复画”

将矩形规范化为 `left, top, right, bottom`，产生四条水平/垂直边。

拟合调整时，对原框四条边与候选框四条边做至多 16 次比较：

1. 只处理同方向、同一条直线上的边；相交但不共线的边正常保留。
2. 共边区间为两个一维区间的交集；只有正长度交集才是需要避让的线段。
3. 从原边扣除交集，保留交集之前、之后的剩余部分，分别用 `moveTo/lineTo` 构建轮廓路径。不能用闭合路径重新连回隐藏段。
4. 浮点容差仅用于判断数值意义上的共线，不能把“离得较近”的两条不同边也隐藏。端点防止线帽露出的让位量按画笔半宽与抗锯齿余量计算，再通过当前缩放换算到图片坐标；让位量不参与命中或坐标计算。

创建矩形时，将草稿边与鼠标所在的水平、垂直引导线比较，剔除共线边，保留另外两边。依据坐标判断，覆盖向左上、右上、左下、右下绘制，不硬编码只隐藏右边和下边。

每帧只计算创建草稿或唯一选中目标，不额外扫描全部标注对象；无有效预览时直接走原有路径。

### 2. 只替换轮廓，不裁掉整个 Shape

拟定兼容接口：

```python
def paint(self, painter, *, outline_path=None):
    # 原有代码仍生成完整 line_path、顶点和其他绘制内容。
    painter.drawPath(line_path if outline_path is None else outline_path)
    # 填充仍使用原来的完整 line_path；顶点仍按原有流程绘制。
```

以上是接口示意，不是完整替换代码。`None` 表示沿用原轮廓；空 QPainterPath 表示确实没有剩余轮廓，不能通过真假判断误回退为完整边框。已有 `shape.paint(painter)` 调用继续兼容。

不在 Shape 上保存临时缺边状态，也不修改 points、line_color、selected、visible 等字段来达成显示效果。局部路径仅通过函数参数传递，预览退出后下帧自然恢复完整轮廓。

Canvas 的 `show_masks` 分支在普通 Shape 之前还会绘制一次矩形轮廓，必须同时应用相同的剩余轮廓路径；填充继续使用完整 mask_path。否则即使修复 Shape.paint，遮罩轮廓仍会从虚线间隙露出。

使用路径避让而非白色/黑色覆盖擦除；不能为隐藏线条而盖住底图，也不对整个 Shape 设置裁剪区，以免连带裁掉填充、顶点和高亮手柄。

### 3. 两点创建的绘制顺序

```text
图片和已有标注
→ 当前矩形预览（共线边不重复画）
→ 青蓝色十字虚线
→ 原有标签、尺寸等界面信息
```

只在现有 `_rectangle_creation_crosshair_enabled()` 为真时应用新路径。用户关闭创建十字线时，矩形预览仍画完整四边。四极值草稿、非矩形创建继续使用原有渲染。

### 4. Shift / Shift+Alt 预览

在 `paintEvent` 开始时读取现有 `_point_fit_target`、`_point_fit_pending_box`，验证目标仍是当前唯一可操作矩形、候选有效且与原框不同，再生成当前帧只读绘制信息。

原框绘制时传入扣除共边后的轮廓；在后面的 `_paint_point_fit()` 中画完整橙色虚线候选框及定位点。两处使用同一帧信息，避免分别计算时出现不一致。

原生常驻十字线当前可能在编辑模式显示，应在有效拟合预览期间暂时让位，预览结束恢复原配置；不要改写用户设置。创建时“两套十字线不同时出现”的既有规则继续保留。

无效候选、目标失效、多选、锁定、目标隐藏、切图或退出模式时不避让原框。沿用现有清理入口，不额外引入新的几何、dirty 或撤销状态。

## 四、实施步骤与验收

1. **先做共边计算与单元验证**：覆盖完全共边、局部共边、相交、不重合、相同矩形及不同拖动象限。
2. **接入创建显示**：恢复先矩形后十字线的顺序，同时去掉草稿重复实线；验证关闭引导后草稿完整。
3. **接入拟合显示**：橙色候选框、原框共边避让、遮罩轮廓一致、常驻十字线让位。
4. **做像素与交互回归**：直接渲染真实 Canvas，检查虚线间隙不露原实线、非共边保留、取消后完整恢复，而不是只断言函数调用顺序。
5. **真实屏幕验收**：在深浅不同背景的图片上分别创建、缩框、扩框，确认细线与橙色虚线可辨识。

测试缩放至少覆盖 0.25、0.5、1、2、4 倍；覆盖小框、图像边缘、四个鼠标象限、Shift 和 Shift+Alt、遮罩开/关、原生常驻线开/关。顶点/固定角标记处单独检查，虚线间隙采样避开这些有意绘制的标记。

每次预览、取消和重绘前后比较坐标、序列化内容及撤销栈，确认没有数据变化；提交仍只产生现有的一次修改，可按原方式撤销。复用现有单点拟合几何、交互、矩形创建和线宽测试。

本项不涉及 14003 个 JSON 的扫描，不加入文件读取或后台任务；新增工作量只与当前矩形的四条边有关。

## 五、迁移与回退

按“共边工具与兼容绘制接口 → 创建接入 → 拟合接入 → 验证和记录”顺序归集修改。共享 Canvas 只纳入本功能相关差异，不覆盖工作区已有 Inspector 等改动。

回退仅撤销本项新增模块、可选接口及对应绘制接入和测试，不回退整个 canvas.py，也不涉及用户标注数据恢复。实施后将本记录从“方案”更新为实际状态，并补充提交、测试结果和人工验收结果。

## 六、实施结果与验证（2026-11-02）

以上第一至五节保留为提案时的设计状态；实际落地与本文的“拟修改”条目一致，差异记录如下。

| 实际文件 | 状态 |
| --- | --- |
| `anylabeling/views/labeling/rectangle_preview.py` | 新增。四边规范化、共线区间差集、屏幕端点余量、开放路径、单帧 `PointFitPreview` 快照；仅依赖 Qt 几何类型。 |
| `anylabeling/views/labeling/shape.py` | 修改。`Shape.paint(..., *, outline_path=None)` 只覆盖描边；填充、顶点和手柄保持完整几何。 |
| `anylabeling/views/labeling/widgets/point_fit.py` | 修改。单帧快照，候选改为橙色 2.0 cosmetic 完整虚线；相同几何不叠画候选；无效候选保留红色反馈。 |
| `anylabeling/views/labeling/widgets/rectangle_crosshair.py` | 修改。草稿剩余轮廓；有效且不同的拟合预览期间常驻十字线让位，不写配置。 |
| `anylabeling/views/labeling/widgets/canvas.py` | 修改。每帧一份快照供普通/mask 轮廓使用；创建十字线移到草稿预览之后、文字之前。 |
| `tests/test_canvas/test_rectangle_preview_overlap.py` | 新增，35 个用例。 |

实际验证命令与结果：

- 新增专项：`35 passed`。
- `tests/test_canvas`：`578 passed / 1 failed`，失败为既有 `test_groups.py::...fixed_screen_size_while_zooming`（与实施前基线一致）。
- `tests/test_labeling`：`192 passed / 8 failed`，均为既有路径/临时文件权限/mock 契约问题，与 2026-11-02 Inspector 报告记录的基线数量一致。
- `flake8`（语法与未使用导入）：通过；`openspec validate fix-rectangle-preview-overlap --strict`：通过。

未完成：6.1 真实屏幕深浅背景的人工可见窗口验收；未重跑 `pytest tests` 全量；未做性能重测；未提交 Git。详细证据见 [verification.md](../../openspec/changes/fix-rectangle-preview-overlap/verification.md)。

## 七、2026-11-04 P2 修复：原几何变化后的候选失效

复核发现：Shift / Shift+Alt 悬停预览期间，原框被方向键等编辑入口改变后，Canvas 仍用旧几何计算出的候选绘制，并继续按旧候选避让原框，导致实际已无效的橙色候选残留。修复保持显示规则不变，只补充候选与来源的一致性：

| 文件 | 修改 |
| --- | --- |
| `anylabeling/views/labeling/widgets/point_fit.py::_update_point_fit` | 记录本次候选的目标身份、原几何、未裁剪指针和生效的 Shift/Shift+Alt 模式，作为 Canvas 内临时状态 |
| `anylabeling/views/labeling/widgets/point_fit.py::_build_point_fit_preview` | 生成每帧快照前比较来源：悬停期间几何变化时按当前几何与已记录指针重算，普通/mask 轮廓与常驻十字线共用结果；已捕获手势几何变化时取消并消费释放，不重新选角、不提交旧候选 |
| `anylabeling/views/labeling/widgets/point_fit.py::_point_fit_move` | 捕获期间鼠标移动发现几何变化时同样取消并消费，避免旧按下快照再次生成候选 |
| `anylabeling/views/labeling/widgets/canvas.py::Canvas.__init__` | 新增三个仅存在于 Canvas 的临时字段，由 `_clear_point_fit()` 统一清理 |
| `tests/test_canvas/test_rectangle_preview_overlap.py` | 新增 8 项真实 Canvas 事件与像素回归（共 43 项） |

行为约定：重算无效时恢复完整原框并保留红色无效定位反馈；重算仍有效时只按新候选与当前原框的共边避让，并保持 Shift+Alt 向内语义；捕获期间几何改变后取消拟合，释放被消费，键盘微调自身的 dirty/撤销不受影响；预览刷新不新增撤销、序列化或配置写入。

验证（2026-11-04）：定向 `82 passed` 与 `53 passed, 72 subtests passed`；`tests/test_canvas` 排除一个受并行设置持久化改动阻塞的窗口用例后 `599 passed / 5 failed / 2 errors`，失败与错误均为既有 `test_groups` 基线、Windows 临时目录 ACL 或并行 `label_widget.py` 改动，与本项无关；`flake8` 通过；`black --diff` 对 `point_fit.py`、`rectangle_preview.py`、`rectangle_crosshair.py` 无变更；`openspec validate fix-rectangle-preview-overlap --strict` 通过。真实屏幕验收（6.1）仍未完成。
