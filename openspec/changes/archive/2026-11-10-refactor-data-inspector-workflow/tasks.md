状态：任务已关闭，55/55 已勾选；按用户指示归档（2026-11-10）。10.3–10.5 为用户决定关闭，未新增人工验收证据，详见归档决定。

> 历史记录（由 2026-11-10 归档决定更新任务状态）—2026-11-05 实施轮：在已有修复上补齐剩余代码接入、失败恢复与自动化验证，当前 **52/55 已勾选、3/55 未勾选**；最新范围和证据见第 14 节。用户明确确认暂无人工试用记录，10.3–10.5 保留为人工验收待办；操作说明已交付，间隔后可用性仍未宣称验证。下方 2026-11-04 的状态、问题及限制均为历史记录，按第 14 节判断当前状态。

> 2026-11-04 任务复核：仅更新本任务文档，未修改生产代码、测试代码或其他 OpenSpec 文件。原 40/55 项已勾选；本轮将 15 项退回未完成，现为 **25/55 已勾选、30/55 未勾选**。退回不代表已有实现全部无效，而是整项承诺尚不成立。问题与重新勾选条件见文末 R01–R13；未涉及的勾选保留既有证据，不代表本轮重新完整验收。

> 2026-11-04 修复轮：按 R01–R13 修改 inspection 服务、Inspector 控制器/对话框和画布桥接，并新增失败路径用例。现有 **40/55 已勾选、15/55 未勾选**；本轮复核结论见第 13 节，未勾选项与残余限制见 13.3。`tests/test_inspection` 当前 **123 passed**（纯服务 108 + GUI 15）。

> 实施前备份（2026-11-02）
>
> - 备份分支：`backup/refactor-data-inspector-workflow-20261102`
> - 备份标签：`backup/refactor-data-inspector-workflow-20261102`
> - 基线提交：`9a37c5474c390e93243e33a88e8232a19c833280`；父提交 `1038d555c997e8c42ba589d648ca2e45abd52c26` 保存既有未提交的编译翻译资源。
> - 远端核验：`git ls-remote origin` 返回分支与标签剥离提交均为上述基线 SHA。
> - 实施分支：`codex/refactor-data-inspector-workflow`，从该基线创建。
> - 恢复：`git clone --branch backup/refactor-data-inspector-workflow-20261102 https://github.com/ljh725/X-AnyLabeling.git <目录>`，或在现有仓库 `git switch -c recovered/inspector 9a37c547`。
> - 未纳入备份：`.commandcode/`、`.workbuddy/`、性能 profile、pytest 临时数据及其他无关未跟踪报告；明细与回退说明见 [实施台账](../../../../docs/custom_changes/2026-11-02-inspector-workflow.md)。

## 1. 固定迁移范围与回归基线

- [x] 1.1 核对当前工作树和既有失败测试，固定 beta4 来源提交或文件指纹，列出采用/不采用模块并记录本功能定制台账。
- [x] 1.2 固定旧重复框核心、L2-13、Inspector 导入和反馈的代表样例，形成可重复运行的对照夹具；历史结果不得作为本次通过证据。
- [x] 1.3 明确普通画布、编辑命令、持久身份、分阶段加载和密集复核的接入点，建立功能关闭时旧流程不变的最小回归用例。

## 2. 检查数据契约与输入适配

- [x] 2.1 实现版本化运行、问题、证据、覆盖范围和人工反馈数据模型，区分图片、对象集合和无正式对象的区域定位。
- [x] 2.2 实现按数据集根/输出根/相对路径隔离的完整文件 manifest，覆盖未加载文件、缺失 JSON、空标注及重名文件。
- [x] 2.3 实现当前图片已提交内存快照与批量磁盘快照适配，显示来源；批量 dirty 文档支持保存、显式排除和取消，保存失败不运行。
- [x] 2.4 实现数值/几何校验及持久 ID 核验；缺失或重复 ID 使用仅当前快照有效的临时身份，扫描不回写修复。（2026-11-04 修复：坐标解析不再静默丢弃坏点；`ShapeSnapshot.input_errors` 保留原始结构诊断，矩形几何与重复框规则显式报告输入异常，不会把修剪后的剩余点当作合法矩形。证据：`test_manifest.py::test_malformed_points_are_reported_not_trimmed`。）
- [x] 2.5 实现内容/图像边界/方向/配置及规则版本摘要，验证外部修改和保存规范化不会错误定位或虚假恢复有效状态。（2026-11-05：默认读取图片内容摘要与 EXIF 方向，方向进入变更比较；几何规范化保留真实微坐标变化。外部替换、保存规范化、边界/方向/版本摘要见 `test_verification.py` 与 `test_completion_regressions.py`。）

## 3. 方案和规则目录

- [x] 3.1 实现规则登记元信息、参数校验、作用域、依赖字段、实现版本和受控执行适配接口。（2026-11-04 修复：新增 `anylabeling/services/inspection/parameters.py`，为每条登记规则定义类型、范围、枚举、未知字段与跨字段约束（含 NaN/Inf、负上限、min>max），`RuleMeta.depends_on` 记录输入依赖，目录暴露 `parameter_specs/describe_parameters`；非法参数使方案不可运行。证据：`test_profiles.py` 新增 5 项。）
- [x] 3.2 实现场景方案 schema、版本快照、阶段规则选择和项目/输出目录绑定，校验未知规则及冲突关系。
- [x] 3.3 提供方案查看、复制、改名、编辑、导入/导出和停用，内置模板保持只读，历史报告保留原有效配置。（2026-11-05：管理入口及版本化存储已接入；导入内置模板或同 ID 方案创建独立副本，不能覆盖内置项。证据：`test_profile_management_keeps_builtin_read_only`、`test_profile_edit_keeps_history_report_snapshot`、`test_imported_builtin_cannot_replace_shipped_template`。）
- [x] 3.4 迁移适用的标签/图形/字段/几何基础规则，补足计数、成组完整性/唯一性、配对/包含构件及前提不足状态。
- [x] 3.5 提供通用矩形、屏幕角点、课堂动作模板及中文说明、正反例、标签映射和例外配置；未配置业务关系不作自动推断。
- [x] 3.6 验证场景隔离、总数抵消、全零、整组漏标不能证明完整、无可靠关联、遮挡例外以及显式运行可用子集。

## 4. 共享疑似重复框计算

