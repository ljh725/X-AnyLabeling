# 给 GLM-5.3 复核冲突报告六项问题的提示词

下面代码块可整段复制给 GLM-5.3。本任务是对既有冲突报告进行独立复核，不是继续为原结论补充支持材料，也不是修复生产代码。

```text
你现在位于 X-AnyLabeling fork 的 Windows PowerShell 工作区。请直接执行一次“冲突报告六项问题独立复核”。你必须优先寻找反证，不能沿用原报告的 verdict、severity、acceptance 结果作为前提，也不能通过改写措辞掩盖证据不足。

【工作目录和输入】
- fork：D:\xinjiegou-X-AnyLabeling-4.0.0-beta.4
- 可信上游候选目录：D:\X-AnyLabeling-4.0.0-beta.4
- 原冲突报告：D:\xinjiegou-X-AnyLabeling-4.0.0-beta.4\扩展代码冲突检查报告.md
- 原方法：D:\xinjiegou-X-AnyLabeling-4.0.0-beta.4\扩展代码冲突检查_双域四闭环方法.md
- 原审计目录：D:\xinjiegou-X-AnyLabeling-4.0.0-beta.4\.tmp-conflict-audit\audit-20260828-122248
- 新复核目录：D:\xinjiegou-X-AnyLabeling-4.0.0-beta.4\.tmp-conflict-audit\review-six-issues-<YYYYMMDD-HHMMSS>
- Python：C:\Users\20441\.conda\envs\x-anylabeling-cu12\python.exe
- 仓库规则：D:\xinjiegou-X-AnyLabeling-4.0.0-beta.4\AGENTS.md

【六项必须复核的问题】
1. 原报告把四闭环全部标为通过，但 hunk ledger 没有功能归因、共享资源索引部分为空、候选由人工硬编码、部分 E×N finding 缺少原生契约证据。
2. CF-006 可能错误假设应用存在 redo 或 undo 备份仍可恢复，从而把合法 gid 复用误判成冲突。
3. CF-007 可能误解 R2：R2 检查“同一 gid 内相同 label 重复”，并非要求 group_id 全文件唯一。
4. CF-004 使用了“InspectorPanel 无 parent”的错误证据；需要基于真实 Qt parent 链和主窗口关闭路径重新判断线程销毁风险。
5. CF-003 的 5 个 schema 测试失败是测试债，可能不应计为生产代码 confirmed_conflict；同时必须独立确认 HEAD 提交态是否已经失败。
6. 原报告复现命令使用 Git Bash，违反本仓库强制 PowerShell 规则；必须改写并实际验证 PowerShell 命令。

【基本纪律】
1. 先完整阅读 AGENTS.md、原方法、原报告、原审计 acceptance.json、unknown_items.json、conflict_findings.jsonl、conflict_candidates.jsonl、extension_hunk_ledger.jsonl、shared_resource_index.json、native_contracts.json、probe_results.json 和所有 phase 脚本。
2. 本任务只复核和修订报告，不修复缺陷。禁止修改 anylabeling/、tests/、configs、translations、resources.py、pyproject.toml 和原审计目录。
3. 只允许写入新的 review-six-issues 时间戳目录，以及在全部复核完成后更新《扩展代码冲突检查报告.md》。必须先生成证据，后改报告。
4. 保留当前 dirty worktree。禁止 git reset、checkout、clean、stash、merge、rebase、commit、删除用户文件或自动格式化生产代码。
5. 所有命令必须是 PowerShell。多行命令第一行 `$ErrorActionPreference = 'Stop'`；显式程序路径使用 `& '路径'`。禁止 Bash、Git Bash、cmd /c、heredoc、`&&`、`export`、`$HOME` 和 `source activate`。
6. `label_widget.py` 和 `canvas.py` 必须先用 rg 定位，再读取 10～30 行最小窗口。不得反复整文件输出。
7. PyQt 测试使用 `QT_QPA_PLATFORM=offscreen`、给定解释器和新复核目录内已创建的 pytest temp root。若沙箱内发生 Qt DLL 拒绝访问，按环境规则申请在沙箱外重跑同一命令，不得换环境。
8. 不联网、不 fetch、不安装依赖。无法取得的证据标为 unknown，禁止猜测。
9. 对每个旧结论同时建立 supporting evidence 和 contradicting evidence。若只搜支持材料而未搜索反证，该项复核不合格。
10. 不得把“脚本生成了一个 JSON”当成闭环证明；必须验证 JSON schema、内容覆盖率和证据可复现性。

────────────────────────────────────────
一、复核准备：冻结现场并建立独立台账
────────────────────────────────────────

1. 记录当前完整 HEAD、branch、remote、staged/unstaged/untracked 状态、执行时间和原报告对应 HEAD。
2. 对原审计目录中所有 JSON/JSONL 执行：
   - JSON 可解析性；
   - JSONL 实际行数和逐行解析；
   - 必填字段检查；
   - 文件存在性检查；
   - 报告引用数量与实际数量对账。
3. 原审计目录只读，不覆盖其任何文件。所有新脚本和结果写入新的 review-six-issues 目录。
4. 创建 review_meta.json，记录：HEAD、工作区、原审计路径、新审计路径、解释器、Qt 环境、命令规则和所有读取错误。

每个复核项采用统一 verdict schema：

```json
{
  "review_id": "R1",
  "original_claim": "原报告结论",
  "supporting_evidence": [],
  "contradicting_evidence": [],
  "static_checks": [],
  "dynamic_checks": [],
  "verdict": "confirmed|partially_confirmed|rejected|downgraded|upgraded|unknown",
  "revised_status": "confirmed_conflict|latent_conflict|upgrade_conflict|maintenance_risk|intentional_override|compatible|unknown",
  "revised_severity": "P0|P1|P2|P3|none",
  "confidence": "high|medium|low",
  "reason": "必须包含触发条件、违反的不变量和可观察影响",
  "report_changes_required": []
}
```

────────────────────────────────────────
二、R1：四闭环重新验收
────────────────────────────────────────

目标：判断原报告第 36 行“四闭环全部通过”是否成立。不得读取原 acceptance.json 后照抄 pass。

R1-A hunk 归因闭环：
1. 解析 extension_hunk_ledger.jsonl 全部 349 条，输出所有字段及字段覆盖率。
2. 检查每个 hunk 是否含稳定 feature_id/feature_ids，或明确 nonfunctional_classification，或 unknown_reason。
3. 统计：total、attributed_to_feature、nonfunctional、unknown、missing_attribution。
4. 只有 missing_attribution=0 且 unknown 均有证据缺口时，才能通过 hunk 归因闭环。
5. 若原 ledger 只有 path/range/symbol/行数，不得因为“有 349 行”就标为归因完成。

R1-B 共享资源索引闭环：
1. 解析 shared_resource_index.json 的 states/events/ui/config/data/lifecycle/registry/files 八类。
2. 输出每类属性数、记录数、提取规则和样例。
3. 空对象不能算“已建索引”。若某类确实不适用，必须给出机器搜索范围和零命中证据；本项目 states、data、registry 明显适用，不能标 N/A。
4. 独立重建至少以下索引：
   - states：current file、selection、canvas mode、dirty、zoom/scroll、shape list、review/session token 的读写者；
   - data：group_id、shape identity、points、flags、attributes、LabelFile save/load、JSON/SQLite/TSV 的读写者；
   - registry：QAction/shortcut、validation rule registry、模型 registry、converter/exporter、设置 schema key；
   - lifecycle：QThread/QTimer/worker 的创建、parent、启动、取消、wait、finished、deleteLater 和关闭路径。
5. 新索引必须记录提取规则、文件、行号、access_mode 和 component/feature 映射。

R1-C 候选生成闭环：
1. 检查 phase2b_candidates.py 的 32 个候选是否为代码中硬编码列表。
2. 新候选必须主要由共享资源倒排索引机械生成：
   - write↔write；
   - write→read/assumption；
   - delete/replace→use；
   - event↔event；
   - lifecycle↔callback。
3. 手工候选只能作为 supplemental，必须标记 source=manual_supplement，不能参与“机器全量候选闭环”的证明。
4. 输出 generated_candidates.jsonl、manual_supplements.jsonl 和 generation_coverage.json。
5. 对所有高风险生成候选给 verdict；低风险候选可批量说明过滤规则，但不能静默删除。

R1-D E×N 契约闭环：
1. 枚举所有 domain=extension_native finding。
2. 每条必须有 contract_id、native_source、contract、evidence_type 和 exact location。
3. 统计 E×N total、with_contract、missing_contract。
4. 热点/生成物如果只是升级统计，不适用运行契约，也要明确 contract_type=upgrade_boundary，而不是留空。
5. missing_contract>0 时验收门不得通过。

R1-E finding schema 与产物闭环：
1. 每条 finding 必须有 feature_ids 和独立 violated_invariant 字段；不能只把不变量埋在 conflict_path 文本中。
2. 检查 boundary_map.json、conflict_audit_report.md 等报告声称存在的文件是否真实存在。
3. 核对报告“14 个台账/脚本文件”与目录实际文件数，区分台账、脚本、日志、patch 和子目录。
4. 检查 unknown_items 每项是否都有 evidence_gap、impact、next。

R1 输出：closure_recheck.json、rebuilt_shared_resource_index.json、generated_candidates.jsonl、generation_coverage.json、contract_coverage.json、artifact_reconciliation.json。

R1 硬判定：
- 任何一个子闭环不通过，原报告“四闭环全部 ✅”必须被 rejected 或 downgraded；
- 不允许写“虽然缺字段但实质已覆盖”，除非能逐项提供等价结构化证据；
- 新候选生成后如出现原报告未覆盖的高风险候选，必须进入 finding 复核范围并重新计算总数。

────────────────────────────────────────
三、R2：CF-006 undo/gid 复核
────────────────────────────────────────

目标：确认“undo 后画新 person 会复用可恢复 gid 并导致冲突”是否真实可达。

严格步骤：
1. 搜索并画出完整状态机：Canvas.store_shapes、is_shape_restorable、restore_shape、LabelingWidget.undo_shape_edit，以及全仓库 redo/redo_shape/恢复未来状态的入口。
2. 明确 shapes_backups 是单向 undo 栈还是支持 redo；记录每次 pop/append 后哪些状态仍可达。
3. 明确 group_id 的作用域：单文件、跨文件还是项目全局。证据必须来自实现、规则、测试或格式契约。
4. 阅读 gen_new_group_id 的所有调用方，区分“当前文件新 gid”与“全项目唯一 gid”。
5. 在新复核目录编写临时 offscreen 探针，不改 production/tests：
   - 初始 shapes 含 gid=5，建立真实 undo 快照；
   - 执行与 UI 相同的 undo 路径；
   - 生成新 gid 并完成一次真实新建/存储；
   - 尝试通过应用公开入口恢复被撤销的 gid=5 状态；
   - 检查是否能同时得到两个语义冲突的 gid=5 对象。
6. 如果应用没有 redo，或新编辑会使旧未来状态永久不可达，则原触发链不成立。
7. 不得提出“把所有 undo 快照和磁盘 gid 永久并入分配集合”，除非先证明 gid 必须单调且全项目唯一；否则该建议可能制造 gid 无界增长。

R2 判定规则：
- 能通过公开真实路径同时恢复冲突状态：保留/升级；
- 只能直接篡改内部列表才能制造：rejected；
- 不存在 redo 且 group_id 仅文件内当前态使用：rejected；
- 仍有其他独立触发链：拆成新 finding，不得沿用错误 undo 论证。

输出 cf006_recheck.json 和 cf006_probe_results.json。

────────────────────────────────────────
四、R3：CF-007 R2/group_id 语义复核
────────────────────────────────────────

目标：判断批量设置相同 group_id 是否本身违反规则。

严格步骤：
1. 完整读取 GroupLabelUniqueness、GroupIdUniqueness、HeadFaceGroupIdUniqueness 及 rule_config 实例化逻辑。
2. 明确三个不同概念：
   - gid 值重复；
   - 同一 gid 内 label 重复；
   - 同一 gid 内被配置为唯一的 shape/label 类型重复。
3. 明确 R2 的实际判断键是 `(file_path, group_id, label)`，不得把它写成 group_id 全局唯一。
4. 阅读 object_field_edit 的设计、UI 文案和测试，确定批量设置同一 gid 是否就是功能本意。
5. 在新复核目录建立最小纯 Python 场景：
   - person/head/face 使用同一 gid：检查应否报错；
   - 两个相同 label 使用同一 gid：检查 R2；
   - 两个不同文件使用同一 gid：检查作用域；
   - 批量编辑产生上述三种情况后运行真实 ValidationEngine。
6. 分别记录“合法分组”“规则违规”“产品策略未定义”，不能合并成一个结论。

R3 判定规则：
- 仅仅 gid 相同不能成立冲突；
- 只有批量操作能产生同 gid+同 label，且产品契约要求阻止而非允许事后质检时，才可保留 latent conflict；
- 若批量功能就是统一字段值且质检负责发现重复，应改为 intentional/compatible 或最多 maintenance_risk；
- severity 必须按真实数据影响重新评估，不能因为存在 error 级质检规则就自动定 P2。

输出 cf007_rule_semantics.json、cf007_scenarios.json 和 cf007_recheck.json。

────────────────────────────────────────
五、R4：CF-004 Qt parent 与关闭线程复核
────────────────────────────────────────

目标：删除错误的“InspectorPanel 无 parent”证据，并验证真实关闭路径是否可能销毁运行中 QThread。

严格步骤：
1. 静态追踪：InspectorPanel 创建 → addWidget/addDockWidget → Qt 重新设置 parent → LabelingWidget → MainWindow。
2. 列出 InspectorScanThread、QualityScanThread、InspectorExportThread、BehaviorAnalyticsExportWorker 的：
   - 创建位置；
   - parent；
   - 引用持有者；
   - start guard；
   - cancel/abort；
   - wait；
   - finished/deleteLater；
   - 文件切换路径；
   - LabelingWidget.closeEvent/MainWindow.closeEvent/InspectorPanel.closeEvent 可达性。
3. 注意区分：
   - 创建时 parent=None；
   - 加入布局后的运行时 parent；
   - worker parent；
   - 主窗口关闭时子 widget 是否收到 closeEvent；
   - QObject 析构是否发生在 worker 结束前。
4. 编写临时 offscreen 生命周期探针：
   - 实例化真实容器并在布局完成后记录 `inspector_panel.parent()` 链；
   - 启动一个可控、足够长的真实 Inspector/Quality scan；
   - 通过 MainWindow/LabelingWidget 的实际 close 入口关闭；
   - 捕获 Qt message、线程 running 状态、closeEvent 调用、cancel 调用和 wait 结果；
   - 单独验证 BehaviorAnalyticsExportWorker；不得用无关 dummy thread 代替全部真实 worker 后声称已复现。
5. 探针至少重复 3 次。若时序不稳定，记录每次结果。
6. 如果完整 LabelingWidget 因模型/资源过重无法构建，可以用最小真实 InspectorPanel 容器验证一部分，但必须把未覆盖部分列为 unknown，不能称端到端复现。

R4 判定规则：
- parent 证据错误必须从报告删除；
- 实际关闭能稳定 cancel+wait：rejected/compatible；
- 线程仍 running 且对象进入析构，或捕获 destroyed-while-running：confirmed；
- 静态存在缺口但动态未复现：latent_conflict，confidence=medium/low；
- 不得把“可能”写成“高强度静态证明”，除非所有权链和析构路径已经闭合。

输出 cf004_ownership_graph.json、cf004_worker_matrix.json、cf004_probe_results.json、cf004_recheck.json。

────────────────────────────────────────
六、R5：CF-003 HEAD 测试债与分类复核
────────────────────────────────────────

目标：分别证明“测试确实失败”和“失败属于哪种冲突类型”。

严格步骤：
1. 在当前工作区按 PowerShell 规则复跑原 G2 组，先创建独立 pytest temp root：

   $ErrorActionPreference = 'Stop'
   $reviewRoot = '<新复核目录绝对路径>'
   $pytestRoot = Join-Path $reviewRoot 'pytest-tmp-current'
   New-Item -ItemType Directory -Force -Path $pytestRoot | Out-Null
   $env:QT_QPA_PLATFORM = 'offscreen'
   $env:PYTHONDONTWRITEBYTECODE = '1'
   $env:PYTEST_DEBUG_TEMPROOT = $pytestRoot
   & 'C:\Users\20441\.conda\envs\x-anylabeling-cu12\python.exe' -m pytest tests/test_viewport_reset.py tests/test_viewport_controller_results.py tests/test_viewport_label_widget_integration.py tests/test_settings/ tests/test_quality_thresholds.py tests/test_quality_duplicate_rectangles.py -q --tb=line

2. 独立验证 HEAD 提交态，而不是让当前未提交 schema.py 污染结论：
   - 用 `git archive --format=zip --output=<新复核目录>\head.zip HEAD` 导出 HEAD；
   - 用 PowerShell `Expand-Archive` 解压到新复核目录；
   - 在解压出的 HEAD 树中使用同一解释器、独立 pytest temp root运行 `tests/test_settings/test_schema.py -q --tb=line`；
   - 不使用 git checkout/worktree，不修改当前工作树。
3. 对比当前工作区与 HEAD 的 schema.py、test_schema.py diff，明确哪些失败已提交、哪些由未提交行造成。
4. 找到缺 description 的确切 field key，不得只写“某个新字段”。
5. 区分：
   - 生产功能运行失败；
   - schema 与 runtime/config 契约不一致；
   - 测试固定数字/顺序未同步；
   - 可见字段真的缺少 description。

R5 判定规则：
- 只有测试期望陈旧：maintenance_risk/tests_only，不能计入 production confirmed_conflict；
- schema/config/runtime 真不一致并能影响用户：另建独立生产 finding；
- “缺 description”是用户可见质量缺陷，可单独列 P3，但不要与计数断言混成一个 confirmed conflict；
- 修订后必须重新计算 confirmed_conflict 数量和严重度分布。

输出 cf003_current_test.log、cf003_head_test.log、cf003_diff_analysis.json、cf003_recheck.json。

────────────────────────────────────────
七、R6：PowerShell 复现命令合规复核
────────────────────────────────────────

目标：报告中的每条复现命令都符合 AGENTS.md，且复制后能运行。

严格步骤：
1. 删除报告中的 Git Bash 标题和以下写法：`export`、`PY=...`、`$HOME`、Bash 路径、`&&`。
2. 所有复现命令改成 PowerShell 代码块；使用：
   - `$ErrorActionPreference = 'Stop'`；
   - `$env:QT_QPA_PLATFORM = 'offscreen'`；
   - `$env:PYTHONDONTWRITEBYTECODE = '1'`；
   - 明确创建 `$env:PYTEST_DEBUG_TEMPROOT` 对应目录；
   - `& 'C:\Users\20441\.conda\envs\x-anylabeling-cu12\python.exe' ...`。
3. 报告中的路径必须存在；审计脚本必须从仓库根目录可运行。
4. 每条最终保留的命令至少执行一次，记录 command、cwd、exit_code、stdout 摘要和预期结果。
5. 预期为失败的 CF-003 命令必须注明“预期 5 failed，退出码 1”；不能让读者误以为复现失败表示命令无效。
6. 不要声称 Git Bash 与仓库规则“等效”。

输出 powershell_commands.ps1、powershell_reproduction.json 和 powershell_command_review.json。

────────────────────────────────────────
八、附带一致性检查（不得遗漏）
────────────────────────────────────────

六项复核完成后，再修正以下由证据直接暴露的一致性问题：
1. probe_a 只是直接调用 `_selection_gesture.begin()` 和 reset_state，不是完整鼠标+切图端到端复现。CF-001 应区分“内部状态泄漏已确认”和“用户可见影响由静态推导”；如可行，补真实 QMouseEvent/QTest 场景。
2. probe_b 的 JSON 字段结果显示 unknown_shape_key_preserved=true，但 note 写“被丢弃”。读取 Shape.load_from_dict/other_data/to_dict 后修正矛盾。
3. CF-016 重新编译 fork 自己的 `.ts` 不会自动丢字符串；只有 `.ts` 合并/覆盖错误才会发生。重新评估它是 upgrade_conflict 还是普通 maintenance_risk，并降低没有真实三方上游证据时的置信度。
4. CF-022、CF-025、CF-036 没有已证实触发序列或可观察影响；按 finding 规则重新分类，不得把“调查线索/清单自认未完成/多写者存在”直接叫 latent conflict。
5. 检查报告引用的所有文件和行号是否准确，例如 CF-002 的 set_file_list 实际调用位置、InspectorPanel 加入布局后的 parent 位置。

输出 consistency_followups.json。

────────────────────────────────────────
九、重分类、改报告和最终验收
────────────────────────────────────────

1. 汇总 R1～R6 与附带检查，生成 reclassification.json：列出每个受影响 CF 的 old_status/old_severity/new_status/new_severity、原因和证据文件。
2. 重新生成 status 与 P0/P1/P2/P3 统计。禁止手工保留旧的 37/3/11/4/5/9 等数字。
3. 只有证据全部生成后才更新《扩展代码冲突检查报告.md》：
   - 修正执行摘要和四闭环状态；
   - CF-006/CF-007/CF-004/CF-003 按新 verdict 改写；
   - 修正测试、unknown、artifact 索引和 PowerShell 命令；
   - 保留旧结论被推翻的变更记录，不能静默删除；
   - 报告明确区分 production conflict、latent risk、upgrade risk、maintenance/test debt、rejected false positive。
4. 新建 six_issue_review_report.md，逐项说明原结论、反证、复核方法、结果和报告改动。

最终验收门：
- [ ] R1 的 hunk attribution、八类资源、机器候选、E×N contract、schema/产物检查都有数字证据
- [ ] 不再用硬编码候选的 32/32 verdict 证明候选全集闭环
- [ ] CF-006 的 undo/redo 可达性由真实状态机和探针验证
- [ ] CF-007 明确区分 gid 重复与 gid+label 重复
- [ ] CF-004 使用运行时 parent 链，关闭探针至少重复 3 次
- [ ] CF-003 当前工作区和独立 HEAD 树均有测试证据
- [ ] 所有复现命令均为已实际执行的 PowerShell
- [ ] finding 具有 feature_ids 和独立 violated_invariant
- [ ] E×N finding 均有 native contract 或明确 upgrade_boundary
- [ ] unknown 每项均有 evidence_gap/impact/next
- [ ] 报告所有统计由 reclassification.json 重新计算
- [ ] 原审计目录和生产代码未被修改
- [ ] 最终 git status 仅出现新复核目录和报告预期修改

如果任一验收门失败，必须把对应闭环写为“未通过”或“部分通过”，禁止用绿色勾号。不要为了完成任务伪造动态结果、补写不存在的 contract，或把 unknown 改名为 maintenance_risk。

【最终回复格式】
完成后给出：
1. 六项问题各自 verdict；
2. 哪些旧 finding 被确认、降级、拒绝或拆分；
3. 新旧 status/severity 统计差异；
4. 四闭环的新状态及未通过原因；
5. 动态探针和测试命令结果；
6. 正式报告修改摘要；
7. 新复核目录全部关键产物路径；
8. unknown/阻塞项；
9. 实际修改文件列表。

现在开始直接执行。先冻结现场并读取全部原证据，然后严格按 R1→R6→附带一致性→重分类→报告验收的顺序持续完成，不要停留在计划阶段，不要修复生产代码。
```

