# A 组深度核查：流程 / 质量 / 持续执行类 7 个候选

- **核查人**：deep-process（共享任务 task-4，A 组）
- **抓取时间**：**2026-11-09**（首轮 09:15–09:47 +08；本机 DSH 09:48 重启后 09:53 恢复补查）
- **目标项目**：X-AnyLabeling（PyQt6 桌面标注工具，Windows；`label_widget.py` 约 9,968 行、196 个 pytest 文件、当前 23 个未提交改动、已有 openspec 流程）
- **环境**：DSH 0.2.2-rc.1，profile = `desktop`，沙箱 workspace-write
- **纪律**：**本轮只读调查，未安装、未卸载、未运行任何插件**。凡涉及"能不能真跑起来"的结论一律标注 **实测：未做**。
- **证据分层**：**【作者声明】**=市场页/README/包元数据作者自述；**【源码发现】**=我直接读到的 package.json / cordis.patch.yml / adapter 源码 / 测试文件清单；**【我的推断】**=由上述事实推理。未读到的明确写"未验证"。

### 数据来源与可信度说明

| 来源 | 用途 | 抓取时间 |
|---|---|---|
| 本地市场快照 `.tmp/dsh-sel-20261109/plugins_raw.json`（9,687 条，`updated=2026-11-08`）+ `candidates.csv` | stars / downloads / added / install 命令 / 分类 | 2026-11-09 08:58 快照 |
| 市场页 `https://awesome-dsh-plugin.com/p/<owner>/<name>/` | 安装命令、简介、**渲染后的 GitHub README 全文** | 2026-11-09 |
| `https://registry.npmjs.org/<pkg>/latest` | **npm 上真实 package.json**（`dsh` 字段、engines、deps、scripts） | 2026-11-09 |
| `raw.githubusercontent.com` | GitHub-only 包的 package.json / patch / adapter 源码 | 2026-11-09 |

**踩坑记录（影响证据完整度）**：① `raw.githubusercontent.com/PerryLink/dsh-doublecheck/HEAD/package.json` 抓取失败一次，改用 npm registry 取到同一份 manifest；② `@michengai/dsh-pua` 首次抓取失败、第二次成功；③ 抓取 `dsh-client-auto-continue` 期间出现一次 aborted（09:47 前后，与宿主重启时间吻合）；④ **未抓 GitHub API**，因此"最近提交/issue 数"没有硬数据，只有 npm 发布时间与版本号可推；⑤ 抓取 `superpowers-dsh`、`dsh-pua`、`dsh-auto-continue`、`dsh-task-ledger` 的 **README 全文未读**（只读到市场页简介/目录描述 + npm manifest），这四条的"停止条件"证据因此弱于另外三条，已逐条标注。

---

## 0. 先说三个跨候选的结构性发现

**发现 1（最重要）：目录的 `capabilities` 字段不能当作"是否真执行"的证据。**
市场目录给 Aegis 标了 `shell|fs-write|fs-read|env`、分类"执行型"，但它的 DSH 接入层源码（`extensions/dsh/index.js`）只做了两件事：挂一个只读的文件系统技能 provider（`includeDefaultRoots:false`，指向自带 `skills/`），并在生命周期开始注入一条路由用 user message。**它没有注册任何 tool、command、hook，也没有写文件。**【源码发现】
→ 判定"执行型 / 提示型"必须看 **package.json 的 `dsh` 字段 + adapter 源码**，不能看目录标签。本报告已按这个口径重判。

**发现 2：`engines.dsh` 的 prerelease 语义是 A 组最大的兼容性不确定性，且作者们的写法互相矛盾。**
- `dsh-doublecheck` 的写法是逐版本叠加：`>=0.2.0-0 <0.3.0 || >=0.2.1-0 <0.3.0 || >=0.2.2-0 <0.3.0`——`-0` 正是 node-semver 用来"允许该 `x.y.z` 元组的 prerelease 通过"的技巧。【源码发现】
- 若按**严格 node-semver**（不含 `includePrerelease`），`@michengai/dsh-pua` 的 `>=0.2.0-rc.1 <0.3.0-0` **不覆盖 0.2.2-rc.1**（范围内唯一带 prerelease 的比较子是 `0.2.0-rc.1`，元组是 `[0,2,0]`，与 `[0,2,2]` 不同）；但它的 devDependencies 又全部钉在 `0.2.2-rc.1`。【源码发现，两者矛盾】
- **我的推断**：DSH 的 engines 校验大概率是严格模式（否则 doublecheck 作者不需要逐个 minor 加 `-0` 行），那么 dsh-pua 可能在安装/加载时被版本门拦下。**实测：未做**；本轮**无法**从 DSH 源码确认——checkout 位于 `app.asar` 内部，`ops_grep` 对 asar 路径返回 `PATH_RESTRICTED`（我试过一次，未绕过）。
→ 结论：**只有 dsh-doublecheck 一个候选有"显式 0.2.2-rc.1 适配声明"，其余都在 0.2.1-rc.2 或更早就停止验证了。**

**发现 3：目录元数据滞后于 npm。** `superpowers-dsh` 目录写 0.4.0、npm 实际 **0.5.0**；`dsh-task-ledger` 目录写 0.1.7、npm 实际 **0.1.10**。选版本千万别按目录抄。【源码发现】

---

## 1. 对比总表

