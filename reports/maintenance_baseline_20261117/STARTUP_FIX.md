# 维护测试修正：真实窗口启动与清理

首次完整回归在 `test_staged_output_window.py::test_output_switch_reads_current_then_background`
初始化窗口时进入 `QMessageBox.critical()`。外层无输出 180s 后结束进程树；
没有完整 JUnit，不能将该轮称为完整回归通过。

以 60s 外层超时最小复现，观察器仅记录后调用真实错误方法，未屏蔽弹窗。
原始错误为 `No active configuration session; start the application or call begin_session() first.`，
见[原始日志](staged-modal.log)、[命令/退出码](staged-modal.json)。
写保护始终保留，未改 tests/conftest.py。

按 AGENTS.md 修正两个旧窗口测试文件：13 个分阶段加载窗口和 UI density
夹具均在隔离生效后调用 get_config，并将返回配置交给 MainWindow。
加载用例的原有 theme/auto_save/keep_prev/EXIF/checkbox 条件作为真实启动覆盖传入，
避免首次偏好保存重建有效配置时丢掉测试输入；失败时也清理本测试创建的窗口，
防止旧窗口跨配置隔离生命周期处理回调。不改生产代码或原断言。

中间尝试也保留：仅建立会话但仍直接 config.update 时，checkbox 断言失败，
组合运行随后原生退出 `3221226505 / 0xC0000409`；后者单跑通过。
见 [组合日志](startup-fix.log)、[退出码](startup-fix.json)、
[首断言单跑](staged-first.log)、[原生退出节点单跑](staged-native.log)。
这不构成对全部历史原生退出的统一根因结论。

最终两个完整文件合跑 **15 passed，54.30s，退出码 0**，外层 300s 未触发。
见[命令与环境](startup-fix-final.json)、[日志](startup-fix-final.log)、
[JUnit](startup-fix-final.xml)。运行基于 `6c9af4dc` 加本批两文件测试差异；
生产源码树仍是 `01efe6fe526f49a44353ffcbc5efc5e089a1e77f`。
两文件 flake8 退出 0，定向 diff 空白检查通过；完整回归另行重新执行。
