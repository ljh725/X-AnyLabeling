# CUSTOM-002：分阶段标注加载

- 分类：原项目目录加载/搜索/审核导航性能与异步一致性改造。
- 状态：源码已存在；OpenSpec原记录31/31完成；历史报告包含测量及复核，不代表本轮重新通过全套测试。
- 来源：2026-10-29在4043583b之后的既有工作区改动，本轮只归档备份。
- 修改原有文件：label_widget.py、utils/async_exif.py、utils/file_search.py。
- 新增实现文件：utils/staged_annotation_loading.py。新增文件是此改造的辅助实现，不计为独立新增产品功能。
- 新增测试：tests/test_staged_annotation_metadata.py、tests/test_staged_output_window.py，以及reports下的复核用例。
- 行为：后台路径扫描/搜索，分批显示和审核回填，旧请求/保存版本隔离，未知审核候选等待，EXIF取消/退出协调。
- 数据：仍以JSON为真实源；不引入SQLite或全局索引。
- 证据：[交付报告](../../reports/staged_annotation_loading/REPORT.md)、[OpenSpec任务](../../openspec/changes/staged-annotation-loading/tasks.md)。旧报告的环境、限制和未通过项保持有效，不能把所有回归描述为全通过。
- 备份：本次pre-drag固定快照将这项既有实现纳入；回退这项需检查后续交互优化依赖，不建议整文件覆盖。
