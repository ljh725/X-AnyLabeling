# PRW 真实数据：拖框卡顿最终定位

日期：2026-10-30。用户确认数据集为 PRW_image_11792 与 PRW_json_11792。

## 定位结论

当前工作区在这套数据上的持续拖框卡顿，主要由主线程中两项重复工作造成：**每次鼠标移动两遍全文件列表构建；每次移动两次同步完整重绘**。审核状态首次回填另有可测开销，EXIF 单独运行在本机本轮测试中影响较小。后台任务结束后原代码仍慢，因此后台扫描并非持续卡顿的主要原因。

## 复现条件

- 只读查询正在运行的标注进程，确认解释器为 x-anylabeling-cu12，工作目录为 D:/X-AnyLabeling-4.2.1，命令为 anylabeling/app.py。未附加或修改用户进程。
- 独立真实 MainWindow，通过正常 import_image_folder 流程枚举全部 **11,792 张真实图片路径**，解析真实标注；没有构造虚拟文件条目。
- 使用同一真实首图 PRW_c1s1_000151.jpg，1920×1080，54 个对象（三框、51 个关键点），读取用户保存的显示配置；窗口大小 2560×1377。配置中 EXIF 开启、show_masks 关闭；扫描是否运行由各对照条件独立控制。
- 两轮随机顺序，4 种后台条件 × 3 种前台处理方式，每项 100 个真实 mouseMoveEvent，共 **24 个条件样本、2,400 次移动**。
- 审核条件运行原有 MetadataWorker 和 GUI 回填定时器；列表预置未知状态，等第一批真实磁盘结果到达后开始计时，保证测到首次回填，而非已完成状态的空更新。EXIF 使用原有扫描线程，记录每个事件的任务活跃状态。
- 关闭自动保存、继承标注；使用独立配置和 QSettings。原数据目录有写保护审计钩子。A/B 只在诊断进程临时替换状态栏槽函数或 repaint 调度，应用源码未修改。

## 实测结果

下表每格为单次移动处理的 **中位数 / P95，单位 ms**；每格汇总两轮 200 次移动。

| 后台状态 | 当前代码 | 去掉全列表遍历 | 再合并重绘 |
|---|---:|---:|---:|
| 后台任务全部结束 | 42.34 / 49.34 | 19.75 / 22.01 | 10.07 / 12.26 |
| 仅 EXIF 扫描 | 43.04 / 50.70 | 20.38 / 23.06 | 10.30 / 12.43 |
| 仅审核扫描及首次回填 | 43.28 / 50.84 | 20.44 / 27.46 | 15.82 / 18.84 |
| EXIF 与审核同时运行 | 43.90 / 51.51 | 20.83 / 27.57 | 16.85 / 21.66 |

统计包含鼠标事件处理及其后的 Qt 事件队列处理。路径缓存和视口裁剪没有在 A/B 中加入，所以上述收益可以直接归于这两项替换，而非其他隐藏优化。

## 原因一：文件总数进入高频鼠标处理

`Canvas.mouseMoveEvent → show_shape.emit → LabelingWidget.show_shape` 每次更新坐标/宽高，先执行 `len(self.image_list)`，再执行 `self.filename in self.image_list`。`image_list` 是重新逐项提取 Qt 文件列表文本的属性，不是缓存列表。每次移动为 11,792 个条目提取两遍文本，共 23,584 次条目访问。

在后台结束的原代码条件中，两次列表构建平均占 **22.38 ms/移动**。这项耗时不需要网络、后台扫描或大量标注对象即可发生。

代码：[show_shape](D:/X-AnyLabeling-4.2.1/anylabeling/views/labeling/label_widget.py:6398)、[image_list](D:/X-AnyLabeling-4.2.1/anylabeling/views/labeling/label_widget.py:8114)。

## 原因二：先画旧位置，再画新位置

普通拖框路径在更新坐标前调用一次 repaint，移动后又调用一次。两轮共 200 个移动事件，原路径执行 400 次 paintEvent；合并后为 200 次。后台结束条件中，原代码两次绘制平均占 **15.90 ms/移动**。

代码：[移动前重绘](D:/X-AnyLabeling-4.2.1/anylabeling/views/labeling/widgets/canvas.py:2536)、[移动后重绘](D:/X-AnyLabeling-4.2.1/anylabeling/views/labeling/widgets/canvas.py:2720)。

## 后台扫描的已测角色

审核首次回填条件确实处理真实标注并更新未知状态；它可以增加单次周期和尾部延迟。该开销包含后台竞争、GUI 状态回填及其引起的后续重绘，不能仅以 `_poll_metadata` 函数自身耗时代表全部影响。

比较表中的后台结束、EXIF、审核、同时运行四行，可以判断影响幅度。本轮 EXIF 的差异较小，不宜把小幅差异当作稳定性能保证；审核首次回填增加的开销更明显。**关闭后台扫描不能消除原代码的持续慢拖，处理两个前台热点才带来主要改善。**

## 与三份历史记录的关系

1. [点击画面卡顿分析](D:/xinjiegou-X-AnyLabeling-4.0.0-beta.4/docs/output_dir_click_lag_analysis.md:62) 中重复同步重绘的方向与本次计时吻合。旧版 Inspector 路径不能直接套用到当前版本；此次没有证据把 Inspector 当作原因。
2. [路径缓存与绘制裁剪记录](D:/xinjiegou-X-AnyLabeling-4.0.0-beta.4/docs/pose-120_impl_pose加载优化代码改造.md:402) 是进一步降低单图绘制成本的方向，但无需先迁移整套缓存就能消除主要耗时。
3. [后台扫描手动化记录](D:/xinjiegou-X-AnyLabeling-4.0.0-beta.4/docs/filter-090_summary_后台扫描手动化总结.md:3) 描述了旧版首图显示后的后台负担；当前审核回填也有影响，但实测没有取代前台两个热点成为主因。

另外，旧修改版 **e24a95292（2026-08-03）** 已将 `show_shape` 改为查询 `fn_to_index`，避免全列表构建。该点是 Git blame 和 diff 确认的既有修复，当前 4.2.1 未带入。

## 验证边界与后续处理

本结论针对用户确认的本地 PRW 数据、当前源码及已保存显示配置下复现的持续拖框问题。使用 offscreen Qt，不把处理时间等同于物理屏幕 FPS；未对用户进程现场采样，也未对网络数据集、所有图片与所有编辑模式作穷举。因此结论不宣称排除了所有其他场景的卡顿。

修复顺序已有实测依据：先移除状态栏全列表查询，再在普通拖动路径合并重绘；之后再按需要优化审核回填。三份生产源码测试前后 SHA256 一致。此次只完成定位，未交付生产修复。

原始数据：[real_background_results.json](D:/X-AnyLabeling-4.2.1/reports/drag_diagnosis_20261029/real_background_results.json)。复测脚本：[benchmark_real_background.py](D:/X-AnyLabeling-4.2.1/reports/drag_diagnosis_20261029/benchmark_real_background.py)。前一轮未预置未知状态的试验保留为 real_background_unprimed_results.json，不混入本表。
