# 小目标 Person 矩形尺寸浮层 — 实现 Review 清单 v1

> 基于需求：`docs/小目标Person矩形实时尺寸显示需求修订_v1.md`
> 实现：GLM-5.2 · Review：Codex
> 生成时间：2026-07-24

## 1. 修改文件列表

| 文件 | 改动类型 | 说明 |
| --- | --- | --- |
| `anylabeling/configs/xanylabeling_config.yaml` | 新增 | 顶层 `show_rectangle_pixels: true`（紧邻 `show_labels`，默认启用） |
| `anylabeling/configs/quality/l1_l2_threshold_profile_v0.yaml` | 已有 | `person_small_target.min_edge_px: 36.0`（上一轮已加，本轮无改） |
| `anylabeling/views/labeling/widgets/canvas.py` | 重构 | 浮层核心：metrics 收敛、拖边解析、label helper、锚点重写、开关属性、补 emit |
| `anylabeling/views/labeling/label_widget.py` | 新增 | View 开关 action「显示矩形框像素」接线 + 阈值窄接口接入 |
| `anylabeling/views/labeling/widgets/inspector/quality/threshold_profile.py` | 新增 | 窄接口 `read_person_small_target_threshold()` |
| `anylabeling/resources/translations/{en_US,zh_CN,ja_JP,ko_KR}.ts/.qm` | 新增 | 4 条文案 × 4 语言，已重编译 |
| `tests/test_size_overlay.py` | 重写 | 44 个测试，覆盖需求 §12 全部子项 |

## 2. R1–R8 缺陷修复说明

### R1 直接拖边时浮层消失 ✓
**根因**：`mousePressEvent` 在拖边开始时调用 `deselect_shape()`（`canvas.py:1545`）清空 `selected_shapes`，旧解析器依赖 `len(selected_shapes)==1`，导致拖边期间返回 None。
**修复**：`_resolve_overlay_metrics` 新增拖边优先级分支，改读 `rect_edge_active_edge.shape`（拖动期活跃边引用的 shape），其 `.points` 在 `_rect_edge_drag_update` 中实时更新。拖边优先级高于单选。
**验收**：`test_rect_edge_active_drag_resolves_even_without_selection` —— 拖动期 selected_shapes 为空时 metrics 仍解析成功，source=`rect_edge_active`。

### R2 使用整张 pixmap 当 viewport ✓
**根因**：旧 `_paint_overlay_box` 用 `(0, 0, pixmap.width, pixmap.height)` 作为锚点 viewport。
**修复**：新增 `_visible_overlay_rect()`，复用 paintEvent 已有的 culling viewport 算法（`offset_to_center()` + `self.width()/self.scale`），并与 pixmap 范围取交集。
**验收**：`test_uses_current_visible_region_not_full_pixmap` —— 视口平移到矩形自然锚点之外时，锚点被 clamp 进可见区域。

### R3 隐藏状态遗漏 ✓
**根因**：旧守卫只查 `shape.visible` 和 `hidden_by_filter`，漏掉过滤引擎的 `canvas.visible[shape]` 通道。
**修复**：所有候选统一过 `is_shape_interactive(shape)`（含 `canvas.visible` / `shape.visible` / `hidden_by_filter` 三重检查）。
**验收**：3 个测试分别覆盖 `shape.visible=False`、`hidden_by_filter=True`、`canvas.visible[shape]=False`（过滤引擎真实通道）。

### R4 缩放后浮层变大 ✓
**根因**：旧 `font_size = max(6.0, round(8.0/scale))`，放大到 `scale>1.33` 时被钉死在 6pt（图像坐标），再被 painter 放大，实际屏幕字体随放大变大。
**修复**：采用路线 B（图像坐标系 + 除以 Shape.scale），去掉 `max(6.0)` 下限，改为 `max(1, round(8.0/scale))`（仅防 0），padding/gap 同理线性反缩放。
**验收**：`test_font_size_scales_linearly_inverse` —— scale 0.25/1.0/4.0 下屏幕像素均 ≈8px；scale=4 时 font_size=2（非 6）；`test_W_H_invariant_across_zoom` —— 同矩形 W/H 在三档缩放下一致。

### R5 UI 文案未翻译 ✓
**根因**：旧浮层文案硬编码中文 `f"最大边 {max_edge:.1f} px < {threshold:g} px"`。
**修复**：全部改 `self.tr(...)`（`"W %.1f px  H %.1f px"` / `"Max edge %.1f px < %g px"`），4 个 .ts 文件各加翻译条目，重编译 .qm。注意 .ts XML 中 `<` 转义为 `&lt;`。
**验收**：代码内无裸中文文案；.qm 编译输出 4 语言 1131/1122 条翻译完成。

### R6 阈值读取耦合 QA profile ✓
**根因**：旧 `_load_person_small_target_threshold` 调完整 `load_threshold_profile()`（校验全部 rules），无关 rule 配置错误会导致 UI 阈值静默回退。
**修复**：新增窄接口 `read_person_small_target_threshold()`，直接 `yaml.safe_load` 只读 `person_small_target` 块，仅校验 `min_edge_px`（数字/有限/>0）。label_widget 改调此窄接口。
**验收**：`test_invalid_rules_do_not_block_read` —— profile 含坏 rules 数组仍能读到阈值；`test_falls_back_on_missing_block` —— 缺块回退 36.0。

