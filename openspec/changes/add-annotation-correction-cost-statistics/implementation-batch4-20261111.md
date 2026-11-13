# 第 4 批（遗留代码项）实施记录（2026-11-11）

范围：批次 1–3 遗留的**代码可完成项**。本批勾选 **2.2、2.5、3.3、4.4、5.1、5.3、5.5、6.5、6.6**；
`tests/test_correction_metrics/` 由 **311 → 334 passed**（新增 23 个用例）。

本批不触碰真实桌面才可验证的项目（7.5 尾项、9.2、9.4、9.5、10.4 GUI 部分），
理由见 §5。

## 1. 2.2 图片内容身份下沉到服务层

`anylabeling/services/correction_metrics/core.py` 新增：

- `IMAGE_DIGEST_LIMIT = 64 MiB`；
- `image_content_digest(path, limit=...)`：≤ limit 时 SHA-256 全文摘要；超大文件回退
  `size:<n>:mtime:<ts>`；不可读返回 `""`（未知版本，而不是一个共享常量）。

`views/.../controller.py` 的 `content_digest()` 改为薄别名，`enter_image` / `prediction_applied` /
`prediction_saved` 继续调用同一实现。`tests/test_correction_metrics/test_identity_digest.py`
新增 5 个用例：同内容不同路径同摘要、内容变化换摘要、缺失文件未知、
超大文件回退、同名图片不同根目录数据集身份不同。

**为什么之前没勾**：批次 1 审计只看到"服务层未实现摘要"。现在摘要本身在服务层，
调用方最多传错路径，不会再各自实现一套。

## 2. 2.5 显式类别版本

`core.py`：

- `initialise_state()` 新增 `category_version: 1` 与 `class_migrations: []`；
- `CorrectionRound._record_class_migration()`：只有**实际发生变化**的声明才追加记录
  （`{version, previous, mapping, comparable, seq}`），版本号 +1；同一个映射重复声明幂等；
  恒等映射（`{"cat": "cat"}`）不消耗版本号；合并/拆分会把 `comparable=False` 一并写进记录；
- `report_row()` 新增 `class_version`、`class_migrations`；`category_version` 优先使用预测来源的
  类别版本，只有本地有迁移记录且来源未知时才回退为 `local-v<version>`，**不改变 CSV 契约列**。

新增 4 个用例（`test_taxonomy.py`）：一对一改名生成 v2 且幂等；恒等声明不生成版本；
合并生成版本且标不可比；来源类别版本优先于本地标签。

## 3. 3.3 故障恢复入口

`storage.MetricsStore.retry()`：

- 写入线程仍存活：只做一次 `flush` 探活，成功则清除粘性 `error`；
- 线程已退出（致命 SQLite 错误、库被重建、只读文件恢复可写）：先以只读方式验证库可打开，
  再启动新的写线程；
- **不删除任何已记录的 gap / `_target_faults`** —— 恢复后的库不能看起来像从未丢过数据。

`controller.retry_storage()` 调用它并清除对应降级键；`degraded_reason` 现在也会直接显示
`store.error`（即使没有观察者调用失败）。`panel.py` 新增 `retry_requested` 信号与
`metrics_retry_button`：仅在存在记录异常时出现，控制器负责连接；`i18n.py` 补齐四语文案。

新增 3 个用例（`test_fault_matrix.py`）：写线程退出后 retry 可继续落库、retry 不隐藏已记录缺口、
controller 重试后降级横幅消失。另有面板可见性用例（`test_panel_review.py`）。

## 4. 4.4 / 5.1 / 5.3 / 5.5 / 6.5 / 6.6

### 4.4 矩形入口事务

代码在批次 2A 已接入（创建、删除、复制、粘贴、批量改类、拖动/拖边/拟合/微调），本批补三方面证据
（`test_net_diff.py`）：

- 复制/粘贴得到**新身份** → `added=1 / transactions=1 / touches=1`；
- 同身份同内容（含 `locked` 开关）→ `patch()` 返回 False，事务、触达、去重对象均为 0；
- 一次批量粘贴 3 个新对象 → 1 事务、3 触达、3 去重对象。
  逐入口 GUI 回归仍归 9.2。

### 5.1 连续自动保存

新增 2 个用例（`test_checkpoint.py`）：

- 同一内容连续 `prepare_save`+`saved` 三次：revision 只有一个，`transactions/touches/geometry`
  不重复增长，`time.working` 保持 12.0s（保存不清空过程成本）；
- 一次保存失败后 revision 保持上一次成功值，草稿仍标 `is_draft`。

### 5.3 / 5.5 完成与继续修正