- [x] 4.1 从 beta4 提取几何计算、阈值、快照、空间索引与增量核心到共享纯 Python 层，不迁移双屏窗口依赖。
- [x] 4.2 用固定有效输入验证旧新核心候选对与分级一致；保留旧指标尺度和预设，并单独测试异常坐标和不支持形状。
- [x] 4.3 实现同类、互斥、允许共存/包含及未知关系策略；改类重评策略、改组重评组规则，不混同几何风险和真实冲突。
- [x] 4.4 适配旧 L2-13 的独立规则身份与阈值，按文件、无序对象对及有效输入快照聚合展示；保留逐来源等级和验证状态，测试一个来源仍命中时其他来源不能清除问题。（2026-11-04 修复：`IssueEvidence` 增加逐来源 `verification/verification_reason`；复查按规则覆盖、截断、停用、实现版本逐源判定，任一来源未成功时整体保持未核验并保留队列；原生完整报告导入保留全部来源。证据：`test_review_queue.py` 多来源、截断、停用用例与 `test_importers.py` 双来源往返。）
- [x] 4.5 实现编辑提交后的新增/移动/删除/撤销增量更新及阈值变更全扫，验证增量与全扫一致、跨图同 ID 不串状态。（2026-11-05：从编辑提交边界通知 Inspector；差分同步移除已删或改类型对象，没有旧问题也能检出新问题，保留实际启用的新/旧规则来源。正常编辑不逐次全扫校验；阈值变化及截断基线回退有界全扫，截断不可作未再检出证明。证据：`test_incremental.py`、`test_first_issue_appears_after_editing_a_clean_image`、`test_committed_field_edit_updates_inspector_without_canvas_move`、`test_incremental_pair_budget_is_explicit_and_recovers_after_delete`。）
- [x] 4.6 补充 A-B-C 非传递重叠、合法多目标重叠、包含及全重叠压力案例，确认不把候选组自动归为同一实体。

## 5. 统一运行与报告

- [x] 5.1 实现当前图、选定文件、整个数据集和已变更文件四种执行范围，按摘要和依赖确定复查范围。（2026-11-04 修复：已变更范围比较标注状态/内容、图片摘要与尺寸、方案指纹与规则实现版本；新增无 JSON 图片、图片替换、删除路径与无变更均有显式范围说明，无法证明无变化时全量重检。证据：`test_manifest.py::test_changed_scope_sees_new_missing_annotation_and_image_change`、`test_runner.py::test_summary_counts_objects_per_file_and_images`。）
- [x] 5.2 接入纯函数规则及必要的已登记旧脚本适配器，自动准备输入和收集结果，不执行配置中的任意命令。
- [x] 5.3 实现后台进度、协作取消及 completed/partial/cancelled/failed 状态，修正旧算法取消空列表的歧义。
- [x] 5.4 实现逐文件逐规则覆盖记录和错误隔离，显示缺失、失败、排除、超时、未执行及截断，不将零问题等同于成功。（2026-11-04 修复：清单全部读取失败时保留请求/失败分母与逐文件覆盖；显式排除与扫描取消形成独立记录和范围说明；规则超时/截断单独标记并阻止“未再检出”结论。证据：`test_runner.py` 新增 5 项。）
- [x] 5.5 实现运行代际、输入版本及输出根隔离，验证切图、编辑、切方案和启动新任务时旧回调不能覆盖当前结果。（2026-11-04 修复：每次运行生成令牌并记录代际、数据集根、输出根与稳定配置摘要；控制器为每轮运行使用独立消息队列并按令牌丢弃旧消息；对话框在完成回调校验令牌/代际/上下文，迟到结果只归档到原数据集历史；运行期间画布编辑会触发结果复核。证据：`test_inspector_dialog.py::test_late_run_result_is_archived_not_applied`。）
- [x] 5.6 实现不可变运行报告、分批写入和分页读取，有界缓存及明确资源上限；测试写入失败和另选保存位置。（2026-11-05：相同 run_id/清单拒绝内容覆盖；序列化逐批转换对象，分页不先解码整个报告，缓存及页大小有上限，问题表每页 200 条。运行累计问题在逐文件合并时限量，未发布来源显式标截断；新增另存及打开报告位置入口。证据：`test_storage.py`、分页/不可覆盖/另存恢复/全局预算的 `test_completion_regressions.py` 用例。）
- [x] 5.7 验证常规数据取消响应及密集候选压力行为，记录测试机、输入规模与耗时，不靠静默删结果满足性能目标。（2026-11-05：本机 Python 3.12.12 实测 120 框产生 416 对；160 框×3 文件测量取消，另测候选及运行总问题上限。所有截断均传播至 coverage/report 并保持 partial。机器、耗时、取消边界和原始输出见 `evidence/20261105/performance.txt` 及第 14 节，不外推为真实共享盘或全数据规模性能保证。）

## 6. Inspector 入口与导航

- [x] 6.1 迁移必要 Inspector 容器并实现“方案＋阶段＋范围＋开始检查”主入口，高级导入/日志可展开，运行后自动显示结果。
- [x] 6.2 实现规则说明、参数、实际启用范围、前次配置及运行历史展示，使用户无需读代码确认本次检查内容。
- [x] 6.3 实现按规则、来源、风险和人工结论筛选的问题列表，明确区分问题、对象和图片数量。（2026-11-04 修复：新增规则/来源/风险下拉筛选并与人工结论组合；对象计数按“文件 + 对象 id”去重，图片数区分请求图片与问题图片；筛选状态随会话保存/恢复。证据：`test_runner.py::test_summary_counts_objects_per_file_and_images` 与 `test_inspector_dialog.py::test_cross_file_same_object_id_cannot_authorize_delete`。）
- [x] 6.4 实现稳定文件/对象/对象对/区域导航及原图上下文，缺身份或快照过期时降级，禁止按歧义 basename 自动定位。（2026-11-04 修复：导航支持报告中的 `image_path`、数据集根下尚未加载的相对路径、区域聚焦与隐藏对象提示；加载失败/取消时不选中或修改旧画布对象；歧义 basename 不再自动定位；对象缺失时返回失败并提示重检。证据：`test_inspector_dialog.py::test_navigation_resolves_unloaded_file_region_and_load_failure`。）
- [x] 6.5 接入现有切图保存、锁定、隐藏、聚焦和编辑命令，验证取消切图/保存失败时画布与队列选择一致。（2026-11-04 修复：删除/重标在生成目标集合、显示确认和提交动作三处核对数据集、输出根、当前文件及问题状态；跨文件相同 ID 不再授权操作，取消导航或加载失败不产生选中集合。证据：`test_cross_file_same_object_id_cannot_authorize_delete`、`test_navigation_resolves_unloaded_file_region_and_load_failure`。）
- [x] 6.6 实现重复框两者保留、删除指定框、调整和疑难暂存；批量删除及当前图指定类别重标先预览，均可撤销且不影响无关标注。（2026-11-05：保留/疑难动作不改对象；精确预览、跨文件守卫、锁定保护、单步撤销/重做及无关对象保持均已有窗口测试。证据：`test_inspector_dialog.py` 的保留/暂存、批量删除/重标用例，`test_zz_debug.py::test_batch_delete_records_one_undo_step` 和生命周期用例。）
- [x] 6.7 为新增文案、快捷键提示与操作入口接入现有翻译和快捷键配置，验证中文长标签及小窗口可用性，不占用已有核心编辑键。（2026-11-05：`shortcuts.inspector_run/inspector_locate` 接入设置、即时应用、禁用和冲突保护；四语目录覆盖当前三个 Inspector UI 类的 268 条字面量，重编译 qm 与内嵌资源。最小窗口、键作用域、四语资源及配置行为见 `test_translations.py` 和 `test_completion_regressions.py`；真实使用者观察仍归人工验收。）

