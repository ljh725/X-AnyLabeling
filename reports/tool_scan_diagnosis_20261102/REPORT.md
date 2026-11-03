# beta.4 十字线、代码分类与工具卡顿诊断

日期：2026-11-02（Asia/Shanghai）。本次交付是代码定位、分类导出和只读性能诊断；没有修改应用运行源码，也没有执行标签改名、删除或标注写入。工作区原有 Inspector 等未提交修改保留。

## 1. beta.4 十字线显色代码

本机存在原始 beta.4 与个人修改 beta.4，二者的十字线实现不同，不能只凭 YAML 中有颜色字段就认为该字段驱动当前绘制效果。

| 版本 / 对象 | 颜色、宽度及透明度来源 | 关键位置 |
| --- | --- | --- |
| 原始 `D:/X-AnyLabeling-4.0.0-beta.4` | `canvas.crosshair.color = #00FF00`、`width = 2.0`、`opacity = 0.5` | `anylabeling/configs/xanylabeling_config.yaml:109` |
| 原始 beta.4 设置窗口 | 选择颜色、输入十六进制颜色；返回 show/width/color/opacity | `widgets/crosshair_settings_dialog.py::choose_color`（216）、`get_settings`（229） |
| 原始 beta.4 绘制 | `QColor(self.cross_line_color)`，虚线，`p.setOpacity(self.cross_line_opacity)`；宽度除以缩放值后取整 | `widgets/canvas.py` 2734–2741；`set_cross_line`（3605） |
| 个人修改 `D:/xinjiegou-X-AnyLabeling-4.0.0-beta.4` | `RectangleGuidePalette.guide = (0, 150, 230, 220)`，固定屏幕宽度 1.5，虚线；候选框橙色 `(220,130,0,255)`，拒绝反馈红色 `(210,60,60,255)` | `widgets/rectangle_guide_overlay.py::RectangleGuidePalette`（11）、`guide_pen`（26） |
| 个人修改 beta.4 接入 | `_draw_crosshair()` 调用 `_rectangle_guide_renderer.render()`；仅两点矩形创建时显示 | `widgets/canvas.py::_draw_crosshair`（6347）、`_rectangle_creation_crosshair_enabled`（1494） |
| 个人修改 beta.4 配置作用 | `apply_canvas_crosshair()` 只应用 `show_when_drawing`；YAML 保留 color/width/opacity，但这条绘制链路不读取它们 | `settings/runtime_applier.py::apply_canvas_crosshair`（385） |
| 当前 4.2.1 常驻十字线 | 读取 YAML 的 color/width/opacity；设置窗口已有颜色控件 | `settings/schema.py` 1030、`settings/runtime_applier.py` 342、`widgets/canvas.py::_cross_line_pen`（6121） |
| 当前 4.2.1 两点矩形辅助线 | `GUIDE_COLOR = QColor(0,150,230,220)`、`GUIDE_WIDTH = 1.5`；不读取配置的颜色/透明度/宽度 | `widgets/rectangle_crosshair.py` 7–8、`_draw_rectangle_crosshair`（76） |

个人修改 beta.4 的核心显色代码已单独导出到 [rectangle_guide_overlay.py](beta4_crosshair/rectangle_guide_overlay.py)，逐文件 SHA256、原始路径、函数源码及行号见 [evidence.json](beta4_crosshair/evidence.json)。其中 `pen.setCosmetic(True)` 保持线宽不随缩放变化，alpha 220 约为 86% 不透明度。当前辅助线与常驻线通过 `_native_crosshair_enabled()` 避免重叠。

如果目标是改变“画矩形时”的十字线颜色，应定位个人 beta.4 的 palette 或当前 4.2.1 的 `GUIDE_COLOR`；如果目标是改变常驻十字线，使用当前配置的 `canvas.crosshair.color`。本次只定位和整理，未擅自改变颜色或迁移整套渲染器。

## 2. 代码已分类导出

比较基线：本地上游 4.2.1 提交 `6d250499d2dd81f78723b9217c7a9abf0443ca25`；当前 HEAD 为 `9a37c5474c390e93243e33a88e8232a19c833280`，清单以当前磁盘内容为准，包含此前已有未提交代码。

