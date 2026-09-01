# 给 GLM-5.3 执行扩展代码冲突检查的提示词

下面代码块可整段复制给 GLM-5.3。任务性质是代码审计：只检查、验证和报告，不擅自修复生产代码。

```text
你现在位于 X-AnyLabeling fork 的 Windows PowerShell 工作区。请直接执行一次高强度“扩展代码冲突审计”，不要只写计划、泛泛做 code review，或把 Git merge conflict 当成全部问题。

【工作目录和输入】
- fork：D:\xinjiegou-X-AnyLabeling-4.0.0-beta.4
- 可信上游候选目录：D:\X-AnyLabeling-4.0.0-beta.4
- 强制方法文档：D:\xinjiegou-X-AnyLabeling-4.0.0-beta.4\扩展代码冲突检查_双域四闭环方法.md
- 功能总表：D:\xinjiegou-X-AnyLabeling-4.0.0-beta.4\功能总表_上游与个人扩展.md
- 个人扩展清单：D:\xinjiegou-X-AnyLabeling-4.0.0-beta.4\个人修改与扩展清单.md
- 上游对比方法：D:\xinjiegou-X-AnyLabeling-4.0.0-beta.4\上游对比与清单更新_三层四闭环方法.md
- 临时审计目录：D:\xinjiegou-X-AnyLabeling-4.0.0-beta.4\.tmp-conflict-audit
- 正式报告：D:\xinjiegou-X-AnyLabeling-4.0.0-beta.4\扩展代码冲突检查报告.md
- Python：C:\Users\20441\.conda\envs\x-anylabeling-cu12\python.exe

【真正的审计目标】
检查两个域：
1. 扩展代码内部 E×E：不同个人扩展功能之间是否重复接管、争抢状态、覆盖事件、违反彼此假设、产生生命周期/并发/配置/数据冲突。
2. 扩展与原生 E×N：fork 扩展是否违反上游原生契约、绕过原生流程、破坏数据兼容、改变共享状态语义，或制造当前/未来上游升级冲突。

这里的冲突包括静态、运行时、时序和升级冲突。仅仅“修改了同一文件”不是冲突；仅仅“测试都通过”也不能证明没有冲突。每个有效 finding 必须给出：前置条件、触发顺序、A 的动作、B 的假设、被破坏的不变量、可观察影响和证据。

【操作边界】
1. 先完整读取仓库 AGENTS.md、强制方法文档、两份功能清单和相关已有审计产物。
2. 本任务是检查，不是修复。禁止修改应用源码、tests、配置、翻译和生成资源；只允许新建/更新 `.tmp-conflict-audit` 内审计脚本与产物，以及正式报告《扩展代码冲突检查报告.md》。
3. 当前工作树有用户修改。必须全部保留，禁止 git reset、checkout、clean、merge、rebase、stash、删除、自动格式化、自动提交。
4. 全部命令使用 PowerShell；多行命令以 `$ErrorActionPreference = 'Stop'` 开头。不要使用 Bash heredoc、`&&` 或 `cmd /c`。
5. 优先使用 `rg` 精确定位。`label_widget.py` 和 `canvas.py` 是高成本文件，必须先 rg 行号，再读取 10～30 行最小窗口；不得反复整文件输出。
6. 测试使用给定 Python 解释器，优先窄测试和 selector，使用 `-q`。除非确实验证跨系统冲突，不要直接跑全套 pytest。
7. 若 PyQt6 因 sandbox/Qt DLL 权限失败，按环境规则申请在 sandbox 外重跑同一命令；不要更换环境或安装另一个 Qt。
8. 不联网、不 fetch、不安装依赖。若本地上游完全不可用，记录 unknown 和证据缺口，不要伪造来源结论。
9. 不要忽略 Permission denied、解析失败或无法读取；它们必须进入 unknown_items.json 并限制最终结论。
10. 从仓库能查明的信息不要询问用户。持续执行到报告和验收完成；只有不同基准会实质改变结论且无法从本地证据判定时才停下报告阻塞。

【阶段 0：固定现场】
1. 记录 fork remote、branch、完整 HEAD、提交时间、staged/unstaged/untracked 状态。
2. 检查上游候选目录存在性、Git HEAD/remote/dirty；不是 Git 仓库时生成目录 manifest 摘要。
3. 独立记录 UPSTREAM_SOURCE、UPSTREAM_BASE、TARGET、WORKTREE_SNAPSHOT、执行时间、工具版本和读取错误。
4. 工作区未提交代码也属于本轮扩展检查范围，但必须与已提交扩展分开标记。
5. 写 `.tmp-conflict-audit/audit_meta.json`。审计过程中若工作树变化，重新快照并在报告解释。

【阶段 1：建立原生—扩展边界】
1. 不要按文件夹名称猜哪些是扩展。结合可信上游目录、git diff、现有功能清单和工作区，精确形成：
   - 原生文件/符号 N；
   - fork-only 扩展文件；
   - modified 原生文件里的扩展 hunk/符号；
   - 删除或替换的原生入口；
   - 未提交扩展；
   - generated/docs/tests/engineering-only 分类。
2. 为每个扩展组件分配 component_id，为每项功能分配 feature_id，并保持与现有清单可映射。
3. 为每个扩展组件枚举与原生及其他扩展的边：imports、inherits、overrides、calls、called_by、connects_signal、emits_signal、installs_event_filter、reads_state、writes_state、owns_object、reads/writes/migrates_config、reads/writes_data、registers_key、starts_worker、receives_async_result。
4. 生成 native_inventory.json、extension_inventory.json、extension_hunk_ledger.jsonl、boundary_map.json。
5. 检查“有实现但无入口/注册”的死代码，以及“有 UI 入口但实现/持久化链不完整”的 stub。
6. 边界闭环条件：未分类文件、hunk、符号和扩展组件为 0；无法分类的写入 unknown_items.json。

【阶段 2：建立共享资源索引并生成候选】
1. 对全部组件建立倒排索引，资源类型至少包括：
   - current file、selected shapes、canvas mode、dirty、zoom/scroll、review item 等共享状态；
   - key/mouse/wheel、shape changed、file loaded、close、scan finished 等事件；
   - QAction、shortcut、shortcut context、objectName、menu、dock、tab index；
   - YAML/schema/runtime 配置键和迁移；
   - LabelMe JSON、shape identity、group_id、flags、attributes、points、缓存和索引；
   - QWidget/QObject/QThread/QTimer/worker 所有权与生命周期；
   - model/rule/converter/exporter/CLI/translation context 等注册键；
   - 输出文件、报告、临时目录、模型缓存等文件资源。
2. 生成 E×E 和 E×N 候选，但不要盲目做所有组件笛卡尔积。仅当组件共享资源、调用边界、事件或时序前提时生成候选。
3. 优先级依次为：write↔write、write→assumed/read、delete/replace→use、event↔event、lifecycle↔callback、重复昂贵 read。
4. 每个候选必须记录 candidate_id、domain、components、feature_ids、shared_resource、access_modes、生成原因、初始风险。
5. 输出 shared_resource_index.json 和 conflict_candidates.jsonl。
6. 对 label_widget.py、canvas.py、settings、label/shape 序列化、Inspector/复核/筛选/索引、自动标注 registry、resources 构建链建立专项候选组。

【阶段 3：静态契约检查】
按 C1～C9 全部检查，不得只搜 TODO、异常或 merge marker：

C1 符号/注册：重复 action、shortcut、objectName、配置键、registry、命令、资源、translation context；导入遮蔽和同名异义。

C2 API/继承：override 签名、返回、异常、副作用；super 调用遗漏/重复；私有 API 耦合；monkey patch；可变对象身份与所有权变化。

C3 状态/所有权：多个真相源；selection/mode/dirty/current file/zoom/shape list 共享写；切图、取消、关闭、异常后的复位；删除/替换后继续使用；半完成状态被信号观察。

C4 事件/UI：shortcut context；eventFilter 和 key/mouse/wheel accept/ignore；模式互斥；重复 signal connection；错误 disconnect；递归信号；blockSignals/防重入标志异常恢复；Dock/Tab 固定索引。

C5 配置/数据：YAML default→schema→UI→runtime applier→落盘→迁移全链；同键异义；旧配置兼容；JSON round-trip；未知字段保留；group_id/flags/attributes/points/shape identity；撤销/保存/自动保存/切图的 dirty 语义；quality 子包只读边界。

C6 并发/生命周期：QObject thread affinity；worker 晚到结果；重复启动/取消；timer/future/connection 清理；parent/deleteLater/quit/wait；后台结果覆盖新文件或新用户状态。

C7 依赖/构建：互斥 onnxruntime；启动环境变量；自动生成 resources.py；翻译/资源/模型 YAML/入口点打包；CPU/GPU/平台分支。

C8 性能/资源：重复全量扫描/索引；UI 线程 I/O；paint/mouse 热路径 O(n²)；缓存失效和内存增长；节流导致其他组件读取旧状态。

C9 上游升级：高密度修改原生文件；复制原生实现后分叉；私有 API/固定布局/隐式顺序依赖；删除原生入口但调用残留；可文本合并但语义不兼容。

对每个 E×N 候选，必须先从上游实现、上游测试或真实原生调用方提取 native contract，再判断扩展是 preserve、extend、intentional_override、violate 或 unknown。不要以“扩展现在能跑”替代原生契约分析。

输出 native_contracts.json，并为所有候选填写初步 verdict 和证据位置。

【阶段 4：运行时场景验证】
1. 先把候选按影响和证据排序。所有 P0/P1、write↔write、delete/replace→use、lifecycle↔callback 必须进行动态验证或给出为何无法运行的具体原因。
2. 优先运行现有窄测试。可以在 `.tmp-conflict-audit` 编写临时只读探针/offscreen Qt 场景，但禁止向 tests/ 或生产代码写入为了审计而新增的测试。
3. 场景至少覆盖并按真实操作顺序组合：
   - 启动→加载目录/文件→切图→关闭；
   - 创建/编辑/删除→撤销/重做→保存→重载；
   - 单选/多选/框选→绘制/平移/缩放→复核/跨图操作；
   - 筛选/Inspector/质检复核→导航→编辑→复扫；
   - 设置修改→即时应用→重置→重启读取；
   - worker 运行时切图、重复启动、取消、关闭；
   - 旧 JSON、未知字段 JSON、异常数据 round-trip。
4. 按共享资源挑选组合，不要求所有功能全排列，但必须覆盖：
   - 每个核心状态至少一个双功能场景；
   - 同时影响三个以上组件的状态至少一个三功能场景；
   - 所有 P0/P1 候选对应场景。
5. 在场景中显式验证：
   - current file、UI、数据模型一致；
   - selection 无已删除/旧文件对象；
   - canvas 互斥 mode 不会同时生效；
   - dirty、save、undo/redo 一致；
   - 配置 UI、内存和落盘一致；
   - worker 结果只应用到仍有效上下文；
   - JSON round-trip 不丢字段；
   - 关闭/切图/异常后无悬挂线程、timer、连接和状态。
6. 测试通过时确认它确实触发冲突候选的顺序和交叉状态，不能只记测试文件名称。
7. 生成 scenario_matrix.json 和 test_evidence.json，记录命令、退出码、触发路径、断言、结果和限制。

【阶段 5：上游演进检查】
1. 统计扩展修改最密集的原生文件和符号，分别给出 hunk 数、耦合组件数和共享状态数。
2. 搜索复制的上游实现、`_private` API、固定 menu/tab 索引、隐式 signal 顺序和生成物手工修改。
3. 若本地存在可用的更新上游引用，只使用只读 diff/merge-tree/目录三方比较；禁止实际 merge/rebase。
4. 区分 textual conflict、semantic conflict、generated overwrite、private API drift、duplicate implementation drift。
5. 生成 upgrade_hotspots.json。每个热点说明触发上游升级风险的具体原因，不要只按修改行数排名。

【阶段 6：候选判定】
每个 candidate 必须落入且只能落入一个主要结论：
- confirmed_conflict
- latent_conflict
- upgrade_conflict
- maintenance_risk
- intentional_override
- compatible
- unknown

严重度与置信度分开：
- P0：数据损坏/丢失、安全、稳定崩溃、无法启动；
- P1：核心标注错误、跨文件污染、线程/生命周期高风险；
- P2：局部失效、偶发状态错误、明显升级阻塞；
- P3：维护风险、轻微 UI 冲突、低概率兼容问题。

每条 finding 必须包含：
- conflict_id、domain（extension_internal 或 extension_native）、C1..C9；
- severity、confidence、status；
- components、features、文件和精确行号；
- preconditions、trigger_sequence；
- conflict_path：A action → shared resource → B assumption → violated invariant；
- observable_impact；
- static/runtime/native-contract evidence；
- false-positive checks；
- recommended_direction；
- required_regression_test。

如果缺少触发条件、被违反的不变量或可观察影响，只能作为调查线索/maintenance_risk/unknown，不能夸大成 confirmed bug。compatible 和 intentional_override 也要保留反证依据，避免未来重复调查。

输出 conflict_findings.jsonl 和 unknown_items.json。

【阶段 7：正式报告】
创建或更新《扩展代码冲突检查报告.md》，使用以下结构：
1. 执行摘要：基准、范围、结论数量、最高风险、硬门槛是否通过；
2. P0/P1 确认冲突；
3. P2/P3 确认或潜在冲突；
4. 扩展内部 E×E 交互矩阵；
5. 扩展—原生 E×N 契约矩阵；
6. intentional override 与 compatible 项摘要；
7. 上游升级热点；
8. 动态场景和测试结果；
9. unknown、扫描限制和证据缺口；
10. 按收益/风险排序的修复方向和必须新增的回归测试；
11. 审计产物索引与复现命令。

报告必须以 finding 为中心，先给结果再给过程。每条问题链接到精确文件/行号，说明触发链和影响。不要只输出大段模块介绍，不要把代码风格问题混进冲突主列表。

【最终硬验收】
逐项确认：
1. 原生/扩展/modified hunk/工作区边界闭环；
2. 未分类、无法读取项是否为 0；
3. 状态、事件、UI、配置、数据、生命周期、注册、文件资源是否全部建索引；
4. 所有共享写、替换后使用、事件争抢、异步寿命候选是否有 verdict；
5. 每个 E×N verdict 是否有原生契约证据；
6. override/super、signal/event/shortcut、配置链、JSON round-trip 是否检查；
7. 每个 P0/P1 是否有复现、测试或高强度静态证明；
8. 双功能和三功能高风险场景是否覆盖；
9. 关闭、切图、取消、异常、后台晚到是否覆盖；
10. 上游热点、私有 API、复制实现、生成物风险是否覆盖；
11. 每条 finding 是否包含触发链、不变量和可观察影响；
12. unknown 是否说明证据缺口和影响范围；
13. 结束时 git status 是否与记录的工作区变化一致。

若任何硬门槛未通过，报告只能写“在已完成范围内发现/未发现以下冲突”，并显著说明缺口；禁止写“代码不存在冲突”。不要修复发现的问题，除非用户随后单独授权。

【最终回复】
完成后给出高密度摘要：
- 审计基准和实际范围；
- E×E、E×N 候选数及各 verdict 数量；
- P0/P1/P2/P3 数量和最关键的 3～10 条结论；
- 动态场景及测试命令结果；
- 边界/候选/判定/场景四闭环是否通过；
- unknown 和未覆盖范围；
- 正式报告及全部审计产物路径；
- 实际修改的文件列表。

现在开始直接执行。先读取所有约束和方法，再持续完成边界建模、候选生成、静态检查、动态验证、上游升级分析、正式报告和最终验收，不要停留在计划阶段。
```

