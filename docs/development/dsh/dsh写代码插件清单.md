# DSH 市场里「写代码」的插件清单

> 数据来源：本机 `dshmarket`（可视化插件市场）所用的公开目录 `awesome-dsh-plugin.com/plugins.json`，快照更新于 **2026-11-06**，共 **9,305** 个插件、23 个分类。下表星数/下载量即该目录的统计值（目录里 0 表示作者未采集到，不代表没人用）。
>
> 市场**没有**「写代码」这一个单独分类，最贴近的是 **开发与运行时（dev，540 个）** 和 **Git 与代码评审（git，177 个）** 两类；真正提升编码体验的还有散在「工具与能力 / 技能包 / 工作流」里的 LSP、代码图谱、diff 审查、工程方法插件。下面按写代码的实际流程整理成 8 组。

## 如果只装 3～4 个

| 插件 | 为什么先装它 | 安装目标 |
| --- | --- | --- |
| **dsh-lsp-actions** | 把真实语言服务器的诊断/格式化/补全/代码动作/符号/重命名接到 agent 手里，是目前市场里最「IDE 内核」的一件事 | `dsh-lsp-actions` |
| **dsh-diff-approval** | agent 每次 edit/write 自动汇总，可逐块「保留 / 回退」，写坏了不用靠 git 兜底 | `dsh-diff-approval` |
| **brooks-lint** | 6 个代码质量技能：代码审查、架构审计、技术债、测试质量、健康看板、修复 | `brooks-lint` |
| **superpowers-dsh** | 移植自 obra/superpowers 的 TDD + 调试 + 规划 + 协作技能，约束「先计划后编码」 | `superpowers-dsh` |

---

## 1. 代码编辑 / IDE 式工作台

| 插件 | 做什么 | 热度 | 安装目标 |
| --- | --- | --- | --- |
| **dsh-better-sidebar**（已装） | 侧栏完整工作台：文件渲染编辑、终端、Git、子代理，三方插件可注册新 Tab | ★4959 / ↓289k | `dsh-better-sidebar` |
| **dsh-codex-ui** | Codex 风格侧栏 + 工作区会话树 + 全局搜索 + 轮次导航 | ★270 / ↓76k | `@michengai/dsh-codex-ui` |
| **seektty** | 终端工作区：VS Code 主题、结构化工具与 Diff 视图、Skill/MCP 浏览 | ★192 / ↓1.6k | `seektty` |
| **DSH_VsCodeMode** | 基于 Monaco 的中央文件编辑器（文件页签、Ctrl+P、状态栏）+ agent 改动逐处采纳/拒绝 | ★24 / ↓12k | `dsh-vscode-mode` |
| **dsh-solution-explorer** | VS Code 风格文件树 + 源代码管理（暂存/提交/分支/多仓库/语法高亮编辑） | ★11 / ↓2.2k | `dsh-solution-explorer` |
| **dsh-code-server-app** | 直接把 code-server（VS Code 网页版）打包进 DSH，要专业编辑体验时最直接 | ★7 / ↓2.8k | `dsh-code-server-app` |

## 2. 语言智能 / 代码理解（真正决定「会不会改代码」）

| 插件 | 做什么 | 热度 | 安装目标 |
| --- | --- | --- | --- |
| **dsh-lsp-actions** | LSP 动作面：诊断、格式化、补全、代码动作、符号、签名提示、inlay hints、重命名 | ★36 / ↓6.6k | `dsh-lsp-actions` |
| **GraphFlow** | 面向编程 agent 的本地代码知识图谱，10 个 MCP 工具：分层上下文压缩、DAG 规划、增量 AST 建图、影响分析 | ★30 / ↓16.5k | `@roarpeng/graphflow` |
| **dsh-codegraph** | 13 个 `codegraph_*` 工具包装 codegraph CLI：符号查询、callers/callees、影响分析、受影响测试，免 grep | ★22 / ↓1.4k | `@jiangzhenguo/dsh-codegraph` |
| **dsh-code-index** | Impact X-Ray 展示变更影响与源码证据 + 符号导航 + 有界 Context Pack | ★9 / ↓3.4k | `dsh-code-index` |
| **dsh-tool-lens** | 确定性 AST 代码图谱：调用链消歧、重构爆炸半径、循环依赖审计、API 契约追踪 | ★4 / ↓925 | `@trench-xinxin/dsh-tool-lens` |
| **dsh-refactor-insight** | 把坏味道（超长文件/深嵌套/上帝对象）转成带定位、优先级、依赖顺序的重构计划 | ★0 / ↓1.3k | `dsh-refactor-insight` |

