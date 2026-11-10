# DSH 环境现状审计（本机真实运行态）

- 审计对象：本机桌面端 DeepSeek Harness（Electron）＋ profile `desktop`
- 审计时间：2026-11-09 08:58–09:55（Asia/Shanghai）；期间 09:48 本机 DSH 重启过一次，GUI 端口 7862 → **1709**
- 审计性质：**只读**。未安装/卸载/升级任何插件，未修改 profile 配置，未改项目文件
- 审计结论一句话：**当前 profile 是「12 个第三方插件装了但 2 个没启用、6 个内置 experimental bundle 全启用、真正提供模型可调用工具的只有 4 个来源（dsh-ops / task-board / agent-team / 内核 bundle），而唯一被寄予厚望的视觉能力 modlens 已加载但实测调用失败」**。

---

## 0. 四层判定口径（本报告全程遵守）

| 层级 | 判据 | 本报告用词 |
|---|---|---|
| L1 已安装 | 包实体存在于 `profiles/desktop/node_modules/<pkg>`（或随 Electron 打进 app.asar） | 已安装 |
| L2 已启用 | 包名出现在 `profiles/desktop/package.json → dsh.profile.bundles` 列表（否则不会进配置树） | 已启用 |
| L3 工具已加载 | 该插件声明的工具/命令真正出现在**本会话工具表**里（运行时事实，不看配置文件） | 工具已加载 |
| L4 实测可用 | 本次审计中**真的调用过并有成功输出** | 实测可用 |

> 本报告最重要的一条方法论：**配置文件说什么不算数，运行时工具表才算数**。后文有 3 处「声明与实际不一致」的实例佐证。

---

## 1. 运行时、profile、模型与权限

### 1.1 版本与运行方式

