# OpenSpec 未完成任务清单

更新日期：2026-11-10（Asia/Shanghai）。

当前共有 **3 个未完成变更、59 项未完成任务**。本清单依据当前工作区的 `openspec list --json` 与各变更 `tasks.md` 汇总，包含未提交的任务状态；本页仅汇总任务状态，没有重新运行功能测试或人工验收；2026-11-10 Inspector 重构的关闭与归档决定见下文。

各变更的 `tasks.md` 是状态维护入口。本页是快照，明细使用普通列表，避免维护第二套勾选状态；下次更新时应重新读取原始任务清单。

数字键类别保存修复已于 2026-11-10 独立复核完成，重新运行 53 项定向及相邻回归全部通过，详见[复核证据](changes/fix-digit-rectangle-label-save/verification.md)。以下其他变更沿用现有记录。

## 未完成变更汇总

| 变更 | 已完成 / 总数 | 剩余 | 主要待办 |
| --- | ---: | ---: | --- |
| [标注修正成本统计](changes/add-annotation-correction-cost-statistics/tasks.md)（`add-annotation-correction-cost-statistics`） | 1 / 54 | 53 | 开发、接入、测试和人工验收；目前仅完成实施基线记录。 |
| [密集标注复核工作流](changes/add-dense-annotation-review-workflow/tasks.md)（`add-dense-annotation-review-workflow`） | 61 / 66 | 5 | 真实屏幕及无障碍验收、回归异常排查、双人对照试用、质量复核与交付核对。 |
| [Inspector 双屏导航简化](changes/simplify-inspector-dual-screen-navigation/tasks.md)（`simplify-inspector-dual-screen-navigation`） | 25 / 26 | 1 | 真实双屏验收及截图、操作记录。 |

## 2026-11-10 已归档

[Inspector 工作流重构](changes/archive/2026-11-10-refactor-data-inspector-workflow/tasks.md) 已按用户“直接全部勾选并归档”的指示关闭，55/55 已勾选。原剩余 10.3–10.5 三项按用户决定关闭，未新增人工验收证据；五份规格已同步到主规格。详见[归档决定](changes/archive/2026-11-10-refactor-data-inspector-workflow/archive-decision-20261110.md)。后续 Inspector 双屏导航任务保持独立待办。

## 已完成但未归档的变更

以下四项当前任务已全部勾选，本清单沿用现有任务与验收记录，不以本次汇总代替验收，也不自动归档：

| 变更 | 当前进度 |
| --- | ---: |
| [restore-v430-canvas-controls](changes/restore-v430-canvas-controls/tasks.md) | 31 / 31 |
| [fix-rectangle-preview-overlap](changes/fix-rectangle-preview-overlap/tasks.md) | 24 / 24 |
| [fix-user-settings-persistence](changes/fix-user-settings-persistence/tasks.md) | 27 / 27 |
| [fix-digit-rectangle-label-save](changes/fix-digit-rectangle-label-save/tasks.md) | 10 / 10 |

`migrate-canvas-controls-from-v430` 的 CLI 状态为 `no-tasks`，其历史任务已移交到 [`restore-v430-canvas-controls`](changes/restore-v430-canvas-controls/tasks.md)，移交依据见[历史任务及合并映射](changes/migrate-canvas-controls-from-v430/tasks.md)。不重复统计，也不把 `no-tasks` 解释为已完成。

## 未完成任务明细

下列文字保留原任务要求及其已有进展说明。任务中引用的相对路径按原 `tasks.md` 所在目录理解；点击任务编号可回到源文件。历史测试数字仅为原记录，不代表本次重新验证。

### 标注修正成本统计（53 项）

源清单：[`add-annotation-correction-cost-statistics`](changes/add-annotation-correction-cost-statistics/tasks.md)。

#### 1. 实施基线与验收样本