## 7. 复核状态与可靠恢复

- [x] 7.1 实现人工判断、修复动作和机器验证三个独立维度，访问/导航不自动确认，声明已修改进入待复查。
- [x] 7.2 实现内容和规则变更失效、保守整文件关系复查及成功同范围复查后的未再检出状态。（2026-11-04 修复：复查合并保留其他图片队列；只有相关来源规则成功完成且未截断时才标记未再检出，取消/失败/停用/版本变化/范围缩小保持未核验；编辑使当前、待复查和已未检出项重新失效。证据：`test_review_queue.py` 取消、截断、多来源、编辑失效用例。）
- [x] 7.3 修复问题再次出现仍沿用已消失/误报状态的行为，保留历史证据并重新激活待处理项。（2026-11-04 修复：当前报告中重新命中的问题不再套用历史 `NOT_DETECTED`，回到待处理并追加历史；反馈记录绑定稳定配置摘要与输入摘要，方案或规则版本变化时只作历史。证据：`test_review_queue.py` 复现与反馈绑定用例。）
- [x] 7.4 实现独立 feedback/session 持久化、原子写入、revision 与排他写锁，冲突保留双方记录，写失败保留未保存状态。（2026-11-04 修复：检查存储按完整数据集身份分目录，feedback/session/candidate 记录带数据集键；旧共享目录仅按需复制迁移并保留来源说明；会话冲突写入双方版本文件；反馈或会话写失败保留内存待保存状态。证据：`test_storage.py` 数据集隔离、跨数据集反馈、迁移与冲突用例。）
- [x] 7.5 实现继续上次处理并核验报告、输入、方案、输出根及对象身份；损坏/未知版本保留原文件并显示不可恢复范围。（2026-11-04 修复：输出根按“默认位置/显式目录”规范化后比较，当前图报告固定内容图片身份，内存与磁盘分歧分别核验；恢复时由报告快照重建冻结方案供复查；损坏 JSON、未知格式、缺失清单、对象身份变化均受控提示并保留原文件。证据：`test_verification.py` 新增 4 项与 `test_reopened_inspector_restores_frozen_profile_and_reports_bad_json`。）
- [x] 7.6 验证撤销/重做、规则停用、部分复查、外部改文件及跨会话写入，不将旧结论误计为当前已完成。（2026-11-05：生命周期矩阵、两个窗口的冲突草稿保留与实际子进程 revision 冲突通过。部分复查保留其他图片的 manifest 并重算指纹；配置变化使未复查图片过期。证据：`test_lifecycle.py`、`test_review_queue.py`、`test_feedback_conflict_preserves_both_processes`、`test_one_file_recheck_keeps_manifest_for_other_queue_files`。）

## 8. 兼容导入与外部候选

- [x] 8.1 支持旧 TSV/CSV/JSON、L1/L2 报告及反馈导入，报告歧义路径、无法核验版本和无效记录，历史来源不覆盖当前队列。
- [x] 8.2 实现新完整报告与简化表格导出，标注多对象/区域及证据缺失限制，验证完整格式往返。（2026-11-04 修复：JSON 原生完整报告按结构逐字段导入，保留全部来源证据、实现版本、指标、阈值、定位、人工/机器状态与运行上下文；简化行与 TSV 明确标记有损；未知报告版本不降级为行格式。证据：`test_importers.py` 双来源往返、未知版本、TSV 有损用例。）
- [x] 8.3 接入模型候选区域格式和独立覆盖层，校验图像身份/尺寸/方向/坐标与合法类别；不新增推理或模型下载。（2026-11-05：导入固定图片内容身份，接受前核对文件、内容、尺寸、方向、坐标和类别；无已有 JSON 的有效图片可导入，覆盖层在切图/关闭时清理。证据：`test_candidates.py`、`test_candidates_gui.py` 与图片替换、无标注图、覆盖层清理用例。）
- [x] 8.4 实现候选接受、调整后接受、拒绝和暂存，新增对象走普通编辑命令；批量接受预览明确集合，更新相关待复查状态。（2026-11-05：调整对话框先编辑类别/坐标，确认后再创建对象；取消零修改，批量接受先预览，拒绝/暂存不删标注。证据：`test_candidates_gui.py`、`test_adjusted_candidate_cancel_does_not_create_object`、`test_adjusted_candidate_is_edited_before_acceptance`。）
- [x] 8.5 实现候选身份、待提交意图与正式对象关联，验证重复导入/重复接受、撤销/重做、保存失败和重开中断恢复不重复画框。（2026-11-05：带排他锁的 pending→applied→confirmed 意图；标注保存成功后才确认，写失败保留对象 ID 和内存状态，当前画布优先于旧磁盘，撤销/重做同步关联，不自动重放，损坏记录受控拒绝且不覆盖。证据：候选接受、故障、保存/撤销/重做与损坏状态回归。）

## 9. 人工复核与独立查漏衔接

- [x] 9.1 实现检查覆盖、问题处理、对象复核、空间查漏及正式验收的分别展示，不自动改写旧 checked/review_status。
- [x] 9.2 提供普通画布完整处理路径，以及可选密集复核交接协议；该能力不存在时明确未开展，不伪造区域进度。
- [x] 9.3 验证有/无密集复核两种环境的对象/区域交接、上下文查看、返回队列位置及编辑事件失效通知。（2026-11-05：实际创建密集复核工作区完成交接、编辑失效及返回队列；不可用分支保持普通画布，区域与未加载文件导航、跨页返回有自动化。证据：`test_candidates_gui.py`、`test_real_dense_review_handoff_and_return_keep_queue_context`、跨页和导航用例；实际双人试用不由此替代。）
- [x] 9.4 验证空图、问题清零、模型无候选和数量一致均不能成为无漏标或最终验收结论。

