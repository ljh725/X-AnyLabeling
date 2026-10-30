# 矩形框拖动不连续：问题定位

> 2026-10-30 补充：已使用用户确认的全部真实 PRW 路径、保存的显示配置和真实后台任务完成交叉实测。最终主次判断及数据见 [PRW 真实数据定位报告](D:/X-AnyLabeling-4.2.1/reports/drag_diagnosis_20261029/REAL_DATA_REPORT_20261030.md)。本文件保留 10 月 29 日的初步诊断过程。

日期：2026-10-29，Asia/Shanghai。目标为当前工作区代码。本次只做诊断与进程内 A/B 实验，未修改应用源码。

## 结论

已在关闭后台扫描、没有网络数据读取的受控场景中复现随数据集文件数增加而变慢的拖框处理。当前明确的两个热点为：

1. **主要热点：每次鼠标移动更新状态栏，都重新遍历两遍完整文件列表。** 这是目录总图片数影响单张图片交互速度的直接原因。
2. **叠加热点：每次鼠标移动执行两次同步完整重绘。** 随当前图片对象数和绘制成本增加而加重。

自动 EXIF、后台审核状态回填可能进一步影响打开大目录后的交互，但不是本次受控复现的必要条件。旧版路径缓存和绘制裁剪是有价值的后续优化，不能取代首先移除上述两处已测热点。

## 1. 调用链与代码证据

```text
Canvas.mouseMoveEvent
  ├─ canvas.py:2536 repaint()                  完整同步重绘，坐标尚未更新
  ├─ canvas.py:2720 bounded_move_shapes(...)   更新选中框坐标
  ├─ canvas.py:2721 repaint()                  再次完整同步重绘
  └─ canvas.py:2728 show_shape.emit(...)
       └─ LabelingWidget.show_shape
            ├─ label_widget.py:6406 len(self.image_list)
            └─ label_widget.py:6408 self.filename in self.image_list
                 └─ label_widget.py:8114 image_list 属性
                      每次遍历 file_list_widget 全部条目，调用 item()/text() 并新建列表
```

目录含 11,000 张图片时，一次状态栏更新调用 `image_list` 两次，总共约 22,000 次条目访问及文本提取。即使当前图片只有三个框，也会执行这部分工作。不是每次拖动都读取 11,000 张图片，而是重复访问 11,000 个 Qt 列表项。

普通拖框的坐标提交和自动保存发生在松手后的 `store_moving_shape()` / `shape_moved` / `set_dirty()` 链路，不能解释本次持续拖动阶段的全部开销。

## 2. 受控计时

使用本机既有 conda 环境、PyQt6/Qt 6.10.0，启动真实 MainWindow、真实 Canvas 与原有信号连接；1920×1080 的真实 PRW 图片，只读载入一次。文件列表分别放入 1、1,000、11,000 个路径字符串，额外路径是测试用字符串，不打开这些图片。分别显示真实的三个矩形框，或原图全部 54 个对象（三框、51 个关键点）。

关闭 EXIF、目录扫描、审核回填、自动保存和继承上一张标注。断言相关定时器与 EXIF 线程均未运行。每种条件发送 90 个带左键按下状态的鼠标移动事件，验证框坐标确实变化；每次事件后处理 Qt 事件队列，计入绘制和状态栏处理。

| 文件列表数量 | 当前画布对象 | 原代码中位耗时 | 仅去掉状态栏全列表扫描 | 再将同步重绘改为可合并的 update |
|---:|---:|---:|---:|---:|
| 1 | 3 | 7.08 ms | 6.72 ms | 3.18 ms |
| 1,000 | 3 | 9.01 ms | 6.04 ms | 3.23 ms |
| 11,000 | 3 | 35.29 ms | 9.92 ms | 4.13 ms |
| 1 | 54 | 17.20 ms | 16.20 ms | 8.20 ms |
| 1,000 | 54 | 21.33 ms | 16.75 ms | 8.62 ms |
| 11,000 | 54 | 49.80 ms | 16.87 ms | 9.03 ms |

11,000 个条目、54 个对象的原代码分项（平均每个移动事件，包含关系不可全部相加）：

- `image_list` 两次构建：32.12 ms；包含它的 `show_shape` 共 32.78 ms。
- 两次 `paintEvent` 合计：15.15 ms。
- 真正移动框坐标的 `bounded_move_shapes`：0.026 ms。
- 90 次移动对应 **180 次 image_list 构建和 180 次 paintEvent**。去掉扫描后列表构建次数为零；合并刷新后绘制变为 **90 次**。
- 原代码单次事件中位数 49.80 ms，P95 65.00 ms；两项运行时替换后中位数 9.03 ms，P95 13.57 ms。