| 候选 | 精确安装目标（桌面 profile 用 `--profile desktop`） | 类型 | 核心能力 | DSH 0.2.2-rc.1 兼容 | 外部依赖 | 匹配度 | 停止与恢复机制 | 维护 | 建议 |
|---|---|---|---|---|---|---|---|---|---|
| **dsh-doublecheck**（PerryLink） | `dsh plugin --profile desktop add dsh-doublecheck`（npm 0.9.30） | **执行型**：2 个插件行 + 3 个 tool + 2 个 command + 4 个 skill + 1 个 session projection | 需求审讯→六维 spec→红/绿测试证据→对抗评审→四阶段交付闸门，输出 deliverable/rework | ✅ **明确适配**：`engines.dsh` 含 `>=0.2.2-0 <0.3.0`；README 声明 2026-11-05 适配 rc.1 | 无网络/无凭据；可选依赖内置 `auto-review`（弱依赖，缺失则降级本地 reviewer）；需要 `subagent` 服务 | **高** | 强度 `remind/warn/block` 三档；reviewer 不可用时写"unavailable"不伪造；adversary `timeoutMs=120s`、`maxFindings≤20`；**会话日志即状态**，resume/fork 重放得到同一结论 | ⭐58 / 4,741 dl / v0.9.30（2026-11-05 发布） | **建议入选（A 组首选）** |
| **Aegis**（GanyuanRan） | `dsh plugin --profile desktop add github:GanyuanRan/Aegis`（git，非 npm，v2.15.0） | **提示型**：1 个行，只挂 skills 目录 + 会话启动路由注入；**0 tool / 0 command / 0 hook 写操作** | 方法论包：基线优先规划、系统化调试、完成前验证、修复/退役跟踪、UI-UX 治理 | ⚠️ **未声明**：package.json **无 `engines` 字段**；peer 只写 `>=0.1.0-rc.6`（optional）；作者自己的宿主矩阵说 DSH "install guide 存在，release 级 smoke 待做" | 运行期无；但 `aegis-doctor.py` 验证流程需要 **python3**，测试脚本需要 bash | 中 | 无自动续跑、无熔断（因为它不执行）；只有 activation mode（auto/explicit）与 TDD 开关（默认 off） | ⭐1,411 / 无 npm / v2.15.0；基准更新到 2.10.8（2026-09-25） | 备选，**不要与 superpowers-dsh 同装** |
| **superpowers-dsh**（LayneChai，精确包名 `superpowers-dsh`） | `dsh plugin --profile desktop add superpowers-dsh`（npm **0.5.0**，目录写 0.4.0 已滞后） | **提示型**：只注册 14 个 skill（obra/superpowers v7.0.2 移植），**零运行时依赖** | TDD、系统化调试、写计划、并行派发、code review、完成前验证等技能文本 | ⚠️ **未声明**：无 `engines`、无 deps、无 peer；纯文本、API 暴露面最小，但也没人验证过 rc.1 | 无 | 中低 | 无执行逻辑，无停止/恢复概念；完全靠模型自觉 | ⭐135 / 8,270 dl / v0.5.0（2026-11-08 发布） | **淘汰**（被 Aegis 覆盖且更薄） |
| **loopx**（loopx-project） | `dsh plugin --profile desktop add "https://github.com/loopx-project/loopx/releases/download/dsh-loopx-plugin-v0.1.1-beta.6/dsh-loopx-plugin-0.1.1-beta.6.tgz"` | **执行型**（3 个 Loader 行 + GoalBar 宿主路由 + 可选 observer） | 长周期状态内核：Goal/Todo/门禁/证据/配额/恢复/交接；有界同会话续跑 | ❌ **硬阻断**：beta.6 只接受 0.1.5 rc~stable、0.1.7-rc.2、**0.2.0-rc.2、0.2.1-rc.1、0.2.1-rc.2**，README 明写"排除其他未鉴定的 prerelease 元组"；安装器会**在改 profile 前拒绝不兼容宿主** | **重**：Node 22.22.3+、pnpm、**Python 3.11+ + pip**、首次启动联网；LoopX CLI ≥1.2.4 由插件 pip 装到隔离 runtime | 低 | 最细：Driver 只重试安全只读/idempotent 调用，**最多 2 次额外重试（共 3 次）**；typed denial/schema 不符/取消/人工输入**永不重试**；无累计 8 次熔断、无插件自有持久激活态；每次自动续跑前重校验绑定+配额 | ⭐6,537 / 无 npm / v0.1.1-beta.6；README 自曝 beta.6 热卸载会断开 DSH | **淘汰（不兼容）** |
| **dsh-pua**（MichengAI，`@michengai/dsh-pua`） | `dsh plugin --profile desktop add @michengai/dsh-pua`（npm 1.0.8） | **执行型**（host 侧 `/pua` + **web 客户端 UI** 卡片；manifest 无 `tools:register`） | 失败后促换方法、宣称完成前核验收据；15 种公司风格/角色模式；可选验收循环 | ⚠️ **半确定**：`engines.dsh: ">=0.2.0-rc.1 <0.3.0-0"`；devDeps 全钉 **0.2.2-rc.1**（说明按 rc.1 构建），但按严格 semver 该范围不含 rc.1（见 §0 发现 2） | 无凭据；需 web 客户端插槽（6 个 client 注入）；`overrides` 写在被依赖包里对消费方**无效** | 中低 | 验收循环的退出条件：**验收命令通过 / 达到迭代上限 / 用户取消**（作者声明，具体上限数值未查到）；无宿主级熔断证据 | ⭐65 / **26,965 dl**（下载/星标比异常）/ v1.0.8（2026-11-05 发布） | **淘汰**（与 auto-review/goal 语义重叠） |
| **dsh-auto-continue**（HsiangNianian） | `dsh plugin --profile desktop add dsh-client-auto-continue`（npm 0.17.4，**包名与插件名不同**） | **执行型**（host hook + **web 客户端 UI**；非模型工具） | 请求因网络/超时/宿主崩溃中断后自动发"继续"；错误分类、自适应退避、模板化续跑文本、浏览器通知 | ⚠️ **未验证**：无 `engines.dsh`；peer `dsh-settings: ^0.1.0-rc.7 \|\| ^0.1.7-0 \|\| ^0.2.0-rc.1`，`test:runtime` 只跑 0.1.7 / 0.2.0 / 0.2.1 / 0.2.1-rc.2，**没有 0.2.2** | 无凭据；web 客户端插槽 | 中低 | 测试文件显示存在 `loop-guard-progress`、`autonomous-loop`、`manual-resume-pauses`、`failure-classification` → **有轮次守卫与"手动恢复即暂停"**（源码发现：仅见测试文件名，未读实现，上限数值未验证） | ⭐187 / 10,818 dl / v0.17.4（2026-11-07 发布） | **淘汰**（内置 goal/agent-team 已覆盖） |
| **dsh-task-ledger**（cq-guojia） | `dsh plugin --profile desktop add dsh-task-ledger`（npm **0.1.10**，目录写 0.1.7） | **提示型 + 看板**（技能 + web 侧边栏看板；manifest **无 `tools:register`**，含 `copy-skill.mjs`/`verify-skill.mjs`） | 任务由代理创建/认领/推进/结案，写入 workspace 纯文本台账；看板汇总进行中/逾期/停滞 + 周趋势 | ⚠️ **未声明**：只有 `engines.node >=22.5`，**无 `engines.dsh`** | 无凭据；但引入**非官方第三方运行时依赖 `dsh-plugin-core ^0.35.7`**（不在 `@deepseek-ai` 作用域）；web 客户端插槽（含 sidebar） | 低 | 无续跑/熔断概念；恢复 = 台账文本本身（git 同步），无进程级恢复 | 星标未采集 / **23,622 dl** / v0.1.10（2026-11-09 发布）；4 天内从 0.1.7→0.1.10 | **淘汰**（内置 task_board 更强） |

> 兼容性一带的 ✅/⚠️/❌ 含义：✅ = 作者显式声明并覆盖 0.2.2-rc.1；⚠️ = 无版本门禁或只验证到 0.2.1；❌ = 作者显式排除。**所有安装后的真实加载行为均未实测。**

---

## 2. 逐候选 8 点核查

### 2.1 dsh-doublecheck / PerryLink

**① 精确安装目标与市场数据**
`dsh plugin --profile web add dsh-doublecheck`（作者给的 web 写法）→ 本项目应写 `--profile desktop`。【我的推断：profile 名替换，命令结构不变】
npm 包名 `dsh-doublecheck`，版本 **0.9.30**，★58，30 天下载 4,741，加入目录 2026-08-14，分类 Workflow & Automation。仓库 <https://github.com/PerryLink/dsh-doublecheck>，市场页 <https://awesome-dsh-plugin.com/p/PerryLink/dsh-doublecheck/>。【作者声明/目录数据】

**② 真执行 vs 提示型 —— 判定：执行型（证据最硬的一个）**
- `dsh.capabilities: ["tools:register"]`，`dsh.bundle.patch: "./cordis.patch.yml"` → 注册模型工具并插入插件行。【源码发现】
- 两个行：`doublecheck-grill`、`doublecheck-guard`；另有可选 `dsh-doublecheck/invariant` 伴随行（向宿主 `invariants` 注册表报告写路径矛盾）。【源码发现】
- 3 个 tool：`doublecheck_skills`、`doublecheck_spec`、`doublecheck_report`；2 个 command：`/doublecheck`、`/gate`；4 个 skill；1 个 session projection `doublecheck`（**120 字符硬预算**的单行状态）。【作者声明 + 源码发现：`dsh.capabilities`】
- 写文件：`doublecheck-spec.md`、`doublecheck-report.md`、`gate-report.md`、`gate-report.json`（走 `ctx.fs`），全部落在 session workspace 内。【作者声明】
- 需要宿主 hook 能力：监听 `tools/pre-execute`、`tools/post-execute`、`agent/turn-stopping`，且声明每个 listener 都 `next()` 透传、不短路。【作者声明（未读实现，未验证）】

**③ DSH 0.2.2-rc.1 兼容性 —— 本组唯一"显式 ✅"**
`engines.dsh = ">=0.1.6-0 <0.2.0 || >=0.2.0-0 <0.3.0 || >=0.2.1-0 <0.3.0 || >=0.2.2-0 <0.3.0"`，`engines.node = "^22.19.0 || >=24.9.0"`。README 兼容表：`dsh-v0.2.2-rc.1`（adapted 2026-11-05），"gate and projection paths are covered by the rc.1 test suite"。【源码发现 + 作者声明】
peerDeps：`@deepseek-ai/cordis ^4.0.5-alpha.1`、`@deepseek-ai/schemastery ^3.18.5-alpha.1`、`dsh-llm/dsh-agent/dsh-skill/dsh-tools/dsh-session/dsh-commands/dsh-invariants/dsh-session-projection` 均为 `>=0.1.6-0 ... >=0.2.2-0 <0.3.0` 的多段范围 → 0.2.2-rc.1 落在 `>=0.2.2-0 <0.3.0` 内。✅
唯一小瑕疵：`dsh.dshWorkshop.compatibility.dshVersions` 只列到 `0.2.1-alpha.1`（滞后于 engines 与 README）。【源码发现】

**④ 人工确认 / 外部服务 / 凭据 / 额外运行环境**
- 无网络请求、无凭据、无 API key（README 明确"makes no direct network requests"）。【作者声明】
- 需要宿主提供 `subagents` 服务（consistency / review 两个阶段各起 1 个 forked 子代理）；`gate.review.engine:auto` 时若本会话已有 `autoReview/verdict` 事件则可零成本复用——**本项目已装内置 `auto-review`，这是正向协同**。【作者声明 + 我的推断】
- `doublecheck_report` 的逐维度核对需要 `workflowEngine`（本项目内置 `workflow` 已启用）。【作者声明】
- 会调用 `ask_user_question` 并把其调用记录当作"需求审讯证据"——本项目该工具存在，✅。【作者声明】
- 安装脚本：**无 postinstall**；`prepare` 只在 git 渠道触发（`tsc` 构建），npm 渠道是预构建产物（fileCount 58）。【源码发现】

**⑤ 与已装插件 / 内置能力的重复与冲突**
- 与 `cc-safety-net`：两者都监听 `tools/pre-execute` / `tools/post-execute`。README 声明每个 listener 都经 `next()` 透传、不会让链条短路；`dsh-plugin-doctor` K10–K13 全 pass。**我未读实现，未验证**——这是本候选最需要人工确认的一条。【作者声明】
- 与内置 `auto-review`：**不是重复而是互补**（gate 折叠 auto-review 的 verdict 记录；缺失时降级本地 reviewer，不伪造结论）。【作者声明】
- 与内置 `task_board` / `goal`：无重叠（它不管任务分派、不管目标续跑，只管"交付是否有证据"）。
- 与 openspec：**存在概念重叠**——openspec 已有 change/spec 流程，doublecheck 又要一份六维 spec（`doublecheck-spec.md`）。会多一个 spec 权威源。【我的推断】建议只让它产**验收/证据**部分，spec 正文仍以 openspec 为准。
- 工具名全部带命名空间、不提供 service key、不注册 client slot、不注册 webServer 前缀 → 无插槽竞争。✅