## 3. 改动审查 / 逐块 diff（写代码最高频的一环）

| 插件 | 做什么 | 热度 | 安装目标 |
| --- | --- | --- | --- |
| **dsh-diff-approval** | 每次 edit/write/str_replace_editor 自动汇总，单块/多块/整文件保留或回退，可导入 git 改动双栏对照 | ★15 / ↓6.8k | `dsh-diff-approval` |
| **dsh-diff-viewer** | PiUI 风格 diff 查看器，替换 write/edit 默认 DiffBlock | ★25 / ↓0 | 见目录页（tgz） |
| **dsh-change-review** | 追踪会话内 write/edit 并展示 diff：会话隔离、子代理聚合、SSE 实时推送 | ★14 / ↓0 | `github:cirelir/dsh-change-review` |
| **dsh-vscode-review** | 把每次写入/编辑/`rm` 记进 shadow git 仓库，在 VS Code 里逐 hunk 接受或撤回 | ★10 / ↓0 | `github:Tlyer233/dsh-vscode-review#path:/dsh-review` |
| **dsh-review-checkout** | Codex 风格：每轮变更卡片、净差异统计、真实行号、按轮一键撤回 | ★7 / ↓1.8k | `dsh-review-checkout` |
| **dsh-approval-gate** | 自动审批门控（安全操作自动放行、危险转人工）+ unified diff + 一键撤销 | ★110 / ↓4.1k | `dsh-approval-gate` |

## 4. Git / PR / 提交

| 插件 | 做什么 | 热度 | 安装目标 |
| --- | --- | --- | --- |
| **@linxin666/dsh-client-ui-git-graph**（已装） | 输入框上方的分支选择器 + 分支泳道提交图谱 | ★9959 / ↓116k | 已装 |
| **codex-guard** | 提交前 PR 卫生检查：TODO 残留、硬编码密钥、非规范提交信息 | ★132 / ↓0 | `github:Akimiya-z/codex-guard#path:/dsh` |
| **dsh-git-panel**（xbzbing） | IDE 风格 Git 面板：三栏总览 + 变更记录页 + 逐文件暂存/丢弃 + amend | ★33 / ↓8.3k | `@xbzbing/dsh-git-panel` |
| **dsh-github** | GitHub CI 集成：action.yml、PR 评审机器人（行内评论 + status 门禁）、PR/issue 工具 | ★28 / ↓7.2k | `@perrylink/dsh-github` |
| **dsh-git-worktree** | 任务在隔离 worktree/Session 中跑，Ready for Review、可撤回预览、人工确认交付 | ★21 / ↓2.5k | `dsh-git-worktree` |
| **dsh-ide-git** | JetBrains 风格 Git 工具窗口：分支树、可筛选提交图谱、行级 diff、合并/变基/优选/重置 | ★19 / ↓12.4k | `dsh-ide-git` |
| **dsh-code-review**（MichengAI） | `/review`、`/review-status`、`/review-cancel`，独立子 Agent 审查指定 Git 范围 | ★16 / ↓25k | `@michengai/dsh-code-review` |
| **dsh-github-flow** | 把本机 `gh` 包装成 agent 工具集（PR/Issue/Actions/仓库检索）+ `/gh` 命令 | ★15 / ↓3.8k | `dsh-github-flow` |
| **dsh-worktree-panel** | worktree 面板：项目 → 主/关联 worktree → 会话，脏工作树与活跃会话保护 | ★9 / ↓0 | `github:HeathHe/dsh-worktree-panel` |

