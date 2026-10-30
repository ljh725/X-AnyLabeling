# CUSTOM-003：大数据集拖动响应优化

- 分类：原项目交互性能修复；不是新增产品功能。
- 状态：方案已建立，生产代码未实施。
- OpenSpec：[smooth-canvas-dragging](../../openspec/changes/smooth-canvas-dragging/proposal.md)。方法见 design.md，执行顺序见 tasks.md。
- 证据：[真实PRW定位报告](../../reports/drag_diagnosis_20261029/REAL_DATA_REPORT_20261030.md)。原代码无后台42.34ms，进程内两项对照10.07ms；不是已实施结果。
- 计划修改：label_widget.py::show_shape 去掉全列表遍历；widgets/canvas.py::mouseMoveEvent 合并经确认的刷新路径。
- 计划新增：有意义的交互回归、实际改后基准产物；不新增产品入口、数据格式或依赖。
- 依赖：现有分阶段加载、矩形迁移交互及对象身份；不回滚这些已存在功能。
- 实现提交：无。后续分状态栏/绘制两个提交，均带 CUSTOM-003。
- 备份/回退：见 [BACKUP-20261030.md](BACKUP-20261030.md)。代码恢复与标注数据恢复分开。
- 当前验证：已完成问题定位；修复行为及改后性能尚未验证。