**⑥ 停止条件 / 失败处理 / 中断恢复 —— 本组最强**
- 三档强度：`intensity: remind / warn / block`（默认 `remind`）；`strict.patch.yml` 可一键全 `block` + 强制覆盖率。【作者声明】
- 红绿灯规则：spec 缺失、最新测试非绿、覆盖率低于阈值、编辑未映射到任何 spec 维度、blocker/major finding → 每项一个红灯 + rework 建议；**warning 与 skip 永不翻转判决**。✅ 这是"明确不会无限循环"的设计。【作者声明】
- reviewer/adversary 跑不起来时，结论写 `unavailable`/skip，**不伪造判决**（fail closed / fail loud）。【作者声明】
- 预算：`adversaryTimeoutMs=120000`、`adversaryMaxFindings=5`（1–20）、`gate.consistency.timeoutMs=120000`。✅
- 中断恢复：**"Replay is the state"**——所有证据从会话日志折叠，`/gate run` 在 resume / fork / 重启后重得出同一结果；projection `stateVersion: 3`，升级后丢弃旧缓存重算。【作者声明】
- 已知限制（重要）：`/doublecheck on|off` 与 `/gate run` 的持久记录依赖宿主的 `ignorable` append 通道；文档列举了多条无该通道的宿主线会"跳过写入、开关退化为进程内"。**0.2.2-rc.1 是否具备该通道，README 没有明说 → 未验证**。影响：即便丢失，也只是"开关不跨重启"，闸门判决仍可重算。【作者声明 + 我的推断】

**⑦ 测试与实机证据覆盖了什么、还缺什么**
- 作者侧：`vitest` 全量 + `test:coverage`；`prepublishOnly = typecheck:ci + build + test`；npm 发布带 **SLSA provenance 签名**（`dist.attestations.provenance`）与 GitHub Actions 可信发布（`_npmUser.trustedPublisher`）。【源码发现】
- 作者侧：`dsh-plugin-doctor` K10–K13 全 pass（插件互操作性静态检查）。【作者声明】
- 缺：**在 0.2.2-rc.1 上与本项目真实 pytest 会话的端到端验证**。测试命令识别正则里明确含 `pytest`（`testCommandPatterns` 默认列表），所以 196 个 pytest 文件能被识别；但"`[exit code: N]` 折叠 + 覆盖率百分比解析"在 Windows/MSYS 下是否稳定，**未验证**。【作者声明 + 我的推断】
- 缺：`cc-safety-net` 共存的实际运行证据（只有静态互操作论证 + 作者自己的 doctor 报告）。
- **实测：未做。**

**⑧ 维护情况 / 使用成本 / 配置复杂度**
- 版本 0.9.30，npm 发布时间约 **2026-11-05**（由 npm `_npmOperationalInternal.tmp` 毫秒时间戳换算，【我的推断】）；市场 added 2026-08-14。8 月中旬到 11 月初从 0.1.x 走到 0.9.x，迭代非常活跃。【作者声明 + 我的推断】
- 成本：零配置可跑（bundle patch 自带两行）；默认 `remind` 只会提醒不拦截。每次 `/gate run` 起 1–2 个 forked subagent（有 token 成本）；`gate.review.engine:auto` + 已有 auto-review 记录时可降到 0。【作者声明】
- 复杂度：**中**。要读懂的新概念有：六维 spec、红/绿证据、四阶段闸门、`intensity`、`volatile` 设置卡。对零编程基础用户，建议先用 `remind` + 默认 config，只学会 `/gate run` 和 `/doublecheck status` 两个命令即可。【我的推断】

---

### 2.2 Aegis / GanyuanRan

**① 精确安装目标与市场数据**
市场页 <https://awesome-dsh-plugin.com/p/GanyuanRan/Aegis/>：★**1,411**、**无 npm 包**、加入目录 2026-08-15。
安装（市场页）：`dsh plugin --profile web add github:GanyuanRan/Aegis`；README 给的 DSH 原生写法：`dsh plugin --profile <profile> add "git+https://github.com/GanyuanRan/Aegis.git"`。→ 本项目：`dsh plugin --profile desktop add "git+https://github.com/GanyuanRan/Aegis.git"`。【作者声明】
仓库 <https://github.com/GanyuanRan/Aegis>，MIT，version **2.15.0**，`private: true`。【源码发现】

**② 真执行 vs 提示型 —— 判定：提示型（尽管目录标"执行型"）**
- `dsh.bundle.patch: "./extensions/dsh/cordis.patch.yml"` → 该 patch **只插入一行**：`id: aegis-method-pack`、`name: 'aegis/extensions/dsh/index.js'`。【源码发现】
- `index.js`：`inject = ["skills", "agents"]`；`apply()` 里只做 `applyFilesystemProvider(ctx,{providerName, includeDefaultRoots:false, bundledSkillDir: <pkg>/skills/, watch:false})` + `installBootstrap(ctx,{createUserMessage, skillsRoot})`。**没有 `ctx.tools`、没有 `ctx.commands`、没有写文件、没有网络。** 注释自述："does not copy skill bodies, replace the native skill tool, or add runtime authority."【源码发现】
- → 净效果：把自带的 `skills/` 目录挂成一个技能源，并在会话生命周期开始注入一段 Aegis 路由 user message。**能力全部来自技能文本，执行由宿主现有工具完成。**【源码发现】
- 目录给的 `shell|fs-write|fs-read|env` 来自技能里教模型去用的能力，不是插件自身注册的能力。【我的推断】

**③ DSH 0.2.2-rc.1 兼容性 —— ⚠️ 无版本门禁**
- package.json **完全没有 `engines` 字段**。【源码发现】
- `peerDependencies`：`@deepseek-ai/dsh-agent`、`dsh-llm`、`dsh-skill-filesystem` 均 `>=0.1.0-rc.6`，且全部 `optional: true`。【源码发现】
- 运行期真正 import 的三个东西：`@deepseek-ai/dsh-llm` 的 `createUserMessage`、`@deepseek-ai/dsh-skill-filesystem` 的 `apply`、自己的 `./bootstrap.js`。**这三个面在 0.2.2-rc.1 是否还兼容，作者没有声明、我也没有验证** → 这是"无门禁"的双刃：不会被拦住，但也可能静默出错。【我的推断】
- 作者自己的宿主兼容矩阵把 `DeepSeek Harness` 列在"install guides exist; release-level fresh host smoke is still pending"（有安装指南，发布级实机 smoke 待做）。【作者声明】

**④ 人工确认 / 外部服务 / 凭据 / 额外运行环境**
- 运行期：无凭据、无网络、无外部服务。✅
- 但**安装验证流程需要 python3**：`python scripts/aegis-doctor.py --write-config --json`，判成功要看 `"ok": true`、`"workspaceSupport": "available"`、`"configStatus": "configured"`。【作者声明】
- 维护者测试需要 bash：`bash tests/e2e/run-all.sh --full --host-profile fast`。【作者声明】
- 可选：手动把一段"全局路由前缀"复制到宿主全局用户规则里（`GLOBAL_USER_RULES_TEMPLATE.md`），作者说不装也能用、但路由可能不稳。【作者声明】
- 安装期：git 渠道会跑 `prepare`——但 package.json **没有 `scripts` 字段**，所以不会构建；也就不会遇到 pnpm `allowBuilds` 拦截。✅【源码发现】

**⑤ 与已装插件 / 内置能力的重复与冲突**
- **与 superpowers-dsh 直接重复**：Aegis 自述"derived from Superpowers (obra)"，两者提供同一套方法论的移植。【作者声明】→ 只能选一个。
- 与内置 `skill-explorer`（已装）：Aegis 挂一个新的 skill provider，skill-explorer 会多出一个来源分组；功能上不冲突，但技能数会变多（Aegis 的技能树很大）。【我的推断】
- 与内置 `goal` / `task_board` / `auto-review`：无重叠（它不注册工具、不续跑、不做授权复核）。
- 与 `dsh-doublecheck`：方法论重叠（两者都讲"完成前验证"），但**层不同**——Aegis 是提示词纪律，doublecheck 是可重放的证据闸门。同时装会得到"两套话术 + 一个闸门"，噪声大于收益。【我的推断】

**⑥ 停止条件 / 失败处理 / 中断恢复**
- **没有执行循环，所以没有熔断/重试/恢复可言。** 它只有两个开关：`activation-mode auto|explicit`、`tdd-mode off|auto`（默认 off）。【作者声明】
- 文档层面有"简单任务走快车道、只在风险足够时才加仪式"的复杂度治理，属于提示层约束，无强制力。【作者声明】
- 中断恢复：无——会话重启后只剩技能文件与（可能的）`CONTEXT.md` 术语表。【我的推断】

**⑦ 测试与实机证据覆盖了什么、还缺什么**
- 作者侧有 A/B 基准：120 次有效运行 / 20 个 case，contract pass rate 61.67% → 93.33%，unsafe outcomes 13.33% → 0%，95% 区间 +15.00 ~ +50.00 pp；但作者自己限定这是"bounded advisory evidence"，且**评测客户是 Codex，不是 DSH**。【作者声明】
- 缺：**DSH 宿主上的发布级 smoke**（作者自己承认）。缺：Windows + PyQt6 项目上的效果证据。
- **实测：未做。**

