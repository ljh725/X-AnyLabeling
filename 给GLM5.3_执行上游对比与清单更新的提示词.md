# 给 GLM-5.3 的直接执行提示词

下面代码块内的内容可整段复制给 GLM-5.3。它的目标不是只给建议，而是直接完成审计、更新两份清单并提交可核验结果。

```text
你现在在 Windows PowerShell 环境中维护 X-AnyLabeling fork。请直接执行一次“上游对比与两份清单更新”任务，不要只写计划或解释方法。

【工作目录与参照物】
- fork 根目录：D:\xinjiegou-X-AnyLabeling-4.0.0-beta.4
- 本地可信上游候选目录：D:\X-AnyLabeling-4.0.0-beta.4
- 方法文档：D:\xinjiegou-X-AnyLabeling-4.0.0-beta.4\上游对比与清单更新_三层四闭环方法.md
- 待更新文档一：D:\xinjiegou-X-AnyLabeling-4.0.0-beta.4\功能总表_上游与个人扩展.md
- 待更新文档二：D:\xinjiegou-X-AnyLabeling-4.0.0-beta.4\个人修改与扩展清单.md
- 审计临时产物目录：D:\xinjiegou-X-AnyLabeling-4.0.0-beta.4\.tmp-doc-update

【总目标】
以方法文档为强制执行规范，机器穷举 fork 相对可信上游的全部文件和代码变化，将变化归纳为真实、可达、可验证的功能或工程变化，然后更新两份清单。最终必须同时完成：集合闭环、变更闭环、功能闭环、文档闭环。不能用“看起来差不多”“行数同量级”代替精确对账。

【开始前必须遵守】
1. 先完整读取仓库 AGENTS.md、方法文档和两份待更新文档，再执行任务。
2. 全部命令使用 PowerShell 语法；多行命令第一行设置 `$ErrorActionPreference = 'Stop'`。
3. 优先使用 `rg`、`git` 和明确路径；Python 使用：
   C:\Users\20441\.conda\envs\x-anylabeling-cu12\python.exe
4. 当前工作树包含用户已有修改。必须保留所有修改，禁止执行 git reset、git checkout、git clean、删除、覆盖回滚、自动提交或与任务无关的格式化。
5. 本任务只允许修改两份清单文档以及 `.tmp-doc-update` 内的审计脚本/产物。不要修改应用源码、测试、配置和生成资源。
6. 不得联网拉取或 fetch，除非现有本地参照物完全无法完成来源判定；若确实需要联网，先报告原因并等待授权。
7. 不要因为看到 Permission denied 就忽略路径；任何无法扫描或读取的目标都必须进入 scan_errors.json，并阻止“全量无遗漏”结论。
8. 不要先向用户询问可以从仓库和文档中自行发现的信息。只有基准确实无法判定且不同选择会改变结论时才停下报告阻塞。

【阶段一：固定基准与快照】
1. 读取 fork 的 remote、branch、完整 HEAD、提交时间和 `git status --porcelain=v1 -z -uall`。
2. 检查本地上游候选目录是否存在、是否为 Git 仓库、HEAD/remote/dirty 状态；若不是 Git 仓库，把它作为目录快照并计算 manifest 摘要。
3. 从两份旧文档的“基准与验证方法”中提取上次确认覆盖到的 DOC_BASE。不要把 DOC_BASE 当作 UPSTREAM_BASE。
4. 独立确定并记录：
   - UPSTREAM_SOURCE：可信上游来自哪里；
   - UPSTREAM_BASE：来源判定所用上游版本或目录树摘要；
   - DOC_BASE：旧文档覆盖到的 fork commit；
   - TARGET：当前完整 HEAD；
   - WORKTREE_SNAPSHOT：staged、unstaged、untracked 文件和 patch/manifest 摘要。
5. 把以上内容、时间、脚本摘要、排除规则摘要写入 `.tmp-doc-update/audit_meta.json`。
6. 已提交内容和未提交工作区必须分开审计、分开写文档；工作区内容只能进入“进行中”。

【阶段二：第一层——对称文件全集】
1. 编写或修正 `.tmp-doc-update` 内的审计脚本。文件写入必须使用可靠的编辑方式，不要用易破坏编码的临时 shell 拼接。
2. 双方采用对称的文件枚举口径。若使用 Git 输出，必须用 `-z` NUL 分隔；不要用普通 splitlines 解析 porcelain 路径。
3. 完整枚举 tracked、untracked 和 excluded/ignored 候选。是否属于噪声只能在机器点名后分类，排除项必须写入 exclusions.json，并记录每条规则的命中数量和样例。
4. 目录扫描必须捕获 os.walk/onerror、权限、坏链接、无法读取、大小写冲突等错误，写入 scan_errors.json。
5. 为双方生成 manifest，字段至少包括：相对路径、文件种类、大小、SHA-256、来源集合、读取状态。
6. 生成主四桶：identical、modified、fork_only、upstream_only；另外生成 renamed_or_moved、copied、binary_or_large、generated、symlink_or_mode_changed、case_collision、unreadable 辅助表。
7. 生成：
   - upstream_manifest.json
   - fork_manifest.json
   - exclusions.json
   - scan_errors.json
   - buckets.json
   - rename_copy_candidates.json
8. 验证四桶并集和交集关系。若 scan_errors 中还有未解决错误，不得进入“保证全量”的结论；先尝试安全的只读替代枚举方式，仍失败则明确列为未决。

【阶段三：第二层——diff hunk 与功能归因】
1. 分别生成两种 diff，严禁混用：
   - 累计来源 diff：UPSTREAM_BASE → TARGET；
   - 本轮增量 diff：DOC_BASE → TARGET，再叠加 WORKTREE_SNAPSHOT。
2. 使用 rename/copy 检测，至少包含 `--find-renames=40% --find-copies=40% --full-index --binary` 和 numstat/name-status 结果。
3. 为每个文本 hunk 生成 hunk_id（路径、old/new range、内容 hash）；整文件新增、删除和二进制变化也生成等价 ledger 项。
4. 每个 ledger 项必须归入：一个或多个 feature_id，或明确的 refactor/format_only/version_only/generated/docs_only/tests_only 等非功能原因。不要只做文件级概括。
5. 机械枚举以下功能面，新增、删除、改名、默认变化都要检查：
   - QAction、action helper、QShortcut、菜单、工具栏、右键菜单、按钮、动态 action、信号连接、快捷键配置；
   - YAML 默认值、schema、类型/范围、运行时应用器、持久化、旧配置迁移；
   - 模型/组件/规则/导入导出器 registry、CLI 命令；
   - JSON 字段、序列化、缓存、索引、兼容读取；
   - 依赖、打包、资源、i18n、构建脚本、平台兼容；
   - 测试、质检规则、阈值、报告格式和错误处理。
6. 逐个检查 DOC_BASE..TARGET 的 commit，每个 commit 必须归入功能、工程、测试、文档、生成物或明确的琐碎项。
7. 为每项功能分配稳定 feature_id，并分类为 added、enhanced、behavior_changed、fixed、renamed_or_moved、deprecated_or_removed、performance、security、compatibility 或 engineering_only。
8. 每项已完成功能建立可达链：入口/触发方式 → 注册/信号/导入 → 核心逻辑 → 持久化/文件输出/可见结果 → 测试或实际证据。
9. 只有实现文件但无入口的标为 implemented_but_unreachable；只有入口没有完整处理的标为 stub_or_incomplete，不能计入已完成能力。
10. 生成：
   - cumulative_diff_summary.json
   - incremental_diff_summary.json
   - hunk_ledger.jsonl
   - surface_inventory.json
   - feature_ledger.json
   - unresolved_items.json
11. feature_ledger 至少包含：feature_id、名称、功能域、变化类型、来源结论、状态、首次引入 commit、相关文件、hunk_ids、入口、输出/持久化、验证证据、置信度、备注。

【阶段四：第三层——证据验证】
1. 来源判定使用官方 commit/tag 或可信上游目录快照证据；不能只凭类名、代码风格或 commit message 猜测。
2. 结构证据使用文件分桶、diff、pickaxe、调用关系和知识图谱。若使用 `.understand-anything`，先核对 meta.json 的 gitCommitHash，过期必须注明，不能当作当前代码事实。
3. 行为证据优先使用现有窄范围测试、UI/CLI 可达性、输入输出样例。不要为了这次文档任务修改应用代码来让测试通过。
4. git diff、pickaxe 和同一代码生成的图谱不是三条完全独立来源证据，不要机械凑“两条路径”。
5. 每项功能标记 confirmed/high/medium/unknown。无法证实的内容保留 unknown 和证据缺口，不要强行二分。
6. 生成 evidence_matrix.json，记录每项功能的来源、结构、行为证据和置信度。

【阶段五：更新两份文档】
1. 以 feature_ledger.json 为唯一中间事实源，先更新《个人修改与扩展清单》，再同步《功能总表》。不要在两份文档中独立凭印象编写。
2. 《功能总表》描述当前产品全貌：上游、个人新增、个人增强、个人修改、退役和进行中状态均清楚标识。
3. 《个人修改与扩展清单》只描述相对指定上游基准的 fork 变化：修改文件、功能变化、删除/退役、工程变化和工作区进行中。
4. 每个个人功能在两份文档中使用相同 feature_id。验证：
   表一中“个人新增/个人增强/个人修改”ID 集合 == 表二对应“已实现/进行中”ID 集合。
5. 表二中的删除/退役项必须同步影响表一；进行中项不得在表一被写成稳定已发布能力。
6. 更新两份文档的表头基准、完整 SHA、工作区状态、验证方式、统计口径、文件数、功能数、action/配置数量和未知项。
7. 不要把 generated、tests、docs 的行数混成手写功能代码行数；各种口径分别注明。
8. 保留文档中仍准确的历史信息，不要为了重写风格删除有价值内容。

【阶段六：验收与收口】
逐项验证并写入 `.tmp-doc-update/audit_report.md`：
1. 四个基准是否明确且未混用；
2. 双方枚举口径是否对称；
3. unreadable、permission_error、path_collision、unexpected_error 是否为 0；
4. 四桶和 manifest 是否精确闭环；
5. rename/copy/binary/generated 是否有结论；
6. 每个 hunk/整文件变化是否有归因；
7. UI、配置、注册表、数据契约、工程面是否完成枚举；
8. 每项已完成功能是否有可达链和验证证据；
9. 每个 commit 是否完成归因；
10. 两份文档的个人 feature_id 集合是否一致；
11. 删除、退役、默认变化、进行中状态是否同步；
12. unknown/未决项是否完整披露；
13. 审计结束时重新读取 git status，检查期间是否出现新变化。

如果所有硬门槛通过，可以写“在记录的基准与扫描口径下完成全量审计，未发现未归因项”。不要写绝对化的“永远保证无遗漏”。如果有门槛未通过，仍尽可能完成可确认部分的文档更新，但必须在表头和最终报告显著列出未决项及影响范围。

【最终回复格式】
执行完成后只给一个高密度结果摘要，必须包含：
- 两份文档各更新了什么；
- UPSTREAM_BASE、DOC_BASE、TARGET、WORKTREE_SNAPSHOT；
- 四桶数量、扫描错误数量、hunk 总数/未归因数、功能数量和置信度分布；
- 两表 feature_id 对账结果；
- 执行过的验证命令及结果；
- 所有 unknown、阻塞、限制和需要人工确认的点；
- 本次实际修改的文件列表。

现在开始直接执行。先读取约束和现状，然后持续完成到验收结束，不要停留在计划阶段。
```

