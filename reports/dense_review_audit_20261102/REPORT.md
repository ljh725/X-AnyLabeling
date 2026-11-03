# 密集标注复核工作流独立复核

日期：2026-11-02（Asia/Shanghai）。对象：`add-dense-annotation-review-workflow` 当前工作区首版实现。

结论：**发现3项可复现问题，暂不满足最终验收。**现有63项新增测试通过不代表全部规格场景及减负目标已满足。本轮未修改应用代码、规格或任务勾选，仅新增复核报告与独立探针。

## 实际验证

- 独立重跑 `tests/test_dense_review`：**63 passed in 32.64s**。
- 独立补充探针 `test_audit_probes.py`：**3 failed in 7.03s**，分别对应以下3项问题，均为预期行为断言失败而非测试环境失败。
- `openspec validate add-dense-annotation-review-workflow --strict`：通过。此检查只验证文档结构，不表示代码验收通过。
- `git diff --check`：通过，存在其他文档的换行提示。
- 当前任务统计：52项勾选，11项未勾选；未改动任务书状态。
- 测试使用 Python `C:/Users/20441/.conda/envs/x-anylabeling-cu12/python.exe`、`QT_QPA_PLATFORM=offscreen` 和工作区临时样本。初次沙箱运行因Pillow DLL访问被拒而未收集；获准在沙箱外运行后，第一次因探针指定的临时目录父路径不存在出现44 passed/19 setup errors，建立父目录后完整重跑得到上述63 passed。环境错误不计为产品缺陷。

本轮未重跑全部历史回归、未使用真实业务图片、未进行可见窗口人工验收或两位使用者减负实验。

## F1 — [P1] 调框后对象卡片复用旧裁图

位置：`anylabeling/views/labeling/dense_review/workspace.py:795–798`；`thumbnails.py::cached_image`。

操作：打开工作区并等待对象卡片生成，将该对象矩形从原位置移动到另一位置，触发正常dirty/复核同步并处理GUI事件。

结果：对象账本边界已改变，卡片请求路径却只用shape_id查询当前代际的缓存，命中后直接跳过裁图请求。刷新卡片的签名也只有批次和成员列表；普通调框未提升缩略图代际。探针观察到移动后该对象没有发起新边界请求。旧卡片可能继续显示另一个人物，而框和类别文字已经更新，影响后续动作判断。

预期：缓存命中与请求至少关联当前边界、上下文和源图版本；调框后旧结果不能成为新内容的展示依据。修复应处理正在生成的同ID旧请求和已记录的失败状态，不能仅刷新文字。

对应任务：5.1、5.3、5.4、9.3。探针：`test_changed_bounds_request_fresh_card`。

## F2 — [P2] 一次审核撤销后，更早的审核历史无法继续撤销

位置：`anylabeling/services/dense_review/session.py:1006–1018`；主窗口 `undo_shape_edit`。

操作：确认对象a，然后将对象b标为疑难，执行一次撤销。

结果：b的疑难正确撤回，但`undo_progress`将`_last_action`清为空，导致`can_undo_progress()`返回false，即使更早的a确认仍留在进度历史。主窗口接下来会禁用撤销，或在尚有画布历史时转而撤销标签/框，不能按真实操作顺序撤回更早确认。这是undo问题，不是报告已披露的redo缺失。

预期：撤销入口依据剩余真实事务顺序和当前内容决定下一步；连续审核操作可以依次撤销，审核与画布编辑交错时仍保持正确顺序。

对应任务：3.6、7.7、9.2。探针：`test_two_progress_commands_can_be_undone_consecutively`。

## F3 — [P2] 从全图返回时覆盖用户局部倍率

位置：`anylabeling/views/labeling/dense_review/workspace.py:1170–1177`。

操作：进入单目标编辑，将倍率手动设为175%，通过工作区的“看全图/返回局部”按钮往返一次。

结果：主窗口先恢复保存的倍率和滚动位置，但工作区随后执行`_focus_current()`，重新按目标计算倍率和中心；探针实际返回800%，而非175%。用户需要重新缩放才能回到原来的观察尺度，违背减少重复缩放和恢复视图的要求。

预期：全图返回保留原目标、用户倍率和中心；恢复显示策略不能重新覆盖已还原的视图。

注：单独调用主窗口底层函数会看到聚焦隐藏未恢复，但实际工作区按钮另有恢复显示逻辑，因此本报告不把“聚焦显示丢失”列为缺陷；已沿真实按钮路径改为验证倍率恢复。

对应任务：6.4及工作区规格的全图返回场景。探针：`test_full_image_roundtrip_restores_user_zoom`。

## 未完成验收与记录一致性

任务1.3、3.6、7.8、9.3、9.5、10.1–10.5、11.1仍未勾选，包括授权密集图样本、完整撤销/重做契约、翻译、延迟注入、导出往返、性能及真实减负实验。报告已如实披露大部分限制，不能将52项勾选视为最终交付。

任务5.3勾选“卡片虚拟化”，实施报告同时说明当前仅为缩略图懒生成，完整虚拟列表未完成；建议收紧任务完成表述，避免将部分实现记为完整满足。当前尚无数据证明新增卡片界面减少疲劳或达到p95性能目标。

## 复现命令

在项目根目录创建可写的临时目录父路径后执行；不要复用已有重要数据目录作为pytest basetemp。

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
& C:/Users/20441/.conda/envs/x-anylabeling-cu12/python.exe -m pytest tests/test_dense_review -q --color=no -p no:cacheprovider --basetemp reports/dense_review_audit_20261102/pytest-temp-rerun
& C:/Users/20441/.conda/envs/x-anylabeling-cu12/python.exe -m pytest reports/dense_review_audit_20261102/test_audit_probes.py -q --color=no -p no:cacheprovider --basetemp reports/dense_review_audit_20261102/probe-temp-rerun --tb=short
```

探针保存在报告目录，不属于应用实施代码；修复后三项断言应转为通过，再补充交错历史和旧裁图迟到等邻近场景。