**⑧ 维护情况 / 使用成本 / 配置复杂度**
- v2.15.0，基准从 2.7.6（2026-08-11）走到 2.10.8（2026-09-25），另有独立桌面产品 Autoloom 在推 → 维护活跃。【作者声明】
- 成本：装完即可用，但"验证安装成功"这一步需要 python3 跑 doctor，对零编程基础用户是一道门槛。【我的推断】
- 复杂度：**低-中**（配置少，但技能很多、触发靠自然语言匹配，容易"不知道它有没有生效"——作者自己提供了一份"trigger-chain diagnosis"文档，说明这是常见问题）。【作者声明】

---

### 2.3 superpowers-dsh / LayneChai

**① 先确认作者与精确包名**
"superpowers-dsh" 这个**精确 npm 包名只对应 LayneChai 一个仓库**：<https://github.com/LayneChai/superpowers-dsh>（市场页 <https://awesome-dsh-plugin.com/p/LayneChai/superpowers-dsh/>）。【源码发现：registry `_id: superpowers-dsh@0.5.0`，repository 指向该仓库】
但必须提醒：市场里至少有 **6 个**同方法论（obra/superpowers 移植）的包，极易混淆——`LittleBlackTong/dsh-plugin-superpowers`(0.1.2)、`JasonFreeLab/dsh-superpowers`(@jasonfreelab 0.3.1)、`goodjin/dsh-superpowers`(@goodjin2 0.3.1)、`dennisrongo/dsh-plugins#dsh-superpowers`(0.4.0)、`Meteor-system/superpowers-for-dsh`、`icanfinish11/dsh_superpowers`。【源码发现：candidates.csv 检索结果】
安装：`dsh plugin --profile desktop add superpowers-dsh`。【作者声明】
市场数据：★135、8,270 下载、加入目录 2026-08-23；目录写版本 0.4.0，**npm 实际 0.5.0**（滞后）。MIT。

**② 真执行 vs 提示型 —— 判定：纯提示型**
- `dsh.bundle.patch: "./cordis.patch.yml"`；`dsh.superpowersUpstream: "v7.0.2"`；**没有 `dsh.capabilities`、没有 `dependencies`、没有 `peerDependencies`、没有 `scripts.postinstall`**（只有 `sync`/`compat`/`verify` 三个开发脚本）。【源码发现】
- 包体 85 个文件、解开 2.36 MB → 主体就是 SKILL.md + 参考资料。【源码发现】
- 目录简介："以 Cordis 插件安装并注册 14 个技能（零运行时依赖）"。【作者声明】
- → 它只往技能注册表里加文本，不注册 tool/command/hook，不写文件。

**③ DSH 0.2.2-rc.1 兼容性 —— ⚠️ 无任何声明**
- 无 `engines`、无 peer → 无法从元数据判断。纯 skill 文本对宿主 API 的依赖面最小（只需要技能注册表能读它的 manifest），理论上最不容易被 0.2.x 的 API 变更打坏。【源码发现 + 我的推断】
- 反向风险：也没有任何"我在 rc.1 上验证过"的声明；技能 frontmatter 的 schema 若在 0.2.x 收紧，可能在加载时静默丢技能。【我的推断，未验证】

**④ 人工确认 / 外部服务 / 凭据 / 额外运行环境**
- 无。零依赖、无网络、无凭据。【源码发现】
- 但技能内容会指示模型使用 shell / fs / 网络（目录 capabilities 标了 `shell|fs-write|fs-read|network|env`），实际权限由你的权限档决定 → 在 `workspace-write` 下网络与越界写仍会被拦。【作者声明 + 我的推断】

**⑤ 与已装插件 / 内置能力的重复与冲突**
- **与 Aegis 完全重复**（同一上游方法论）。【作者声明】
- 与已装 `skill-explorer`：会多一个技能来源，不冲突。
- 与内置 `goal/task_board/auto-review/workflow`：无技术冲突，也无协同。
- 与 `dsh-doublecheck`：技能里同样有 TDD / 完成前验证 → 语义重复，但一个是文本一个是闸门。

**⑥ 停止条件 / 失败处理 / 中断恢复**
- **无**。没有执行逻辑，就没有停止条件、重试、熔断、恢复。全部依赖模型遵守文本。【源码发现 + 我的推断】
- 这类包唯一的"失败模式"是：技能被加载但模型没触发 → 无提示、无日志断言。【我的推断】

**⑦ 测试与实机证据覆盖了什么、还缺什么**
- 作者侧脚本：`sync`（从上游同步）、`compat`（检查 DSH 兼容）、`verify`（校验技能）——说明有基本的自检，但**这些是开发脚本，不是 CI 证明**；未见测试结果或 release 说明。【源码发现】
- 缺：DSH 0.2.2-rc.1 加载证据、14 个技能是否全部注册成功的证据、Windows 下的技能触发证据。
- **实测：未做。**

**⑧ 维护情况 / 使用成本 / 配置复杂度**
- v0.5.0，npm 发布时间约 **2026-11-08**（由 npm 内部时间戳换算，【我的推断】）→ 相当新。
- 成本：极低（装完不用配）。
- 复杂度：**最低**，但带来的确定性也最低（纯文本、效果取决于模型是否读技能）。
- 判断：**它是"薄"的那一类**——Aegis 在同一方法论上多做了基线优先、完成前证据、退役跟踪、UI/UX 治理与基准测试，所以薄的那份没有独立存在价值。【我的推断】

---

### 2.4 loopx / loopx-project

**① 精确安装目标与市场数据**
市场页 <https://awesome-dsh-plugin.com/p/loopx-project/loopx--packages-dsh-loopx-plugin/>：★**6,537**（A 组最高）、无 npm 包、加入目录 2026-08-31。
精确安装（作者推荐的不可变 release 资产）：
```
dsh plugin --profile desktop add "https://github.com/loopx-project/loopx/releases/download/dsh-loopx-plugin-v0.1.1-beta.6/dsh-loopx-plugin-0.1.1-beta.6.tgz"
```
备选：`dsh plugin --profile desktop add github:loopx-project/loopx#path:/packages/dsh-loopx-plugin`（会触发 pnpm 构建审批）。【作者声明】
**注意**：`dsh plugin add git+https://github.com/loopx-project/loopx.git` 会装错——README 明写会报 `loopx-repository: entry file missing: index.js`，因为 monorepo 根不是插件包。【作者声明】

**② 真执行 vs 提示型 —— 判定：执行型（本组最重）**
三个独立 Loader 行 + 一个可选 observer：【作者声明】
1. `loopx-init-command`：自动安装/升级 LoopX CLI（`pip install --upgrade --target <plugin-runtime> 'loopx>=1.2.4'`）、把 workflow 技能装到 `$DSH_AGENTS_HOME/skills`、在 DSH 发布 Web URL 之前完成 bootstrap；`/loopx-init` 是显式修复命令。
2. `loopx-driver`：被动同会话续跑。**只有当且仅当当前 Session 里出现"精确的 typed loopx 技能调用证据"** 时才可能激活，然后向活着的 DSH Agent 排入心跳任务。
3. `loopx-goalbar`：注册认证路由 `/api/loopx.goalbar`，在原生 GoalBar 与 Queue 之间插一个 GoalBar（仅当存在唯一 `(goalId, loopxAgentId)` 绑定）。
4. 可选 `observer`（默认关，需 3 个环境变量齐全才注册 hook，只写 ndjson 诊断）。
→ 真执行、真跑子进程、真写文件（`~/.agents/runtime/dsh-loopx-plugin`、`~/.agents/skills`）、真做网络（首次启动下载/安装）。【作者声明】

**③ DSH 0.2.2-rc.1 兼容性 —— ❌ 硬阻断**
- beta.6 的定位："targets the qualified **DSH 0.2.0-rc.2** API and retains the qualified frozen 0.1.5 and 0.1.7-rc.2 compatibility ranges"；当前源码还额外鉴定 **0.2.1-rc.2**。【作者声明】
- 原文："It accepts ... the explicitly qualified 0.1.7-rc.2, 0.2.0-rc.2, 0.2.1-rc.1 and 0.2.1-rc.2 candidates. **It excludes earlier 0.2 candidates, stable 0.2.1, and other unqualified prerelease tuples.**"【作者声明】
- 并且："The installer **rejects an incompatible host before changing its profile**."【作者声明】
→ **0.2.2-rc.1 属于"other unqualified prerelease tuples"，安装器会拒绝。这是本组唯一一个"确定装不上"的候选。**（实测：未做——但不装也有作者明文，风险等级已足够高。）【作者声明 + 我的推断】
- 另一条硬伤：**published beta.6** 仍会给共享 Web 加依赖，**热卸载可能把 DSH 一起断掉**，必须先关 DSH 再用原生 CLI 移除。【作者声明】

