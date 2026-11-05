# Inspector 工作流实施与验证

> 最新验证：2026-11-05，代码与自动化任务 52/55 完成，仅 10.3–10.5 人工验收待办。最新范围、命令与原始证据见本页末尾及 [任务记录第 14 节](tasks.md#14-2026-11-05-代码实施与验收范围)；下方 2026-11-02/04 数字属于历史记录。

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

# 2026-11-04 复核修复轮

本轮按任务文档第 11 节 R01–R13 修复，未改动其他 OpenSpec 变更。核心改动与证据索引见 [tasks.md](tasks.md) 第 13 节；此处只记录执行命令与结果。

- 新增纯服务模块：`services/inspection/parameters.py`（规则参数契约）、`services/inspection/review_queue.py`（复查队列合并、逐来源验证、反馈绑定、画布操作守卫）。
- 主要修改：模型（逐来源验证、输入诊断、图片摘要种类、范围说明、数据集键）、manifest（异常坐标诊断、变更范围、排除记录）、runner（全失败计数、排除/取消/超时/截断）、verification（输出身份规范化、图片身份）、storage（数据集隔离与迁移、会话冲突）、importers（原生报告往返）、Inspector 控制器/对话框（令牌与代际、筛选、恢复、跨文件守卫）、`label_widget.py`（未加载文件/区域导航、加载失败保护、删除/重标文件身份校验）。
- 新增测试：`tests/test_inspection/test_review_queue.py`，并扩充 manifest/profiles/runner/storage/verification/importers/inspector_dialog 用例。

实际命令与结果：

```powershell
$env:QT_QPA_PLATFORM='offscreen'
$env:PYTHONDONTWRITEBYTECODE='1'
C:/Users/20441/.conda/envs/x-anylabeling-cu12/python.exe -B -m pytest tests/test_inspection -q --tb=short -p no:cacheprovider --basetemp=<工作区内临时目录>
```

结果：**123 passed**（纯服务 108、Inspector GUI 15），0 failed。定向回归：`tests/test_canvas/test_navigation.py` 非 MainWindow 用例 81 passed，`tests/test_labeling/test_batch_edit_fields.py` 21 passed，`flake8 --select=F,E9` 对本次涉及目录无命中。

未运行：完整 `tests/test_labeling`/`tests/test_canvas`、真实磁盘故障、跨进程冲突、性能基准、密集复核真实交接和两位使用者试用。当前工作树的 `tests/conftest.py` 属于并行的用户配置重构，直接构造 `MainWindow` 会因缺少活动配置会话弹出模态错误框；Inspector 窗口夹具本轮显式建立测试会话后运行，其他 GUI 套件的既有挂起与本变更无关。Windows 沙箱下 pytest 临时目录需要工作区内的 `sitecustomize` 兼容层（未写入仓库）。

勾选口径：本轮只勾选具有失败路径自动化证据的 15 项；5.6、5.7、6.6、6.7、7.6、8.3–8.5、9.3、10.3–10.5 等保持未勾选，残余限制见 [tasks.md](tasks.md) 13.3。

## 2026-11-05：剩余代码接入与交付验证

当前进度 **52/55**；10.3、10.4、10.5 按用户“暂无记录，保留人工验收待办”的明确答复保持未勾选。新 [操作说明](../../../docs/zh_cn/inspector.md) 已提供，不能据此替代真实使用者的间隔后验证。

变更覆盖：图片内容/EXIF/微坐标摘要；方案导入只读保护；差分编辑与删除同步；有界候选和运行问题缓存；不可覆盖、分批写入与分页报告；另存与打开报告位置；候选先调整后接受、持久意图、保存/撤销/重做和损坏恢复；跨文件覆盖层守卫；跨页队列恢复、部分复查 manifest 合并与实际密集复核交接；可配置快捷键和四语资源。对应任务与逐条证据见 [tasks.md 第 14 节](tasks.md#14-2026-11-05-代码实施与验收范围)。

| 检查 | 实际结果 | 原始证据 |
| --- | --- | --- |
| 完整 Inspector（排除无断言临时诊断） | 192 passed | [inspection.xml](evidence/20261105/inspection.xml) |
| 设置/schema/runtime、批量编辑、编辑命令范围、导航 | 116 passed、1 skipped、2 deselected、11 subtests passed | [related.xml](evidence/20261105/related.xml) |
| 运行器/复查状态/全局预算/性能定向 | 30 passed，与全套重叠 | [budget.xml](evidence/20261105/budget.xml) |
| 最后候选覆盖层和未保存提示补验 | 9 passed，与全套重叠 | [overlay.xml](evidence/20261105/overlay.xml) |
| 单独性能基准 | 3 passed，与全套重叠 | [performance.txt](evidence/20261105/performance.txt)、[performance.xml](evidence/20261105/performance.xml) |
| 四语字面量/编译资源 | 每种语言覆盖 268 条 UI 字面量，内嵌 qm 可加载 | 资源测试及目录静态比对 |

性能样本为本机 Intel64 Family 6 Model 165 Stepping 3 / GenuineIntel、Python 3.12.12：120 个矩形、416 个候选，运行 **0.1299 s**；160 个矩形×3 文件，在首个文件进度回调取消，返回 **0.0090 s**，总耗时 **0.2165 s**。超上限明确 partial/truncated，不依靠静默删结果满足门槛。该数据不覆盖共享盘阻塞 I/O 或更大规模压力。

可重复命令（PowerShell，仓库根目录）：

```powershell
$env:QT_QPA_PLATFORM='offscreen'
$env:PYTHONDONTWRITEBYTECODE='1'
$py='C:/Users/20441/.conda/envs/x-anylabeling-cu12/python.exe'
& $py -B -m pytest tests/test_inspection --ignore=tests/test_inspection/test_zz_diag.py -q --tb=short --color=no -p no:cacheprovider --basetemp=.tmp/inspector-recheck-new
& $py -B -m pytest tests/test_settings/test_schema.py tests/test_settings/test_runtime_applier.py tests/test_labeling/test_batch_edit_fields.py tests/test_labeling/test_editing_command_scope.py tests/test_canvas/test_navigation.py -k 'not image_switch_restores_fractional_zoom_and_pan_and_fit_resets and not shared_view_tracks_revisits_and_reset' -q -p no:cacheprovider --basetemp=.tmp/inspector-related-new
& $py -B -m pytest tests/test_inspection/test_performance.py -q -s -p no:cacheprovider --basetemp=.tmp/inspector-performance-new
& $py -B -m flake8 --jobs 1 anylabeling/services/inspection anylabeling/views/labeling/inspector tests/test_inspection/test_completion_regressions.py --select F,E9
openspec validate refactor-data-inspector-workflow --strict
```

跳过项是当前环境没有可用字体族的字体切换用例；两个 deselected 是既有 MainWindow 配置会话夹具不完整的导航用例。Inspector 的真实窗口夹具、批量操作、交接、候选和独立子进程冲突已运行。没有宣称完整 labeling/canvas 回归或真人试用通过。

本轮处理中发现并修正两个验证问题：新增快捷键使设置字段数从 147/90 变为 149/92，更新相应断言后相关回归通过；`QTranslator.translate` 原生 char* 接口使用 UTF-8 字节后资源用例通过。普通沙箱下的 Qt DLL 与格式化器子进程限制通过已授权的工具执行解决，未改动用户真实设置。

回退只撤销本功能差异；保留独立报告、反馈、候选意图以及用户已保存的标注。未执行 Git 提交或 OpenSpec 自动归档。
