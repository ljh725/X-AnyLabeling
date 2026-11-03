# 密集标注复核工作流实施报告

日期：2026-11-02（Asia/Shanghai）
分支：`codex/refactor-data-inspector-workflow`
实施前基线：`9a37c5474c390e93243e33a88e8232a19c833280`
状态：实施中；自动化测试通过，人工试用、性能门槛、翻译导出和训练导出往返未完成。实现尚未提交 Git。

## 备份与基线

- 现有远端备份分支/标签：`backup/refactor-data-inspector-workflow-20261102`，指向 `9a37c547`。
- 本功能另建了本地基线标签 `backup/add-dense-annotation-review-workflow-20261102`，已核验指向 `9a37c5474c390e93243e33a88e8232a19c833280`；该标签尚未推送到远端。
- 当前实现仍在工作区未提交。重装或恢复前应先按项目台账提交/推送并核对远端 SHA。
- 恢复基线：`git switch -c recovered/dense-review 9a37c547`，或克隆上述备份分支。

## 已实现

### 纯 Python 服务 `anylabeling/services/dense_review/`

- 版本化 `xanylabeling_dense_review` 命名空间；对象、批次、新增待处理、游标、确认签名、疑难/暂跳、查漏计划、区域基线。
- 类别/几何独立签名；矩形按规范化边界比较，等价点序和整数/浮点表达不误失效，真实微调仍失效。
- 全对象账本与稳定批次；改类不移动对象、不重复进入另一批；未配置/不支持形状进入“其他待处理”。
- 新对象独立“新增待处理”；删除保留会话内墓碑，撤销恢复原身份、位置和确认；复用身份但内容不同不继承。
- 批次候选集合排除疑难、暂跳、手动隐藏、临时筛选、加载失败、不支持对象；确认指纹防范围变化，重复确认幂等。
- 默认“一次确认整批”；可选仅类别/仅框；每批“完成并下一个”和“暂跳下一个”。
- 失效表：几何变化撤回两项；改类撤回类别，框规则不同或未知时撤回几何；纯显示变化不失效；规则变更保守失效。
- 整图重叠网格查漏；显式区域完成、疑难、暂跳、恢复；新增/删除/移动仅撤回旧/新位置相交区域，未知旧基线整图撤回。
- 完成条件由当前状态派生：对象两项有效、无疑难/暂跳/新增待处理、所有区域完成、无不支持形状；空标注图仍要求查漏。
- 进度撤销：批次确认一条撤销；编辑导致失效与编辑同步撤销；现有画布无重做栈，redo 未实现。
- 顶层命名空间与标注同一 JSON 原子保存；图像指纹仅在加载/会话建立时计算。

### UI `anylabeling/views/labeling/dense_review/`

- 非模态工作区入口（默认关闭），批次面板、对象卡片、规则简述、统计、动作栏、空间查漏页。
- 卡片显示短编号、类名、类别/框状态；可见项优先后台裁剪、可调上下文、有界 LRU、代际丢弃；失败显示“图块加载失败”并排除。
- 并排比较不复制标注、不改变身份；成员名单可查看。
- 焦点显示/全部标注/原图无标注；全图临时查看后恢复倍率、中心、目标、批次；切换目标前取消未完成草稿。
- 稳定倍率档位按框宽、高与上下文计算；细长目标不裁出视野。
- 疑难按钮可填原因；快捷键直接标记并留空原因；逐框完成/暂跳。
- 查漏区域虚线覆盖；普通平移/缩放/浏览不记完成；完成区域不自动确认新增框。
- 未保存进度显示“复核进度待保存”。

### 主窗口接入

