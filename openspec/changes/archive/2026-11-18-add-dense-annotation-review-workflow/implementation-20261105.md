# 密集标注复核工作流：2026-11-05 实施与验证

状态：本轮代码实施及可自动验证的功能已补齐；整体验收仍未完成。真实屏幕/无障碍、两位使用者试用与独立质量复核没有执行；大范围 Qt 合跑提前退出仍待定位，不自动归档。

## 基线与修改范围

- 工作树：`codex/4.2.1-baseline-organization`，HEAD `67c98a80`。实施前已有大量画布、设置、Inspector 等未提交改动，以及导航同步、虚拟卡片和异步比较的部分实现。本轮在其上补齐、验证，没有重置工作区或将其他改动作为本次成果。
- 服务：`anylabeling/services/dense_review/{models,session}.py`。纯状态模型保持不依赖 Qt，运行时文字可由 UI 提供翻译回调；数据版本和原有身份/确认语义保持。
- UI：`anylabeling/views/labeling/dense_review/{workspace,thumbnails,config_dialog}.py`。补齐逐框/暂跳跨批次前进，先更新游标再自动保存；查漏重开后恢复画布区域；比较视图支持异步结果、失败重试与关闭清理；卡片区和批次区可单独收起。
- 资源：本功能中英日韩文案、动态状态/规则提示及实际 Qt 上下文，重新编译 `.qm` 和 `resources.py`。保留其他功能已有翻译；未将日/韩的其余历史未译项计作本次全部完成。
- 工具与测试：修正基准脚本的计时终点、期望目标、模型 API 和真实切图资源测量；补充保存冲突、自动保存、真实 executor 生命周期及翻译资源回归。旧 GUI 夹具的真实配置启动通过可选测试插件补齐，不屏蔽配置写入错误或放宽隔离保护。

## 复核问题的处理

| 问题 | 本轮结果 | 证据 / 剩余部分 |
| --- | --- | --- |
| DR-01 会话/列表跨批次同步 | 批次完成、逐框完成、暂跳均检查会话、卡片、画布和确认范围；逐框末尾跨批次缺口已修复 | `test_cross_batch_completion_keeps_views_in_sync` 三种参数 |
| DR-02 图块/比较 | 冷缓存请求、迟到更新、失败重试、窗口关闭清理；容量恢复时可重新请求，卡片隐藏不阻断比较；内容变化不继承旧失败 | `test_direct_batch_click_schedules_visible_thumbnails`、`test_compare_cold_cache_requests_updates_and_failures` |
| DR-03 虚拟化 | 以模型/代理渲染替代逐对象控件，图标 LRU 48、provider 图像 LRU 64；增加真实任务和已解码结果共同的 32 项容量限制 | `test_card_view_virtualizes_and_bounds_resources`；资源原始 trace |
| DR-04 小窗口 | 类别栏和卡片栏可分别收起，保留数量、范围、动作及紧凑批次选择 | `test_small_window_can_collapse_each_auxiliary_panel`；真实屏幕 M1 待执行 |
| DR-05 翻译 | 字面量、动态状态和规则提示使用实际上下文；源码和内嵌 `.qm` 比较，并检查占位符 | 翻译测试；字体/读屏及人工语言检查 M1 待执行 |
| DR-06 性能终点 | 必须匹配调用者给出的预期批次和对象，列表、模型、卡片选择、画布选择一致，正确目标发生 paint，画布非加载且可用；错误/超时不计成低延迟样本 | 新基准报告；真实屏幕适用性 M5 待执行 |
| DR-07 资源 | 通过正常 `load_file` 切换两张图片及两个输出上下文，包含工作区关闭重开；记录 provider、图标、队列、在途任务与 RSS | 每规模 16 次及独立 64 次 trace；RSS 与逻辑缓存限额分开解释 |
| DR-08 保存/恢复 | 实际原子替换失败保持原文件与内存；实际拖框只在 release 保存，批次确认再保存一次；真实冲突对话框三条选择路径；重开查漏恢复到原区域 | GUI 测试与 JUnit；74 条 Scenario 映射 |
| DR-09 生命周期/回归 | 真实线程在拖动等待期间可取消；旧代际不发表、队列有界，关闭后不再接任务；相关子集通过 | 大范围合跑未完整结束，9.7 保留未完成 |
| DR-10 人工与交付 | 补齐可执行协议、指标分母、空图口径、交叉顺序与质量复核规则 | 只有协议，未冒充实际试用；10.4、10.5、11.3 保留 |

