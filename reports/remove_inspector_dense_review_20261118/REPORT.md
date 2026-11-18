# Inspector 与 Dense Review 退役验证

验证对象为工作分支 `codex/4.2.1/remove-inspector-and-dense-review`。生产起点 `ade2d67c` 与实施起点 `20cba258` 的源码、测试和脚本一致。[接线与基线](WIRING.md) · [规格预演](SPEC-REHEARSAL.md)

## 兼容与资源

- 共享 JSON 写入批次 33 项通过。批处理和标签对话框在实际 `os.replace` 失败时保留原文件字节，并清除同目录临时文件。
- Dense Review 拆除后，真实离屏窗口切图专项 1 项通过。普通矩形预览、框选、可见性、筛选、锁定、图片标签、设置、统计和批量 AI 保存的组合 152 项通过，另有 2 个子测试通过。
- 旧配置与数据的真实离屏窗口用例 3 项通过，覆盖 `false`、`true`、`"failed"`。框位置更新后，稳定对象 ID、未知格式复核载荷、全局及形状扩展均保留。空载荷图片不产生复核字段。既有报告、规则、复核配置及进度文件逐字节一致。普通打开快捷键和 YOLO 训练标签导出有效。
- `20cba258` 写入含 `inspection_edit`、`review-confirm`、`review-undo` 的隔离 SQLite 库。现行代码保留历史事件来源及计数，CSV 导出保留三种操作计数。确认及撤销进度在导出中各计一次，修正事务及触达仍各为一次。
- 用 `scripts/compile_languages.py` 重新生成 `.qm` 和 Qt 资源。从 `.ts` 移除英语 579 条、简中/日/韩各 565 条消息，其余消息的上下文和内容逐项一致。四种语言均从磁盘和 `:/languages/translations/` 加载成功，普通设置仍可翻译。日、韩各保留编译器报告的 28 条未完成及 45 条未翻译消息。

## Windows 回归

环境为 `x-anylabeling-cu12`、Python 3.12.12、pytest 9.0.3、Qt offscreen。测试使用独立 `.tmp` 配置、`get_config()` 和 `--basetemp`。运行使用 `-vv -o faulthandler_timeout=30`，外层硬超时分别为 950 秒、2400 秒、120 秒。临时日志和 JUnit 输出位于 `.tmp/retire-regression/`。

| 范围 | 实际结果 |
| --- | --- |
| `test_canvas`、`test_labeling`、`test_config`、`test_settings`、`test_correction_metrics` 和批处理范围测试 | 1563 通过、1 跳过、8 既有失败（含 2 个子测试）、143 子测试通过。11 分 37 秒 |
| Windows 完整 CI 范围，排除工具栏布局与点云 | 2110 通过、30 跳过、14 既有失败（含 2 个子测试）、173 子测试通过。13 分 34 秒 |
| CI 排除的工具栏布局，Windows 单独执行 | 两项失败。`20cba258` 独立副本使用同一 Conda 环境复现相同断言。按钮高度为 26（预期至少 28），缩放后尺寸 39×39（预期 42×42） |
| CI 单独运行的点云 | Windows 无 Linux xcb、Xvfb 和软件 GL 组合，未执行 |

逐项对照 [移除前 Windows 失败清单](../maintenance_baseline_20261117/full-recheck-summary.json)，14 个失败项的用例及原因均可对应。包括远程自动标注 JPG 临时文件权限 2 项，训练 YAML 正则、用户路径和进程停止 3 项，属性编辑替身缺少 `copy` 和 `_metadata_generation` 2 项，图片标题路径 1 项，属性上传 1 项及 2 个失败子测试，视频 MP4 临时文件权限 2 项，透明度提示措辞 1 项。

移除前失败中，四项 `test_shape_filter` 随复核分支退出转为通过。画布亮度节流用例本轮通过。旧的跨批次交接用例随专属功能退役。移除前 JUnit 中 Inspector 和 Dense Review 分别有 217 和 309 条用例记录。本轮不收集两个专属目录，并删除成本统计测试中 6 条专属运行接线用例，保留普通撤销、重做及历史复核计数的断言。

人工真实屏幕、物理双屏、真实训练与真实模型推理留待独立验证。窗口和编辑用例在 offscreen 中运行，批量预标注使用测试预测结果。

Python 定向静态检查未发现新增缺失名称或未使用的局部变量。`label_widget.py` 的四条 F841 在 `20cba258` 同样存在。收尾格式调整后复验矩形预览及旧数据兼容，61 项通过。

## 规格与恢复

同步九份增量。七份完全退役的主规格经 54 条标题逐一核对后移除，画布恢复替换一条有效要求，旧数据兼容新增三条。旧密集复核和界面打磨分别按 61/66、20/20 归档，原增量和证据留在对应归档目录。现行主规格及活动变更 `openspec validate --all --strict` 为 21 项通过。

移除前完整恢复点为 `20cba258f6f7fb23cb794c8e9606d537e2d5e9b6`。共有写入、Inspector 和 Dense Review 三个本地提交分别为 `6cba0176`、`651177f7`、`959a166f`。单项恢复按 [CUSTOM-126](../../docs/custom_changes/2026-11-18-remove-inspector-and-dense-review.md) 的依赖说明进行。
