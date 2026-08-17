## 1. 建立状态机契约与纯数据模型

- [x] 1.1 新建 `widgets/viewport_state_machine.py`，定义 `ViewportStatus`、`ViewportSource` 和受支持的缩放模式枚举或常量映射。
- [x] 1.2 将 `ViewportState` 定义为 `frozen=True` 的不可变快照，并实现正缩放值、有限中心坐标和有效缩放模式校验。
- [x] 1.3 定义不可变 `ViewportLoadPlan`，能够表达 `FORCE_DEFAULT`、`EXACT`、`PREVIOUS_VIEWPORT`、`PREVIOUS_SCALE` 和 `DEFAULT` 五种来源及其载荷。
- [x] 1.4 实现单一 FileId 规范化函数，覆盖绝对路径、路径分隔符、相对路径和 Windows 大小写一致性。
- [x] 1.5 实现稀疏 `ViewportStateMachine`，以内存映射、pending 集合和 active FileId 派生 `UNKNOWN`、`CACHED`、`RESET_PENDING` 三种状态。
- [x] 1.6 封装只读状态查询和调试快照，停止向业务代码暴露可直接修改的内部字典。
- [x] 1.7 添加状态不变量检查，保证同一 FileId 不得同时存在精确历史和 pending 标记。

## 2. 实现状态转换和加载计划解析

- [x] 2.1 实现成功捕获提交：`UNKNOWN/CACHED → CACHED`，只覆盖同一图片的最后一次有效快照。
- [x] 2.2 实现单图失效：`UNKNOWN/CACHED → RESET_PENDING`，同步删除该图片的精确历史。
- [x] 2.3 实现 pending 消费，只有默认视图成功应用后才执行 `RESET_PENDING → UNKNOWN`。
- [x] 2.4 实现 active FileId 的成功提交与清除，确保继承来源始终是最后一个完成加载的图片。
- [x] 2.5 实现五级 `resolve_load_plan()` 优先级，并保证精确历史与 reset pending 不受 A 开关歧义影响。
- [x] 2.6 将 `keep_prev_scale` 表达为独立的 `PREVIOUS_SCALE` 计划，不允许其覆盖 B 或精确视口历史。
- [x] 2.7 实现批量 reset 的稳定去重、目标快照、事务提交和异常回滚结果。
- [x] 2.8 实现 `clear_session()`，一次清除精确历史、pending、active 文件和临时上一张缩放。

## 3. 为纯状态机建立转换矩阵测试

- [x] 3.1 新增 `tests/test_viewport_state_machine.py`，覆盖三种状态的创建、查询和互斥不变量。
- [x] 3.2 添加 A 开启/关闭 × 目标 UNKNOWN/CACHED × 上一张有/无状态的加载计划矩阵。
- [x] 3.3 添加 B pending 对 A 和 `keep_prev_scale` 的最高优先级测试。
- [x] 3.4 添加正序、倒序、重复访问和任意跳转测试，证明不同 FileId 不会反向覆盖。
- [x] 3.5 添加 FileId 多种路径写法归一为同一身份以及不同数据集清理隔离测试。
- [x] 3.6 添加当前、区间、全部目标的批量去重、UNKNOWN 目标 pending 和异常回滚测试。
- [x] 3.7 添加 5000 个已访问或待重置图片的线性操作测试，并断言切图解析不扫描完整文件列表。

## 4. 重构 Qt ViewportController 捕获路径

- [x] 4.1 让 `viewport_controller.py` 组合纯 `ViewportStateMachine`，保留必要的旧公开入口作为迁移 facade。
- [x] 4.2 定义不可变 `ViewportCaptureResult`，区分成功、无 pixmap、无滚动区域、无效缩放和无效坐标。
- [x] 4.3 将捕获改为“读取全部依赖 → 计算图像中心 → 完整校验 → 提交快照”的两阶段流程。
- [x] 4.4 保证捕获失败不覆盖最后一次有效快照，也不错误切换 active FileId。
- [x] 4.5 为零缩放、空 pixmap、缺失 QScrollArea、窗口 resize 和正常中心坐标往返添加 Qt offscreen 测试。

## 5. 重构 Qt 视口应用路径