| 分类 | 文件数 | 实际产物 |
| --- | ---: | --- |
| 源代码修改 | 10 | 上游已有运行文件的修改补丁：[source_modifications/changes.patch](code_categories/source_modifications/changes.patch) |
| 扩展代码 | 33 | 相对上游新增运行模块的完整副本：[清单](code_categories/README.md)；位于 `code_categories/extension_code/` |
| 测试及工程配套 | 40 | 新增文件副本和已有文件补丁；位于 `code_categories/tests_and_engineering/` |
| 翻译及生成资源 | 9 | `.ts` 差异补丁；`.qm` 与 `resources.py` 登记 SHA256，升级时重新生成 |

完整逐文件分类、字节数、SHA256、是否未跟踪见 [inventory.json](code_categories/inventory.json)。运行代码保持原目录，避免移动文件导致导入失效。补丁基于上游版本生成，用于审查和迁移参考，不能再次直接应用到已包含这些修改的当前工作区。

功能归类与文件分类分别维护：

- **原功能修改/增强**：批量改标、数字键改标、选择/隐藏/锁定、标签显示、窗口密度、拖动响应、分阶段目录加载。历史功能清单见 [CATALOG-20261030.md](../../docs/custom_changes/CATALOG-20261030.md)。
- **扩展能力**：单点拟合、拖边、两点矩形辅助线、四极值、对象身份、组合筛选、矩形尺寸规则、共享视图，以及正在实施的 Inspector。Inspector 未提交且仍有人工验收项，不以本次导出替代验收。
- **待实施的原功能优化**：CUSTOM-001 的统计总览/标签管理器后台扫描。本次确认其仍为方案，没有因目录加载已后台化就自动覆盖这两个工具。

新增文件也可能为原功能优化服务（例如分阶段目录加载模块），旧 `canvas.py` 也会接入扩展能力，所以不能单凭 Git 的 A/M 判断整个功能的性质。

## 3. 真实数据与卡顿原因

用户提供的图片目录：

```text
\\192.168.3.248\opt\shenzhen\stand_roi.tar\stand_roi\stand_roi_person_yolo_edit\站立检测训练集\images\train-ljh-v1
```

相邻标注目录：同一数据集的 `jsons/train`。图片目录含 14003 张 JPG，标注目录含 27837 个 JSON。按图片同名映射，14003 张全部有对应 JSON；本次只扫描这 14003 份，而非整个标注目录。总览扫描读到 16506 个标注对象，随后标签管理器扫描读到 16510 个，唯一类别均为 `stand`。数据没有冻结，数量差异与期间存在外部编辑相容，不能将这两次视为同一份静态内容。两个工具使用当前文件列表和 `output_dir` 映射，不直接统计文件夹里全部 JSON。

### 实测

在隔离的 offscreen Qt 窗口中调用现有方法，使用真实共享盘路径；未加载图片像素、未调用模型推理、未点击修改确认。100 文件预热后依次执行全量统计与标签管理器，系统和 SMB 缓存未清空。

| 全量扫描阶段 | 统计总览 | 标签管理器 |
| --- | ---: | ---: |
| 总耗时 | 143.683 秒 | 168.187 秒 |
| `os.path.exists`（各 14003 次） | 45.755 秒 | 53.155 秒 |
| `open`（各 14003 次） | 58.533 秒 | 68.777 秒 |
| `json.load`（各 14003 次，含读取） | 36.604 秒 | 44.580 秒 |
| 其中 JSON 解码 | 0.415 秒 | 0.444 秒 |
| 其余工作（包含循环、关闭文件、Qt 和计时包装） | 2.790 秒 | 1.675 秒 |
| GUI 心跳最大间隔 | 0.219 秒 | 168.190 秒 |
| 最终类别表行数 | 2（stand + Total） | 1 |
| 标注对象数 | 16506 | 16510 |

标签管理器 `init_label_info()` 为 168.163 秒，`init_ui()` 仅 0.0026 秒。总览有模态 `QProgressDialog.setValue()` 在扫描期间处理事件，所以心跳持续，但全量读取仍占用 GUI 调用链并等待约 2 分 24 秒。标签管理器初始化扫描期间无该处理，约 2 分 48 秒没有心跳。

存在性检查、打开文件及 `json.load` 内读取（扣除解码）合计约占总览的 97.8%、标签管理器的 98.7%。这表明当前负担主要在共享盘逐文件访问与读取，而非 JSON 解码或类别排序。未进行本地盘对照，因此不将全部 I/O 时间严格等同于纯网络传输延迟。

