# 第 2 批 A 段实施记录（2026-11-10）：适配层与观察者接线

范围：把"有服务层但没有界面适配层"补上，使 `metrics_available()` 由恒假变为可用，并让 `label_widget` 预埋的 26 个观察点真正落到 controller。**本轮不声称完成 tasks.md 的 4.x/5.x/6.x**，逐条状态见 §4。

## 1. 交付

| 文件 | 作用 |
| --- | --- |
| `anylabeling/views/labeling/correction_metrics/controller.py`（约 700 行） | 会话协调器：数据集范围启用/本地库、按图片冻结起点、12 个观察者操作、WorkClock 计时桥、分页读取、CSV 导出、面板/汇总入口、`start_metrics()`、每秒心跳 |
| `.../panel.py`（约 560 行） | 可收起当前图片面板：来源/轮次/计时/计数/草稿与已保存净结果/完整性原因、N/A 规则、"开始-暂停-继续/完成本轮/查看汇总" |
| `.../report_dialog.py`（约 1270 行） | 汇总与导出：50/页分页、排除原因聚合、类别方向表搜索排序、密度/类别分组、两种 CSV + 指标字典、后台线程 + 取消 + 原子发布 |
| `.../i18n.py` | 补齐面板与汇总所需四语文案（171 条） |
| `label_widget.py` | 修复 `save_labels()` 失败路径的 `UnboundLocalError`（`metrics_token` 在 try 内赋值，except 引用会掩盖真实保存错误） |

## 2. 观察者接线（26 处调用点）

`notify_metrics` 的 26 处调用现在都能命中 controller：

- `enter_image` / `leave_image` / `stop`：切图与关闭生命周期（含计时片段收尾、flush）
- `edit(kind, source, changed=, removed=)`：create/delete/duplicate/paste/geometry/relabel/attributes/undo/redo
- `prepare_save` / `save_result`：保存检查点（成功才推进 revision）
- `discard`：丢弃回到最后保存版本并保留过程
- `review_event(kind)`：复核确认/撤销
- `prediction_applied` / `prediction_unapplied`：单张预测应用与迟到结果
- `geometry()`：无对象 ID 的旧信号，按"记录不完整"披露（`unidentified-geometry`），不伪造数量
- `reconcile_dirty()`：仅刷新，不作为操作账本

## 3. 验证（可复跑）

```powershell
$env:QT_QPA_PLATFORM='offscreen'; $env:PYTHONPATH='D:/X-AnyLabeling-4.2.1'
& C:/Users/20441/.conda/envs/x-anylabeling-cu12/python.exe -m pytest tests/test_correction_metrics -q --tb=short -p no:cacheprovider
```

结果：**114 passed / 0 failed**（原 64 + controller 15 + wiring 5 + panel 14 + report 16）。
另有相邻回归 `test_settings/test_schema.py` 7 passed；`test_correction_metrics_gate.py` 的 MainWindow 用例在本沙箱离屏构造会挂起（既有环境限制），其"未完成工作区禁用入口"分支通过 monkeypatch 保持稳定。

## 4. 仍未完成的 4.x–6.x（不勾选，逐条原因）

| 任务 | 缺口 |
| --- | --- |
| 4.1 | `AutoLabelingResult` 仍无 `provenance` 字段；controller 只读取已存在的属性，模型/配置/提示词/耗时尚无来源 |
| 4.2 | 能记录"应用了预测"，但替换/追加模式靠 provenance 推断，缺字段时默认 replacement；迟到/取消路径已有 controller 方法但无调用方 |
| 4.3 | 批量预标注 `utils/batch.py` 直写 JSON，没有通知；逐图保存结果与起点未建立 |
| 4.4 | 创建/删除/复制/粘贴的 hooks 已带对象，逻辑可用；未做 GUI 级逐入口回归 |
| 4.5 | **拖动/拖边/单点拟合/键盘微调仍只走无 ID 的 `geometry()`**，无法归属对象；需要改 canvas 的完成事务携带对象 ID（下一步重点） |
| 4.6 | 数字/对话框改类已带 shapes；**全局类别管理 `LabelModifyDialog.modify_label` 未通知** `taxonomy_saved` |
| 4.7 | 撤销记事件但缺 `undo_of` 关联；Inspector 实际编辑部分接入；密集复核确认完全未接入 |
| 5.1 | 已接入并有测试（保存成功才推进、失败保留草稿） |
| 5.2 | 丢弃与切图已接入并有测试；**取消导航**未单独验证 |
| 5.3–5.6 | "完成本轮"可由面板触发且绑定成功保存版本；批量完成、完成失效、质量状态展示未做 |
| 6.1–6.6 | WorkClock 与每秒心跳已接线，但**计时状态机无单元测试**，前后台/锁屏适配器未接线，空闲扣除 UI、崩溃尾段处理未做 |

## 5. 已知限制

- 面板以独立窗口形式出现（`QWidget` 子窗口），未嵌入右侧栏；后续需要按 `design.md` D7 做成可停靠面板。
- `metrics_available()` 现在为真，菜单入口可用；但 4.x/4.5 的缺口意味着**拖动类操作会被标记为记录不完整**，这是诚实降级而非通过。
- 统计库目录默认 `~/.xanylabeling/correction_metrics/`，可用环境变量 `XANYLABELING_METRICS_DIR` 覆盖；不写共享盘。