**④ 人工确认 / 外部服务 / 凭据 / 额外运行环境 —— 本组最重**
- Node.js **22.22.3+**（排除 Node 23）、**pnpm**、**Python 3.11+ 且带 pip**、首次 DSH 启动需**联网**。【作者声明】
- LoopX CLI ≥ **1.2.4**（含 Windows peer-file 修复），由插件装到隔离 runtime，不改系统 Python。【作者声明】
- 运行期还要：`loopx` 技能对当前 Session 的 typed 调用证据、`.loopx/registry.json`、绑定 + 配额。做财务类操作还要 provider 凭据（`loopx dsh-launch` 从机器凭据注入环境，不进 argv）。【作者声明】
- 首次使用要在 Session 的 shell 里手动跑 `loopx --registry .loopx/registry.json resolve-agent-thread ...` 验绑定，`status=bound` 才准入。【作者声明】

**⑤ 与已装插件 / 内置能力的重复与冲突 —— 重复度最高**
- 与内置 `goal`：直接冲突/重复。goal 已有"同会话目标状态 + 自动续跑轮次 + max_goal_rounds + blocked 需连续 3 轮"；loopx 的 Goal/continuation/quota/recovery 是**平行实现**，且它自己声明"LoopX remains the only authority for Goal, Agent, Todo, quota, activation"→ 两个 Goal 权威源会打架。【我的推断】
- 与内置 `task_board`：Todo/门禁/证据重复。
- 与内置 `schedule`：心跳/定时续跑重复。
- 与 `dsh-rewind-plugin`：恢复语义不同（loopx 是状态内核恢复，rewind 是会话/文件回滚），但都会改"恢复"的心智模型。
- 与 `dsh-task-ledger`：台账重复（若两者都装，会有两套任务账）。
- 唯一真增量：**跨宿主/provider 中立的外部状态内核 + 配额与交接（handoff）+ 证据账本**，面向"长周期多代理/团队"。对本项目的单人 Windows 桌面工具，收益远小于成本。【我的推断】

**⑥ 停止条件 / 失败处理 / 中断恢复 —— 本组写得最细，但用不上**
- Driver 重试边界：只重试"安全的固定 argv LoopX 读"和"幂等的 `quota should-run` receipt"，**最多 2 次额外重试（共 3 次）**；每次重试用同一个 `--turn-instance-id`。【作者声明】
- **永不重试**：typed 授权拒绝、schema 不兼容、取消、需要人工输入。【作者声明】
- **无累计 8 次失败熔断、无插件自有持久激活态**；激活投影只存在于进程内，且只由当前 Session 的 typed 事件历史重建。【作者声明】
- 续跑上限来自 LoopX 的 quota + 本地 scheduler 对"未变化轮询"的上限；**只有一个 typed 的 LoopX 本地调度计划能安排下一次唤醒**。【作者声明】
- 人工优先：一条人类消息会撤掉未认领的自动预留；混合批次会拒绝自动消息并恢复人类工作。【作者声明】
- 每次自动准入**最多排 1 个 Driver 自有 followup**。【作者声明】
- 中断恢复：`resolve-agent-thread` 要求唯一 Goal/Agent 匹配，工作前与工作后各校验一次绑定+配额；失败则**不伪造 writeback/spend/void 回执**。【作者声明】
✅ 这是 7 个候选里唯一给出"精确重试次数 + 明确不重试清单 + 无熔断的理由"的。

**⑦ 测试与实机证据覆盖了什么、还缺什么**
- 作者侧测试面很宽：`pnpm smoke:mcp-transport / smoke:artifact / smoke:profile / smoke:runtime / smoke:docker`、隔离 profile 的真实 web 进程、live-disable 探针、ClientModuleSystem 的 VM 文档 harness、Docker 里跑 Debian + PEP 668 私有安装、以及"owner-reviewed packed-browser gate"（人工层）。作者明确说这些层**不能替代真实浏览器 React 交互**。【作者声明】
- 缺：Windows 原生实机验证（作者自己列为"distinct delivery step"）；0.2.2-rc.1 上的任何验证。
- **实测：未做。**

**⑧ 维护情况 / 使用成本 / 配置复杂度**
- ★6,537 但**没有 npm 包**，只发 release tarball；版本 v0.1.1-beta.6（仍是 beta）；README 自曝热卸载断连缺陷 → 成熟度与星标不匹配。【作者声明 + 我的推断】
- 成本：**高**（Node 22.22.3+/pnpm/Python 3.11+pip/联网 + CLI bootstrap + 手验绑定 + `.loopx` registry）。
- 复杂度：**极高**。三行 Loader + 路由 + GoalBar + 可选 observer + SDK 相关实验模块（`native-operation-context`、`native-operation`，需显式 patch 才加载）。
- 结论：**即使它兼容，对"零编程基础的个人开发者 + 单个 PyQt 桌面工具"也是过度工程。**

---

### 2.5 dsh-pua / MichengAI

**① 精确安装目标与市场数据**
市场页 <https://awesome-dsh-plugin.com/p/MichengAI/dsh-pua/>：★65、**26,965 下载（30 天）**、加入目录 2026-09-18、分类 `agi`。
安装：`dsh plugin --profile desktop add @michengai/dsh-pua`。npm 包名 `@michengai/dsh-pua`，版本 **1.0.8**（与目录一致）。仓库 <https://github.com/MichengAI/dsh-pua>，Apache-2.0。【作者声明 + 源码发现】

**② 真执行 vs 提示型 —— 判定：执行型（宿主命令 + Web 客户端 UI）**
- `dsh.bundle.patch: "./cordis.patch.yml"`；`dsh.client` 注入 6 个客户端模块（connection / api-remotes / ui-settings / ui-conversation / ui-commands / ui-primitives），`platform: "web"`。【源码发现】
- 有 `./client`、`./remote` 两个子导出 → 有客户端组件与 remote 面。【源码发现】
- 能力（目录）：提供 `/pua` 命令；15 种公司风格、角色模式、全局与会话设置、可选验收循环；运行状态卡片。【作者声明】
- **但 manifest 没有 `dsh.capabilities: ["tools:register"]`**（对比 doublecheck 有）→ 我的判断：它**不注册模型工具**，`/pua` 是 command，风格/循环靠命令注入 + 客户端卡片 + 提示词实现。【源码发现 + 我的推断】

**③ DSH 0.2.2-rc.1 兼容性 —— ⚠️ 半确定，且可能是坑**
- `engines.dsh: ">=0.2.0-rc.1 <0.3.0-0"`，`engines.node: ">=22.19.0"`。【源码发现】
- **devDependencies 全部钉在 `0.2.2-rc.1`**（dsh-llm/agent/scope/tools/sandbox/session/commands/settings/subagent/terminal/agent-loop/attachment/http-proxy/subprocess/api-gateway/api-remotes/ptc-runtime/system-prompt/user-approval/client-ui-chat/sandbox-policy/user-questions/client-ui-slots/client-ui-theme/typert-protocol/typert-registry/output-retention/subprocess-local/client-connection/client-ui-commands/client-ui-renderer/client-ui-settings/session-projection/session-persistence/client-ui-primitives/tool-bash-persistent/tool-pwsh-persistent/api-session-controller/client-ui-conversation/client-ui-input-trigger/session-format-v2-to-v3/subagent-fork-in-process/subagent-spawn-in-process）。→ **作者明确是按 0.2.2-rc.1 构建和测试的。**【源码发现】
- peerDependencies 也都写成 `>=0.2.0-rc.1 <0.3.0-0` 这一档。【源码发现】
- 但按**严格 node-semver**，`>=0.2.0-rc.1 <0.3.0-0` 不含 `0.2.2-rc.1`（见 §0 发现 2）。如果 DSH 的 engines 校验是严格模式，**这个包会在加载时被自己的 engines 拦下**——尽管它明明是为 rc.1 构建的。**这是本候选最危险、也最需要先验证的一点。实测：未做。**【我的推断】
- 另注：它把 `@deepseek-ai/cordis: 4.1.0`、`schemastery: 3.19.0` 写在 `overrides` 里。**npm/pnpm 会忽略依赖包自带的 `overrides`**，所以这对消费方无效，只是作者本地构建的痕迹。【源码发现 + 我的推断】

**④ 人工确认 / 外部服务 / 凭据 / 额外运行环境**
- 无凭据、无网络服务、无额外运行时（deps 只有 `zod 4.4.3`）。✅
- 需要 Web 客户端插槽（6 个 client 注入）→ 与 UI 类插件存在插槽竞争可能。【源码发现】
- 不需要人工确认门（没有 approval 逻辑的证据）。【我的推断】

**⑤ 与已装插件 / 内置能力的重复与冲突**
- 与内置 `auto-review`：**语义重叠**——auto-review 在 Auto 权限档做"逐工具 LLM 授权复核"；pua 做"宣称完成前核验收据"。两者都属"别信模型说完成"，但层不同（授权 vs 验收）。同时开会让模型收到两套"要证明"的指令。【我的推断】
- 与内置 `goal`：pua 的可选验收循环会自己续跑，与 goal 的自动续跑轮次可能**叠加**，造成双重续跑风险。【我的推断，未验证】
- 与 `dsh-doublecheck`：验收证据重叠（doublecheck 的 gate 更硬、有可重放判决）；pua 的优点只是"话术风格"。
- 与已装 `dsh-pet` / `dsh-whale-widget`：都是装饰/陪伴类，无关。
- **命名冲突风险**：`/pua` 是自定义 command，短名容易和别的插件撞；未见作者声明避让。【我的推断】

