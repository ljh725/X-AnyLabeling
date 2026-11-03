# Inspector 工作流实施与验证

2026-11-02，实施分支 `codex/refactor-data-inspector-workflow`，基线 `9a37c547`。核心服务、Inspector UI 与主窗口入口已实现；任务清单中未勾选项仍视为未完成，未归档。

- 新增纯 Python 服务：`anylabeling/services/inspection/`（模型、方案、规则、重复框、manifest、运行器、存储、导入、候选、交接）。
- 新增 UI：`anylabeling/views/labeling/inspector/`；`label_widget.py` Workflow 菜单入口与画布桥接。
- 新增测试：`tests/test_inspection/`，覆盖数据契约、方案、重复框、规则、取消终态、存储冲突、导入往返和 GUI 集成。

实际命令与结果：

```powershell
$env:QT_QPA_PLATFORM='offscreen'
C:/Users/20441/.conda/envs/x-anylabeling-cu12/python.exe -m pytest tests/test_inspection -q --tb=short --color=no -p no:cacheprovider
```

结果：**80 passed**。新增用例覆盖：删除只作用于画布选中对象、恢复报告核验当前磁盘与未保存画布内容、运行尊重用户选择的方案、manifest 读取失败计入请求/失败文件与 partial 终态。

相关回归：定向 labeling 25 passed；canvas 543 passed / 1 既有失败；widgets 29 passed / 3 既有失败；labeling 全量 192 passed / 8 既有失败；staged 32 passed；settings 20 passed；utils/config 85 passed / 8 skipped。既有失败已在基线 worktree `9a37c547` 复跑确认相同。

重复框核心与 beta4 对照：160 个矩形、38,160 对指标，指标最大差 0.0、分级不一致 0、候选对集合不一致 0；证据见 [duplicate_core_comparison.json](../../../reports/inspector_workflow_20261102/duplicate_core_comparison.json)。

`openspec validate refactor-data-inspector-workflow --strict` 通过。版本化运行/问题/证据/覆盖/反馈模型、当前图内存快照与批量磁盘快照、缺失/重复身份临时快照、四角点例外、L2-13、取消/部分完成终态、feedback/session revision 冲突、TSV/JSON 导入导出与 GUI 复查路径已有自动化。

未验证：方案改名/编辑/停用、批量删除与按类别重标预览、i18n/快捷键、逐次编辑增量结果、候选覆盖层/批量接受/撤销关联、密集复核交接、性能时延、两位使用者试用和人工验收。实施尚未提交 Git；回退与限制见 [实施报告](../../../reports/inspector_workflow_20261102/REPORT.md)。