### R7 浮层位置不符合新需求 ✓
**根因**：旧 `pick_overlay_anchor` 默认「矩形右上角外侧优先」，与需求「标签框上方优先」冲突。
**修复**：重写 `pick_overlay_anchor`：① 若有 `label_rect` → 锚定标签框上方（左/居中/右对齐）；② fallback 按矩形上方外侧→内侧→左上外侧→内侧；③ clamp 到 visible_rect。新增 `_label_text_for_shape` + `_label_rect_for_shape` helper（从 paintEvent 标签段抽出），浮层与标签绘制共用同一 label_rect 几何（禁止近似算法）。
**验收**：`test_label_above_when_label_rect_given` —— 浮层在标签框正上方左对齐。

### R8 缺少 View 功能开关 ✓
**根因**：上一版无独立开关，浮层始终显示。
**修复**：照抄 `show_labels` 模式新增 `show_rectangle_pixels`：yaml 默认 `true` → View 菜单 checkable action（紧邻 Show Labels）→ `set_canvas_params` 通用槽 → canvas 属性 → closeEvent 持久化。`_draw_size_overlay` 开头 `if not self.show_rectangle_pixels: return` 守卫。两个开关完全独立。
**验收**：`test_default_config_has_key` / `test_canvas_default_true` / `test_independent_from_show_labels`。

## 3. 数据收敛（需求 §3）

- **统一契约** `_rectangle_metrics`：返回 `(x_min,y_min,x_max,y_max,width,height,max_edge,label,shape,source)`，全部原始 float，状态栏（取 int）与浮层（取 float）共用同一来源。
- **信号签名不变**：`show_shape(int,int,QPointF)` 保持，新增 `_emit_show_shape_from_shape` 从 metrics 取 int H/W emit。
- **补 emit 的路径**：`_rect_edge_drag_update`（拖边）、wheelEvent 的 `_scale_rectangle`/`_adjust_rectangle_edge`（滚轮缩放/调边）——这三条路径此前只 `update()` 不 emit，状态栏 H/W 不刷新，现统一收敛。

## 4. 新增/修改测试

`tests/test_size_overlay.py`（44 用例，覆盖需求 §12）：

| 测试类 | 覆盖需求 | 用例数 |
| --- | --- | --- |
| `TestNormalizeTwoPoints` | §12.1 正反坐标 | 4 |
| `TestSizeFromBbox` | §12.1 尺寸 + §12.4 缩放无关 | 3 |
| `TestIsPersonSmallTarget` | §12.1 阈值边界 35.9/36.0/36.1 + 非 person | 7 |
| `TestPickOverlayAnchor` | §12.1 标签上方锚点 + fallback + visible_rect clamp | 6 |
| `TestCanvasTargetResolution` | §12.2 创建/单选/拖边/多选/非矩形/三种隐藏/开关 | 13 |
| `TestNoSideEffects` | §13 无副作用 + metrics 是 float | 3 |
| `TestZoomStability` | §12.4 字号线性反缩放 + W/H 不变 | 2 |
| `TestViewToggle` | §12.3 默认配置/canvas 属性/与 show_labels 独立 | 3 |
| `TestThresholdNarrowReader` | §10/R6 窄接口不受坏 rules 影响 | 3 |

## 5. 本地测试命令与结果

```powershell
$py = "$env:USERPROFILE\.conda\envs\x-anylabeling-cu12\python.exe"
& $py -m pytest tests/test_size_overlay.py -q                          # 44 passed
& $py -m pytest tests/test_rect_edge_canvas_semantics.py -q            # passed
& $py -m pytest tests/test_canvas_interaction.py -q                    # passed
& $py -m pytest tests/test_quality_thresholds.py -q                    # passed
& $py -m pytest tests/test_size_overlay.py tests/test_rect_edge_canvas_semantics.py tests/test_canvas_interaction.py tests/test_quality_thresholds.py -q
# → 107 passed, 79 warnings (warnings 均为 pre-existing numpy deprecation)

& $py -m black -l 79 --target-version py312 `
  anylabeling/views/labeling/widgets/canvas.py `
  anylabeling/views/labeling/label_widget.py `
  anylabeling/views/labeling/widgets/inspector/quality/threshold_profile.py `
  tests/test_size_overlay.py                                           # 全部格式化通过

& $py -m flake8 anylabeling/views/labeling/widgets/inspector/quality/threshold_profile.py tests/test_size_overlay.py
# exit 0（新增代码零警告）

& $py scripts/compile_languages.py                                     # 4 语言 .qm 编译成功
```

**flake8 说明**：`canvas.py` / `label_widget.py` 仍有 pre-existing 警告（F841 blocker 变量、C901 复杂度、F541 f-string），均不在本次新增代码行上。

## 6. 未完成项说明

无未完成的 P1/P2 项。全部 R1–R8 缺陷已修复并有测试覆盖。

**需手工验证（绘制层无单测先例）**：
- 浮层实际画出的视觉效果（字号、颜色、半透明背景）；
- 锚点回退在视口四边缘的实际位置；
- 浮层不遮盖目标主体；
- View 菜单「显示矩形框像素」实际切换行为与持久化。

## 7. 不在范围（需求 §13）

未新增小目标模式、未弹对话框、未改 JSON schema/undo/dirty、未用 show_labels 代替、未大重构绘制顺序、未改无关筛选/质检/自动标注。