- Workflow 菜单新增 Dense Review；配置读写到数据集/输出目录 `.xanylabeling/dense_review/config.json`。
- 会话随图片/输出目录重载；打开工作区恢复保存进度；未知版本保留原内容并阻止启动，用户可显式重建。
- 保存前注入进度；保存成功清理墓碑并标为已保存；保存失败保留内存进度与 dirty。
- 外部文件变化检测与明确重载/保留本地/取消对话框。
- 批次确认/内容编辑撤销接入现有 Ctrl+Z；批次确认在无画布编辑时也可撤销。
- Inspector 交接改为 `dense_review_available=True`、`dense-review.v1`；交接界面的人工验证未完成。

## 评审问题修复（F1–F4）

- F1 调框后卡片复用旧裁图：缓存键加入边界/上下文/源图版本，边界变化使旧缓存和失败状态失效；同 ID 旧请求被丢弃。
- F2 连续审核撤销只生效一次：撤销入口改为查看剩余动作顺序，连续审核操作可依次撤销。
- F3 全图返回覆盖用户倍率：返回局部时不再调用 `_focus_current()` 重新计算倍率。
- F4 框移走再移回后审核抢先撤销：统一动作历史按真实顺序记录审核与内容变更；同一内容哈希不再被当作事务顺序证据。
- 新增 7 项探针后 `tests/test_dense_review` 为 **70 passed**；详见 [评审响应](REVIEW-RESPONSE-20261102.md)。

## 自动化证据

| 检查 | 结果 |
| --- | --- |
| `tests/test_dense_review` | **70 passed** |
| `tests/test_inspection` | **80 passed** |
| 定向 labeling | **72 passed, 15 subtests** |
| labeling 全量 | **192 passed, 8 failed**, 45 subtests |
| canvas | **578 passed, 1 failed**, 83 subtests |
| widgets | **29 passed, 3 failed**, 2 subtests |
| settings 单文件 | schema 7；controller 13；dialog/runtime/shape 21 passed, 1 skipped, 9 subtests |
| utils/config | **85 passed, 8 skipped**, 28 subtests |
| OpenSpec strict | 通过 |
| flake8/Black/compileall/`git diff --check` | 通过 |

### 既有失败（与基线一致）

- canvas：固定屏幕标签宽度 `179 != 139`。
- widgets：亮度节流 `0 != 1`；工具栏布局 `26 < 28`、`39 != 42`。
- labeling：8 项 `SimpleNamespace`、Windows 路径/标题、Windows 临时文件权限失败。

`tests/test_settings` 整个目录一次运行时在 `test_dialog_layout` 后出现原生访问冲突；各文件单独运行通过。该组合运行未记为通过，也未确认属于本变更新增。

## 未完成 / 未验证

- 真实屏幕人工验收：卡片密度、缩略图上下文、失败状态、比较、快捷键、无障碍。
- 30 对象/6 类、小目标、遮挡规则差异、框截断手臂、错分第三批、无框图等授权样本。
- 性能：暖缓存首帧 p95 ≤150ms、GUI 心跳 p95 ≤50ms、拖框回退 ≤10%、缓存峰值；未实测。
- 两位实际使用者、顺序交叉对照、独立质量复核；减负未验证。
- `.ts/.qm` 翻译生成与四种语言；新增文案未进入翻译周期。
- 训练导出与旧程序标签往返；仅确认元数据不进入 shape。
- 卡片迟到/快速切图/关闭窗口等延迟注入测试。
- 完整虚拟列表与小窗口专用收起控件；当前为懒生成缩略图 + 可调整布局。
- 批次确认 redo（现有画布无重做栈）。

## 回退

1. 删除新增目录 `anylabeling/services/dense_review/`、`anylabeling/views/labeling/dense_review/`、`tests/test_dense_review/`。
2. 还原 `label_widget.py`、`widgets/canvas.py`、`settings/schema.py`、`configs/xanylabeling_config.yaml`、`tests/test_settings/test_schema.py` 与 Inspector handoff 的本功能改动。
3. 保留标注 JSON 中的 `xanylabeling_dense_review` 原内容；不要把它解释为旧审核通过。需要清理时先备份并显式删除该命名空间。