- [1.2](changes/add-annotation-correction-cost-statistics/tasks.md#L4) 整理矩形修改入口矩阵：创建、删除、复制/粘贴、拖动/拖边、两种单点拟合、键盘微调、数字/对话框批量改类、全局类别管理、Inspector 修改、撤销及 AI 单张/批量结果；标明每个入口的事务完成边界和实际保存路径。
- [1.3](changes/add-annotation-correction-cost-statistics/tasks.md#L5) 建立授权或自制固定样本：空图、30 人多类别密集图、300 矩形压力图、遮挡小目标、部分锁定对象、混合非矩形、未知来源旧标注及“5 人工框+3 AI 框”追加案例，固定对象 ID 和预期结果。
- [1.4](changes/add-annotation-correction-cost-statistics/tasks.md#L6) 建立本变更的测试/验证目录和场景覆盖表，将四份 specs 的需求与后续任务、验证证据对应；记录既有定向测试基线，区分既有失败与新增失败。

#### 2. 统计数据契约与纯逻辑

- [2.1](changes/add-annotation-correction-cost-statistics/tasks.md#L10) 实现独立纯数据模型与模式版本：数据集、图片内容版本、轮次、会话、预测运行、对象来源、事务、时间片段、保存 revision、完成版本及完整性；固定 `unknown-existing/replacement/additive`、`processing-complete` 和默认 `not-assessed` 的语义。
- [2.2](changes/add-annotation-correction-cost-statistics/tasks.md#L11) 实现基于数据集图片/标注根目录、图片内容及稳定对象 ID 的身份关联；覆盖同名文件、对象重排、另存为分支、重复/缺失对象 ID 和外部内容变化，无法可靠关联时标记缺口。
- [2.3](changes/add-annotation-correction-cost-statistics/tasks.md#L12) 实现普通矩形几何规范化与 B/F/G/C 净差异计算，验证新增、删除、改框、改类、去重原始修改及原样保留；等价点序/数值表示不产生变化，真实微坐标调整仍被识别。
- [2.4](changes/add-annotation-correction-cost-statistics/tasks.md#L13) 实现累计事务数、对象触达次数与去重对象数，支持一事务多对象/多字段、重复事件幂等、无变化/取消不计修正；验证新增再删及多次修改再撤销的过程/净结果分离。
- [2.5](changes/add-annotation-correction-cost-statistics/tasks.md#L14) 实现显式类别版本和一对一重命名映射，保留重命名前个人改类；合并/拆分/冲突导致 C 未知时，对依赖 C 的指标传播 N/A；实现初始/最终类归属及零分母规则。
- [2.6](changes/add-annotation-correction-cost-statistics/tasks.md#L15) 实现普通矩形支持范围与完整性判定：混合形状、类型转换、来源未知、日志/计时缺口分别记录原因；相关子集可查看，完整对照排除并列出原因，不生成模型质量结论。

#### 3. 本地存储与恢复基础

- [3.1](changes/add-annotation-correction-cost-statistics/tasks.md#L19) 实现本机应用数据目录下的版本化 SQLite 存储、索引和事务；标注可以在共享盘，统计库保持本机，未知新模式版本不覆盖或猜测迁移。
- [3.2](changes/add-annotation-correction-cost-statistics/tasks.md#L20) 实现单写入后台有界队列、事件序号/幂等写入及 flush 检查点；统计关闭时不初始化数据库和后台采集，队列积压不得无限增长或静默丢失。
- [3.3](changes/add-annotation-correction-cost-statistics/tasks.md#L21) 实现存储锁、只读、磁盘满和队列饱和的故障降级，显示受影响轮次/片段，保留可验证记录并支持恢复后续记录，保证原有编辑保存继续可用。
- [3.4](changes/add-annotation-correction-cost-statistics/tasks.md#L22) 实现待保存检查点、成功保存 revision 与内容摘要核对；在“记录待提交前/后、标注写盘前/后、统计确认前/后”故障注入，证明不能产生未保存却已完成的结果。
- [3.5](changes/add-annotation-correction-cost-statistics/tasks.md#L23) 实现按需恢复、外部修改检测、另存为分支和中断记录；保存未知状态时只恢复可验证部分，不用当前文件补造历史；提供统计库备份/回退说明。

#### 4. 预标注与编辑事务接入

- [4.1](changes/add-annotation-correction-cost-statistics/tasks.md#L27) 为 `AutoLabelingResult` 兼容增加可选预测来源信息，并由运行协调器统一补充可获得的运行 ID、模型/权重与配置身份、提示词、阈值和耗时；来源字段使用允许列表排除密钥、授权头和带凭据链接，旧模型仍可运行。
- [4.2](changes/add-annotation-correction-cost-statistics/tasks.md#L28) 接入单张预测实际应用，区分替换与追加、已有保留对象和本次预测对象；处理迟到/取消/失败、内存草稿起点和再次推理新轮次，保留旧轮次成本。
- [4.3](changes/add-annotation-correction-cost-statistics/tasks.md#L29) 接入批量预测逐图保存结果与一致起点；必要时最小复用原子写入助手，确保部分失败不会被报告为整批成功，批量 AI 不启动人工计时、不自动完成图片。
- [4.4](changes/add-annotation-correction-cost-statistics/tasks.md#L30) 接入矩形创建、删除、复制/粘贴及批量操作，发出一个完成事务与实际变化对象集合；复制对象获得新身份，锁定/无变化对象不计入受影响集合。
- [4.5](changes/add-annotation-correction-cost-statistics/tasks.md#L31) 接入拖动、拖边、Shift/Shift+Alt 单点拟合和键盘微调的完成边界；一次既有编辑事务只记录一次，不采集逐帧鼠标位置、不在绘制路径写存储。
- [4.6](changes/add-annotation-correction-cost-statistics/tasks.md#L32) 接入单个/批量数字改类、字段对话框和全局类别管理；区分个别对象改类与体系更名，捕获影响已保存图片的更名范围及完成失效，不把自动载入当人工操作。
- [4.7](changes/add-annotation-correction-cost-statistics/tasks.md#L33) 接入撤销、Inspector 实际编辑和密集复核确认/撤销，记录操作来源与关联事务；支持现有恢复语义，不新增旧系统没有的重做能力，不将审核进度当框修改。

#### 5. 保存、丢弃与完成状态

- [5.1](changes/add-annotation-correction-cost-statistics/tasks.md#L37) 在普通/自动保存的成功返回处确认固定对象快照和 revision，保存失败保持草稿；验证连续自动保存不会重复计数或清空过程成本。
- [5.2](changes/add-annotation-correction-cost-statistics/tasks.md#L38) 接入 Save/Discard/Cancel、切图和关闭生命周期；丢弃恢复最后保存净结果并保留已放弃成本，取消导航保持当前图片会话，切图重开不重新冻结已有起点。
- [5.3](changes/add-annotation-correction-cost-statistics/tasks.md#L39) 实现明确“完成本轮”和范围可见的批量完成，完成仅绑定成功保存版本；未保存/失败项明确列出，保存、切图和批量预测完成均不能隐式完成统计。
- [5.4](changes/add-annotation-correction-cost-statistics/tasks.md#L40) 实现完成失效：任何实际标注内容变化（含非矩形和全局类别更名）使当前完成失效，缩放/选择不失效；重复完成去重，撤销/丢弃不自动冒充一次新的完成声明。
- [5.5](changes/add-annotation-correction-cost-statistics/tasks.md#L41) 实现完成时冻结成本和关闭计时、已完成图重开只浏览、“继续修正”同轮恢复及“开始复核”新阶段；首次实际编辑可自动恢复但不回填此前浏览时间。
- [5.6](changes/add-annotation-correction-cost-statistics/tasks.md#L42) 实现统计完成、既有 checked/复核标记和质量来源的独立展示；默认质量未评估，只引用来源/范围/保存版本匹配的明确已有结论，不由完成或原样保留自动写入质量通过。

#### 6. 应用内计时

- [6.1](changes/add-annotation-correction-cost-statistics/tasks.md#L46) 实现使用单调时钟的互斥计时状态机与片段归属，覆盖未就绪、前台作业、暂停、后台、阻塞和关闭；用假时钟验证状态转换不重叠、不负时长。
- [6.2](changes/add-annotation-correction-cost-statistics/tasks.md#L47) 接入图片可交互、切图和相关标注弹窗状态；审图无输入仍计时，取消切图不分配目标图片时间，一段时间只属于一个图片/轮次/阶段。
- [6.3](changes/add-annotation-correction-cost-statistics/tasks.md#L48) 接入显式暂停/继续、应用前后台、锁屏和休眠恢复；显式暂停不能因重新激活被解除，系统时间变更不扩大/缩短可验证处理时长。
- [6.4](changes/add-annotation-correction-cost-statistics/tasks.md#L49) 实现默认 120 秒可配置的非阻塞待确认空闲提示、确认审图/排除空闲与调整审计；原始时段保留，扣除只能作用于实际 working 区间且不能重复扣除。
- [6.5](changes/add-annotation-correction-cost-statistics/tasks.md#L50) 接入模型运行与真正阻塞等待的独立记录，验证后台推理 20 秒与审图 20 秒并行不会合成 40 秒人工处理时间，也不能从审图时间扣去整段模型耗时。
- [6.6](changes/add-annotation-correction-cost-statistics/tasks.md#L51) 实现每秒时间持久化边界及异常尾段处理；崩溃只恢复已验证时间并标缺口，停机期间不计时，长间隔心跳不能直接补算为作业。

#### 7. 工作流与汇总界面

- [7.1](changes/add-annotation-correction-cost-statistics/tasks.md#L55) 增加默认关闭的工作流入口和范围选择、设置/schema、可配置无冲突快捷键；开关和启动范围可见，关闭时不产生事件/计时/存储负担。
- [7.2](changes/add-annotation-correction-cost-statistics/tasks.md#L56) 实现可收起的当前图片面板，显示来源/轮次、时间状态、起始/当前数量、累计事务、去重对象、草稿/已保存净结果、完成及完整性；支持暂停/继续/完成/汇总而无需逐框填表。
- [7.3](changes/add-annotation-correction-cost-statistics/tasks.md#L57) 实现按图片/轮次/阶段的分页汇总，区分历史版本和当前有效完成图片；只在可比集合中计算统计值，明确显示排除数量和原因。
- [7.4](changes/add-annotation-correction-cost-statistics/tasks.md#L58) 实现类别方向表、类名搜索排序及目标数量/模型版本分组，注明初始/最终数量口径、分母、样本量和顺序重用条件；空图除零和 C 未知传播 N/A，不输出准确率、每类精确用时或自动提速。
- [7.5](changes/add-annotation-correction-cost-statistics/tasks.md#L59) 完成现有中英日韩语言资源、窄窗口布局和状态提示；核对正常画布、密集复核和 Inspector 的焦点/快捷键/保存语义不被面板改变。

#### 8. 可追溯导出

- [8.1](changes/add-annotation-correction-cost-statistics/tasks.md#L63) 固定图片/轮次明细、类别方向明细和指标字典的 CSV 契约，包含来源、图片及保存版本、会话/阶段引用、完成/完整性、各计数和时间口径；多会话累计行不因重复引用而重复聚合。
- [8.2](changes/add-annotation-correction-cost-statistics/tasks.md#L64) 实现固定读取快照的后台导出，用户继续编辑不改变本次截止状态；默认导出成功保存版本，未完成/历史记录单独标识。
- [8.3](changes/add-annotation-correction-cost-statistics/tasks.md#L65) 实现 UTF-8 BOM、标准引号、中文/逗号/换行兼容与公式文本安全表示；验证前导空白和 `= + - @` 文本不会成为表格公式，数值与 N/A 语义保持可解释。
- [8.4](changes/add-annotation-correction-cost-statistics/tasks.md#L66) 实现导出进度、取消和临时文件原子发布；取消/失败时保留原报表完整，不留下冒充成功的部分目标文件。
- [8.5](changes/add-annotation-correction-cost-statistics/tasks.md#L67) 对 UI 汇总与 CSV 做同一固定样例的逐项核对，并验证不含密钥、不向标注 JSON 写事件、原有训练导出字段保持兼容。

#### 9. 回归、性能与人工验证

- [9.1](changes/add-annotation-correction-cost-statistics/tasks.md#L71) 完成纯服务场景测试：多对象事务、改类/改框重叠、重复回调、撤销回起点、新增再删、类别更名/合并、微坐标、零对象和混合范围；断言与 specs 的预期集合/计数一致。
- [9.2](changes/add-annotation-correction-cost-statistics/tasks.md#L72) 完成 GUI 定向回归：各矩形入口、锁定对象、剪贴板、撤销、自动保存、切图/取消、已完成图浏览、继续修正和复核交接；覆盖开启/关闭统计两种模式。
- [9.3](changes/add-annotation-correction-cost-statistics/tasks.md#L73) 完成保存/数据库/队列/崩溃/外部修改故障矩阵，验证已保存结果可核对、缺口不隐藏、原有标注可继续保存，导出不包含草稿冒充的交付结果。
- [9.4](changes/add-annotation-correction-cost-statistics/tasks.md#L74) 在固定硬件上比较 30/300 矩形操作的开关差异，达到主线程新增采集 p95 ≤ 5 ms；对 10,000 图/100,000 操作库验证首屏 p95 ≤ 2 s、导出取消 ≤ 1 s、GUI 心跳新增阻塞 ≤ 100 ms，记录冷/热条件和实际结果。
- [9.5](changes/add-annotation-correction-cost-statistics/tasks.md#L75) 用授权/自制密集人体样例完成两位使用者难度匹配、交叉顺序的试用，检查静止审图计时、无额外逐框确认、类名多时的查询和结果可解释性；未完成试用不得勾选。
- [9.6](changes/add-annotation-correction-cost-statistics/tasks.md#L76) 执行与受影响模块相称的现有标注、画布、设置、自动标注、密集复核和 Inspector 回归，运行格式/静态检查与 `openspec validate add-annotation-correction-cost-statistics --strict`；区分既有失败、新失败、跳过和未运行项目。

#### 10. 交付与回退记录

- [10.1](changes/add-annotation-correction-cost-statistics/tasks.md#L80) 编写用户说明：启用范围、暂停/完成/复核、过程与净结果、时间估计、来源未知、类别改名、指标分母和不完整数据含义，提供可复现示例报告。
- [10.2](changes/add-annotation-correction-cost-statistics/tasks.md#L81) 在本变更 `verification.md` 汇总需求到证据、测试命令/环境/结果、性能和人工试用；未通过或未运行项明确保留，不能以规划工件完成冒充功能交付。
- [10.3](changes/add-annotation-correction-cost-statistics/tasks.md#L82) 更新对应 `docs/custom_changes/` 记录和索引，归集本功能修改、依赖、配置、统计库位置、来源兼容和备份/回退步骤，不将工作区其他改动并入本功能成果。
- [10.4](changes/add-annotation-correction-cost-statistics/tasks.md#L83) 验证关闭或回退统计功能后旧标注仍可正常打开、编辑、保存及导出；保留统计库供导出，不删除图片/标注。确认所有必须验收项已有证据后再准备归档，当前任务不自动归档。

### 密集标注复核工作流（5 项）

源清单：[`add-dense-annotation-review-workflow`](changes/add-dense-annotation-review-workflow/tasks.md)。

#### 7. 低成本确认与反馈

- [7.8](changes/add-dense-annotation-review-workflow/tasks.md#L79) 为新增用户可见文案、快捷键提示和无障碍名称接入现有翻译流程，复核中文长类名、小窗口和键盘操作可用性。补充：四语言 `.ts` 已补齐新增文案与 `Redo` 快捷键标签，`lrelease` 重编 `.qm`；`app.py::load_translator` 源码优先磁盘 `.qm`、打包回退 `:/languages/`；`tests/test_dense_review/test_translations.py` 6 passed / 10 subtests；窄窗口长类名截图见 `images/dense_review/06-narrow-window.png`。真实屏幕字体度量、无障碍与四语言人工检查仍属 10.4。 **2026-11-04 复核：DR-05：中文和部分新增快捷键测试已通过，但日/韩工作区主体及源码/打包资源路径仍未完整覆盖；四语言真实屏幕、无障碍和键盘验收未完成。保留历史 6 passed，不将其视为本任务全部完成。** 2026-11-05 进展：本功能主体、动态状态及规则中英日韩文案与磁盘/内嵌资源测试已完成；真实屏幕、读屏、字体/DPI 与语言人工检查未执行，按 M1 保持未勾选。

#### 9. 故障与集成回归

- [9.7](changes/add-dense-annotation-review-workflow/tasks.md#L100) 在当前工作树修订上重跑与本功能相关的密集复核、画布、标注、设置及 Inspector 定向集成回归，记录基线/工作区差异、命令、环境、通过/失败/跳过/未运行；复核历史 settings 合跑原生访问冲突，不以各文件单跑通过替代合跑结果，也不在无基线证据时归因本功能。对应 DR-09。 2026-11-05 进展：密集复核 142 passed/602 subtests；设置、Inspector 和相关标注合跑 186 passed/1 skipped/24 subtests。大范围运行及独立画布复验提前退出（0xC0000409），未生成完整 JUnit，最后记录在矩形预览键盘微调用例附近，尚未可靠定责；不能把子集通过视为整组通过。补真实隔离启动，不屏蔽持久化错误。

#### 10. 性能与减负验证

- [10.4](changes/add-dense-annotation-review-workflow/tasks.md#L107) 用两位实际使用者、难度匹配且顺序交叉的图片组各进行至少两轮对照，记录缩放/拖动/重复访问/确认次数、总耗时及同等时长疲劳自评。DR-10：试用前固定设备、规则、难度分层和主要指标；优先使用互不重复图片组，复用须披露记忆效应；记录每人每轮原始计数及分母，空图单列每图耗时与漏标，不能按零对象归一化。
- [10.5](changes/add-dense-annotation-review-workflow/tasks.md#L108) 由独立复核记录错类、框错误、漏标与分歧，评估速度和疲劳收益是否以质量为代价；无质量退化、两人均愿采用且主要负担指标改善才标记减负已验证。DR-10：事先约定独立复核和质量判定口径，报告错类、框错误、漏标、误检及返工的计数、分母、分歧与裁决；小样本描述不能推广为普遍收益。

#### 11. 文档、发布与回退

- [11.3](changes/add-dense-annotation-review-workflow/tasks.md#L114) 执行OpenSpec严格验证与文档/代码差异检查，确认所有承诺有实现和证据；有未通过行为或性能项时保留未完成任务，不提前归档或宣称上线。补充：`openspec validate ... --strict` 通过；未通过/未验证项保留在原任务中。 **2026-11-04 复核：DR-10：strict 仅证明文档结构，不能证明所有承诺均有实现/证据。待本次实现缺口、当前回归、真实性能口径及人工验收逐项有结果后再完成交付核对；未完成时不归档或宣称上线。** 2026-11-05 进展：代码、逐场景映射和历史/当前证据已更新，strict 与差异检查单列；M1–M5 人工部分和 9.7 未决问题未全部关闭，保留未完成，不归档。

### Inspector 双屏导航简化（1 项）

源清单：[`simplify-inspector-dual-screen-navigation`](changes/simplify-inspector-dual-screen-navigation/tasks.md)。

#### 6. 文档、资源与交付验收

- [6.3](changes/simplify-inspector-dual-screen-navigation/tasks.md#L42) 实际双屏验收：主窗口保持完整画布、Inspector 可独立移动／缩放，两边 F1／F2 同步定位且不抢焦点；验证重复框选择删除、保存复查、跨图取消、最小化、第二屏断开和不同缩放下按钮可用，附截图及操作记录。

## 刷新方法

运行 `openspec list --json` 核对变更计数，再读取 `openspec/changes/*/tasks.md` 中未勾选项更新本页。只有原任务已有对应完成证据时才更新原任务状态；本页不单独宣布功能完成。