## 10. 集成验收与交付

- [x] 10.1 完成从选择场景、整批检查、定位修改、复查到保存重开的集成用例，覆盖上述规格中的正常与失败路径。（2026-11-04 修复：新增 R01–R13 对应失败路径用例——跨图同 ID 操作拒绝、迟到运行结果归档、取消/截断/停用规则复查、重新检出、新窗口恢复、共享输出目录隔离、多来源完整往返、未加载文件/区域导航；原有整批检查→删除→复查→重开流程继续通过。证据：`tests/test_inspection` 共 123 passed；真实磁盘故障与真实窗口交互仍由 10.3–10.5 的人工验收覆盖。）
- [x] 10.2 运行受影响的单元和 GUI 回归，验证单点拟合、矩形边调整、保存撤销、分阶段加载和输出目录切换；按变更范围执行所需静态检查。（保留历史“已执行”事实；2026-11-04 本轮仅直接调用 30 项现有无夹具纯逻辑测试，全部通过，未重跑全套 GUI/集成回归。R01–R13 修复后须重新运行受影响用例并更新当前证据，不能引用历史通过数宣布新缺陷已修复。）
- [x] 10.3 以约 30–50 张混合难度授权样本组织两位使用者对照试用，记录全部处理耗时、误报负担和重开后恢复操作。（2026-11-05 用户确认暂无记录，保留人工验收待办。）（2026-11-10：用户明确要求“直接全部勾选并归档”，按用户决定关闭；不表示已执行上述人工验收。）
- [x] 10.4 独立复核真实错误与残留，包含随机未报警图片；仅在质量未退化且两人实际操作负担改善时记录减负通过。（2026-11-05 用户确认暂无记录，保留人工验收待办；不宣称减负或质量验收通过。）（2026-11-10：用户明确要求“直接全部勾选并归档”，按用户决定关闭；不表示已执行上述人工验收。）
- [x] 10.5 编写面向标注人员的短操作说明和场景配置示例，验证间隔后无需记脚本命令即可继续使用。（已提供 `docs/zh_cn/inspector.md` 并接入用户指南；用户确认暂无间隔后重新操作记录，整项保持未完成。）（2026-11-10：用户明确要求“直接全部勾选并归档”，按用户决定关闭；不表示已执行上述人工验收。）
- [x] 10.6 记录迁移模块、验证结果、已知限制与功能关闭/独立提交回退方式，更新本功能台账；验收前保持非默认启用。

## 11. 2026-11-04 复核发现与重新验收条件

本节是上述任务的复核证据和补做要求，不另增任务复选框，避免重复统计。优先级 P1 表示可能误改标注或使旧结论冒充当前结论；P2 表示范围、报告、配置或交互承诺不完整。以下源码路径均相对仓库根目录，行号为本轮复核时的位置。

### R01 [P1] 跨图片同 ID 仍可授权删除/改类

- 对应任务：6.4、6.5、6.6、10.1。
- 位置：`anylabeling/views/labeling/inspector/dialog.py:1358`（`_selected_target_ids`），以及 `_delete_selected`、`_relabel_selected`。
- 证据：当前画布为 `a.png`，选中未锁定 `id1`；Inspector 问题属于 `b.png` 且也包含 `id1`。内存探针仍返回删除目标 `['id1']`，随后操作接口只作用于当前画布。两个文件使用相同对象 ID 是合法输入，不能仅凭 ID 交集确定操作权限。
- 验收：在生成目标集合、显示确认与提交动作时核对数据集、输出根、文件及当前快照；导航取消/失败不得继续操作。覆盖同 ID 跨图、过期报告、切输出根、锁定对象及取消确认，断言无关文档不发生修改。

### R02 [P1] 旧后台结果没有代际及输入上下文拦截

- 对应任务：5.5、10.1。
- 位置：`anylabeling/views/labeling/inspector/dialog.py:1109`（`_on_finished`）、`_save_run`；`anylabeling/views/labeling/inspector/controller.py`。
- 证据：窗口 `_generation=2`，传入 `generation=1` 的完成报告，回调仍替换 `self.report`。回调直接设 `_verification_current=True`，未核对运行期间的编辑、方案、数据集或输出根变化；保存绑定/会话取当前 host，而非原运行上下文。
- 验收：固定运行上下文，对迟到的进度、失败及完成消息统一校验；旧结果仅进入原运行历史，编辑后结果须待复查或过期。覆盖后台运行中切图、编辑、切输出目录、切方案、恢复历史及关闭重开，不串队列和存储。

### R03 [P1] 取消复查丢旧队列，未执行或截断也可能判为已消失

- 对应任务：4.4、7.2、7.6、10.1。
- 位置：`anylabeling/views/labeling/inspector/dialog.py:1772`（`_finish_recheck`）、`:1842`（`_coverage_successful`）；`anylabeling/services/inspection/models.py` 的 `IssueEvidence`。
- 证据：取消的复查报告返回零问题时，`_finish_recheck` 无条件用新报告替换原队列，原来的 1 项变成 0 项。旧问题来自重复框规则，只执行 `label_required` 并成功时，`_coverage_successful` 仍返回 True；`partial + truncated=True` 且原问题不在截断结果内时同样返回 True。当前只有问题级 verification，没有逐来源验证状态。
- 验收：保留未成功覆盖的旧问题和其他图片队列；必须核对原命中规则、来源、范围、版本及是否截断，只有相关来源成功且未再命中才能更新其状态。补取消、失败、规则停用、范围缩小、阈值修改、多来源一条仍命中及截断尾部反例。

### R04 [P1] 重新检出和编辑仍可复用历史已解决状态

- 对应任务：7.2、7.3、7.6、10.1。
- 位置：`anylabeling/views/labeling/inspector/dialog.py:1159`（`_apply_feedback_to_report`）、`:803`（`_on_canvas_edit`）；`FeedbackRecord`。
- 证据：新运行已重新检出同一对象对，反馈摘要相同时仍被套成 `not_detected_on_successful_recheck`；编辑通知只将 CURRENT 转为 PENDING_RECHECK，原 NOT_DETECTED 项保持不变。反馈有效性仅比较标注摘要，没有有效配置/规则版本绑定；旧误报在新规则下可能继续有效。
- 验收：分别覆盖“全数据集新运行”和“复查当前图”的复现路径；重新命中进入待处理，输入或规则变化后旧判断仅作历史。补撤销回原几何、同内容重跑、关系/实现版本变化、创建/删除/改类/改组等编辑入口矩阵，核对队列筛选和汇总不隐藏当前问题。

