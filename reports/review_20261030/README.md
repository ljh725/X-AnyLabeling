# 复核报告：单点拟合与矩形边调整算法改进

日期：2026-10-30
复核对象：工作区未提交改动（相对 `625e87a6`），两条 OpenSpec 变更
`improve-point-fit-algorithm`、`improve-rectangle-edge-adjustment`

## 一、结论

两项算法改进均已按各自规格实现，逻辑自洽，未发现阻断性缺陷，建议保留。

需要处理的是 1 项产品层面的行为变化（P1）、1 项与提案意图仍有差距的边界不连续（P2），
以及记录可复核性和代码质量方面的若干问题。清单见第四节。

## 二、复核方式与证据

| 项目 | 命令 | 结果 |
|---|---|---|
| 专项用例 | `pytest tests/test_canvas/test_shift_point_fit_geometry.py test_shift_point_fit_interaction.py test_rectangle_edge_migration.py` | **152 passed**（几何 27 + 交互 30 + 边 95） |
| 完整画布 | `pytest tests/test_canvas` | **543 passed / 1 failed / 83 subtests**，失败项为既有 `test_groups.py::...fixed_screen_size_while_zooming`，与基线日志一致 |
| 规格校验 | `openspec validate <change> --strict` | 两条均 `is valid` |
| 格式 | `black --check` 三个算法文件 + `git diff --check` | 通过 |
| 对抗性探针 | `reports/review_20261030/probe_algorithms.py`、`probe_algorithms2.py` | 14 组性质检查全部通过 |

探针覆盖的性质（非仓库原有测试）：

- 单点拟合：松开时提交的矩形与最后一次预览**逐值相等**（随机 400 组，含缩放 0.3/1/2.5、Alt、越界拖动）；
  预览锚点必定是预览矩形的一个角；判断带在 `(151.5, 100) ↔ (151.5, 99.9)` 不跳变。
- 边调整：命中返回的边一定是四条边中几何距离最近的一条（随机 500 组）；小框中央 1/2 区域永不被判为边；
  拖动只改一条边、不翻转、位移精确等于鼠标位移；极小框的精确角点不会被把手抢走；NaN 几何不抛异常；
  重叠对象在上时把手让位；极端缩放下把手半径与绘制均不越界。

## 三、逐条对照规格

### 3.1 单点拟合（spec: `rectangle-point-fit`）

| 规格要求 / 场景 | 实现 | 判定 |
|---|---|---|
| 判断带在框边连续、横纵分别按自身尺寸限制 | `rect_edge_click.py:46-49`：`band = min(8, 1 + outside)`，再分别以 `宽/4`、`高/4` 封顶 | 符合 |
| 跨上边 `(151.5,100)→(151.5,99.9)` 均判 top_right | 探针与 `test_crossing_boundary_has_no_band_jump` 一致 | 符合 |
| 1.5 屏幕像素窄框不得整体落入无法判断区 | 中点外侧 1/4 区间可判（`test_thin_box_keeps_left_and_right_quadrants`） | 符合 |
| 按下后冻结原始几何、角点、Alt 模式 | `point_fit.py:186-200` 先预览再落 `_point_fit_box/_corner/_inward`；`_update_point_fit` 在按下态覆盖传入的 `inward`（`:113-114`） | 符合 |
| 跨固定点走 min/max 规范化，不换锚点 | `rect_edge_click.py:72-100`；`test_fit_keeps_anchor_across_centre_and_anchor` | 符合 |
| 预览显示裁剪后的锚点与落点，提交与预览一致 | `point_fit.py:129-144`；探针随机 400 组无偏差 | 符合 |
| 无效拟合回退原生选择与移动，成功拟合一次撤销 | `point_fit.py:189-191` + `canvas.py:2503-2511`；`test_ambiguous_fit_falls_back_to_native_drag` | 符合（行为风险见 P1） |
| Shift 取消不写入几何与撤销 | `test_shift_released_before_mouse_cancels` | 符合 |

### 3.2 矩形边调整（spec: `rectangle-edge-adjustment`）