## 当前自动化结果

最终源码、测试和编译资源的 SHA-256 清单见 [source-sha256.json](evidence/20261105/source-sha256.json)。清单描述当前工作树文件，不代替原始运行记录或独立提交。

环境：Windows，Python 3.12.12，PyQt6 6.10.2 / Qt 6.10.0，`QT_QPA_PLATFORM=offscreen`，`PYTHONDONTWRITEBYTECODE=1`。配置及 QSettings 隔离到项目 `.tmp`，不使用真实标注数据。

| 检查 | 结果 | 原始记录 |
| --- | --- | --- |
| 密集复核全部测试 | **142 passed，602 subtests passed**，134.23 s | [JUnit](evidence/20261105/current-dense.xml)、[日志](evidence/20261105/current-dense.log) |
| 设置、Inspector 交接/对话框及相关标注操作合跑 | **186 passed，1 skipped，24 subtests passed**，114.60 s | [JUnit](evidence/20261105/related.xml)、[日志](evidence/20261105/related.log)；退出码 0 |
| Black / flake8 / OpenSpec / 差异检查 | 全部通过 | [Black](evidence/20261105/black-final.log)、[静态检查](evidence/20261105/static-final.log)；strict 与 diff 检查均通过，不以此替代功能或人工验收 |

密集复核命令：

```powershell
python -B -m pytest tests/test_dense_review -q -x -p no:cacheprovider --junitxml=.tmp/dense-implementation-20261105/current-dense.xml
```

相关子集包含 `tests/test_settings`、`tests/test_inspection/test_handoff.py`、`tests/test_inspection/test_inspector_dialog.py`，以及 `tests/test_labeling` 的 `test_digit_label_actions.py`、`test_editing_command_scope.py`、`test_batch_edit_fields.py`、`test_check_status.py`、`test_image_switch.py`、`test_label_file_load.py`、`test_label_file_save.py`、`test_shape_filter.py`、`test_label_locks.py`。采用：

```text
-p tests.test_dense_review.integration_plugin
--basetemp=.tmp/dense-implementation-20261105/pytest-scope
-q -o faulthandler_timeout=30 -p no:cacheprovider
```

该插件通过真实 `get_config()` 安装隔离配置会话，只对显式选择的运行生效；正常密集复核套件不依赖它。

### 未纳入通过结论的运行

- 最初沙箱导入 QtCore DLL 被拒绝，未进入测试；后续获准在可加载 DLL 的环境执行。
- 大范围首次合跑在 `test_canvas/test_navigation.py` 创建窗口时，因旧夹具绕过配置启动而停留在保存失败模态框，已中止并保存 [堆栈](evidence/20261105/regression.log)。
- 未补启动的相关合跑还出现测试临时配置目标不满足 `.tmp` 隔离守卫的错误，以及 `test_check_status.py` 相同模态框阻塞，已中止。没有将这些运行计作产品通过。
- 补真实隔离启动后的大范围运行包含 dense_review、settings、canvas、labeling 及 Inspector 交接，仍在画布部分提前退出，日志有一项失败但未生成完整 JUnit，无法给出最终通过数或可靠定责。见 [合跑日志](evidence/20261105/integrated.log)。不得把之后相关子集通过当作该次合跑通过；历史 settings 合跑崩溃问题也没有由此宣告全部关闭。
- 单独复验画布套件仍提前退出，实际退出码 `-1073740791`（`0xC0000409`），见 [日志](evidence/20261105/canvas.log) 和 [退出码](evidence/20261105/canvas-exit.txt)。补充系统字体路径 `QT_QPA_FONTDIR=C:/Windows/Fonts` 后，原字体度量用例通过，但原生退出仍出现；最后记录运行到 `test_rectangle_preview_overlap.py::test_nudge_preview_preserves_host_dirty[16777234-False-False]`，见 [逐项日志](evidence/20261105/canvas-fonts.log) 和 [退出码](evidence/20261105/canvas-fonts-exit.txt)。这仅定位运行位置，不能认定故障责任或推断相关测试全部通过；9.7 保留未完成。
- 首轮定向 GUI 复验确认查漏区域未恢复的失败：5 passed、1 failed，见 [修复前 JUnit](evidence/20261105/gui-baseline.xml)。修复后的证据包含在当前 142 项全套通过中。