这些结果定位 CPU/Qt 处理开销，不等同于物理屏幕 FPS。测试为顺序执行、热缓存、offscreen，不计显示器/桌面合成/GPU 呈现；没有对用户当前窗口做现场采样。状态栏 A/B 保留相同坐标/宽高文本，移除无实际文本差异的分支及其全列表查询。重绘 A/B 为测试进程中的临时替换，退出即恢复，不是已交付修复。

## 3. 三份历史记录与当前问题的对应关系

### 点击画面卡顿分析

[output_dir_click_lag_analysis.md](D:/xinjiegou-X-AnyLabeling-4.0.0-beta.4/docs/output_dir_click_lag_analysis.md:62) 已指出重复同步重绘、属性面板重建、Inspector 列宽重算等问题。重复重绘与当前拖框链路直接吻合，本次计时已验证其开销。

当前 4.2.1 的 `label_widget.py` 没有旧修改版的 Inspector 刷新链路，因此不能把旧版 Inspector 分支直接认作当前根因。选中后的 `shape_selection_changed` 信号处理在本次场景约 1.6～2.9 ms；这不是完整鼠标点击事件或所有属性配置的测量，不能据此排除其他选中场景。

### 绘制裁剪和路径缓存改造

[pose-120_impl_pose加载优化代码改造.md 第 7 节](D:/xinjiegou-X-AnyLabeling-4.0.0-beta.4/docs/pose-120_impl_pose加载优化代码改造.md:402) 记录缓存路径/bbox、绘制前视口裁剪。旧修改版现有代码已核实包含这些机制；当前 4.2.1 的 `Shape.make_path()` 每次新建路径，`bounding_rect()` 再调用它取边界，未保留同一套通用缓存与裁剪。

这些措施主要减轻单图对象多时的绘制成本。只有三个框时，大目录也能明显拖慢，说明它们不是本次最先应处理的原因。

### 后台扫描手动化总结

[filter-090_summary_后台扫描手动化总结.md](D:/xinjiegou-X-AnyLabeling-4.0.0-beta.4/docs/filter-090_summary_后台扫描手动化总结.md:3) 记录首图已经显示后，自动 EXIF 和 DatasetIndexWorker 持续影响 UI。提交 `476ad1fa`（2026-05-22）称改为手动后 1.1 万张图片不再出现当时卡顿。

当前版本没有该旧版 DatasetIndexWorker，但有目录加载后的后台审核读取、10 ms 定时器回填和配置开启时的自动 EXIF 扫描（`_poll_metadata`、`_start_pending_exif`）。这属于可能叠加的负担，不能直接照搬旧版全部根因。此次完全禁用这些任务后仍复现慢拖，因此后台扫描不能单独解释问题。

## 4. 额外找到的精确历史修复

旧修改版当前 `show_shape()` 已改为 `self.filename in self.fn_to_index`，不再读取两遍 `image_list`。

通过 Git blame 和提交 diff 核实，修改来自 **`e24a95292`，2026-08-03，`Sync pending project changes`**：

```diff
- num_images = len(self.image_list)
+ has_indexed_current_file = bool(
+     self.filename and self.filename in self.fn_to_index
+ )
- if num_images and self.filename in self.image_list:
+ if has_indexed_current_file:
```

宽高分支和纯坐标分支均修改。当前 4.2.1 工作区仍为旧的两遍全列表读取方式。这是已存在于旧修改版、当前未保留的具体优化，不能仅凭版本号推断已经继承。

## 5. 处理优先级

1. **首先处理 `show_shape` 中全列表构建**：使用现有文件索引或移除结果相同的冗余分支，使鼠标移动耗时不再随目录图片数线性增加。
2. **合并拖动路径的重绘请求**：坐标更新后统一请求绘制，避免先画旧位置、再画新位置两次完整渲染。需回归普通拖框、顶点/边缩放、旋转、绘制预览等受影响交互，不能无差别替换所有 repaint。
3. **随后评估后台任务调度**：拖动期间的审核回填预算、EXIF 开启时影响；先测再决定是否暂停、节流或改手动。
4. **最后评估路径/bbox 缓存和视口裁剪**：面向单图大量对象的额外收益，必须保证点坐标变化、Undo、边界和关键点绘制正确。

## 产物与保护

- [benchmark_drag.py](D:/X-AnyLabeling-4.2.1/reports/drag_diagnosis_20261029/benchmark_drag.py)：可复测脚本。
- [results.json](D:/X-AnyLabeling-4.2.1/reports/drag_diagnosis_20261029/results.json)：18 种条件的原始计时、调用次数和源码哈希。
- 测试使用独立配置/QSettings；审计钩子禁止修改原数据目录；测试前后三份应用源码 SHA256 与目标标注 JSON SHA256 一致。没有操作正在使用的标注窗口。
