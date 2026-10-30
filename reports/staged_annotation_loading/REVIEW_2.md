# staged-annotation-loading 第二轮复核

日期：2026-10-29。结论：上一轮四项问题的原复现及扩展回归已经通过；拖入图片的修复仍有两处边界缺口，建议补齐后验收。本轮只新增复核文档及测试，没有修改应用源码或真实数据集。

## 已确认的修复

- 两个 controller 只有在线程退出且当前代次队列排空后才释放 worker，未消费结果计入 is_running；原尾批竞态复现通过。
- 启动目录明确设置异步首图加载，旧 last_open_dir 设置不再覆盖启动目录；启动首图和带搜索的启动场景通过。
- 当前图片读取后同时更新存在性、审核和代次，回填阻断相关信号；有/无 JSON 和权限异常扩展测试通过。
- 空闲、路径扫描及元信息扫描期间拖入图片的已覆盖场景通过，原未审核导航永久等待不再出现；但以下时序和筛选边界尚未覆盖完整。

## 1. [P2] done 已收到但列表尚未建完时拖入图片，会遗漏新增条目

位置：`anylabeling/views/labeling/label_widget.py:8124-8125`、`:8235-8242`（以函数与分支为准）。

`import_dropped_image_files` 只看 `_view_timer.isActive()` 来决定把新文件放进 `_view_pending_dropped`。这个计时器在后台 done 已经收到、UI 仍分批消费 `_view_buffer` 时也保持活动。待拖入队列却只在收到 done 的那个分支搬入列表；done 已消费后再拖入，不会再发生第二次 done，所以文件一直留在 pending，列表结束时没有该项，也没有为它启动元信息读取。

真实窗口复现：600 张图片，驱动真实轮询至 `_view_finished=True` 且 `_view_buffer` 尚有条目，拖入目录外 extra.png，等待列表和状态扫描结束。extra.png 不在 image_list，`_view_pending_dropped` 仍保留其路径。

建议：将后台枚举完成与 UI 列表消费完成视为两个阶段。done 后的新拖入也必须进入可消费队列，或者在完成检查前统一排空 pending；不能仅在一次性 done 回调处理。维持去重及最终元信息扫描覆盖。

## 2. [P2] 拖入路径直接进入当前结果，绕过仍有效的搜索条件

位置：`anylabeling/views/labeling/label_widget.py:8128-8136`；done 分支直接追加 pending 同样缺少过滤。

空闲时拖入代码直接创建 QListWidgetItem；忙碌时 pending 也直接加到匹配结果。两条路径都没有应用当前文件名、序号或属性筛选。用户搜索框仍有条件，却看到不符合条件的文件；重新执行同一搜索又会移除它，结果不一致。

真实窗口复现：当前图片 cat.png，搜索 `cat` 并等待完成，再拖入 dog.png，列表变为 `[cat.png, dog.png]`，但搜索框仍是 `cat`。这属于本变更搜索结果正确性的未完成边界，不声称历史同步版从未有类似行为。

建议：完整路径集合可以接纳新文件，当前显示视图必须按最新条件重新匹配；属性匹配继续放后台。对 idle、扫描中、done 后缓冲未排空的拖入统一处理，并保留当前编辑内容。增加名称匹配与不匹配、序号、属性筛选下的拖入回归。

## 验证与性能证据

- 本轮实际重跑：`test_review_regressions.py`、`tests/test_staged_output_window.py`、`tests/test_staged_annotation_metadata.py`、`tests/test_utils/test_file_search.py`，**59 passed，28 subtests passed，54.81 秒**。日志 `review2-tests.log`。
- 新增 `test_review2_regressions.py` 两项测试：**2 failed，7.98 秒**，均为上述目标行为断言失败，日志 `review2-extra-tests-final.log`。初次试探选择 900 条时未进入所需时序，不作为缺陷证据；最终使用 600 条并等待真实队列就绪，成功进入并验证该边界。
- OpenSpec 严格校验和 git diff --check 通过。只进行文档格式校验不能证明实现行为正确。
- 修复者新增的 `review_fix_results.json` 记录首帧中位数约 0.099 秒、全状态约 6.497 秒；当前 label_widget.py SHA256 与该记录一致：`e8a729e5783aff66dbd5d240a608935b267f4abf4cdd52cac33d4f30c7e03496`。这是核对已有只读性能证据，本轮没有再次运行 PRW 性能测试。
- 所有新复现使用临时图片及 offscreen 真实 MainWindow。没有对原 PRW 图片或标注进行写入，没有更改任务勾选状态，也未宣称完整候选审核套件通过。

重跑新增测试（项目根目录，PYTHONPATH 为项目根及 benchmarks/canvas_drawing_20261029/.deps，QT_QPA_PLATFORM=offscreen）：

```text
D:/Python311/python.exe -m pytest reports/staged_annotation_loading/test_review2_regressions.py -q -p no:cacheprovider --basetemp=reports/staged_annotation_loading/review2-rerun
```
