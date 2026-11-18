# 退役接线与回归对照

| 范围 | 专属接线 | 共用行为与验证路径 |
| --- | --- | --- |
| Inspector | `label_widget.py` 工具菜单、窗口、切图通知、问题定位、候选编辑与交接；`widgets/canvas.py` 候选叠层；`views/labeling/inspector/`、`services/inspection/`；默认 YAML 与设置快捷键 | 普通切图、选择、焦点和关闭；`utils/batch.py` 与 `widgets/label_dialog.py` 调用 Inspector 的 `atomic_write_json`，先迁出 |
| Dense Review | `label_widget.py` 工作区、显示、空间复核、进度、保存/切图/历史钩子；`widgets/canvas.py` 绘制、命中和候选菜单；`shape.py` 样式覆写；`views/labeling/dense_review/`、`services/dense_review/`、`utils/style.py` | 画布正常绘制、命中、对象筛选/锁定、分组、编辑历史；`LabelFile.other_data` 透传顶层扩展；原生图片审核和训练导出 |
| 设置与统计 | `config.py` 密集复核默认值，默认 YAML 及 `settings/{schema,runtime_applier}.py`；主窗口复核确认与候选来源接线 | 普通快捷键设置、配置保存、编辑/撤销/AI 批处理计费事件及历史来源读取 |
| 资源与指南 | 四份 `.ts` 与生成的 `.qm` 和 Qt Python 资源，README 与中文用户手册入口；未发现 qrc 中以两项功能命名的独占图标 | 保留共用图标、历史操作指南和已有样本引用 |
| 脚本与测试 | `scripts/` 中的 `benchmark_dense_review.py`、`generate_dense_review_samples.py`、`capture_dense_review_screenshots.py`，以及 `tests/test_inspection/`、`tests/test_dense_review/` 和成本统计的复核接线用例 | `test_rectangle_preview_overlap.py`、`test_label_locks.py`、`test_schema.py` 中的普通行为断言继续执行。已有指标测试覆盖批处理及标签改写 |
| OpenSpec | 七份 Inspector 主规格，密集复核和界面打磨活动 delta；历史重设计已归档 | 更新 `canvas-controls-recovery`，新增旧数据兼容规格，核对成本统计和关键点有效约束 |

普通保存路径为 `LabelingWidget` → `LabelFile.save`，继续维护 `checked`、对象 ID 和其他数据。批处理通过 `utils/batch.py` 发布单个标注，标签改写通过 `LabelModifyDialog.modify_label` 发布单个标注并通知分类变更。普通画布的回归范围包括预览、矩形调整、视图恢复、选择和对象历史。

移除前对照为 [11-17 Windows 完整复测](../maintenance_baseline_20261117/full-recheck-summary.json) 的 2632 通过、29 跳过、20 失败（含 2 个子测试），以及 [11-18 训练停止对照](../stabilize_maintenance_baseline_20261118/REPORT.md)。旧失败包括密集复核交接、画布筛选桩对象缺少复核属性、属性编辑测试桩、Windows 路径和临时文件行为、训练停止、属性上传和画布调节。退役与修复后的结果应按用例名比对。

## Inspector 批次

移除了候选叠层、独立窗口和交接。保留普通对象编辑、切图、焦点、关闭、审核、共用图标和仍有 Dense Review 消费者的通用工作台样式。移除前专属测试随服务退出。

隔离的缩放和平移切图测试 1 项通过。组合运行 174 通过、1 项设置字段计数失败。将第二处仍使用 94 的快捷键数断言同步为 90 后，设置 schema 7 项复跑通过。所有 Dense Review 用例在组合运行通过，涵盖窗口开关、焦点和快捷键、空间复核、后台工作关闭。