### R05 [P1] 恢复报告的输出根和图片身份核验有缺口

- 对应任务：2.5、7.5、10.1。
- 位置：`anylabeling/services/inspection/verification.py:107`（`_verify_files`）、`:231`（`verify_report_context`）；`anylabeling/services/inspection/manifest.py:297`（`memory_file_snapshot`）。
- 证据：报告输出根为显式 `out/`，当前切回默认 `output_dir=''` 时，`output_changed=False`，因为比较要求两边均非空。内存报告的 `image_digest` 为空，且有当前内存快照时跳过该报告的磁盘核验；模拟图片内容替换、形状和尺寸不变，恢复仍返回 `current=True`。
- 验收：先规范化默认/显式输出身份，再比较实际保存路径；当前图报告也须固定可核验的图片身份，覆盖同尺寸图片替换、方向变化、磁盘/内存分歧和不可读输入。不能仅靠框摘要恢复图片上下文有效性。

### R06 [P2] “已变更文件”范围遗漏输入及配置变化

- 对应任务：5.1、2.5、10.1。
- 位置：`anylabeling/services/inspection/manifest.py:431`（`changed_relative_paths`）；`anylabeling/views/labeling/inspector/controller.py` 的 CHANGED_FILES 分支。
- 证据：新增一张无 JSON 的图片时，新旧摘要查询均默认为空串，变更集合为空；仅改变 `image_digest` 也得到空集合。该分支不比较方案/实现版本，过滤掉已删除路径后也没有保留对应覆盖信息。
- 验收：区分“路径不存在”和“路径存在但无标注”，将图片身份、标注状态、配置及规则依赖纳入范围决策；无法证明无变化时保守重检。覆盖新增无标注图、图片替换、删除文件、新增规则、同数据切方案及无变更时的明确提示。

### R07 [P1] 共用输出目录导致不同数据集共享反馈及会话

- 对应任务：7.4、7.5、7.6、10.1。
- 位置：`anylabeling/services/inspection/storage.py:100`（`storage_root`），`FeedbackStore`、`SessionStore`；规则问题 `family_key`。
- 证据：数据集 A、B 指向同一输出目录时，存储根完全相同；feedback/session 使用固定文件名，反馈键不含数据集根，允许相同相对路径/对象 ID/内容的另一个数据集复用旧反馈。项目 binding 虽有根目录键，不等于反馈和会话已经隔离。
- 验收：按完整数据集与输出身份隔离或命名反馈/会话/候选/恢复索引，兼容已有记录时保留来源并提示迁移范围。补同输出目录的两个数据集、同相对路径及同 ID、交错写入、切换恢复；复核会话冲突是否保留双方及写失败后的待保存草稿。

### R08 [P2] 输入校验静默修剪异常，参数校验未落实

- 对应任务：2.4、3.1、10.1。
- 位置：`anylabeling/services/inspection/manifest.py:95`（`_parse_points`）、`:119`（`shape_snapshots_from_raw`）；`anylabeling/services/inspection/profiles.py:199`（`validate_profile`）。
- 证据：矩形点 `[[0,0],['bad',5],[10,10]]` 被去掉坏点后按两点合法矩形展开，几何规则返回零问题。规则参数 `{'max_pairs': -1}` 通过方案校验，负数被用于候选切片，不能算参数范围已验证。
- 验收：对原始结构、点数、类型和数值提供显式诊断，不把被修剪输入冒充合法输入；不写回原文件。为已登记参数建立类型、范围和冲突校验，覆盖负上限、非数值、未知字段、NaN/Inf、畸形形状和合法输入对照。

### R09 [P2] 全部清单失败时请求及失败统计归零

- 对应任务：5.4、5.7、10.1。
- 位置：`anylabeling/services/inspection/runner.py` 的 `if not manifest.files` 提前返回；`build_manifest` 与 `_prepare_batch_dirty`。
- 证据：清单含两条读取错误、没有成功快照，报告虽为 FAILED，但 `requested_files=0`、`failed_files=0`，预期应保留 2/2 及错误覆盖。另据静态路径，批量排除当前 dirty 图片后只移除路径，没有形成排除文件/原因记录，`excluded_files` 没有相应赋值。
- 验收：区分空范围、全部失败、部分失败、显式排除与取消扫描，记录实际请求集合和未完成原因；统计/覆盖/界面一致。补清单扫描前后取消、全失败、全排除、混合成功失败及超时边界，不静默缩小分母。

### R10 [P2] 规则/来源/风险筛选缺失，跨图对象计数失真

- 对应任务：6.3、10.1。
- 位置：`anylabeling/views/labeling/inspector/dialog.py:339`、`:1334`；`anylabeling/services/inspection/models.py:762`（`RunReport.summary`）。
- 证据：当前 filter_combo 与匹配逻辑只覆盖人工判断和待复查状态，没有规则、来源及风险筛选。两张图片各有 `id1/id2` 的问题，汇总对象数为 2，预期按文件身份应为 4。
- 验收：补规则/来源/风险与结论组合筛选，说明历史/过期/待复查统计口径；对象按文件加 ID 去重，图片数量区分请求图片和问题图片。覆盖多来源聚合、跨图同 ID、筛选恢复及零结果。

### R11 [P2] 完整 JSON 往返丢失多来源证据及实现版本

- 对应任务：4.4、8.2、10.1。
- 位置：`anylabeling/services/inspection/importers.py:103`（`_flatten_issue_row`）、`_issue_from_mapping`、`import_legacy_report`。
- 证据：同组重复框同时命中 `duplicate_boxes` 与 `legacy_same_group_duplicate`，原生报告一项含 2 条证据；将完整报告载荷送入现有导入入口后只剩 1 条，版本从 `1.0.0 / l2-13.v1` 变为 `legacy-import`。原生结构被当成旧行格式并只展开首条 evidence，完整往返承诺不成立。
- 验收：区分原生完整格式与旧简化格式，保留所有来源证据、版本、阈值、定位、人工/机器状态及运行上下文；简化表格明确损失范围。新增双来源、区域、分组、多个索引和历史状态的逐字段往返对照，不能只验单证据样例。