## 5. 工程方法 / 技能包（让模型「会写」而不只是「能写」）

| 插件 | 做什么 | 热度 | 安装目标 |
| --- | --- | --- | --- |
| **brooks-lint** | 6 个代码质量技能：代码审查、架构审计、技术债、测试质量、健康看板、修复 | ★1556 / ↓2k | `brooks-lint` |
| **Aegis** | 编码 agent 软件工程方法包：基线优先规划、系统化调试、提示词卫生、完成前验证 | ★1411 / ↓0 | `github:GanyuanRan/Aegis` |
| **dsh-mattpocock-skills-deck** | 自带 mattpocock/skills 的 27 个工程与效率技能 | ★280 / ↓18.8k | `dsh-mattpocock-skills-deck` |
| **superpowers-dsh** | Superpowers 移植：TDD、调试、规划、协作，14 个技能、零运行时依赖 | ★135 / ↓8k | `superpowers-dsh` |
| **dsh-super-code** | 更快更省的编码 agent 预设（作者称 SWE-bench Pro 高难 100 题：耗时 −36%、输入 token −17%、正确率 +5pt） | ★23 / ↓4.3k | `dsh-super-code` |
| **supergraph** | 规范计划 → TDD → 自动修复闭环 → 代码知识图谱 → 多智能体分波执行（需先装 codebase-memory-mcp） | ★23 / ↓0 | `github:datit309/supergraph` |
| **dsh-programming-mode** | 编程模式 preset：强制「先计划后编码、TDD、系统化调试、完成前验证」，含 20 个技能 | ★12 / ↓1.7k | `@ziduup/dsh-programming-mode` |
| **dsh-swarm** | 六种专职 agent（编排/规划/开发/方案评审/代码评审）的阶段流水线，评审只读、通过才合并 | ★7 / ↓1.5k | `@joekytc/dsh-swarm` |
| **SpecWave** | ICVO 编码规范套件（原 dsh-coding-kit）：`apply_coding_standards` 注入规范 + P0 门禁 CLI | ★6 / ↓2.8k | `spec-wave` |

## 6. 测试 / 重构

| 插件 | 做什么 | 热度 | 安装目标 |
| --- | --- | --- | --- |
| **dsh-simplify**（MichengAI） | `/simplify`：在选定 Git 变更范围内简化代码（支持暂存/提交/未跟踪） | ★11 / ↓16.9k | `@michengai/dsh-simplify` |
| **dsh-test-autofix** | `run_tests` 工具：自动识别 pytest/jest/vitest/cargo/go/npm，提取失败 file/line/断言，死循环检测 | ★0 / ↓385 | `dsh-test-autofix` |

## 7. 把别的编码 CLI / Agent 拉进 DSH

| 插件 | 做什么 | 热度 | 安装目标 |
| --- | --- | --- | --- |
| **deja-vu** | 读本机 42 个编程 agent（Claude Code、Codex、Cursor、Copilot、Cline、Zed…）的会话历史，提供 recall/blame/fix 工具 | ★1422 / ↓7.6k | `dsh-deja` |
| **dsh-chat-import** | 把 13 家 coding agent 的对话历史导入成可续聊的 DSH 会话，并可反向导出 | ★287 / ↓15.4k | `dsh-chat-import` |
| **dsh-ntr** | 任意 ACP Agent 接进 DSH：工具调用在主聊天区，diff 汇总到独立 NTR 页 | ★107 / ↓6.7k | `dsh-ntr` |
| **Codingns4DSH** | 十几种编程助手 CLI + 持久终端 + 远程工作区，统一到 DSH 原生界面 | ★67 / ↓4.2k | `@jingyi0605/codingns4dsh` |
| **dsh-codex-workflow** | Codex 负责计划与独立审查，DSH 原会话负责改码与跑测试 | ★6 / ↓2.1k | `dsh-codex-workflow` |
| **dsh-codex-peer** | 与本地 Codex CLI 对等协作：共享工作清单、派活、互相审查、全程留档 | ★1 / ↓0 | `github:wuanthony397-hash/dsh-codex-peer` |
| **dsh-plugin-ide-hub** | 一个入口管 8 个编码 IDE（dsh/Claude Code/Codex/ZCode/Qoder/CatPaw/Trae/OpenCode） | ★2 / ↓850 | `dsh-plugin-ide-hub` |