`json.load` 耗时包含读取及解码，解码时间已经包含在该列中，不能再次相加。每文件的 Python 包装和计时存在少量开销。本次单次顺序测量用于定位瓶颈，不能作为所有机器/冷缓存环境的固定耗时。

### 调用链和影响

1. **统计总览**：`label_widget.py::overview()` → `OverviewDialog.init_ui()` → `populate_table()` → `get_total_infos()` → `get_label_infos()`。在 `self.exec()` 前就扫描；逐文件 `exists`、`open`、`json.load`，再遍历 shapes。单类别也照常创建所有 shape 明细字典，之后标签汇总视图只显示两行、22 个单元格。此次慢点主要不在类别表格。
2. **标签管理器**：`LabelModifyDialog.__init__()` 在 `init_ui()` 之前调用 `init_label_info()`；它读取全部对应 JSON 并向集合加入每个 shape 的类别。没有后台 worker，也没有该阶段的进度/事件处理，因此窗口迟迟出现、界面心跳停止。
3. **统计总览重复工作**：切换 Label/Shape、修改范围、导出都会重新扫描。切换到 Shape 还会生成 16506 行、148554 个表格单元格，可能额外卡顿；本次只测了初始标签汇总，没有将形状表渲染时间算入实测。
4. **标签管理器提交**：改名/删除时 `modify_label()` 再次同步读取、遍历并写入范围内文件。仅改颜色、显示或会话锁已有跳过 JSON 改写的逻辑；本次未测试写入耗时。

按代码分析，扫描工作量约为 `O(图片数 + 标注对象数)`，类别排序为 `O(类别数 × log(类别数))`；没有类别两两比较、重复框检测或模型算法。类别只有一个，仍必须读取文件才能确认其内容及数量，不能看到首个 `stand` 就提前结束。

来源核验也排除了误归因：当前 `OverviewDialog` 与 `LabelModifyDialog` 的整类 AST 均与上述上游基线完全相同。`label_dialog.py` 虽有本地修改，差异在另一个 `LabelDialog` 类的批量编辑字段处理。**当前卡顿链路继承自该基线的同步全量扫描，主要受共享盘小文件访问影响；没有证据将它归因于新增 Inspector 或类别复杂算法。**

### 建议实施顺序

1. 将两个工具的读取、JSON 解析与聚合移入共用后台任务，窗口先出现，提供文件进度、取消、错误信息；后台化解决界面阻塞，本身不保证共享盘总耗时缩短。
2. 同一次成功扫描复用标签/形状结果，切换视图不再读盘；按范围、输出目录及文件列表代次隔离结果，提供重扫入口反映外部更改。
3. 减少独立网络元数据请求：评估目录快照匹配，或直接打开并处理缺失异常；仍需保留权限/损坏文件的错误区分。不要将 `exists` 简单删掉后忽略异常。
4. 大形状表按批填充或改用表格模型；批量改名/删除作为独立后台写入任务，设计逐文件原子写入、取消边界和已改/未改/失败报告。
5. 若需要进一步缩短共享盘总时间，使用同一批数据做本地盘对照，再评估有限并发或可验证失效的增量索引。此次没有引入数据库，也没有用跨会话缓存替代真实 JSON。

详细实施和验收要求沿用 [CUSTOM-001 方案](../../docs/custom_changes/2026-10-29-dataset-scan-progress.md)。该优化尚未实施。

## 4. 产物与验证

- [原始性能数据](results.json)、[只读测量脚本](benchmark.py)。脚本安装审计钩子，拒绝共享盘写入/删除/改名；界面心跳间隔为 10 ms。
- [代码分类脚本](organize_code.py)、[十字线证据提取脚本](capture_crosshair.py)、[分类与来源检查脚本](verify_artifacts.py)。
- [验证结果](verification.json)：92 个文件哈希与工作区一致；66 份导出副本与原文件逐字节一致，Python 副本 AST 可解析；3 份补丁可由 Git 解析；两个工具类与基线 AST 一致。
- 本轮没有改变运行行为，因此没有把既有回归测试或人工体验标为“优化后通过”；单次 offscreen 测量也不替代真实屏幕体验验收。