- 5.3 的"完成本轮"、范围可见的批量完成（`complete_scope` + 汇总对话框入口）已在批次 3 补齐，
  本批只核对语义并勾选。
- 5.5 修复一个真实计时缺陷：`finish_round()` 成功时只改轮次状态，**没有关闭 WorkClock**，
  完成后的浏览仍在累加处理时间。新增 `_freeze_clock()`：适配器存在时
  `adapter.set_completed(True)`，否则 `clock.change(completed=True)`，随后写 `closed=True`
  检查点。`resume_round()` 仍以新会话继续累计（旧会话已闭合，报告按会话求和）。
  新增用例 `test_completion_extra.py::test_finishing_freezes_the_timer_and_resume_starts_a_new_session`：
  20s → 完成 → 浏览 30s 仍为 20s → 继续修正 5s → 两会话合计 25s。

### 6.5 模型运行与阻塞等待分开展示

- 服务层本就分开：`inference_seconds`（预测来源）与 `time.blocking_wait`（阻塞状态），
  报告/CSV 也分列；本批补**界面并列展示**：面板新增 `model_runtime`、`blocking_time`
  两行（`N/A` 表示未知，绝不与处理时间相加），汇总表新增 `inference_seconds`、
  `blocking_wait_seconds` 两列；`reporting.saved_row` 增加扁平化 `blocking_wait_seconds`
  供表格读取（CSV 仍从 `time` 派生，两者同源）。
- 新增 3 个用例：`20s 推理 + 20s 审图` 分别记录且无 `elapsed_total`；面板两行显示；
  汇总表两列显示。
- 阻塞等待的接线沿用批次 2B：`clock_adapter._is_blocked()` 读取 `_batch_processing_active`，
  批量预标注期间整段记为 `blocking_wait`，不计人工处理。

### 6.6 每秒持久化与崩溃尾段

`controller.tick()` 每秒写一次绝对快照，`clock_adapter` 心跳同为 1s；`WorkClock` 的
`max_gap` 把长间隔记为 timing gap。新增用例（`test_timing.py`）：
5 个真实 tick 后 `working == 5.0`；模拟异常退出（写线程结束但不 `close()`）+ 停机 3600s 后重开，
恢复值仍是 5.0s、带 `interrupted-time` 缺口；再 tick 1s 只增加 1s。证明停机时段不被补算。

## 5. 仍然未勾选（必须真实桌面/人工）

| 任务 | 原因 |
| --- | --- |
| 7.5 | 新文案已进 `i18n.TRANSLATIONS`（四语回落），但 `lupdate`/`lrelease`/`pyrcc` 未重编译；真实屏幕焦点/快捷键核对未做 |
| 9.2 | 需要真实桌面逐入口 GUI 回归 |
| 9.4 | GUI 主线程 p95 与 10,000 图规模需真实桌面；服务层数据见 `verification.md` |
| 9.5 | 两位使用者对照试用，必须真人 |
| 10.4 | 关闭/回退后的 GUI 行为；服务层 12 用例已通过 |

对应条目仍在 [manual-acceptance-checklist.md](manual-acceptance-checklist.md)。

## 6. 验证

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| 统计测试全量 | `pytest tests/test_correction_metrics -q -p no:cacheprovider` | **334 passed** |
| 设置/组件回归 | `pytest tests/test_settings tests/test_widgets -q --tb=no -rf` | 142 passed, 1 skipped, 4 failed（均为本功能未触及的画布调整/工具栏布局，见 §7） |
| 标注回归（抽样） | `pytest tests/test_labeling/test_edit_mode_shortcut.py tests/test_labeling/test_label_widget_brush_mode.py` | 8 passed, 1 failed（沙箱 `config.yaml` 写到隔离区外，非功能失败） |
| 静态检查 | `flake8`（7 个改动文件） | 仅 3 条既有告警（W504 ×1、E129 ×2，均在未改动代码上） |
| OpenSpec | `openspec validate add-annotation-correction-cost-statistics --strict` | `Change 'add-annotation-correction-cost-statistics' is valid` |

## 7. 已知问题与说明

- `test_widgets` 的 4 个失败与 `test_labeling` 的 1 个失败在本次改动前即存在（画布调整节流/工具栏
  几何、沙箱配置写保护），与本功能无关；未修改相关代码，也未放宽写保护断言。
- 本批**没有**运行 `black`：仓库现有 `correction_metrics` 源码并非 black 输出格式，执行 black 会产生
  ~1200 行与本功能无关的重排；本次只按周边风格手工对齐，避免混淆审查。`flake8` 新增代码零告警。
- `.ts/.qm` 仍待统一重编译（7.5）；当前新文案通过 `TRANSLATIONS` 四语回落在界面生效。