**⑥ 停止条件 / 失败处理 / 中断恢复**
- 验收循环退出条件（目录描述）：**"直到验收命令通过、达到迭代上限或用户取消"**。【作者声明】
- **具体"迭代上限"是几、是否可配、超限后行为，我没有读到 README 正文 → 未验证。**
- 无宿主级熔断、无跨重启恢复的证据；`/pua` 是命令驱动，重启后需要重新开关。【我的推断】

**⑦ 测试与实机证据覆盖了什么、还缺什么**
- 作者侧：`npm test = build + node --test tests/*.test.mjs`；`test:compat = node scripts/check-compat.mjs`；`prepack = build + verify`。有 CI 可信发布（`trustedPublisher` + provenance）。【源码发现】
- 缺：README 未读 → 功能清单只有目录描述；缺 0.2.2-rc.1 真机加载证据；缺"验收循环上限"的具体证据。
- **实测：未做。**

**⑧ 维护情况 / 使用成本 / 配置复杂度**
- v1.0.8，npm 发布时间约 **2026-11-05**（由内部时间戳换算，【我的推断】）；1.0.x 语义化版本说明作者认为已稳定。
- **数据异常**：★65 但 30 天下载 26,965 —— 下载/星标比 ≈ 415:1，远高于 A 组其他候选（doublecheck 82:1、auto-continue 58:1、Aegis 无 npm）。可能是聚合/镜像/CI 安装造成，也可能是刷量。**选型时不要被下载量误导。**【我的推断，无法证实】
- 成本：低（装完即有 `/pua` 与客户端卡片）。
- 复杂度：**中**——15 种公司风格 + 角色模式 + 全局/会话双层设置，配置项多，且对"零编程基础"用户是干扰项。【我的推断】

---

### 2.6 dsh-auto-continue / HsiangNianian

**① 精确安装目标与市场数据**
市场页 <https://awesome-dsh-plugin.com/p/HsiangNianian/dsh-auto-continue/>（注意市场页 slug 是 `dsh-auto-continue`，**npm 包名是 `dsh-client-auto-continue`**，安装命令以包名为准）：★187、10,818 下载、加入目录 2026-08-14、分类 `ui`。
精确安装：`dsh plugin --profile desktop add dsh-client-auto-continue`。版本 **0.17.4**。仓库 <https://github.com/HsiangNianian/dsh-auto-continue>，MIT。【作者声明 + 源码发现】

**② 真执行 vs 提示型 —— 判定：执行型（宿主 hook + Web 客户端）**
- `dsh.bundle.patch: "./cordis.patch.yml"`；`dsh.client.inject` 5 个客户端模块（connection / locale / ui-settings / ui-settings-plugins），`platform: "web"`。【源码发现】
- 有 `./client` 子导出、locale 文件 → 有可见 UI（设置卡 + composer 开关 + 浏览器通知）。【源码发现】
- 行为（目录）：请求因网络、超时或宿主崩溃等**非人为失败**中断后，自动排队发一条本地化的"继续"；支持错误分类、自适应退避、模板化继续文本、浏览器通知。【作者声明】
- 不注册模型工具（manifest 无 `tools:register`）→ 它是**宿主侧自动续跑器 + UI**，不是给模型用的工具。【我的推断】

**③ DSH 0.2.2-rc.1 兼容性 —— ⚠️ 未验证，且 peer 范围尤其可疑**
- **无 `engines.dsh`**。【源码发现】
- `peerDependencies`：`@deepseek-ai/dsh-settings: "^0.1.0-rc.7 || ^0.1.7-0 || ^0.2.0-rc.1"`（optional）、`@deepseek-ai/cordis: "^4.0.1"`、`@deepseek-ai/schemastery: "^3.18.1"`、`react: "^18.2.0"`。【源码发现】
- 按严格 semver，`^0.2.0-rc.1` **不含 0.2.2-rc.1**（同样是元组问题）；但 peer 不满足通常只是警告，不会阻断安装。【我的推断】
- `test:runtime` 脚本明确列出的宿主版本：`0.1.7`、`0.2.0`、`0.2.1`、`0.2.0-rc.2`、`0.2.1-rc.2`、`0.2.1` —— **没有 0.2.2-rc.1**。【源码发现】
- 客户端注入的模块名（`dsh-client-ui-settings-plugins` 等）在 0.2.x 有改名史（本项目已知 0.1.7-alpha.1 期间 settings namespace registry 被删）→ 客户端 API 是易碎面。【我的推断】

**④ 人工确认 / 外部服务 / 凭据 / 额外运行环境**
- 无凭据、无外部服务、无额外运行时。✅
- 需要 Web 客户端插槽；需要通知权限（浏览器通知）。【作者声明】

**⑤ 与已装插件 / 内置能力的重复与冲突**
- **与内置 `goal` 重复**：goal 已有同会话目标状态 + 自动续跑轮次 + `max_goal_rounds` 上限 + blocked 判定；auto-continue 又加一层"失败后续跑"。【我的推断】
- **与内置 `agent-team` 部分重复**：Agent Teams 本身有等待/继续语义。
- 与内置 LLM 重试：作者定位是"在 dsh 内置重试之上"处理**非重试类失败**（宿主崩溃/网络断），理论上分层不冲突，但两层续跑叠加时谁先触发未验证。【我的推断】
- 与已装 `dsh-better-sidebar` / task-board / skill-explorer：**客户端插槽竞争**（它注入 ui-settings 与 composer 区域）。【我的推断】
- 与 A 组其他：与 loopx 的 Driver 续跑、dsh-pua 的验收循环**三重叠加**风险。

**⑥ 停止条件 / 失败处理 / 中断恢复**
- 测试文件清单里出现：`loop-guard-progress`、`autonomous-loop`、`manual-resume-pauses`、`failure-classification`、`silent-turn-boundaries`、`session-modes`、`boot-scan-isolation`、`stats-freshness`、`settings-host-compat`。【源码发现：仅文件名单，未读实现】
- 由此【我的推断】：存在**循环守卫（loop guard）**、**自主循环上限**、**手动恢复会暂停自动续跑**、**按错误类型分类决定是否续跑**。这三条正是"停止条件/失败处理/恢复"该有的东西。
- **但具体的"最多 N 次"、"退避曲线参数"、"崩溃后是否续跑上一轮"没有读到源码或文档 → 未验证。** 这是本候选最大的证据缺口。

**⑦ 测试与实机证据覆盖了什么、还缺什么**
- 作者侧测试面很宽：23 个 node 测试（含 `simulate-host`、`simulate-client-loader`、`boot-scan-stored-sweep`、`settings-migration`、`maintenance-turns`、`publish-prerelease`），以及 `test:runtime` 对多个真实宿主版本做 `settings-host-live` / `profile-compatibility` / `boot-scan-host-live` / `boot-scan-restart-live`。→ **测试覆盖明显强于它的星标水平**。【源码发现】
- 缺：0.2.2-rc.1 的 runtime 测试；Windows 桌面 profile 下的实机（它的 runtime 测试是 `0.2.1-rc.2` 等，未见 desktop profile 特化）。【源码发现】
- **实测：未做。**

**⑧ 维护情况 / 使用成本 / 配置复杂度**
- v0.17.4，npm 发布时间约 **2026-11-07**（内部时间戳换算，【我的推断】）→ 很活跃（0.17.x 说明迭代了很多轮）。
- 成本：低（装完有默认配置 + 设置卡）。
- 复杂度：**低-中**（模板化继续文本、错误分类、退避都可调，但对零编程基础用户默认值就够）。
- 唯一真价值场景：**长任务跑到一半宿主崩了**。但本项目已有 goal/agent-team 的续跑，且内置 LLM 重试覆盖 provider 层失败 → 增量边际。

---

### 2.7 dsh-task-ledger / cq-guojia

**① 精确安装目标与市场数据**
市场页 <https://awesome-dsh-plugin.com/p/cq-guojia/dsh-task-ledger--packages-plugin/>（注意 slug 带 `--packages-plugin`，因为包在 monorepo 子目录）：**无星标数据（目录未采集）**、**23,622 下载（30 天）**、加入目录 **2026-11-05**（A 组最新）、分类 Workflow & Automation。
精确安装：`dsh plugin --profile desktop add dsh-task-ledger`。npm 包名 `dsh-task-ledger`，目录写 0.1.7、**npm 实际 0.1.10**。仓库 <https://github.com/cq-guojia/dsh-task-ledger>（包在 `packages/plugin`），MIT。【作者声明 + 源码发现】