| 项 | 事实 | 证据 |
|---|---|---|
| DSH 版本 | **0.2.2-rc.1** | `"D:\DeepSeek Harness\resources\runtime\cli\bin\dsh.cmd" --version` → `0.2.2-rc.1` |
| 运行方式 | **桌面端 Electron**（不是 CLI 常驻、也不是独立 web server）。Web GUI 由 Electron 内建 host-webserver 提供 | GUI `http://127.0.0.1:1709`（重启前 7862）；`resources/app.asar` 213 MB；`app.asar.unpacked/dsh/node_modules` 仅放原生模块 |
| 实现 checkout | 打包在 asar 归档内：`D:\DeepSeek Harness\resources\app.asar\dsh\`（bash 视角是**文件**，不是目录）。审计用自写 asar 解析器读出 22,102 个条目、331 个 `@deepseek-ai/*` 包 | `.tmp/dsh-sel-20261109/env/asar_scan.py`、`asar_extract2.py`；结果 `.tmp/.../asar_out/shipped_pkg_names.txt` |
| 自带运行时 | node **24.21.0** + pnpm **11.28.5**（DSH 自带）；宿主另有 node **v22.20.0**（`/c/nvm4w/nodejs`）、python **3.13.13** | `resources/runtime/versions.json`；`command -v node/python` |
| CLI 能力边界 | CLI **不能**管理 desktop profile：`--dump-config` 被拒；`plugin list` 报 `EPERM ... package.json.lock`。desktop profile 由 Electron 独占管理 | `dsh --profile desktop --dump-config` → `error: profile "desktop" is managed exclusively by the Electron application`；Lead 实测 `dsh plugin --profile desktop list` → `EPERM package.json.lock` |

**对选型/自动化的影响（重要）**：
- 想批量装/停插件，**CLI 路线不可用**；只能走 GUI（插件页 / dshmarket / Discover）或 `plugin_manager` 工具。
- 任何「脚本化改 profile」的方案在 desktop profile 上都会撞 Electron 独占/锁文件。
- 版本 0.2.2-rc.1 是 **rc 预发布**，插件的 `engines.dsh` 兼容区间必须逐个核（见主表）。

### 1.2 profile

| 项 | 事实 |
|---|---|
| profile 名 | `desktop` |
| 目录 | `C:\Users\20441\.dsh\profiles\desktop` |
| 组成 | `package.json`（12 个第三方依赖 + 16 项 `dsh.profile.bundles`）、`cordis.yml`（空根 `[]`）、`cordis.patch.yml`（用户层 131 行）、`pnpm-lock.yaml`、`pnpm-workspace.yaml`（`nodeLinker: hoisted`，`autoInstallPeers: false`） |
| 组成顺序 | `dsh-base` → `dsh-web-app` → `plugin-market-bundle` → `dshmarket` → `dsh-context` → `dsh-better-sidebar` → `@liustack/modlens` → `cc-safety-net` → `dsh-rewind-plugin` → `@linxin666/task-board` → `@linxin666/skill-explorer` → `@linxin666/git-graph` → `agent-team-profile` → `forge-bundle` → `auto-review` → `dsh-ops` |
| 注意 | profile 的 `node_modules` 里**没有任何 `@deepseek-ai/*` 包**；6 个内置 bundle 全部从 app.asar 解析。第三方只有 12 个（`@dsh-ops`、`@linxin666`、`@liustack` 等作用域目录是它们的依赖/自身） |

### 1.3 模型路由

- `cordis.patch.yml` 覆盖了 `agent-default-model`：
  - `provider: commandcode`，`model: deepseek/deepseek-v4.1-flash-fast`，**`reasoningEffort: max`**
  - 内置默认（`dsh-base` 层）是 `deepseek-official / deepseek-flash`，被用户层覆盖
- `llm-pi-ai` 里 `commandcode` provider 配置：`api: openai-completions`，`baseURL: https://api.commandcode.ai/provider/v1`，`apiKeyEnv: COMMANDCODE_API_KEY`，`retryPolicy.maxRetries: 8`（针对大上下文 TRANSPORT 断连放宽），`compat.supportsReasoningEffort: true`
- 该 provider 声明 7 个模型（deepseek-v4.1-flash / -fast、Kimi-K3.1-Pro、Kimi-K3、Kimi-K2.7-Code、GLM-5.3-flash、GLM-5.3-flashx），上下文窗口 256K–1M
- **关键限制**：该路由**不声明图片输入**。本会话 `read_image` 直接报：`model "deepseek/deepseek-v4.1-flash-fast" does not declare image input`。这决定了「截图理解/视觉验收」必须靠外部视觉桥（本机装了 modlens），而 modlens 当前不可用（见 §4.4）

### 1.4 权限与审批

| 项 | 事实 | 证据 |
|---|---|---|
| 沙箱 | `sandbox-policy.mode = process.env.DSH_PERMISSION_MODE ?? 'workspace-write'`，`workspaceRoot = process.cwd()` | `dsh-base/cordis.patch.yml` L240-247 |
| 审批 | `approval.policy = (DSH_PERMISSION_MODE ?? 'workspace-write') === 'danger-full-access' ? 'never' : 'ask'` | 同上 L259-262 |
| 预设 | `read-only / workspace-write / danger-full-access` 三档 | 同上 L264-276 |
| 本会话 | 审批被禁用：需审批的动作直接拒绝（子 agent 权限固定，不可提升） | 运行时上下文 |
| 「答题器」 | `ask_user_question` 工具已加载（来自 web-app bundle 的 `dsh-tool-ask-user`），但本会话角色是子 agent，实际提问会打扰 Lead，未使用 | 工具表 |

**对选型的影响**：workspace-write + ask 是「人工在环」默认档；`auto-review` bundle 只在 **Auto 权限档**工作（逐工具 LLM 授权复核），**对 workspace-write 无作用**——所以它现在等于空转（见 §6）。

---

## 2. 主表：插件逐个核实

> 版本来源：`node_modules/<pkg>/package.json`（第三方）／app.asar 内包（内置 bundle）。
> 兼容性判据：`engines.dsh` / `dsh.engines.dsh` / `dsh.compatibility.dshReleases` 与 **0.2.2-rc.1** 比对。
> 「工具已加载」= 本会话工具表可见；「实测可用」= 本次审计真调用过。

### 2.1 第三方插件（12 个）

| 插件（用途） | 包名 | 实装版本 | 已安装 | 已启用(bundles) | 工具已加载 | 实测可用 | 兼容性 vs 0.2.2-rc.1 | 证据 | 备注 |
|---|---|---|---|---|---|---|---|---|---|
| 任务看板（宿主持久化 + 会话执行 + cron） | `@linxin666/dsh-client-ui-task-board` | 0.4.14 | ✔ | ✔ | **✔ 8 个 `task_board_*`** | **✔**（`task_board_list` 返回 `ok:true`，board revision 0、0 任务、时区 Asia/Shanghai、maxSubtaskDepth 1） | `dsh.engines.dsh >= 0.2.1-rc.3` ✔（无上界） | `node_modules/@linxin666/dsh-client-ui-task-board/package.json` + `cordis.patch.yml`（插入 `ui-task-board` 行，node 半侧 + browser 半侧） | 双重身份插件；与 Team 的 `team_task_*` 是**两套不同任务系统**，勿混 |
| 技能浏览器（按来源浏览/启停/增删技能） | `@linxin666/dsh-client-ui-skill-explorer` | 0.4.14 | ✔ | ✔ | ✘（纯 UI，无模型工具） | 未验证（需 GUI 点击） | `>= 0.2.1-rc.3` ✔ | 同上结构，插入 `ui-skill-explorer` | 想查「技能从哪来」在这个面板里能看 source 标记（本报告的技能来源疑点可由此确认） |
| Git 图/分支选择（宿主真 git 操作 + /git/* 路由） | `@linxin666/dsh-client-ui-git-graph` | 0.4.14 | ✔ | ✔ | ✘（纯 UI/HTTP，无模型工具） | 未验证 | `>= 0.2.1-rc.3` ✔ | 同上，插入 `ui-git-graph` | 适合「变更审查/回滚前看一眼」，但模型不能直接调用 |
| 视觉桥（给纯文本模型加眼睛） | `@liustack/modlens` | 3.27.2 | ✔ | ✔ | **✔ `modlens_read_image`** | **✘ 失败**：`modlens failed (exit 1): claude-cli provider failed with code 1` | 无 `dsh.engines` 声明；`engines.node >=22.19` ✔ | `node_modules/@liustack/modlens/package.json`（desc: *powered by the free Antigravity CLI*）、`cordis.patch.yml`（插入 `modlens`） | **外部依赖未就绪**（provider 走 `claude-cli`，二进制/登录态缺失）。这是「已加载 ≠ 可用」的头号样本 |
| 危险命令/密钥文件拦截 | `cc-safety-net` | 2.7.2 | ✔ | ✔ | ✘（无模型工具，注入 `tools` 服务做拦截） | 未能证明拦截生效（本次未做危险命令测试） | 仅 `engines.node >=22`；peerDeps 是 `@opencode-ai/plugin`（非 DSH），DSH 支持靠自带 `dist/deepseek-harness/cordis.patch.yml` | `node_modules/cc-safety-net/dist/deepseek-harness/index.js`：`{name:"cc-safety-net", inject:["tools"], apply:Tt}`；`cordis.patch.yml` 插 `cc-safety-net` 行 | 面向 Claude-Code 风格 shell 钩子；本机 shell 实际是 `ops_bash`（dsh-ops），**覆盖面必须实测**，不能假定 |
| 增强侧栏（文件树/编辑器/变更/任务/侧聊） | `dsh-better-sidebar` | 0.28.2 | ✔ | ✔ | ✘（纯 UI，另对外提供 sidebar 扩展服务） | 未验证 | 无 `dsh.engines`；peer 一堆 `^0.2.1-rc.1` ✔ | `node_modules/dsh-better-sidebar/cordis.patch.yml`（`better-sidebar` 行，带双挂载守卫 `!!js` 表达式） | 与「forge 变更面板」「git-graph」功能面有交叠；其 patch 自己写明：<br>同包二次挂载会 `duplicate prefix route` 启动失败 |
| 上下文透视/管理（context dashboard + `/context`） | `dsh-context` | 0.80.2 | ✔ | ✔ | ✘（UI + 命令，无模型工具） | 未验证 | ⚠ **`dsh.engines.dsh: ">=0.2.0-rc.2 \|\| >=0.2.1-rc.2"`**（写法可疑）；`dsh.compatibility.dshReleases` 只列 `0.2.0-rc.2` / `0.2.1-rc.2`，**未声明 0.2.2-rc.1** | `node_modules/dsh-context/package.json`、`cordis.patch.yml` | 兼容性「未声明」≠ 不能用，但升级/排障时是第一嫌疑 |
| 原生文件/Bash/PTC 工具层（Windows 强相关） | `dsh-ops` | 0.5.1 | ✔ | ✔ | **✔ 18 个 `ops_*`**（bash、read_files、grep、glob、stat、write_file、edit_file、diff、copy、move、remove、read_table/read_docx/read_pdf、inspect_local_file、replace、result、discover_tools） | **部分 ✔**：`ops_read_files`/`ops_glob`/`ops_grep`/`ops_bash` 成功；`ops_write_file` 被 `PUBLICATION_DENIED`；`ops_bash` 间歇 `EXECUTOR_UNAVAILABLE` | ⚠ **`dsh.engines.dsh: ">=0.2.2-rc.1 <0.2.3-0"`**——只兼容 0.2.2.x | `node_modules/dsh-ops/package.json`、`dsh-plugin.json`（manifestVersion 0.15，`x-tool-namespaces` 明列 16+1 个 `ops_` 工具）、`cordis.patch.yml`（global.bash=true / hidePwsh=true / hideOfficialTools=true） | **本机 shell 的唯一来源**：内核 `tool-bash` 在 Windows 被禁用（base patch），真正跑命令的是 dsh-ops 自带 bash payload（执行器报错里叫 `Niubash`）。**它把 DSH 版本钉死在 0.2.2.x** |
| 桌宠（娱乐） | `dsh-pet` | 0.4.1 | **✔** | **✘ 不在 bundles** | ✘ | 未验证（未加载） | `dsh.compatibility.dshReleases` 到 `0.2.2-alpha.2`，未列 0.2.2-rc.1 | `profiles/desktop/package.json` L13 有依赖、L20-37 bundles **无**；`node_modules/dsh-pet/cordis.patch.yml` 存在 | **「装了没启用」样本 #1**。Lead 的 `plugin_manager list_plugins` 结果里也没有它 |
| 会话回退 + 工作区文件还原 | `dsh-rewind-plugin` | 0.19.1 | ✔ | ✔ | ✘（UI + 命令） | 未验证 | `>=0.2.1-rc.1 <0.3.0-0` ✔ | `node_modules/dsh-rewind-plugin/package.json`、`cordis.patch.yml` | 与 better-sidebar 的编辑器撤销、git-graph 的回滚**语义重叠**（见 §6） |
| 余额鲸鱼挂件（娱乐） | `dsh-whale-widget` | 0.4.2 | **✔** | **✘ 不在 bundles** | ✘ | 未验证（未加载） | 无 `engines` 声明 | 同 dsh-pet：`package.json` 有依赖、bundles 无 | **「装了没启用」样本 #2** |
| 可视化插件市场 | `dshmarket` | 1.73.8（`^1.73.8`） | ✔ | ✔ | ✘（纯 UI） | 未验证（GUI） | peer `@deepseek-ai/dsh-settings` 覆盖到 `^0.2.1-rc.1` ✔ | `node_modules/dshmarket/package.json`、`cordis.patch.yml`（插 `dsh-market`） | 与内置 `plugin-market-bundle` **功能重叠**（见 §6） |

### 2.2 内置 bundle（6 个，全部来自 app.asar，非 npm 装到 profile）

| 插件（用途） | 包名 | 实装版本 | 已安装 | 已启用(bundles) | 工具已加载 | 实测可用 | 兼容性 vs 0.2.2-rc.1 | 证据 | 备注 |
|---|---|---|---|---|---|---|---|---|---|
| 内核基座 | `@deepseek-ai/dsh-base` | 0.2.2-rc.1 | ✔（asar 内） | ✔ | 间接：`todo_write`、`skill`、`web_search/web_fetch`、`job_*`、`present`、`subagent`/`subagent_fork`、`workflow`、`get_goal/update_goal/create_goal`、`exit_plan_mode`、`plugin_manager` | 部分 ✔（`todo_write`/`plan`/`workflow` 未逐一实调；`present` 未调） | 同版本 ✔ | `asar_out/extracted/.../dsh-base/{package.json,cordis.patch.yml}`（535 行 patch，89 个依赖） | 定义沙箱/权限/审批/skill/goal/plan/subagent/workflow/mcp-resources 等 |
| 浏览器面（Web GUI） | `@deepseek-ai/dsh-web-app` | 0.2.2-rc.1 | ✔ | ✔ | 间接：`ask_user_question`、`schedule_*`、`sidebar_open`、`working_directory`、`subagent`(持久化变体) 等 | `sidebar_open`/`schedule_*` 未调 | 同版本 ✔ | `asar_out/extracted/.../dsh-web-app/{package.json,cordis.patch.yml}` + `presets/{standard,ptc,minimal,cordis}.patch.yml` | 带 5 个 agent preset patch 层 |
| 自定义插件索引（Discover 页） | `@deepseek-ai/dsh-experimental-plugin-market-bundle` | 0.2.2-rc.1 | ✔ | ✔ | 间接：`plugin_market` 工具（仅在 Creator preset 且服务挂载时注册） | ✘ **索引为空**：`cordis.patch.yml` 中 `plugin-market.indexes: []` | 同版本 ✔ | `.../dsh-experimental-plugin-market-bundle/cordis.patch.yml`（插 `plugin-market`、`ui-plugin-market`） | **与 dshmarket 重叠**；且当前无索引源 → Discover 页实际没东西可逛 |
| Agent 团队（协作/任务板/UI 一体） | `@deepseek-ai/dsh-experimental-agent-team-profile` | 0.2.2-rc.1 | ✔ | ✔ | **✔**：`spawn_teammate`、`list_agents`、`send_message`、`wait_agent`、`interrupt_agent`、`team_task_*`(8 个) | **✔**（本审计本身就是 team：`team_task_get/update` 全部成功） | 同版本 ✔ | `.../dsh-experimental-agent-team-profile/cordis.patch.yml`：`maxMembers: 8`、`maxTasks: 256`、`maxMessageBytes: 65536`；同时 `disabled: true` 关掉 `tool-subagent-control`/`tool-subagent`/`tool-subagent-fork` | **声明与实际不一致样本**：patch 说禁用旧 subagent，但本会话 `subagent`/`subagent_fork` 仍在工具表（见 §3.3） |
| 变更请求/worktree 面板 | `@deepseek-ai/dsh-experimental-forge-bundle` | 0.2.2-rc.1 | ✔ | ✔ | 间接：`tool-worktree`（worktree 工具）、forge 面板；`create_worktree` 工具已加载 | 未调用（`create_worktree` 未实调） | 同版本 ✔ | `.../dsh-experimental-forge-bundle/{package.json,cordis.patch.yml}`：worktree、tool-worktree、forge、**forge-github**、forge-session、可选 forge 面板 | GitHub provider 需外部 `gh` CLI/令牌（未验证就绪状态） |
| 逐工具 LLM 授权复核 | `@deepseek-ai/dsh-experimental-auto-review` | 0.2.2-rc.1 | ✔ | ✔ | ✘（无模型工具，是权限评审器） | 不适用 | 同版本 ✔ | `.../dsh-experimental-auto-review/{package.json,cordis.patch.yml}`：desc = *Per-tool LLM authorization review for the DeepSeek Harness **Auto** permission preset* | **它不是代码审查器**。只在 Auto 权限档拦截工具调用做授权评审；当前 workspace-write 档 → 空转。**与后续 code-review 插件无功能重叠**（纠正原假设） |

---

## 3. 分层结论（已安装 ≠ 已启用 ≠ 工具已加载 ≠ 已验证）

### 3.1 已安装但**未启用**（装了也白装）
- `dsh-pet` 0.4.1 —— 在 `dependencies`，**不在 `dsh.profile.bundles`**
- `dsh-whale-widget` 0.4.2 —— 同上
- 判定证据：`profiles/desktop/package.json` L4-17（依赖）对照 L18-39（bundles）；且 Lead 用 `plugin_manager list_plugins`（222 条 loader 条目）确认 active 列表里**没有**这两个包。

### 3.2 已启用但**不提供模型工具**（能力体现在 GUI/命令/钩子层，Agent 调不到）
- `@linxin666/dsh-client-ui-git-graph`（UI + `/git/*` HTTP）
- `@linxin666/dsh-client-ui-skill-explorer`（UI）
- `dsh-better-sidebar`（UI，对外暴露 sidebar 扩展服务）
- `dsh-context`（UI + `/context` 命令）
- `dshmarket`（UI）
- `dsh-rewind-plugin`（UI + 命令）
- `cc-safety-net`（注入 `tools` 服务做拦截，不新增工具）
- `@deepseek-ai/dsh-experimental-auto-review`（权限评审器）

> 含义：这类插件**不会出现在工具表里**，不能因为「工具表没看到」就判定没启用。

### 3.3 工具已加载但**实测失败/受阻**
| 工具 | 状态 | 原始错误 |
|---|---|---|
| `modlens_read_image` | 加载 ✔ / 调用 ✘ | `modlens failed (exit 1): Error: claude-cli provider failed with code 1` |
| `read_image`（原生） | 加载 ✔ / 调用 ✘ | `model "deepseek/deepseek-v4.1-flash-fast" does not declare image input` |
| `ops_write_file` | 加载 ✔ / 调用 ✘ | `rejected: PUBLICATION_DENIED / Publication authorization is unavailable.`（同一工作区里 `write` 原生工具可写成功，说明是 ops 工具链的发布授权问题，不是文件权限） |
| `ops_bash` | 加载 ✔ / **间歇** ✘ | `EXECUTOR_UNAVAILABLE: ... Niubash execution tree link count mismatch: assets/niubash-icon-256.png`（并发调用时互相踩踏；重试常成功） |

### 3.4 **声明与实际不一致**（本审计最有价值的发现）
1. `agent-team-profile` 的 patch 明确 `disabled: true` 关掉 `tool-subagent` / `tool-subagent-control` / `tool-subagent-fork`，**但本会话工具表里 `subagent`、`subagent_fork` 都在**。→ 桌面端（Electron）的实际组合顺序/附加层与我静态读到的 bundle 层不完全一致。
2. `dsh-base` 里 `tool-plugin-manager` 是 `disabled: true`，**但 `plugin_manager` 工具可用**（Lead 实测返回 222 条）。
3. `dsh-ops` 配置 `hideOfficialTools: true` / `hidePwsh: true`，但本会话仍同时能看到原生 `write`/`edit` 与 `ops_*` 两套文件工具。→ 该 profile 的 session preset 很可能不是 Standard（更像 cordis/ptc 混合），或桌面端另有覆盖层。

**结论：只信运行时工具表 + `plugin_manager list_plugins`，不要只读 bundle patch 下结论。**

---

## 4. 本会话工具全量来源映射

| 工具组 | 数量 | 来源 | 证据 |
|---|---|---|---|
| `ops_*`（bash、read_files、grep、glob、stat、write_file、edit_file、diff、copy、move、remove、read_table、read_docx、read_pdf、inspect_local_file、replace、result、discover_tools） | 18 | **dsh-ops 0.5.1** | `dsh-ops/dsh-plugin.json` 的 `x-tool-namespaces`（`publicPrefix: "ops_"`，明列 16 个文件工具 + `bash` + PTC 的 `batch`/`load_sdk`） |
| `task_board_*`（create/get/list/manage/run/schedule/set_parent/update） | 8 | **@linxin666/dsh-client-ui-task-board 0.4.14**（node 半侧注册工具，browser 半侧出 UI） | 该包 `cordis.patch.yml` 注释：「the node half runs in the host process」 |
| `spawn_teammate`、`list_agents`、`send_message`、`wait_agent`、`interrupt_agent`、`team_task_*` | 13 | **@deepseek-ai/dsh-experimental-tool-agent-team**（经 agent-team-profile bundle） | bundle `cordis.patch.yml` 插入 `tool-agent-team` |
| `subagent`、`subagent_fork`、`list_subagent_models` | 3 | `dsh-subagent` + `dsh-tool-subagent`（base；声明被 agent-team 禁用但运行时仍在） | 见 §3.4 |
| `workflow` | 1 | `dsh-tool-workflow` + `dsh-workflow-ptc`（base） | base patch L400-406 |
| `schedule_create/edit/list/view` | 4 | `dsh-tool-schedule` + `dsh-schedule`（web-app bundle） | web-app 依赖列表含 `dsh-schedule`/`dsh-tool-schedule` |
| `todo_write`、`skill`、`present`、`job_*`、`web_search/web_fetch`、`get_goal/update_goal/create_goal`、`exit_plan_mode`、`ask_user_question`、`working_directory` | — | base / web-app bundle | base patch 对应行 |
| `plugin_manager` | 1 | `dsh-plugin-manager` | Lead 实测 222 条 loader 条目 |
| `modlens_read_image` | 1 | **@liustack/modlens 3.27.2** | 调用返回 `modlens failed` |
| `read_image` / `write` / `edit` | 3 | 原生 fs 工具（`dsh-tool-fs`，`applyPatch: false`） | base patch L296-300 |

**技能（skill）现状**
- `office` / `office-docx` / `office-pptx` / `office-xlsx` / `office-render` / `office-export-pdf` / `office-recalculate`：来自磁盘目录 `D:\DeepSeek Harness\resources\runtime\office-skills\`（实测存在 7 个子目录），配合 asar 内 `dsh-skill-office` + `libreoffice-kit(-win32-x64)`。
- `modlens` 技能：`node_modules/@liustack/modlens/skills/modlens/SKILL.md` 存在，但**不在本会话技能目录里** → 装了未暴露。
- `arkcli-*`（约 24 个）、`understand-*`（6 个）、`diagnose-windows-sandbox-acl`：**来源未定位**。已排除：`~/.dsh/skills` 不存在、app.asar 内 grep `arkcli` 零命中、工作区无 `SKILL.md`。旁证：`C:\Users\20441\.arkcli\` 存在完整凭证/身份目录（`config.yaml`、`identities/volc-2106848300/*`），故最可能是 **arkcli CLI 的 `connect` 把内嵌 skills 注入到 DSH 的某个技能根**（`arkcli-connect` 技能描述正是「将 arkcli 内嵌 AI skills 安装到本机检测到的所有 AI Agent」）。
- 建议核实方式（只读）：GUI 里打开 **skill-explorer 面板**（该插件就是按 source 分类浏览技能），或 Lead 跑 `ops_glob` 在候选技能根上找 `SKILL.md`。

**MCP 现状**
| 项 | 事实 |
|---|---|
| 内核能力 | `dsh-mcp-resources` 在 base patch 中**已挂载**（L492-493） |
| MCP 客户端 | `@deepseek-ai/dsh-mcp-client` **存在于 app.asar 的 331 个包中，但未出现在 base/web-app 的 patch 里** → 能力在包里、未挂载 |
| 配置 | profile 的 `cordis.patch.yml` 无任何 `mcp` 段；`~/.dsh/storages` 只有 `session_projcache/` 与 `workspace.json`，无 MCP 服务器配置 |
| CLI | `dsh --help` 只暴露 `plugin` 子命令，**没有 `dsh mcp`** |
| 会话内 | 工具表**没有任何 MCP 工具** |
| 结论 | **当前 0 个 MCP 服务器在跑**。想接 MCP（例如浏览器自动化、Playwright MCP），需要额外挂 `dsh-mcp-client` + 写配置——现有插件组合做不到 |

---

## 5. 重复 / 冲突 / 风险清单（保留 / 调整 / 移除 初判）

| # | 冲突/重复 | 事实依据 | 初判 | 理由 |
|---|---|---|---|---|
| 1 | **两个插件市场**：`@deepseek-ai/dsh-experimental-plugin-market-bundle`（Discover 页） vs `dshmarket`（可视化市场） | 两者 patch 各自插入 `plugin-market`/`ui-plugin-market` 与 `dsh-market`；且前者 `indexes: []` 为空 | **保留 dshmarket，plugin-market-bundle 可移除或补索引** | 两个市场页会让「装插件」入口分裂；内置那个当前没索引源=摆设 |
| 2 | **两套任务系统**：`task_board_*`（@linxin666，宿主持久化 + cron 执行） vs `team_task_*`（agent-team，内存协作板，maxTasks 256） | 工具表同时存在两套；`task_board_list` 显示 board revision 0、0 任务；team 板是本审计实际用的那套 | **都保留，但要分工写清** | task_board 适合「跨天/可调度/给人看的看板」；team_task 适合「本轮多 agent 协作」。混用会导致任务双写、状态双源 |
| 3 | **两条子 agent 通道**：`subagent`/`subagent_fork`（base） vs `spawn_teammate`+`team_task_*`（agent-team，maxMembers 8） | agent-team patch 声明禁掉前者，运行时两者都在（§3.4） | **调整：明确只用 Team 通道做长任务** | 两套都可用=同一次编排可能走不同路径，成本与可控性都不可预期；建议在团队 preset 里显式只留一套 |
| 4 | **三种"回退/撤销/回滚"**：`dsh-rewind-plugin`（会话回退+工作区文件还原） / better-sidebar 编辑器 undo / git-graph（git 回滚） | rewind 描述「In-window conversation rewind with workspace file restore」；better-sidebar 内建编辑器自带 undo；git-graph 做分支/提交 | **保留 rewind + git-graph，明确边界** | rewind 会**改动工作区文件**，与编辑器 undo 语义冲突（undo 是编辑缓冲，rewind 是磁盘+会话）。对零编程用户，误用 rewind 可能同时丢对话与文件改动 → 应写进使用守则 |
| 5 | `cc-safety-net` 的拦截面 | 它 `inject:["tools"]` 做工具级拦截；但本机 shell 是 `ops_bash`（dsh-ops 自带 payload），不是内核 `bash` | **保留但必须实测** | 若它只认 Claude-Code 风格 shell 钩子，则 `ops_bash` 可能绕过拦截 → 「有安全网」是错觉。需一次受控测试（如让它拦一条 `rm`）才能定论 |
| 6 | `auto-review` vs 「代码复核」 | 其 desc 明确是 **Auto 权限档的逐工具 LLM 授权复核** | **不要当成 code review 用** | 原假设「auto-review 与 code-review 插件重叠」**不成立**；在 workspace-write 档它根本不参与。代码复核只能靠 subagent/team + 人工 |
| 7 | **版本钉死风险**：`dsh-ops 0.5.1` 的 `engines.dsh` = `>=0.2.2-rc.1 <0.2.3-0` | `node_modules/dsh-ops/package.json` | **升级 DSH → 必须先确认 dsh-ops 有对应版本** | 这是本机 shell + 全部文件工具的**唯一**提供者；DSH 一升 0.3，它立刻不兼容 → 整套能力归零 |
| 8 | **兼容声明缺口**：`dsh-context 0.80.2`（只声明到 0.2.1-rc.2）、`dsh-pet 0.4.1`（到 0.2.2-alpha.2） | 两者 `dsh.compatibility.dshReleases` 未含 0.2.2-rc.1 | **观察项** | 「未声明」不等于坏，但排障优先级最高 |
| 9 | **modlens 外部依赖** | desc: *powered by the free Antigravity CLI*；报错 `claude-cli provider failed` | **要么修依赖，要么换视觉方案** | 对标注项目这是硬需求（截图理解/视觉验收）；现在等于没有 |
| 10 | **桌面 profile 被 Electron 独占** | `--dump-config` 被拒；`plugin list` EPERM；desktop profile 由 GUI 管理 | **接受现状，自动化只走 GUI + plugin_manager** | 任何「CLI 脚本化插件管理」的设想都要放弃 |
| 11 | **shell 执行器不稳定** | `ops_bash` 并发时 `EXECUTOR_UNAVAILABLE ... Niubash execution tree link count mismatch` | **调整用法：串行调用 bash；失败重试一次；其余读操作走文件工具** | 这是宿主管道问题，不是权限问题；并发会互相踩踏私有副本 |

---

## 6. 能力缺口表（按 7+1 环节）

判定口径：「内核/现有插件提供」= 有工具或机制；「不提供」= 需要新增插件/配置/外部依赖。

| 环节 | 现状 | 提供方 | 缺口 | 结论 |
|---|---|---|---|---|
| ① 需求澄清与记录 | `ask_user_question`（结构化提问）、`todo_write`、`goal`（`create_goal/get_goal/update_goal`）、会话上下文压缩（compaction） | 内核 base/web-app | 无「需求文档沉淀」机制——澄清结果只活在对话/记忆里，没有结构化产出 | **部分提供**：需约定「澄清 → 写入 file」的流程（本项目已有 `dsh_selection_20261109/` 可当落地目录） |
| ② 验收标准与任务规划 | `exit_plan_mode`（计划模式）、`todo_write`、`task_board_*`（宿主持久化看板 + cron）、`team_task_*`；`dsh-context` 看上下文构成 | 内核 + task-board + agent-team | **没有「验收标准执行器」**：task_board 的 acceptance gate 只是记录/声明，不会真的跑测试判定；`skipVerification` 只是跳过记录 | **核心缺口**：需要「可执行验收」的约定（如每次交付必须附测试/截图证据路径） |
| ③ 实现与排错 | `ops_*` 全套文件工具、`ops_bash`、`job_*`（后台任务）、`workflow`（多 agent 并行） | dsh-ops + 内核 | `ops_bash` 并发不稳；`ops_write_file` 当前被 `PUBLICATION_DENIED`（写文件要退回原生 `write`） | **基本提供，但有毛刺**；建议：写文件用 `write`/`edit`，跑命令串行 |
| ④ 测试与代码复核 | `subagent`/`subagent_fork`（可做独立复核者）、`workflow`（结构化 fan-out）、team 多成员；git-graph 看变更 | 内核 + agent-team | **无专用 code-review 插件**（auto-review 不是）；无 lint/test 工具链封装（只能 `ops_bash` 调） | **缺口**：复核靠「再开一个 agent + 明确指令」，无内建质量门 |
| ⑤ 持续执行与中断恢复 | `schedule_*`（cron/一次性）、`job_*`（后台 job）、`goal` + `goal_round_driver`（跨轮继续）、session 持久化（jsonl）+ `session-query-sqlite`（但 `openAt: never`，全文检索关闭）、`dsh-rewind-plugin`（会话回退） | 内核 + 3 个插件 | 会话搜索被显式关闭（`openAt: never`）→ 历史只能按标题/工作区找；`rewind` 是回退不是恢复 | **较强提供**：定时+后台+goal 都在；**但历史检索弱** |
| ⑥ 浏览器/桌面操作 | **无**：会话无任何浏览器 MCP、无桌面自动化工具；`dsh-acp`/`dsh-acp-app` 在 asar 但未挂载；`dsh-mcp-client` 在 asar 但未挂载 | — | **完全缺口** | 对 X-AnyLabeling（PyQt6 桌面程序）做「启动→点按钮→截图」的自动化，**当前做不到**；需要新增 MCP/ACP 或外部脚本 |
| ⑦ 截图理解与视觉验收 | `modlens_read_image`（已加载，**实测失败**）；原生 `read_image`（模型不支持图片输入）；`present`（发布交付物） | modlens（坏） | **端到端不可用**：模型无视觉 → 唯一桥 modlens 的 provider（claude-cli）报错 | **最大缺口**：视觉验收必须先把 modlens 依赖修好，或换带视觉的 provider（`llm-pi-ai` 目录里现有 7 个模型均需重核是否支持图片） |
| ⑧ 状态与交付证据保存 | 文件系统（可写 `dsh_selection_20261109/`、`.tmp/`）、`present`（声明交付物）、session 日志 jsonl、`ops_result`（分页引用大结果） | 内核 + dsh-ops | 无「证据归档规范」；`reports/` 不可写（本会话沙箱限制） | **部分提供**：需约定证据目录（本次即 `.tmp/dsh-sel-20261109/env/` 存原始输出 + `dsh_selection_20261109/` 存交付） |

---

## 7. 本次审计的一手证据清单（命令 + 输出摘录）

| # | 命令/动作 | 输出摘录 | 用途 |
|---|---|---|---|
| E1 | `"D:\DeepSeek Harness\resources\runtime\cli\bin\dsh.cmd" --version` | `0.2.2-rc.1` | 版本 |
| E2 | 同 CLI `--help` | 仅 `dsh plugin --profile <name> <pnpm-args...>` 一个子命令；**无 `mcp`** | CLI 能力边界 |
| E3 | `dsh --profile desktop --dump-config` | `error: profile "desktop" is managed exclusively by the Electron application`（exit 1） | desktop profile 独占 |
| E4 | `cat resources/runtime/versions.json` | `{"node":"24.21.0","pnpm":"11.28.5"}` | 自带运行时 |
| E5 | `cat profiles/desktop/package.json` | 12 个 dependencies；`dsh.profile.bundles` 16 项；**无 dsh-pet / dsh-whale-widget** | 装了≠启用 |
| E6 | `cat profiles/desktop/cordis.patch.yml` | `agent-default-model: provider commandcode / model deepseek/deepseek-v4.1-flash-fast / reasoningEffort max`；llm-pi-ai retryPolicy 8 | 模型路由 |
| E7 | 自写 asar 解析（`.tmp/.../asar_scan.py`） | `total entries: 22102 / shipped @deepseek-ai packages: 331 / base: 5748140` | 内置包清单 |
| E8 | 提取 6 个 bundle 的 package.json + patch | 全部 `0.2.2-rc.1`；agent-team patch 含 `disabled: true` 的 `tool-subagent*` 行；auto-review desc 明确「Auto 预设」 | 内置 bundle 事实 |
| E9 | 读 `dsh-base/cordis.patch.yml` 535 行 | `bash-sandbox disabled: process.platform === 'win32'`；`tool-bash disabled: win32`；`approval.policy: 'ask'`；`sandbox-policy mode: workspace-write` | 权限/shell 真相 |
| E10 | `task_board_list(limit=5)` | `{"ok":true,"board":{"revision":0,...,"maxSubtaskDepth":1,"sessionDefaultPermission":"workspace-write"},"total":0}` | task_board 实测可用 |
| E11 | `modlens_read_image(assets/demo/demo_license_plate.png)` | `Error: modlens failed (exit 1): Error: claude-cli provider failed with code 1.` | 视觉桥实测失败 |
| E12 | `read_image(同一文件)` | `Error: cannot read ... model "deepseek/deepseek-v4.1-flash-fast" does not declare image input` | 模型无视觉 |
| E13 | `ops_write_file(.tmp/.../scan_plugins.py)` | `rejected: PUBLICATION_DENIED / Publication authorization is unavailable.`（改用原生 `write` 成功） | ops 写工具受阻 |
| E14 | `ops_bash(mkdir ...)` 多次 | `EXECUTOR_UNAVAILABLE: the restricted Bash runtime could not be prepared: Niubash execution tree link count mismatch: assets/niubash-icon-256.png`（重试后 `echo probe` 成功） | shell 执行器不稳 |
| E15 | `team_task_get(task-2)` / `team_task_update(claim)` | `{"id":"task-2","revision":1,...,"status":"in_progress","ownerName":"env-auditor"}` | team 工具实测可用 |
| E16 | `ops_grep` 在 `shipped_pkg_names.txt` | 命中 `dsh-mcp-client`、`dsh-mcp-resources`、`dsh-schedule`、`dsh-tool-schedule`、`dsh-subagent`、`dsh-workflow`、`dsh-tool-present`… | 能力是否随包存在 |
| E17 | Lead 实测 `dsh plugin --profile desktop list` | `EPERM ... package.json.lock` | CLI 无法管理 desktop 插件 |
| E18 | Lead 实测 `plugin_manager list_plugins` | 222 条 loader 条目；active 的第三方＝dshmarket、dsh-context、dsh-better-sidebar、modlens、cc-safety-net、rewind、@linxin666 三件、dsh-ops；**无 pet / whale** | L2 启用层权威证据 |

原始输出存档：`.tmp/dsh-sel-20261109/env/`（`plugins_raw.json`、`asar_out/shipped_pkg_names.txt`、`asar_out/extracted/**`、`dump_config.err`）。

---

## 8. 待 Lead/用户执行的确认项（本审计受限于「不得改配置、bash 被停用」）

1. `dsh plugin --profile desktop list` 已由 Lead 跑出 EPERM —— 确认 CLI 路线不可行（已入报告）。
2. 修 modlens：查 `@liustack/modlens` 的 `claude-cli` provider 依赖（Antigravity CLI 是否安装/登录）。命令建议：`ls "$LOCALAPPDATA" | grep -i antigravity`、`modlens doctor`（包内有 `bin`）。
3. 确认 `cc-safety-net` 是否覆盖 `ops_bash`：一次受控测试（让它拦一条明显危险命令，观察是否被 block）。
4. 确认技能来源：GUI 打开 skill-explorer 面板看 `arkcli-*` / `understand-*` 的 source 标记。
5. 若要上线「截图理解」：先确认是否存在**支持图片输入**的模型路由（当前 commandcode 目录 7 个模型均未声明图片能力；需在 Models 页核实）。

---

*本报告只陈述实测事实与判据，不含安装/配置动作。*