## 性能与资源

最终代码的两种规模全部门槛通过。原始报告：[30 对象](evidence/20261105/bench-30-final.json)、[300 对象](evidence/20261105/bench-300-final.json)。历史 2026-11-03 数据不覆盖、不删除，不以新结果把过去失败改写成通过。

| 指标 | 30 对象 | 300 对象 | 门槛 |
| --- | ---: | ---: | --- |
| 暖对象切换 p95 | 23.925 ms | 43.298 ms | ≤150 ms |
| 暖批次切换 p95 | 17.740 ms | 36.355 ms | ≤150 ms |
| 卡片后台心跳 p95 | 2.938 ms | 4.024 ms | ≤50 ms |
| 开启工作区拖框回退 | -9.509% | -8.031% | ≤10% |
| 后台卡片拖框回退 | -1.771% | -4.939% | ≤10% |

参数：30 / 300 对象，每条件每轮 100 样本、3 轮；分别保存冷/暖对象及批次切换、心跳、关闭/开启工作区拖框及卡片后台负载。图内导航与真实切图分开记录。

```powershell
python -B scripts/benchmark_dense_review.py --objects 30 --samples 100 --repeats 3 --lifecycle-switches 16 --json .tmp/dense-implementation-20261105/bench-30-final.json
python -B scripts/benchmark_dense_review.py --objects 300 --samples 100 --repeats 3 --lifecycle-switches 16 --json .tmp/dense-implementation-20261105/bench-300-final.json
```

离屏软件绘制不是 GPU 桌面性能。只对本次环境和样本作结论，后台任务或设备差异可能改变结果；真实屏幕复验见 M5。

64 次资源运行的原始记录：[JSON](evidence/20261105/resources-64.json)、[摘要](evidence/20261105/resources-64.log)。30 对象 RSS 从 234.06 MiB 增至 250.17 MiB，后 32 次为 248.86–250.17 MiB；300 对象从 265.61 MiB 至 268.68 MiB，后 32 次在 267.98–269.44 MiB 波动。图标、缓存和任务数均在逻辑限额内。RSS 含 Qt/分配器暖缓存，不能由有限次数观测推断永远无泄漏；不把它等同 provider QImage 字节。

## 任务与人工验收

逐场景索引：[scenario-matrix.md](scenario-matrix.md)，全部 74 条 Scenario 均有可定位的测试或人工步骤映射。测试只证明其断言范围，带 M1–M5 的观察/手感项目仍待人工。

未完成项及实际状态以 [tasks.md](tasks.md) 为准。四语言真实屏幕/读屏、两位使用者交叉试用、独立质量复核和大范围 Qt 合跑未决问题保持未勾选，不宣称减负已验证或准备归档。

## 回退

先关闭工作区；按本轮文件清单回退相应补丁，保留其他功能的先前修改。统计进度命名空间继续保留，不能删除真实图片或标注。纯模型的新增翻译参数都有默认值，旧调用仍可运行；进度 schema 仍为 1。原有回退和数据核对说明见 [verification.md](verification.md)。