**② 真执行 vs 提示型 —— 判定：提示型 + 看板（不是工具型）**
- `dsh.bundle.patch: "./cordis.patch.yml"`；`dsh.client.inject` 6 个客户端模块（locale / ui-renderer / ui-layout / ui-settings / ui-plugin-manager / **ui-sidebar**），`platform: "web"`。【源码发现】
- **manifest 没有 `dsh.capabilities: ["tools:register"]`**。【源码发现】
- 构建脚本里有 `scripts/copy-skill.mjs`、`scripts/verify-skill.mjs`、`verify = build + typecheck + verify-skill` → **它打包的是一个 skill**。【源码发现】
- 目录描述："任务由代理创建、认领、推进与结案，**每一步直接写入工作区内的纯文本台账**……看板汇总进行中、逾期与停滞的任务与每周趋势"。【作者声明】
- → 我的判定：**代理通过 skill 指导 + 现有 shell/fs 工具去读写台账文本；插件本体提供客户端看板与设置**。目录把它归为"提示词/技能/看板型"是准确的。**是否存在宿主侧 CLI/工具把台账结构化，未读到 README → 未验证。**【我的推断】

**③ DSH 0.2.2-rc.1 兼容性 —— ⚠️ 完全无声明**
- `engines` 只有 `node: ">=22.5"`，**没有 `engines.dsh`**。【源码发现】
- 运行期依赖：**`dsh-plugin-core: "^0.35.7"`** + `@deepseek-ai/schemastery: "^3.18.5"`。【源码发现】
  - `dsh-plugin-core` **不在 `@deepseek-ai` 官方作用域下**，是一个第三方运行时依赖。它是什么、谁维护、是否随 DSH 0.2.x 变——**未验证**，但这是本候选最该先查的一条供应链风险。
  - `schemastery ^3.18.5` 与 0.2.2-rc.1 兼容（本项目已知 schemastery 3.19 在用）。【我的推断】
- 客户端注入含 `ui-sidebar` / `ui-plugin-manager` / `ui-layout` → 与已装 `dsh-better-sidebar` 的插槽目标高度重叠。【我的推断】

**④ 人工确认 / 外部服务 / 凭据 / 额外运行环境**
- 无需凭据、无云服务（作者明说"不涉及云服务，单人多人皆可用、以 Git 同步"）。✅【作者声明】
- 需要 Web 客户端插槽（含 sidebar）。【源码发现】
- 无额外运行时。【源码发现】

**⑤ 与已装插件 / 内置能力的重复与冲突 —— 重复最直接**
- **与内置 `task_board` 直接重复且内置更强**：内置看板卡片能**真正开会话执行**、有 acceptance gate、`update_goal complete` 需通过验收；task-ledger 的看板只是"读台账渲染 + 周趋势"。→ 内置胜出。【我的推断】
- 与已装 `@linxin666/dsh-client-ui-task-board`（也是看板）：**UI 层正面冲突**，两个都在侧边栏抢位置。【我的推断】
- 与 `dsh-better-sidebar`：它 inject `ui-sidebar`，可能替换/竞争侧边栏宿主。【我的推断】
- 与 loopx：Todo/证据账本重复。
- 唯一增量：**纯文本 + git 可 diff 的台账**（对多人协作、要进版本库的任务记录有价值）。本项目是**单人** + 已有 openspec + task_board → 增量接近 0。【我的推断】

**⑥ 停止条件 / 失败处理 / 中断恢复**
- **无执行循环 → 无停止条件、无重试、无熔断。** 台账是文本，恢复 = 重新读文本。【我的推断】
- 中断恢复的实际形态：靠 git 同步与文件本身（作者声明"以 Git 同步"）。没有进程级恢复语义。
- 逾期/停滞检测（看板汇总）是唯一接近"失败处理"的东西，但只是展示，不会自动动作。【作者声明】

**⑦ 测试与实机证据覆盖了什么、还缺什么**
- 作者侧：`verify = build + typecheck + verify-skill`，有 CI 可信发布（provenance 签名）。**未见测试套件**（没有 `test` 脚本）。【源码发现】
- 缺：README 未读；缺 `dsh-plugin-core` 的来源/维护者/行为证据；缺 0.2.2-rc.1 加载证据；缺看板在 desktop profile 的实机证据。
- **实测：未做。**

**⑧ 维护情况 / 使用成本 / 配置复杂度**
- 加入目录 **2026-11-05**，npm 最新 0.1.10 发布时间约 **2026-11-09**（内部时间戳换算，【我的推断】）→ **4 天内 0.1.7 → 0.1.10 三个 patch**，迭代极快、稳定性未知。
- **数据异常**：4 天 23,622 次下载，但星标数据缺失。要么是真被大量安装，要么是聚合/镜像噪声。**不要用它当质量证据。**【我的推断】
- 体积：解开 **20.9 MB / 69 文件**（A 组最大，可能含前端资源）。【源码发现】
- 成本：低（装完即用）；但依赖一个非官方核心包 + 抢 sidebar 插槽 → 风险不对称。【我的推断】
- 复杂度：**低**（概念简单：台账 + 看板）。【我的推断】

---

## 3. 横向对照：停止条件 / 失败处理 / 中断恢复

| 候选 | 有没有"最多 N 次/轮" | 熔断 | 中断恢复 | 证据强度 |
|---|---|---|---|---|
| dsh-doublecheck | 不是"次数"，而是**判定规则**：红灯→rework；adversary 超时 120s、findings 上限 20 | 无"熔断"概念，但**判决永不被 warning/skip 翻转**；seam 不可用写 unavailable | **最强**：replay=state，resume/fork/重启后 `/gate run` 重算同一结论；projection stateVersion=3 | 【作者声明】+ 部分【源码发现】 |
| Aegis | ❌ 无 | ❌ 无 | ❌ 无（不执行） | 【源码发现】 |
| superpowers-dsh | ❌ 无 | ❌ 无 | ❌ 无（不执行） | 【源码发现】 |
| loopx | ✅ 精确：**3 次**（1+2 额外），同 `--turn-instance-id`；续跑上限由 quota + scheduler 未变化轮询上限约束 | 明确的**不重试清单**；并明说"无累计 8 次失败熔断" | ✅ 绑定+配额前后各校验；不伪造 writeback/spend | 【作者声明】（写得最细，但版本不兼容） |
| dsh-pua | ⚠️ "达到迭代上限"存在，**数值未查到** | 未查到 | 未查到 | 【作者声明】弱 |
| dsh-auto-continue | ⚠️ 有 `loop-guard-progress` / `autonomous-loop` 测试，说明有上限，**数值未验证** | 未验证 | ✅ `manual-resume-pauses`：手动恢复即暂停自动续跑；`boot-scan-restart` | 【源码发现】仅测试名，实现未读 |
| dsh-task-ledger | ❌ 无（不执行） | ❌ 无 | ⚠️ 仅"文本 + git" | 【我的推断】 |

**结论**：真正把"停止/失败/恢复"做成产品级能力的是 **dsh-doublecheck**（判定可重放）和 **loopx**（重试边界精确）；但 loopx 在 0.2.2-rc.1 上装不上。其余四个在这个维度上是空白或只有提示词级承诺。

---

## 4. 重复矩阵：A 组 × 内置/已装能力

| 能力 | 内置/已装已有 | A 组重复者 | 判断 |
|---|---|---|---|
| 目标状态 + 自动续跑轮次 | **goal**（max_goal_rounds、blocked 连续 3 轮） | **loopx**（Goal/continuation/quota）、**dsh-auto-continue**（失败后续跑）、**dsh-pua**（验收循环） | 三重重复，loopx 最重 |
| 任务看板 / 任务台账 | **task_board**（能真开会话 + acceptance gate）、**@linxin666/dsh-client-ui-task-board** | **dsh-task-ledger** | 重复且内置更强 |
| 定期唤醒 / 心跳 | **schedule** | **loopx**（heartbeat/scheduler） | 重复 |
| 授权/质量复核 | **auto-review**（逐工具 LLM 授权复核） | **dsh-pua**（完成前核验收据，弱重叠）、**dsh-doublecheck**（gate.review.engine=auto **复用** auto-review 判决） | doublecheck 是**协同**，pua 是重叠 |
| 工程方法论/TDD/调试 | **无内置**（openspec 提供 spec 流程） | **Aegis**、**superpowers-dsh**，以及 dsh-doublecheck 的 4 个技能 | Aegis 与 superpowers 100% 互相重复 |
| 回滚/恢复 | **dsh-rewind-plugin**、**worktree** | loopx（另一套恢复语义） | 语义冲突需注意 |
| 侧边栏 / UI 插槽 | **dsh-better-sidebar**、task-board、skill-explorer、git-graph | **dsh-task-ledger**（inject ui-sidebar）、**dsh-pua** / **dsh-auto-continue**（composer/settings 插槽） | UI 插槽竞争是本组第二大风险 |
| 交付证据 / 验收闸门 | **task_board acceptance gate**（仅对卡片执行） | **dsh-doublecheck**（对**任意会话**的交付） | doublecheck 覆盖 task_board 覆盖不到的场景，**不是重复** |

---

## 5. A 组内部排序与结论

### 5.1 排序（从"最该进组合"到"最该淘汰"）