## 8. 特定技术栈工具链（按需）

| 插件 | 做什么 | 热度 | 安装目标 |
| --- | --- | --- | --- |
| **dsh-gitbash-shell** | Windows：把宿主 shell 换成 Git for Windows bash，并物化四个 Git Bash 预设 | ★43 / ↓12.9k | `dsh-gitbash-shell` |
| **unity-plugin** | 官方 unity CLI：场景命令、编辑器内 C# 求值、建工程/跑测试/构建 | ★63 / ↓2.3k | `@opdsh/unity-plugin` |
| **minecraft-dev** | MC 1.7.10～26.3：9 个技能（插件/模组/Gradle/JDK）+ `mc_scaffold` 生成器 + 构建执行器 | ★39 / ↓3.8k | `minecraft-dev` |
| **dsh-learning-mode** | 边做边教的编码 agent 预设（苏格拉底式引导、TODO(你) 留白） | ★10 / ↓1.1k | `dsh-learning-mode` |
| **dsh-ios-simulator-helper** | 20 个 `ios_*` 工具：Xcode 工程、模拟器、构建、安装、日志（仅 macOS） | ★3 / ↓1.6k | `@zhz8888/dsh-ios-simulator-helper` |
| **dsh-android-emulator-helper** | 23 个 `android_*` 工具：SDK/AVD/模拟器、Kotlin/Compose 工程、Gradle、logcat | ★2 / ↓2k | `@zhz8888/dsh-android-emulator-helper` |

---

## 怎么安装

**方式 A（推荐）**：界面里的插件市场（本机已装 `dshmarket`），搜包名或分类，点安装即可，装完约 1 秒热加载。

**方式 B（命令行）**：本机 profile 叫 `desktop`，所以是

```powershell
dsh plugin --profile desktop add <安装目标>
```

例如：

```powershell
dsh plugin --profile desktop add dsh-lsp-actions
dsh plugin --profile desktop add dsh-diff-approval
dsh plugin --profile desktop add brooks-lint
```

> 目录页给的示例命令统一写 `--profile web`，按你自己的 profile 名替换即可。

## 怎么自己逛

1. 打开插件市场的「发现」页，在分类里选 **开发与运行时**、**Git 与代码评审**；「工具与能力」「技能包」「工作流」里也有大量编码向条目。
2. 搜索关键词：`代码`、`编程`、`LSP`、`AST`、`diff`、`review`、`Git`、`PR`、`TDD`、`重构`、`worktree`。
3. 市场数据源（可直接看全量 JSON）：
   - `https://awesome-dsh-plugin.com/plugins.json`（本清单来源，9305 条）
   - `https://cdn.jsdelivr.net/npm/dsh-plugin-catalog/index.json`（dsh 0.2.1+ 的「发现 → 索引源」可添加，15 秒内可加载）

## 说明

- 目录里 `dev` 分类共 540 个，但其中相当一部分是**DSH 插件开发 / 宿主调试**（插件运行时、MCP 面板、profile 管理、备份恢复等），并不是写业务代码的工具；`git` 分类 177 个则基本都跟代码仓库相关。本清单已按「写代码」这个目标做过筛除。
- 「星数 / 下载量」只作热度参考：目录里不少条目是 0，是因为作者还没采集到 npm/仓库数据，不代表质量差。
- 安装前留意兼容性：市场会在条目上标注与当前 DSH 版本的兼容情况，`engines.dsh` 不满足的会安装失败（本机 DSH 为 0.2.2-rc.1）。