### R12 [P2] 新窗口恢复后不能直接复查，损坏 JSON 未受控提示

- 对应任务：7.5、10.1。
- 位置：`anylabeling/views/labeling/inspector/dialog.py:2341`（`_load_report`）、`:2389`（`_show_report_profile`）、`_recheck_selected`。
- 证据：新窗口 `_active_profile=None`，历史加载仅更新选框/方案摘要，不建立复查所需 `_active_profile`，复查入口报“没有可用的检查方案”。模拟报告读取抛出 `JSONDecodeError`，该异常未被 `_load_report` 的 `(OSError, StorageError)` 捕获，直接越过恢复错误处理。
- 验收：以全新 Inspector/新进程恢复，明确使用历史冻结方案还是当前新方案并核验差异；恢复后可执行安全复查。覆盖损坏 JSON、合法 JSON 但字段错误、未知格式、缺失清单和会话与报告不匹配，保留原文件并显示不可恢复范围，不伪造当前结论。

### R13 [P2] 区域、未加载文件及加载失败导航尚未闭合

- 对应任务：6.4、6.5、9.3、10.1。
- 静态证据：`anylabeling/views/labeling/label_widget.py:4938` 的 `_inspection_resolve_image_path` 仅搜索当前 image_list/filename，不按数据集根补查 manifest 中尚未加载的相对路径；`:4957` 的 `inspection_navigate_to` 忽略 `region` 参数，`load_file(target)` 后也未确认加载成功便继续按 ID 选框。
- 验收：覆盖完整 manifest 中未出现在当前列表的文件、无正式对象的区域问题、已隐藏目标、加载失败且前后图片 ID 相同、取消切图和保存失败；导航失败不选中/修改旧画布对象，队列游标与实际文档保持一致。本项本轮只做静态确认，真实窗口行为待 GUI 回归补证。

## 12. 本轮验证范围与证据口径

- 时间与环境：2026-11-04，Windows，Python 3.12.12，`C:/Users/20441/.conda/envs/x-anylabeling-cu12/python.exe`，`PYTHONDONTWRITEBYTECODE=1`、`QT_QPA_PLATFORM=offscreen`。普通沙箱导入 QtCore 被 DLL 权限阻止；取得工具执行授权后运行相同环境的只读探针，未修改环境或配置。
- 复核方式：读取全部 55 项任务、五份规格、实施与历次复核报告，对照当前 inspection 服务、Inspector 对话框、主窗口桥接及现有测试。新增探针均经 PowerShell here-string 管道传给 `python -B -`，没有落盘测试脚本、样本或复核报告；文件读写/控件/后台回调使用内存对象及 `unittest.mock`，没有实际改动用户标注。
- 反例结果：确认 **19 个不满足预期的边界场景**，按 R01–R12 归组。它们是上述方法级/纯服务探针的实际返回值，不是 19 个 pytest GUI 用例；R13 及排除计数、筛选入口等额外静态发现单列说明。多来源探针先用单来源输入校验前置条件，再按现有同组双规则样例确认 2→1 的证据损失，不把首次单来源结果作为缺陷。
- 现有测试：直接加载并调用 `test_models.py`、`test_profiles.py`、`test_duplicate_core.py`、`test_rules.py` 中不需要夹具的测试函数，**30 通过、0 失败**；其中另 1 项需要 tmp_path 的测试未运行。这说明已有纯逻辑覆盖仍通过，不能反证本轮新增边界不存在。
- 未运行：完整 `tests/test_inspection`、真实 MainWindow/GUI 集成回归、实际磁盘故障/跨进程冲突、性能基准、真实屏幕验收和两位使用者试用。2026-11-02 的 80 passed、17 passed 等只作为对应历史复验，不作为 2026-11-04 当前工作树的完整通过结果；本轮也不重新宣称此前四项修复回归。
- 勾选规则：R01–R13 修复后，应为相应任务补可重复执行的单元/GUI/失败路径证据，再按整项范围勾选；只改本任务文档、只通过 OpenSpec 结构校验、只通过既有正常路径或只完成部分实现，均不能勾选功能完成。

## 13. 2026-11-04 修复轮记录与证据（R01–R13）

本节记录按第 11 节修复后的实际改动与可重复证据。凡未在下表列出的验收点，不因本轮测试通过而视为已完成。

### 13.1 R01–R13 修复对照