| 规格要求 / 场景 | 实现 | 判定 |
|---|---|---|
| 先比距离再判可操作性，最近边不可用时不回退更远边 | `rectangle_edge.py:68-117`，候选统一入列后排序取首个，不满足即 `None` | 符合（探针 500 组验证） |
| 内侧带不超过对边间距 1/4，保留中央移动区 | `tolerance = min(available, span/4)`（`:103-110`）；`test_thin_box_centre_still_moves_the_whole_rectangle` | 符合 |
| 按屏幕距离折算外侧空间，四边对称 | `available = max(0, epsilon - outside_space)`，四边 `outside_space` 分别为 `left / W-right / top / H-bottom` | 符合 |
| 小框中点把手，半径受边长与厚度双重限制 | `radius = min(3/scale, w/4, h/4)`（`:131`）；探针验证不覆盖中心、不重叠 | 符合 |
| 精确角点不被把手拦截，关闭后不显示 | `nearest_vertex` 在把手之后（`:64`）；`test_small_midpoint_handles_are_visible_and_toggle_off` | 符合 |
| 按按下位移拖动、保持对边、限制边界与最小尺寸、一次撤销 | `:220-252`；探针验证位移精确、对边不动、不翻转 | 符合 |

## 四、问题清单

### P1（需产品决策）无效按下回退原生拖动，会静默移动矩形

- 位置：`point_fit.py:189-191`、`canvas.py:2503-2511`
- 现象：`Shift` + 左键落在中心判断带、或裁剪后不足 1×1 时，按下不再被拟合捕获，事件落到原生链路。
  此时只要鼠标移动 1 像素，整个矩形就跟着移动。`test_ambiguous_fit_falls_back_to_native_drag` 断言的正是
  `(100,100,200,200) → (120,110,220,210)`：按住 Shift 的一次拖动把框整体搬走了。
- 与上一版差异：`HEAD` 中 `_point_fit_press` 无条件置 `_point_fit_pressed`，`mouseMoveEvent` 也不看按钮状态，
  拖动会被拟合预览吞掉，不会移动矩形。**这是本次引入的新行为**。
- 影响：用户想拟合角点、但点偏到中心线附近时，松手前的轻微拖动会静默改变标注几何。虽有撤销，
  但用户通常不会意识到自己改了几何。
- 规格现状：spec 明确写了 "Invalid fits SHALL fall back to native selection and moving"，所以当前实现是
  **按规格执行**；建议是在规格层面重新取舍，而不是直接判为实现错误。
- 可选做法：
  1. 保留"回退选择"，但用一次性标志吞掉本次手势的 move/release（不移动几何），松手后清除；
  2. 原生移动加 `startDragDistance` 阈值，低于阈值不移动；
  3. 明确接受现状，并在文档中写清"Shift+拖动在无法判断区会移动矩形"。

### P2（低-中）判断带的"无跳变"只做到一部分

- 位置：`rect_edge_click.py:46-52`
- 现象：判断带随框外距离从 1 增长到 8 屏幕像素，而点击点到中心线的距离是固定的，因此"可判断"仍会在框外
  某个位置翻成"无法判断"。实测（box `(100,100,200,200)`，scale 1）：

  | 位置 | 结果 |
  |---|---|
  | `(151.5, 100)` 边上 | `top_right` |
  | `(151.5, 99.5)` 框外 0.5px | `dead_zone` |
  | `(152, 120)` 框内 | `top_right` |
  | `(152, 99)` 框外 1px | `dead_zone` |

  规格场景只采样了框外 `0.1px` 一个点，所以 `test_crossing_boundary_has_no_band_jump` 通过，
  但"跨边界不翻转"的结论没有被这条用例真正覆盖。
- 影响：比上一版（框外一律 8px）明显收窄，但提案中"框边内外判断带突变"的问题只是在 0～7px 内被摊平，
  没有消除；属于设计取舍（design.md 决策 1 明确"保留中心线歧义"）。
- 建议：二选一——(a) 承认该残余，把上表写进 verification；或 (b) 让判断带只依赖垂直方向的偏移量
  （例如 `min(8, 1 + |垂直偏移|*scale)` 或固定 8px 但按 `最小边/4` 封顶），使"远离框边"不再降低可判断性。

### P3（低）右/下边上限从 `width-1` 改为 `width`

- 位置：`rectangle_edge.py:224`（`max_x, max_y = width, height`）
- 现象：拖到图片最右/最下后，矩形可存成 `right == width`、`bottom == height`。与 `_point_fit_valid_box`
  （`<= width`）一致，也与计划文档"图像范围按 `0～width` 处理，避免贴边矩形被缩小一像素"一致；
  单点拟合、拖边、导入框裁剪三处现在统一。
