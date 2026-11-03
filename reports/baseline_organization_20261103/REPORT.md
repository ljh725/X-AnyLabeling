# 开发基线核验结果

日期为 2026-11-03，时区 Asia/Shanghai。来源提交为 `6b98b76e`，整理分支为 `codex/4.2.1-baseline-organization`。

## 运行环境与命令

解释器为 `C:/Users/20441/.conda/envs/x-anylabeling-cu12/python.exe`，Windows，Qt 离屏模式。TEMP/TMP 设为工作区 `.local/pytest`，没有加载 `.tooling/pytest-shim`。新建的临时运行目录由 `.gitignore` 排除。

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:TEMP = (Resolve-Path .local/pytest).Path
$env:TMP = $env:TEMP
& 'C:/Users/20441/.conda/envs/x-anylabeling-cu12/python.exe' -m pytest -q tests/test_inspection tests/test_dense_review tests/test_canvas tests/test_labeling tests/test_auto_labeling tests/test_settings --basetemp=.local/pytest/baseline-organization --junitxml=reports/baseline_organization_20261103/baseline.xml -p no:cacheprovider
```

## 结果

- 基线摘要为 **1031 passed、14 failed、1 skipped、143 subtests passed**，157.51 秒。原始输出见 [baseline.txt](baseline.txt)，JUnit 见 [baseline.xml](baseline.xml)。
- Inspector 83 通过，密集复核 87 通过，合计 170 通过，与 UI P2 的记录一致。
- Canvas 578 通过，固定屏幕标签宽度 1 项失败，与既有 UI P2 和此前报告一致。
- 对统计入口添加开发状态保护后，独立验证 **2 passed**。见 [metrics-gate.txt](metrics-gate.txt) 和 [metrics-gate.xml](metrics-gate.xml)。测试通过真实主窗口确认菜单禁用，直接调用入口能够提示开发状态。
- 两份 OpenSpec（统计功能和 UI P2）的 strict 校验通过。格式检查覆盖新增入口保护和测试文件。

保存的终端日志已移除 ANSI 颜色控制符，文本与 XML 的行尾空白已归一化，测试消息和结果保留。

## 失败分类

[failures.json](failures.json) 保存节点名称与异常消息。pytest 子测试汇总与 JUnit 父节点数量存在差异，原始两种输出均保留，以下按失败父节点归类。

| 类别 | 节点或范围 | 本次观察与依据 |
| --- | --- | --- |
| 画布标签尺寸 | `test_shape_label_keeps_fixed_screen_size_while_zooming` | 179 与 139 不同，已有 P2 验证明确记录同项失败 |
| 属性测试替身 | `test_batch_edit_resets_only_shapes_with_changed_labels`、`test_save_attributes_uses_standard_shape_serialization` | SimpleNamespace 缺少 copy / _metadata_generation，此类失败在先前功能报告已有记录，仍需单独修复测试与实际契约 |
| Windows 路径 | `test_window_title_includes_annotation_checked_status` | 实际 Windows 路径与测试写死的 POSIX 路径不一致 |
| 上传属性行为 | `test_upload_preserves_auto_switch_signal_state`、`test_valid_upload_rebuilds_open_attribute_panel` | 包含两个信号状态子测试失败及面板对象断言失败，保留为待修基线项 |
| Windows 临时文件 | 视频流 2 项、remote_server 2 项 | 测试保持 NamedTemporaryFile 打开时又按路径读取，出现 PermissionError。基线使用直接环境，未用临时文件 shim 掩盖此限制 |
| 部分统计实现的设置字段 | test_schema 的三个计数用例 | 实际字段 145 / 快捷键 89，测试期望 144 / 88。快照增加 open_correction_metrics，相关测试尚未同步，属于未完成统计工作的基线缺口 |

本轮保留失败作为后续比较起点。完整统计功能的服务、计时、导出和性能验证尚待其实施阶段完成。离屏验证也尚不能代替真实显示器及标注者操作验收。

## 备份与文件范围

整理前完整 bundle 的 SHA-256 为 `52e64152c726a336f72d8495e4ecc51ad309e6b85fb9a0b901f34472d9d38656`，`git bundle verify` 通过。移出跟踪的 887 个文件均在 [cleanup-paths.txt](cleanup-paths.txt) 中，清理前状态见 [inventory-before.json](inventory-before.json)。

本轮源码改动限于未完成统计入口的可用性检查与提示，并增加对应两个回归用例。UI P2 的布局、图标、主题和既有快捷键沿用原提交。完整功能状态、恢复标签和后续顺序见 [开发基线整理](../../docs/version-management/2026-11-03-development-baseline.md)。