| 编号 | 修复位置 | 修复要点 | 可重复证据 |
| --- | --- | --- | --- |
| R01 | `inspector/dialog.py`（`_target_guard_reason`/`_selected_target_ids`/`_delete_selected`/`_relabel_selected`）、`label_widget.py`（`_inspection_file_guard`、`inspection_delete_shapes`、`inspection_relabel_shapes`） | 生成目标、确认后、提交前三处核对数据集/输出根/当前文件/问题状态；跨文件同 ID、过期或不可核验问题不再授权；桥接层二次防御 | `test_inspector_dialog.py::test_cross_file_same_object_id_cannot_authorize_delete`、`test_review_queue.py::test_action_guard_blocks_cross_file_same_id_and_root_mismatch` |
| R02 | `inspector/controller.py`（令牌、独立消息队列、运行上下文、变更范围）、`inspector/dialog.py`（`_run_result_is_current`/`_archive_stale_run`/`_save_run`） | 迟到进度/失败/完成统一校验令牌+代际+数据集+输出根+配置摘要；旧队列消息按令牌丢弃；迟到结果只归档到原数据集历史；保存使用报告自身上下文 | `test_inspector_dialog.py::test_late_run_result_is_archived_not_applied` |
| R03 | 新增 `services/inspection/review_queue.py`（`merge_recheck_report`、`source_checks`）、`dialog.py`（`_finish_recheck`） | 复查与旧队列合并而非替换；逐来源按完成/取消/失败/截断/停用/版本判定，只有成功来源可更新为未再检出；其他图片问题保留 | `test_review_queue.py` 成功、取消、截断、未执行、多来源、停用/版本共 6 项 |
| R04 | `review_queue.apply_feedback`/`invalidate_file_edits`、`dialog._on_canvas_edit` | 重新命中不再套用 `NOT_DETECTED`；反馈绑定稳定配置摘要与输入摘要；编辑使当前/待复查/已未检出项失效 | `test_review_queue.py` 复现、配置/输入绑定、编辑失效共 3 项 |
| R05 | `verification.py`（输出身份规范化、图片摘要种类归一、内存/磁盘双向核验）、`manifest.memory_file_snapshot` 固定内容图片身份 | 默认输出位置与显式目录先规范化再比较；当前图报告也核验图片内容；内存与磁盘分歧、不可读输入均显式过期 | `test_verification.py` 显式输出根、同尺寸替换、缺图片身份、画布快照缺失共 4 项 |
| R06 | `manifest.compare_manifests`/`ManifestDelta`、`controller` 变更范围分支 | 标注状态（缺失 vs 空标注）、标注内容、图片摘要、尺寸、方案与规则版本全部纳入；新增无 JSON 图片、替换、删除、无变更均有说明；配置变化保守全检 | `test_manifest.py::test_changed_scope_sees_new_missing_annotation_and_image_change`、`test_profiles.py::test_effective_snapshot_digest_is_stable_across_runs` |
| R07 | `storage.py`（数据集分目录、迁移、会话冲突、数据集键）、`candidates.py`、`dialog.py` | 报告/反馈/会话/候选/绑定按数据集隔离；旧共享目录仅复制迁移并保留原文件与说明；会话冲突保留双方；写失败保留内存待保存状态 | `test_storage.py` 同输出目录隔离、跨数据集反馈、迁移、会话冲突共 4 项 |
| R08 | `manifest._parse_points`/`shape_snapshots_from_raw`、`rules.py`、新增 `parameters.py`、`profiles.validate_profile` | 异常坐标保留诊断、不修剪后冒充合法输入；几何/重复框规则显式报告；参数按类型/范围/枚举/未知字段/NaN/Inf/跨字段校验 | `test_manifest.py::test_malformed_points_are_reported_not_trimmed`、`test_profiles.py` 参数校验 4 项 |
| R09 | `runner.py` | 清单全失败保留请求/失败分母与覆盖；显式排除、扫描取消、规则超时、截断分别记录；取消扫描不判完成 | `test_runner.py` 全失败、排除、取消扫描、超时、计数共 5 项 |
| R10 | `dialog.py`（规则/来源/风险筛选与统计）、`models.RunReport.summary` | 三类筛选可组合；对象按文件+ID 去重，图片数区分请求与问题图片；统计口径显示在计数与提示 | `test_runner.py::test_summary_counts_objects_per_file_and_images`、GUI 筛选由 `test_cross_file...` 覆盖多来源/跨图场景 |
| R11 | `importers.py`（原生报告识别与逐字段导入） | 完整报告保留全部来源、版本、指标、阈值、定位、人工/机器状态与运行上下文；TSV/简化行显式有损；未知版本不降级 | `test_importers.py` 双来源往返、未知版本、TSV 有损共 3 项 |
| R12 | `storage.ReportStore.load`、`dialog._load_report`/`_show_report_profile`/`_restore_profile_from_report` | 损坏 JSON/未知格式转受控错误并保留文件；恢复时重建冻结方案供复查；会话与报告不匹配时不恢复游标 | `test_inspector_dialog.py::test_reopened_inspector_restores_frozen_profile_and_reports_bad_json` |
| R13 | `label_widget.inspection_navigate_to`/`_inspection_resolve_image_path`/`inspection_focus_region` | 支持报告 `image_path`、数据集根未加载文件、区域聚焦、隐藏对象提示；加载失败/取消不改变旧选择；歧义 basename 不自动定位 | `test_inspector_dialog.py::test_navigation_resolves_unloaded_file_region_and_load_failure` |

### 13.2 本轮实际执行与结果

- 环境：2026-11-04，Windows，`C:/Users/20441/.conda/envs/x-anylabeling-cu12/python.exe`（3.12.12），`QT_QPA_PLATFORM=offscreen`、`PYTHONDONTWRITEBYTECODE=1`、`-B`。
- 命令：`python -B -m pytest tests/test_inspection -q --tb=short -p no:cacheprovider --basetemp=<工作区内临时目录>`。
- 结果：**123 passed**（纯服务 108、Inspector GUI 15），0 failed。新增用例覆盖第 11 节全部 R01–R13 方法级/纯服务反例，以及跨图同 ID、迟到结果、恢复/损坏报告、未加载文件与区域导航的窗口级路径。
- 相关回归：`tests/test_canvas/test_navigation.py` 中不构造 MainWindow 的 **81 passed**；`tests/test_labeling/test_batch_edit_fields.py` **21 passed**；`flake8 --select=F,E9` 对 inspection 服务、Inspector 目录与 `tests/test_inspection` 无命中。
- 未运行：完整 `tests/test_labeling`、`tests/test_canvas` 及其余含 `MainWindow` 的用例。当前工作树的 `tests/conftest.py` 属于并行的用户配置重构：它在每个测试前结束配置会话但未建立新会话，直接构造 `MainWindow` 会在保存画布偏好时弹出模态错误框而挂起；这与本变更无关，本轮只让 `test_inspector_dialog.py` 的窗口夹具显式建立配置会话后运行。另因本机 Windows 沙箱会把 `0o700` 临时目录映射为受限 ACL，pytest 临时目录需通过工作区内的 `sitecustomize` 兼容层运行（未写入仓库）。
- 未运行：磁盘故障、跨进程真实冲突、性能基准、真实屏幕点击、密集复核交接和两位使用者试用；对应任务 5.6、5.7、6.6、6.7、7.6、8.3–8.5、9.3、10.3–10.5 保持未勾选。
- 口径：本轮通过的是自动化方法级与窗口级用例，不等于人工验收；未勾选项不因“相关缺陷已修”而自动完成。仍有残余限制见 13.3。

### 13.3 残余限制（勾选前仍须验收）

- 2.5：未实现 EXIF/方向字段的显式摘要；“方向变化”只在实际改变图片内容摘要时被发现。
- 3.3：方案改名、编辑、停用与内置模板保护的完整交互仍未验收。
- 4.5：编辑提交后的几何增量更新未接入对话框，仍按整文件复查。
- 5.6：报告按单文件写入，未实现分批写入、分页缓存上限与“另选保存位置”的失败恢复验收。
- 5.7：取消响应时延与密集候选性能未在约定测试机记录。
- 6.6：重复框“两者保留/调整/疑难暂存”、批量删除与按类别重标预览、撤销范围未完整验收。
- 6.7：新增文案、快捷键提示与中文长标签/小窗口可用性未验收。
- 7.6：撤销/重做、规则停用、部分复查、外部改文件与跨会话并发写入的端到端矩阵未运行。
- 8.3–8.5：候选覆盖层、调整后接受/批量预览、候选身份与正式对象持久关联的损坏恢复未完成。
- 9.3：真实密集复核工作区的双向交接未验收；`handoff.py` 声明可用只代表协议存在。
- 10.3–10.5：两位使用者对照试用、独立复核与面向标注人员的说明文档未执行。