1. **dsh-doublecheck** —— 唯一 ✅ 兼容 0.2.2-rc.1、唯一执行型且无外部依赖、唯一"证据从会话日志折叠"因而天然可恢复、与内置 auto-review 是**协同**关系。它正好补上你流水线里 **澄清 → 验收标准 → 测试 → 交付** 这四段的可验证性。
2. **Aegis** —— 质量高、维护活跃、1411 星，但**是提示型**，且与 superpowers 重复。作为"方法论读本"可以，作为"流水线组件"不行。
3. **dsh-auto-continue** —— 测试工程做得意外扎实（23 个 host/client 模拟测试），但功能与内置 goal/agent-team 重复，且 runtime 只验证到 0.2.1-rc.2。
4. **superpowers-dsh** —— 干净、零依赖、无风险，但被 Aegis 完全覆盖；选它只是"想要轻一点的文本"。
5. **dsh-pua** —— 有执行面（命令 + 客户端卡片 + 验收循环），但① engines 疑点可能直接挡加载，② 语气风格化对单人开发者是噪声，③ 与 auto-review/goal 语义重叠。
6. **dsh-task-ledger** —— 重复内置 task_board、抢 sidebar 插槽、引入非官方 `dsh-plugin-core`、4 天 3 个 patch、20 MB 体积。增量≈0。
7. **loopx** —— 设计最强、星标最高，但**在 0.2.2-rc.1 上确定装不上**（作者明文排除），且需要 Python+pip+pnpm+联网+CLI bootstrap。**降级为"看设计思路"的参考实现，不是候选。**

### 5.2 只选 1 个 → **dsh-doublecheck**

理由（按你的实际约束排）：
1. **它是唯一"能在 0.2.2-rc.1 上被证明兼容"的**（`engines.dsh` 显式含 `>=0.2.2-0 <0.3.0`，README 声明 2026-11-05 适配 rc.1、gate/projection 路径有 rc.1 测试）。
2. **它是唯一"真执行"且不需要外部运行时的**——Aegis/superpowers 是文本，loopx 要 Python/pip，pua/auto-continue/task-ledger 是 web 客户端 UI。
3. **它直接覆盖你流水线的骨架**：grill（澄清）→ 六维 spec（验收标准）→ red/green（测试）→ gate（交付）。196 个 pytest 文件的命令形态已被默认 `testCommandPatterns` 里的 `pytest` 覆盖；`[exit code: N]` 正是 DSH bash 工具的输出格式。
4. **它不会和内置重复**：goal 管"继续跑"，task_board 管"卡片执行"，auto-review 管"授权"，doublecheck 管"交付有没有证据"——四者分层，且 doublecheck **主动消费** auto-review 的判决。
5. **失败模式温和**：默认 `intensity: remind` 只提醒；reviewer 跑不起来写 `unavailable` 而不是伪造；最坏情况是"开关不跨重启"，不会卡住你的编辑。
6. **对零编程基础友好**：装完零配置，日常只用 `/gate run` 与 `/doublecheck status` 两个入口；报告是可以直接贴进交付说明的 markdown。

**入选后必须先做的 3 件事（未做）**：
- 用 `remind` 档跑一个真实小改动（不是 9968 行的 label_widget.py），确认 `[exit code: N]` 与 pytest 输出能被折叠；
- 与 `cc-safety-net` 同会话共存跑一次，确认两者都监听 pre/post-execute 时不互相吞事件；
- 决定 spec 权威：`doublecheck-spec.md` 与 openspec 谁说了算（建议 openspec 出正文，doublecheck 只登记验收维度）。

### 5.3 为了"覆盖流程"而重复堆叠、应该淘汰的

| 淘汰对象 | 被谁覆盖 | 一句话理由 |
|---|---|---|
| **loopx** | 内置 goal + schedule + task_board | 版本不兼容是硬伤；就算兼容也是"在 Goal 之上再套一个 Goal 权威源" |
| **dsh-task-ledger** | 内置 task_board（更强）+ 已装 task-board UI | 看板重复、sidebar 插槽冲突、引入非官方核心依赖 |
| **dsh-auto-continue** | 内置 goal 续跑 + agent-team + LLM 重试 | 只在"宿主崩溃"这一窄场景有增量，而那恰好也是 goal 能接住的 |
| **dsh-pua** | 内置 auto-review + dsh-doublecheck | "换方法 + 核验"这两件事，review 与 gate 做得更硬；15 种公司风格是噪声 |
| **superpowers-dsh** | Aegis（同一上游、更厚） | 二者同装 = 同一套方法论两份文本 |
| **Aegis**（若选 doublecheck） | dsh-doublecheck 的 4 个技能 | Aegis 的优势在"提示层纪律"，而 doublecheck 在"闸门层"；同时装会得到两套"完成前验证"话术 |

**一句话给 Lead**：**A 组只保留 dsh-doublecheck 一个**；Aegis 可作为"方法论阅读材料"另外评估（不进流水线）；loopx 因 0.2.2-rc.1 不兼容直接出局，其"3 次重试 + 不重试清单"的设计值得作为我们自己写流程规则时的参考。

---

## 6. 未验证清单（下一轮要补的）

| # | 未验证项 | 影响 | 建议怎么补 |
|---|---|---|---|
| 1 | **DSH engines 校验是否 strict semver**（决定 dsh-pua 能否加载） | 高 | 读 DSH 源码的 package-manifest/engines 校验处；注意 asar 需先解包（我这边 `ops_grep` 对 asar 路径 `PATH_RESTRICTED`） |
| 2 | dsh-doublecheck 与 cc-safety-net 的 pre/post-execute 共存实现 | 中高 | 读 `lib/guard/*.js` 的 `ctx.on` 实现，确认 `next()` 透传 |
| 3 | dsh-auto-continue 的"最多 N 次"与退避曲线 | 中 | 读 `tests/autonomous-loop.mjs` / `tests/loop-guard-progress.mjs` |
| 4 | dsh-pua 的验收循环迭代上限数值与是否可配 | 中 | 读 README 正文 + 源码 |
| 5 | dsh-task-ledger 是否真不注册任何宿主工具 | 中 | 读 README + `dist/index.js` 的 `ctx.tools` 出现情况 |
| 6 | `dsh-plugin-core@^0.35.7` 是什么、谁维护、是否适配 0.2.2-rc.1 | 中 | `https://registry.npmjs.org/dsh-plugin-core/latest` |
| 7 | 7 个候选的最近提交 / issue 数 / 是否 archived | 低 | GitHub API `repos/<owner>/<repo>` |
| 8 | loopx 的 beta.6 发布时间（判断"是否可能已出 0.2.2 兼容版"） | 低（已被作者明文排除） | GitHub releases API |
| 9 | 全部候选的**安装 + 加载 + 真实 pytest 折叠** | 最高 | 下一轮实机（本轮明确禁止） |

**实测声明：以上 7 个候选，本轮全部未安装、未运行、未做任何端到端验证。**

---

## 7. 来源链接（均于 2026-11-09 抓取）

**市场页**
- dsh-doublecheck：<https://awesome-dsh-plugin.com/p/PerryLink/dsh-doublecheck/>
- Aegis：<https://awesome-dsh-plugin.com/p/GanyuanRan/Aegis/>
- superpowers-dsh：<https://awesome-dsh-plugin.com/p/LayneChai/superpowers-dsh/>
- loopx：<https://awesome-dsh-plugin.com/p/loopx-project/loopx--packages-dsh-loopx-plugin/>
- dsh-pua：<https://awesome-dsh-plugin.com/p/MichengAI/dsh-pua/>
- dsh-auto-continue：<https://awesome-dsh-plugin.com/p/HsiangNianian/dsh-auto-continue/>
- dsh-task-ledger：<https://awesome-dsh-plugin.com/p/cq-guojia/dsh-task-ledger--packages-plugin/>

**npm manifest（真实 package.json）**
- <https://registry.npmjs.org/dsh-doublecheck/latest>（0.9.30）
- <https://registry.npmjs.org/superpowers-dsh/latest>（0.5.0）
- <https://registry.npmjs.org/@michengai/dsh-pua/latest>（1.0.8）
- <https://registry.npmjs.org/dsh-client-auto-continue/latest>（0.17.4）
- <https://registry.npmjs.org/dsh-task-ledger/latest>（0.1.10）

**GitHub 源码**
- <https://github.com/PerryLink/dsh-doublecheck>（README 中英西葡印五语）
- <https://github.com/GanyuanRan/Aegis>；DSH 接入层：
  - <https://raw.githubusercontent.com/GanyuanRan/Aegis/HEAD/package.json>
  - <https://raw.githubusercontent.com/GanyuanRan/Aegis/HEAD/extensions/dsh/cordis.patch.yml>
  - <https://raw.githubusercontent.com/GanyuanRan/Aegis/HEAD/extensions/dsh/index.js>
- <https://github.com/LayneChai/superpowers-dsh>
- <https://github.com/loopx-project/loopx/tree/main/packages/dsh-loopx-plugin>
- <https://github.com/MichengAI/dsh-pua>
- <https://github.com/HsiangNianian/dsh-auto-continue>
- <https://github.com/cq-guojia/dsh-task-ledger/tree/main/packages/plugin>

**本地快照**
- `.tmp/dsh-sel-20261109/plugins_raw.json`（9,687 条，updated=2026-11-08）
- `.tmp/dsh-sel-20261109/candidates.csv`（7,138 行，A–G 词表初筛）
- `dsh_selection_20261109/catalog_scan.md`（task-1 全量目录扫描，用于确认目录数据源与 capabilities 口径）