- [x] 5.1 定义不可变 `ViewportApplyResult`，区分完整成功、无状态、无 pixmap、无滚动区域、无效状态和默认回退。
- [x] 5.2 在修改 ZoomWidget、Canvas 或滚动条之前完成 pixmap、状态、滚动区域和目标值预检。
- [x] 5.3 对应用前的缩放、模式、滚动条和 QAction 建立窄快照，在 Qt 更新异常时恢复进入前状态。
- [x] 5.4 将图像中心转换、滚动目标计算和边界夹紧集中到一个应用路径，禁止缩放成功但位置失败被报告为完整成功。
- [x] 5.5 添加手动缩放、适应窗口、适应宽度、跨尺寸图片夹紧和缺失滚动区域不半应用测试。

## 6. 收口 LabelingWidget 切图集成

- [x] 6.1 在 `load_file()` 保留“reset 前捕获旧图”和“pixmap 就绪后处理新图”两个明确生命周期点，删除分散的状态决策。
- [x] 6.2 接入“解析计划 → Qt 应用 → 成功提交”的单一路径，只有应用成功后才更新 active FileId 和消费 pending。
- [x] 6.3 新增 `_sync_viewport_ui()` 窄 adapter，统一同步 zoom mode、ZoomWidget、Canvas scale、Fit QAction、滚动条和 navigator。
- [x] 6.4 让精确恢复、A 继承、`keep_prev_scale`、默认加载和当前图片 B 重置全部复用同一 UI 同步入口。
- [x] 6.5 保证 A 开关只作为 `PREVIOUS_VIEWPORT` 策略输入，关闭时仍保存和恢复每张图片精确历史。
- [x] 6.6 处理应用失败：不吞 pending、不写成功缓存、不显示完整恢复成功，并安全回退默认视图。
- [x] 6.7 为正常切图、倒序、跳转、A 动态开关和窗口 resize 添加 LabelingWidget 集成测试。

## 7. 将 B 的重置事务迁入状态机

- [x] 7.1 调整 `_clear_view_state_for_files()`，使它只协调目标范围、状态机批量事务和旧缓存迁移，不再独立解释恢复优先级。
- [x] 7.2 当前图片重置时先提交失效事务，再应用默认视图，并仅在默认应用成功后消费当前 pending。
- [x] 7.3 非当前目标保持 pending 到未来首次成功默认加载；加载失败时验证 pending 仍存在。
- [x] 7.4 保留当前图片、从指定起点到末尾、全部图片三个范围，并验证顶部菜单、文件列表和两套画布右键菜单仍调用同一事务入口。
- [x] 7.5 保持反馈使用有效目标数、失败使用回滚结果，并验证 shape、dirty、配置和标注文件不发生变化。
- [x] 7.6 更新 `test_viewport_reset.py` 和 `test_viewport_context_menu.py`，改用公开状态查询，移除直接写 `controller.states` 的测试做法。

## 8. 淘汰双轨恢复缓存

- [x] 8.1 为状态机加载计划增加来源回归日志和 active FileId 提交断言，并确认旧恢复分支不再参与决策。
- [x] 8.2 删除 `load_file()` 中按文件恢复旧 `scroll_values` 的分支，由精确视口状态承担位置恢复。
- [x] 8.3 删除 `load_file()` 中按文件恢复旧 `zoom_values` 的分支，将 `keep_prev_scale` 改为状态机中的临时上一张缩放策略。
- [x] 8.4 简化 B 和 `_clear_viewport_session()`，删除已经没有恢复作用的旧缓存清理代码，视口状态统一由状态机维护。
- [x] 8.5 搜索并移除生产代码对内部 `states`、`force_default_on_next_load` 和旧恢复字典的直接修改。

## 9. 数据集生命周期、性能和文档验收

- [x] 9.1 核对打开独立文件、导入文件夹、关闭文件和替换数据集入口全部调用统一 `clear_session()`，普通同数据集切图不得清理状态。
- [x] 9.2 验证状态机不遍历 shape、不解码未打开图片、不读写标注文件，并记录正常切图 O(1)、批量重置 O(N) 的测试证据。
- [x] 9.3 更新 `docs/canvas-060_des_视口状态管理.md`，正式记录三态、五级优先级、三种重置范围和状态转换图。
- [x] 9.4 更新功能记录，明确 A 是继承策略、B 是高优先级失效事务、视口历史仅存在于数据集内存会话。
- [x] 9.5 运行视口状态纯测试、Qt offscreen 视口测试和 B 菜单测试，修复所有回归。
- [x] 9.6 对新增/修改 Python 文件运行 Black、Flake8 和 `py_compile`，确认 `label_widget.py` 的改动保持窄范围且无无关格式化。
- [x] 9.7 执行 OpenSpec strict validation，逐项核对规格场景与测试映射后完成实施交接。