- 影响：这是**存储几何的约定变化**。导出（YOLO/COCO 归一化）用 `right/width` 时反而是 1.0，更正确；
  但若有下游按像素索引假设 `<= width-1`（如掩码栅格化、`QImage.pixel`），满宽框会多出一列。
  仓库内 `intersection_point`、`calculate_offsets` 仍用 `width-1`，用途不同、当前无冲突。
- 建议：在 verification 里记录该约定，并对导出链路做一次冒烟（满框图导出/还原）。

### P4（记录可复核性）实施记录与仓库 diff 不一致

- `improve-rectangle-edge-adjustment/verification.md` 称"此前边界测试中四项断言从'边跳到鼠标'改为'边跟随位移'"，
  但 `git diff` 对该测试文件只有 **1 行删除**（`(101,114)` → `(101,110)`）和纯新增用例，
  看不到这四项改动。若改动发生在上一轮未提交工作中，措辞应写明"上一轮"，否则记录与仓库状态对不上。
- `improve-point-fit-algorithm/verification.md` 未提到：
  - 删除了 `test_invalid_proposal_does_not_create_undo`（旧契约"越界提案拒绝且不写历史"已被"裁剪后提交"取代）；
  - `canvas.py` 的 `mouseMoveEvent` 事件链改动（`:2503-2511`）被概括为"Canvas 初始化"，实际是行为改动。
- 建议：实施记录里逐条列出"新增/修改/删除"的用例名，删除项必须写明被哪条新契约替代。

### P5（代码质量，建议排期）

1. `point_fit.py:186-195` 重复调用 `point_fit_decision`：`_update_point_fit` 内算一次，随后又算一次并存为
   `_point_fit_corner`。两处输入当前相同，但属于"同一决策算两遍"，后续改动容易分叉。建议由
   `_update_point_fit` 返回/落库 decision，按下路径直接复用。
2. 单点拟合的"捕获态"是 5 个散落字段（`_target/_start/_box/_corner/_inward`），清理只在
   `_clear_point_fit` 一处集中；边拖动同概念已用 `EdgeDrag` dataclass。建议同样抽 `PointFitGesture`，
   把"冻结"契约变成类型约束，避免将来新增字段漏清理。
3. `rectangle_edge.py:68-117` 用 5 元组位置索引传参（`candidate[0..4]`），可读性差且易错位；
   建议 `EdgeCandidate(distance, edge, inward, outside_space, span)`，并把容差计算抽成
   `_rectangle_edge_band(span, outside_space, small)`。该方法目前约 80 行、承担 5 项职责。
4. "矩形框合法性"现有 4 套规则：`_point_fit_valid_box`、`_point_fit_clamp_box`、`_rectangle_edge_hit:46-52`、
   `_rectangle_edge_handles:125-129`。其中"允许框外"的差异是有意的，但建议合并为一个带参数的助手函数。
5. `_rectangle_edge_handles` 返回裸 `list`，可标注 `list[tuple[QPointF, float, str]]`。
6. `_rectangle_edge_drag_move:251` 仍用同步 `self.repaint()`，与 CUSTOM-003"合并矩形拖动重绘"的 `update()`
   策略不一致；拖边在大图上会每移动事件同步绘制一次。属既有写法，本次未改，建议随 CUSTOM-003 一并收口。

### P6（测试缺口，按价值排序）

1. 把手在非 1x 缩放的命中与显示（半径按 `3/scale` 变化，目前只在 scale=1 断言过像素颜色）。
2. 把手与"上方有其它对象"的优先级（本次新增分支，仅靠 `_rectangle_edge_native_priority` 复用，无专门用例；
   本次探针已验证行为正确）。
3. 单点拟合"按下之后再按 Alt 应被忽略"——冻结契约只测了反方向（先松 Alt）；正方向无用例。
4. 锁定/未选中的小框不显示把手（目前只测了 `set_rectangle_edge_enabled(False)`）。
5. 大框上等距（对角线）按压回退原生操作的用例。

## 五、遗留与后续

- 可见窗口人工体验仍未验收（两份 verification 均已注明）。P1、P2 都属于"只有真机手感才能定论"的问题，
  建议连同把手视觉一起做一次人工验收再归档。
- 本次复核新增文件：`probe_algorithms.py`、`probe_algorithms2.py`（可重复执行，命令见第二节）。
- 未改动任何产品代码。
