# staged-annotation-loading 实现复核

日期：2026-10-29。结论：首屏优化方向和主要实现有效，但存在 4 项已复现问题，不建议按“全部完成”验收。此次仅增加复核文档和复现测试，没有修改应用实现或原始数据集。

## 1. [P1] 线程退出与队列清理之间有竞态，最后一批结果可能永久丢失

位置：`anylabeling/views/labeling/utils/staged_annotation_loading.py:152-177`，同类问题在 `:298-318`。

`poll()` 先读取队列，再调用 `_start_pending()`；后者只判断线程是否存活，线程退出就直接清空 `self.worker`，没有检查该 worker 是否还有未消费的结果。

合法执行顺序是：GUI 看到队列空 → worker 发布最终结果并退出 → GUI 检查线程已退出并丢掉 worker。最后的元信息、匹配结果和 done 都留在无人读取的旧队列。元信息路径可能显示“检查完成”但若干文件一直未知；视图路径丢失 done 后 `_view_finished` 不会变为真，列表可能不完整并一直显示筛选中，后续元信息扫描不启动。

复现：测试在 queue.Empty 和线程清理之间精确放行真实生产线程。两个 controller 均复现，旧队列各留 2 条消息，controller.worker 已变为 None。

建议：将“生产线程退出”和“结果消费完成”分开。当前代次保留 worker，直到退出且最终队列已排空/终止消息已消费；过期代次可丢弃。pending/retry 切换遵循同一规则，is_running/完成判断应包含尚待消费结果。新增尾批、终止消息和取消交错的回归，不要只延长轮询间隔掩盖竞态。

## 2. [P2] 启动参数直接指定目录时首图不再自动加载

位置：`label_widget.py:3026-3047` 调用链与新 `_start_view`、`_poll_view` 的 `_view_first_load`。

构造函数仍调用 `import_image_folder(filename, load=False)`，原同步实现会立即确定 self.filename，再由构造末尾 queue_event(load_file) 加载。现在目录异步扫描，构造末尾 filename 仍为 None，加载事件没有排入；稍后 open_next_image(load=False) 只设置文件名，不加载图。

复现：真实 MainWindow(app, config=..., filename=临时图片目录)，等待视图和元信息计时器结束。列表含图片，filename 正确，但 image.isNull() 仍为 True，画布空白。

建议：明确启动目录的异步首图加载意图，在窗口初始化完毕且路径可用时加载一次，避免与构造函数末尾的文件加载重复。同步检查 last_open_dir 恢复与当前启动目录上下文的关系。增加启动目录、有/无标注、配置搜索条件的集成覆盖。

## 3. [P2] 提前打开尚未检查的图片后，存在性勾选状态不再补齐

位置：`label_widget.py:4843-4851`，与 `_poll_metadata` 的 revision 检查关联。

当前图真实加载后 `_update_current_file_checked_item()` 提高 revision 并设为 ready，但只更新审核值，不更新代表 JSON 存在性的 checkState。之后后台旧 revision 被正确拒绝，却没有别的路径补齐存在性。结果已正常读取的标注仍显示半选/待定；切换输出目录后也可能残留旧存在性值。

复现：暂停 b.json 后台元信息读取，用户主动打开 b.png（真实 JSON 正常读取），放行后台，等待全部完成。条目状态为 ready、审核通过，但 checkState 为 PartiallyChecked 而非 Checked。

建议：从当前图发布权威状态时，在阻断相关信号的范围内同时更新存在性、审核、generation/revision 和错误提示；成功解析且确无 JSON 的场景也明确设置 Unchecked。读取失败不能冒充成功 ready。增加扫描期间切图、有标签/无标签及旧状态切换覆盖。

## 4. [P2] 拖入新增图片没有接入代次状态，未审核导航永久等待

位置：新 `_metadata_state` (`label_widget.py:4739-4744`) 和 `_continue_review_navigation`，兼容入口 `import_dropped_image_files` (`:8088-8114`)。

打开目录后已有 metadata generation。拖入新图片仍用原 `_create_file_list_item()`，条目没有当前 generation/ready 状态，也没有加入后台扫描。导航将它判为 unknown 并调用 prioritize，但已完成的控制器没有 worker，永远不会返回结果。

复现：打开含 a.png 的目录，等待扫描完成，再拖入目录外 b.png；点击下一张未审核。b 没有标注，应按规则可导航，实际仍停在 a、pending navigation 保留，且所有扫描计时器都已停止。

建议：所有条目创建入口统一遵守状态协议；拖入的路径进入后台元信息请求并更新相关路径集合，或者在确实已同步读取的情况下发布完整当前代次状态。不得把“未知但无人负责读取”的条目交给导航等待；测试空闲及扫描中拖入多张图片。

## 验证结果与证据边界

- 重跑现有 `tests/test_staged_output_window.py`、`tests/test_staged_annotation_metadata.py` 和 `tests/test_utils/test_file_search.py`：**42 passed，28 subtests passed，37.16 秒**。
- 复核新增 `reports/staged_annotation_loading/test_review_regressions.py`：**5 failed，9.29 秒**，对应上述 4 项问题（队列竞态分别验证两个 controller）。失败是断言捕获到真实实现行为，并非缺失依赖或测试初始化失败。
- Qt 测试用真实 MainWindow、offscreen 和临时图片/JSON；竞态用可控线程调度稳定复现。没有对原 PRW 数据写入或重新跑大规模性能测试。
- 已核对交付报告与 final_results.json：带框首帧改前中位数 4.990 秒、改后 0.112 秒，改后全状态约 6.496 秒。当前 label_widget.py SHA256 与结果记录相同（4712e5a94710d9dce306d1ee558d67f38b07c48861ef2e068e65b749bc3887ad）。这是对已有性能证据的核对，不是本轮重新测得的数据；正常路径性能达标不能覆盖上述正确性缺陷。
- 原测试日志仍包含交付报告已披露的 Windows 原生模块堆栈；本轮未据此认定新增缺陷。此次没有声称完整候选审核套件通过。

执行环境：D:/Python311/python.exe；PYTHONPATH 指向项目根及 benchmarks/canvas_drawing_20261029/.deps；QT_QPA_PLATFORM=offscreen。

复现命令（在项目目录、上述环境下）：

```text
D:/Python311/python.exe -m pytest reports/staged_annotation_loading/test_review_regressions.py -q -p no:cacheprovider --basetemp=reports/staged_annotation_loading/review-repro-rerun
```

日志：`review-existing-tests.log`、`review-reproductions-all.log`。修复后保留这些回归并重跑相关测试；队列生命周期会影响完成计时，需复测相关性能指标。任务 2.4、3.2、4.1/4.2、6.2/6.5 的完成结论应重新核验。本轮不代替实现者修改清单勾选状态。