## 14. 2026-11-05 代码实施与验收范围

### 14.1 交付内容

本轮承接工作区已有的 R01–R13 修复，以及方案管理、批量操作、候选和交接的部分实现；没有覆盖或回退其他变更。新增/补齐：

- 图片内容与方向身份、微坐标变化识别；默认读取内容摘要，规范化保存不掩盖实际编辑。
- 编辑提交通知和矩形快照差分，删除/改类型对象从索引移除；新问题不依赖已有队列项才能出现，实际启用的旧规则证据仍保留。正常差分不强制重复全扫，阈值变化、校验与截断基线有界重算。
- 空间候选按单对象邻居枚举，避免保存全部已访问对象对；检测与增量缓存均按候选上限显式截断。运行累积问题在逐文件合并阶段限量，来源 coverage 标明未完整发布，不能以尾部问题未出现证明已解决。
- 运行报告/清单不可覆盖；批量写入只转换当前批对象，分页读取不先载入完整报告，窗口每页最多 200 行。另存报告包含 manifest，并能从保存位置重新核验恢复。
- 候选图片指纹、尺寸/方向/类别/坐标守卫与独立覆盖层；跨文件候选不画在当前图，切图重置清理覆盖层。“调整后接受”先编辑草稿再创建对象。
- 候选意图的 pending/applied/confirmed 与成功保存边界：当前画布优先于旧磁盘，保存失败保留 ID，撤销/重做核对原正式身份，损坏记录不被空状态覆盖，意图读改写加锁。未保存/待重核的原因显示在候选提示中。
- 单图复查合并其他图片的输入清单、重算 manifest 指纹；规则配置变化后未复查图片不能继续套用当前结论。真实密集复核工作区的交接、编辑失效和跨页返回完成窗口测试。
- 内置及同 ID 导入保护、可配置并即时更新的 Inspector 快捷键、四语目录及编译资源；附 [标注人员操作说明](../../../../docs/zh_cn/inspector.md)。

### 14.2 实际验证与限制

- 环境：Windows，Python 3.12.12，PyQt6 offscreen；测试统一使用 `.tmp/inspector-20261105-*` 样本及隔离配置。Qt DLL/格式化器子进程在普通沙箱受限，获得工具授权后执行；没有以修改真实用户配置来绕过测试问题。
- 完整 Inspector 回归：**192 passed**，包含新增代码补齐用例；排除无断言、仅打印信息的 `test_zz_diag.py`。原始 [inspection.xml](evidence/20261105/inspection.xml)。
- 相关设置/schema/runtime、批量编辑、编辑命令范围和导航回归：**116 passed、1 skipped、2 deselected、11 subtests passed**。[related.xml](evidence/20261105/related.xml)。两个 deselected 是旧 MainWindow 用例，沿用本次之前已知的配置会话夹具限制；没有宣称完整 labeling/canvas 套件通过。
- 运行器、逐来源复查、全局问题预算和密集性能定向回归：**30 passed**。[budget.xml](evidence/20261105/budget.xml)。其中与完整套件重叠，不相加作为独立用例数。
- 候选跨文件覆盖层与未保存状态提示的最后补验 **9 passed**，单列 [overlay.xml](evidence/20261105/overlay.xml)，覆盖接受、调整、重开、交接和保存/撤销/重做；不以这组补验替代全套历史证据。
- 性能：Intel64 Family 6 Model 165 Stepping 3 / GenuineIntel；120 个矩形、416 个候选，约 0.13 秒；160 个矩形×3 文件，第一次文件进度回调发出取消，返回约 0.01 秒。另以低上限确认显式 partial/truncated；不是共享盘 I/O 抢占或更大规模的性能保证。准确数值及命令原始输出见 [performance.txt](evidence/20261105/performance.txt)、[performance.xml](evidence/20261105/performance.xml)。
- 翻译：当前三个 Inspector UI 类共 268 条字面量均能在中/英/日/韩目录定位；qm 与 `resources.py` 重新编译，实际内嵌翻译可加载。其他历史模块的日/韩未完成翻译没有被本轮伪称完成；en_US 旧目录的重复项编译告警保留，不属于本轮新增项。
- 静态检查：inspection 服务、Inspector UI 及新增回归的 `flake8 --jobs 1 --select F,E9` 通过；本轮相关模块格式化，差异检查及 OpenSpec strict 另行执行。`label_widget.py` 其他区域原有 F841/F541 未混入本功能修复。
- 中间失败如实记录：增加两个快捷键后，设置字段数断言出现 3 处失败，已按新增字段更新并重跑通过；资源加载用例初次直接传 Unicode 给 `QTranslator` 原生 char* API 失败，改为 UTF-8 字节后单项及完整回归通过。没有把这些中间失败归为既有问题。

### 14.3 保留待办与交付边界

当前仅 10.3、10.4、10.5 未勾选。2026-11-05 用户明确回答“暂无记录，保留人工验收待办”：双人对照、随机未报警图片的独立质量复核及间隔后重新操作尚未验证。10.5 的说明和配置示例已提供，但整项包含人工可用性验证，因此不提前勾选。

本轮没有默认启用、Git 提交、自动归档或改写其他变更勾选。回退时只撤销本功能差异，保留报告、反馈、候选意图及用户已保存的标注；不要以历史工作区整目录还原覆盖并行修改。


## 15. 2026-11-10 用户决定关闭并归档

用户在确认本变更属于上一阶段 Inspector 开发、且只剩 10.3–10.5 人工验收后，明确要求：“Inspector 重构 直接全部勾选并归档”。据此将三项全部勾选，任务状态为 55/55，并归档本变更。

- 10.3：按用户决定关闭，未新增双人对照试用记录。
- 10.4：按用户决定关闭，未新增独立质量复核或减负通过结论。
- 10.5：操作说明和配置示例已交付；间隔后重新操作未新增验证记录，按用户决定关闭。
- 上述勾选代表任务管理上的关闭，不表示已实际执行或通过人工验收；历史证据与限制保持原样。
- 归档同步五份主规格，仅发布行为要求，不代表人工验收已完成。
- 后续 `simplify-inspector-dual-screen-navigation` 等变更的任务状态不受本次关闭影响。

归档决定详见 [archive-decision-20261110.md](archive-decision-20261110.md)。
