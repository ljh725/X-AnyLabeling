# 自动保存复核（2026-11-04）

结论：常规自动保存可用，但不能判定功能完全正常。已通过真实离屏 Qt 窗口与磁盘 JSON 复现 3 个缺陷。本次仅添加复核材料，没有修改业务源码或用户标注。

## 验证结果

- 总计 **34 passed、3 failed、4 subtests passed**，耗时 57.81 秒。详见 `results.xml`。
- 6 个新增探针中 3 个通过、3 个失败；原有测试全部通过。
- 已验证：图片编辑自动落盘与重载；拖动松手只保存一次；输出目录自动创建；写入失败保持原文件和未保存标记、取消离开；审核状态落盘；分类标志保存；点云防抖、撤销/重做、离开时刷新待保存内容、保存失败保护、输出目录及取消另存为等。
- 此次为专项测试，不代表全量功能或长时间运行、断电恢复验证。

## 缺陷

### P1：密集复核自动保存绕过外部变更保护

位置：`anylabeling/views/labeling/label_widget.py:3624`（自动保存调用 `save_labels`）；对照 `:9189`（手动保存先调用 `_dense_review_resolve_conflict`）。

复现：打开密集复核、完成批次并保存，然后由外部修改当前 JSON 的 description。确认 `_dense_review_external_conflict()` 返回 True 后开启自动保存并提交变更。磁盘外部 description 被清空，冲突处理函数未被调用，保存状态被标为干净。

影响：两个窗口或外部程序并行修改时，自动保存可静默覆盖外部标注/复核数据。

探针：`test_autosave_observes_dense_review_conflict_guard`。建议所有保存入口共享冲突检查，并在取消保存时保留 dirty 状态。

### P1：创建输出目录失败时异常处理再次抛错

位置：`anylabeling/views/labeling/label_widget.py:7261`、`:7302`。

复现：设置尚不存在的输出目录，模拟 `os.makedirs` 抛出 PermissionError，然后提交自动保存。

结果：`metrics_token` 在目录创建之后才初始化，except 分支却直接引用它，导致 UnboundLocalError；正常保存错误提示没有执行，`set_dirty()` 也没有运行到设置 dirty=True 的分支。

影响：目录无权限、只读位置或父目录异常时，保存失败不能正常处理；若此前为干净状态，还会失去预期的未保存状态保护。测试直接调用捕获到异常，未验证真实事件循环中的进程退出行为。

探针：`test_directory_creation_failure_is_handled`。建议在进入可能失败的代码前初始化 metrics_token，并在尝试保存前标记 dirty。

### P2：“另存为”后自动保存改变目标文件

位置：`anylabeling/views/labeling/label_widget.py:3625`；对照 `:9250` 的 `get_label_file()` 与 `:9136` 的手动保存路径。

复现：对 drag.png 的标注另存为 custom.json，开启自动保存并修改类别。

结果：custom.json 仍保留旧类别 person，修改被写入 drag.json；当前 label_file 同时被切换到 drag.json。

影响：用户指定的另存为文件未更新，原图片同名 JSON 可能被覆盖。当前代码虽明确约定命令行 output_file 在自动保存时被忽略，但并未对交互式“另存为”提示该行为，手动与自动保存路径也不一致。

探针：`test_save_as_target_is_retained_by_autosave`。建议自动保存沿用当前已绑定标注文件路径，或明确设计并提示路径切换行为。

## 环境与复跑

解释器：`C:/Users/20441/.conda/envs/x-anylabeling-cu12/python.exe`，Python 3.12.12，pytest 9.0.3，Windows，QT_QPA_PLATFORM=offscreen。

沙箱内 QtCore DLL 加载被拒，最终获准在沙箱外运行。旧 GUI 测试夹具没有建立最近新增的 user_config 会话，直接运行会在初始化时弹出配置错误提示框并阻塞。`bootstrap.py` 在 tests/conftest.py 提供的独立配置目录中建立正式配置会话；没有替换自动保存或冲突处理实现。未完成的 3 个早期运行已停止，不计入结果。

在项目根目录执行（basetemp 必须使用专用测试目录；pytest 会清理该目录）：

```powershell
$env:QT_QPA_PLATFORM='offscreen'
& 'C:/Users/20441/.conda/envs/x-anylabeling-cu12/python.exe' -m pytest -p reports.autosave_review_20261104.bootstrap reports/autosave_review_20261104/test_probes.py tests/test_labeling/test_drag_commit.py tests/test_labeling/test_label_file_save.py tests/test_pointcloud/test_autosave.py tests/test_labeling/test_check_status.py tests/test_labeling/test_classification_flags.py -q -o faulthandler_timeout=40 -p no:cacheprovider --basetemp=.tmp/autosave-review-session-20261104 --junitxml=reports/autosave_review_20261104/results.xml
```

探针保留真实失败断言，修复前预期返回退出码 1。
