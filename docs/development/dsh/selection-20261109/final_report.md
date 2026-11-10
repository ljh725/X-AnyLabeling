# DSH 插件选型最终报告（X-AnyLabeling 4.2.1 项目）

- 报告时间：2026-11-09（Asia/Shanghai）
- 调查性质：**只读调查与选型**。本轮**未安装、未卸载、未升级任何插件**，**未修改任何持久配置**。
- 目标：用最少的插件，把 DSH 组合成「我提自然语言需求 → 澄清 → 验收标准 → 实现 → 跑测试 → 实机界面验证 → 交付证据」的一条可用流水线，尽量少让我管理技术步骤。
- 证据分层约定：**【实测】**=本次会话亲手跑过；**【报告实测】**=同项目子代理实测并留有命令/输出；**【源码发现】**=读到 package.json / manifest / 源码；**【作者声明】**=README/市场页自述；**【推断】**=基于以上事实推理。凡未做的一律写「未做」。

---

## 0. 一页结论（先看这里）

1. **不装重复的"流程系统"。** 你的 DSH 内核（0.2.2-rc.1）已经自带：目标续跑与轮数上限、任务板（卡片开真实会话 + cron + 验收门）、Agent Teams（派活/共享任务）、子代理、workflow 编排、计划模式、定时任务、会话回退（rewind 已装）。市场上 loopx、dsh-pua、dsh-auto-continue、dsh-task-ledger、superpowers-dsh 这些，基本都是这些东西的重复包装，**不建议装**。
2. **真正缺的只有三件**，各对应一个环节，互不重复：
   - **dsh-doublecheck**（需求澄清 → 验收标准 → 红/绿测试证据 → 对抗评审 → 交付闸门）：补「流程纪律」，是 7+1 个流程候选里唯一**显式适配 0.2.2-rc.1**、真执行、零外部依赖的。
   - **dsh-diff-approval**（每次改动逐文件/逐块 Keep / Revert）：补「改前先看一眼」，你的仓库现在有 23 个未提交改动，这是最低门槛护栏。
   - **dsh-computer-use-win**（Windows UI Automation：读控件树/截图/OCR/点击，只读起步）：补「真的去点软件」，是唯一能驱动 X-AnyLabeling 真实 PyQt6 窗口的工具。**把它当"手"，不当"眼"，更不当"法官"**。
3. **视觉链路不装新插件，先修已装的 modlens。** 现在它坏了（`claude-cli provider failed with code 1`，根因：Claude Code 已装但未登录）。修好它 + 用项目已有的离屏截图（`QWidget.grab()` 0.07 秒出图、中文正常）做像素断言，比装视觉插件更省、更可信。若修不好，唯一零 Key 备选是 **dsh-vision-router**（但必须联网、图片上传到 OVHcloud 法国、要求 Node ≥24.9）。
4. **测试可以真跑，而且能当验收闸门——但必须用固定命令。** 本次实测：加上 `PYTHONPATH=.tooling/pytest-shim`、`QT_QPA_PLATFORM=offscreen`、`--basetemp=<仓库内绝对路径>` 后，原本报 21 errors 的 `test_inspector_dialog.py` **21 passed / 54.35 秒**。之前那 21 个错误是 DSH 沙箱的临时目录 ACL 问题，**不是代码 bug**。
5. **不用装浏览器插件。** 你的验收对象是桌面 PyQt6 窗口，"网页"部分内置的 web_fetch/web_search 够用。dsh-browser 对本地应用零帮助。
6. **不要为了"每个阶段都有一套"而堆叠。** 最终推荐 = **新增 3 个插件 + 2 处配置修复 + 1 条固定测试命令**；其余候选要么淘汰、要么列为备选。

> 一句话组合：**已装底座（dsh-ops + task_board + agent-team + rewind + cc-safety-net + modlens）＋ 新增 doublecheck / diff-approval / computer-use-win（只读）**。

---

## 1. 项目与当前环境摘要

### 1.1 项目（X-AnyLabeling 本仓库）

| 项 | 事实 | 证据 |
|---|---|---|
| 项目类型 | PyQt6 桌面图像/视频/多模态标注工具（GPL-3.0），个人定制分支 | 【实测】`pyproject.toml`、`README_zh-CN.md` |
| 入口 | `anylabeling.app:main`（`python -m anylabeling` 或 `scripts/` 启动脚本） | 【报告实测】project_recon.md |
| Python | `requires-python >=3.11`；实际运行环境 conda `x-anylabeling-cu12` = **Python 3.12.12 + PyQt6 6.10.2 + pytest 9.0.3** | 【实测】 |
| 规模 | `anylabeling/` 486 个模块；`tests/` 204 个测试文件（196 个 `test_*.py`）；`label_widget.py` 9968 行；`inspector/dialog.py` 4688 行；**`resources.py` 141,589 行（生成物）** | 【实测】+【报告实测】 |
| 工作区体积 | 3.4 GB（`.git` 543 MB、`.local` 1.7 GB、`.tmp` 315 MB、`reports/` 6197 文件/4755 张图） | 【报告实测】 |
| 测试配置 | `addopts = --doctest-modules --durations=30 --color=yes`、`testpaths=["tests"]`、markers 仅 `slow`；`tests/conftest.py` 提供 Qt 离屏 + 用户配置隔离 | 【实测】 |
| 未提交改动 | **23 项**，diff 约 ±3.5 万行，但 **97% 是 `resources.py` 生成物**；真正要审约 691 行（`inspector/dialog.py` 608 + `label_widget.py` 83） | 【报告实测】project_recon.md |
| 既有流程 | `openspec/`（proposal → specs → tasks → verification → evidence）；`docs/custom_changes/CATALOG-20261030.md`；`reports/` 逐次留证据；pre-commit（black 79 / flake8） | 【报告实测】 |
| 交付证据习惯 | 已存在 `delivery-receipt.json`（sha256 + git bundle）模式、`reports/*/` 带截图 | 【报告实测】 |

> 结论：这是一个**回归风险高、界面密集、测试多但单次全量跑很慢**的桌面 GUI 项目；对插件的核心诉求是「**别乱改、改了能看、改完能验**」，而不是"再来一套项目管理"。

### 1.2 DSH 版本与运行方式

| 项 | 事实 | 证据 |
|---|---|---|
| 版本 | **DSH 0.2.2-rc.1** | 【实测】`dsh --version` |
| 运行方式 | Electron 桌面端，Web GUI `http://127.0.0.1:7862`（调查期间重启后变 1709，端口不固定） | 【实测】 |
| 实现包位置 | `D:\DeepSeek Harness\resources\app.asar`（213 MB，内含 22,102 个文件；`dsh/node_modules/@deepseek-ai/*` 是内置 bundle） | 【实测】 |
| profile | `desktop`（`C:\Users\20441\.dsh\profiles\desktop`），Electron 独占管理 | 【实测】 |
| CLI 管理 profile | **不可用**：`dsh plugin --profile desktop list` 直接 `EPERM ... package.json.lock`。→ 装/卸插件只能走 **GUI 插件市场** 或 `plugin_manager` 工具 | 【实测】 |
| 模型路由 | `commandcode` → `deepseek/deepseek-v4.1-flash-fast`，reasoningEffort `max` | 【实测】`cordis.patch.yml` |
| 权限模式 | `workspace-write`（只能写工作区；审批提示已开启） | 【实测】运行时上下文 |
| 内置运行时 | node **24.21.0** + pnpm 11.28.5（`resources/runtime/versions.json`）；PATH 上是 node 22.20.0 | 【实测】 |

### 1.3 已装插件：四个层级严格分开

> 口径：**已安装**（在 `package.json` dependencies）≠ **已启用**（在 `dsh.profile.bundles` 且 loader 里 `enabled=true`）≠ **工具已加载**（本会话工具表可见）≠ **实际验证可用**（本次亲手调用过）。

| 插件 | 包名/版本 | 已安装 | 已启用 | 工具已加载 | 实测可用 | 备注 |
|---|---|---|---|---|---|---|
| dsh-ops | dsh-ops 0.5.1 | ✅ | ✅ | ✅ 18 个 `ops_*` | ✅ 读/搜/写文件可用；`ops_write_file`/`ops_stat`/`ops_diff` 恒 `PUBLICATION_DENIED`（改用原生 write/read） | **engines 钉死 `>=0.2.2-rc.1 <0.2.3-0`** —— 升级 DSH 会直接断掉唯一 shell+文件层 |
| dsh-better-sidebar | 0.28.2 | ✅ | ✅ | UI 侧栏 | 部分 | 文件树/编辑器/终端 |
| dsh-context | 0.80.2 | ✅ | ✅ | 上下文面板/`/context` | 部分 | **兼容声明未覆盖 0.2.2-rc.1**（未阻止加载，但属未确认） |
| dshmarket | ^1.73.8 | ✅ | ✅ | 市场 UI | ✅ | 与内置 plugin-market 并存（后者 `indexes: []`，基本空转） |
| @linxin666/dsh-client-ui-task-board | 0.4.14 | ✅ | ✅ | ✅ 8 个 `task_board_*` | ✅ `task_board_list` 实测可用（当前 0 张卡） | 卡片→真实会话、cron、**验收门** |
| @linxin666/dsh-client-ui-skill-explorer | 0.4.14 | ✅ | ✅ | UI | 未测 | 技能中心 |
| @linxin666/dsh-client-ui-git-graph | 0.4.14 | ✅ | ✅ | UI | 未测 | 分支/提交图 |
| @liustack/modlens | 3.27.2 | ✅ | ✅ | ✅ `modlens_read_image` | ❌ **失败**：`claude-cli provider failed (code 1)` | 根因：`~/.claude.json` 无 `oauthAccount`（Claude Code 2.1.177 已装未登录） |
| cc-safety-net | 2.7.2 | ✅ | ✅ | 拦截层 | 未测 | 危险命令拦截 |
| dsh-rewind-plugin | 0.19.1 | ✅ | ✅ | UI/命令 | 未测 | 会话回退 + 工作区还原 |
| dsh-pet | 0.4.1 | ✅ | ❌ **不在 bundles** | — | — | **装了没启用**（装饰类） |
| dsh-whale-widget | 0.4.2 | ✅ | ❌ **不在 bundles** | — | — | **装了没启用**（装饰类） |
| 内置 6 个 experimental bundle | 0.2.2-rc.1 | ✅（asar） | ✅ | agent-team 13 个工具等 | 部分 | agent-team / forge / auto-review / worktree / plugin-market / goal |

**内置能力真相（重要，避免买重复）：**
- **agent-team**：`spawn_teammate`、`send_message`、`wait_agent`、共享任务 DAG（team_task_*）——本次调查就是用它并行完成的（✅ 实测）。
- **goal**：同会话目标 + 自动续跑轮次（`max_goal_rounds` 上限）、`blocked` 需连续 3 轮同一阻塞 → 这就是"有限重试 / 中断恢复"的底座。
- **task_board**：卡片=真实会话、cron 定时、**验收门**（`update_goal complete` 需通过验收，`skipVerification` 可关）→ "任务规划 + 验收"底座。
- **forge**：变更请求/PR 面板，GitHub provider 走本机 `gh` CLI（已装）→ 交付/评审可留痕。
- **auto-review**：**Auto 权限档**下的逐工具 LLM 授权复核，**不是代码审查**；当前 `workspace-write` 档基本空转 → 与市场 `dsh-auto-review`（PerryLink）和三方 `dsh-code-review` **同名不同物**，别混。
- **subagent / workflow / schedule / plan(ui) / ask_user_question / todo / present**：都在。
- **MCP**：当前 **0 个在跑**；`dsh-mcp-client` 在 asar 里但未挂载，也没有 `dsh mcp` 命令。→ 依赖 MCP 的插件（如 computer-use-win）安装时必须先确认这条桥能起来。

### 1.4 能力缺口总表（按你的 7 个环节）

| 环节 | DSH 内核/已装是否覆盖 | 缺口 | 结论 |
|---|---|---|---|
| 需求澄清与记录 | `ask_user_question`、计划模式；项目已有 openspec | 「追问清单 → 结构化验收标准」的强制动作 | **dsh-doublecheck 补** |
| 验收标准与任务规划 | task_board（验收门）、goal | 同上（把"验收标准"写成可核对的 spec） | **dsh-doublecheck 补**；task_board 保留 |
| 实现、排错、测试、代码复核 | ops 文件工具、subagent、agent-team、workflow | 改前逐块确认；结构化跑测试 | **dsh-diff-approval** 补确认；测试用固定命令；`dsh-test-autofix` 备选 |
| 持续执行、有限重试、中断恢复 | goal 轮数上限、rewind、session resume | 基本无 | **不需要新增**（loopx/pua/auto-continue 淘汰） |
| 浏览器/桌面操作 | web_fetch/web_search；无桌面操作 | **真实 PyQt6 窗口操作** | **dsh-computer-use-win 补**（只读起步） |
| 截图理解与视觉验收 | modlens（已装但坏）；离屏截图/ffmpeg/PowerShell 可用 | **读图能力当前不可用** | **修 modlens provider**；备选 vision-router |
| 项目状态与交付证据 | task_board、reports/、openspec、present、forge | 基本无 | **不需要新增** |

---

## 2. 全目录遍历记录（100% 条目）

### 2.1 市场入口与真正的数据源

- 你给的入口 `https://dshmarket.com/browse/`：**不是数据源**，而是每日 CI 生成的**静态 HTML 快照**（1,402,142 字节，`Last-Modified: 2026-11-08 18:44:20 +08`）；页面里 9,463 个插件链接全部服务端渲染，仅 2 个 `<script>` 做前端过滤，**无分页、无 JSON 注入**。
- 真正的完整索引：**`https://awesome-dsh-plugin.com/plugins.json`**（单文件整包下载，**没有分页接口**）。证据链：
  - 已装 `dshmarket` 源码常量 `lib/regions.js:83`：`CATALOG_OFFICIAL = 'https://awesome-dsh-plugin.com/plugins.json'`；
  - 中国区镜像走 npm 包 `dsh-plugin-catalog`（同源）；
  - HTTP 实测：200、`application/json`、GET 12,897,605 B（gzip 3.18 MB）、`ETag` 存在；
  - `/browse/` 页脚自述 "refreshed daily by CI"。
- `dshmarket.com/index.json`（3.92 MB / 4,872 条）是 **npm 包索引**（name/homepage/versions），不是目录 → 不能替代全量清单。
- 9 个猜测端点（`/plugins.json`、`/api/plugins` 等）全部 404（已记录，不作数据源）。

### 2.2 获取时间与条目数（三个口径）

| 口径 | 条目数 | 时点 | 性质 |
|---|---:|---|---|
| `/browse/` 静态页 | **9,463** | 2026-11-08 18:44 +08 | 页面快照，滞后 |
| `plugins.json` 本次快照（统计基准） | **9,687** | `updated=2026-11-08`，抓于 2026-11-09 08:58 | 权威目录 |
| `plugins.json` 线上复核 | **9,714** | `updated=2026-11-09`，复核于 09:35 | 仍在增长（数小时 +27） |

### 2.3 遍历与质量统计（基于 9,687 快照）

- **遍历数量 9,687 / 9,687（100%）**，无获取失败条目。
- **重复项：0**（三种口径：`owner+name` 唯一 9,687；`page` 唯一 9,687；`npm` 唯一 4,870）。
- 唯一 owner 6,312；有 npm 包 4,870（50.3%）；`github:` 安装 3,846（39.7%）；stars 有值 9,047（合计 685,066）；downloads 有值 4,841（合计 20,502,713）。
- **缺失字段**：`npm`/`version` 4,817（49.7%）、`downloads` 系列 4,846（50.0%）、`stars` 640（6.6%）、`icon` 8,722（90.0%）、`capabilities` 2,116（21.8%）。
- 分类 23 个：ui 1,925 / tools 1,313 / session 729 / workflow 569 / dev 551 / usage 512 / model 498 / memory 426 / theme 369 / skill 343 / notify 329 / fun 325 / remote 280 / security 253 / browser 200 / vision 181 / git 179 / docs 176 / market 130 / voice 128 / identity 117 / wsl 87 / agi 67。
- `added` 全部可解析：最早 2026-08-13、最新 2026-11-08；近 7 天 1,213、近 30 天 5,274；逐日 10-31=182 / 11-01=171 / 11-02=208 / 11-03=171 / 11-04=222 / 11-05=238 / 11-06=195 / 11-07=156 / 11-08=231。
- capabilities 词表 top：fs-read 6,556 / fs-write 5,263 / env 5,257 / network 5,234 / shell 3,406 / credentials 897 / llm 796 / subagent 193。

### 2.4 页面 vs JSON 差异（可证伪的对账）

- 集合差：页面缺 **226** 条 + 页面多 **2** 条 → `9,463 − 2 + 226 = 9,687`，**分毫不差**。
- 缺的 226 条 `added` **全部是 2026-11-08**；多的 2 条是已下架/改名的历史条目（`ltmroberthk915/markpilot…`、`qiaohelenjoe/dsh-app…`）。
- 结论：`/browse/` 是 11-08 18:44 的 CI 快照，之后目录又并入 224 条（含下架 2 条）→ **页面不能当全量清单，会漏约 2.4% 最新条目**。

### 2.5 筛选条件与候选

- 关键词：7 类共 **141 个**中英文关键词（需求澄清 / 验收规划 / 实现测试复核 / 持续执行恢复 / 浏览器桌面 / 截图视觉 / 状态证据），逐条匹配 name+owner+中英简介。
- 命中：A 412 / B 1,156 / C 1,262 / D 1,560 / E 2,221 / F 653 / G 4,566；**跨类去重 7,138**（占 73.7%），命中 ≥2 类 3,325、≥3 类 1,072；并按"执行型 vs 提示词/技能/看板型"分档（CSV 7,138 行）。
- **必须说明的偏差**：G 类（状态/证据）召回太宽（几乎所有插件都写 session/memory/report）→ 只看作缩小范围，不作为结论；E/D 类夹杂大量桌宠/皮肤/通知噪声。**最终候选是按"真执行 + 与项目匹配 + 兼容性"人工收敛的**。

### 2.6 本次做到的层级（诚实边界）

| 层级 | 状态 |
|---|---|
| L1 完整目录筛查 | ✅ 完成（9,687 全量统计 + 三种去重 + 字段缺失 + 页面/线上对账 + 7 类初筛 + CSV） |
| L2 阅读作者文档 | ✅ 对**进入深度比较的 19 个候选**完成；其余 9 千余条**未读** |
| L3 检查源码/清单 | ✅ 对上述 19 个候选读 package.json/manifest/关键 README；tool-lens 与 feng 版 code-review 的 package.json 未取到（已在报告标注） |
| L4 实际运行验证 | ❌ **全部未做**（本轮只读，未安装任何候选） |

机器可读产出与脚本在 `.tmp/dsh-sel-20261109/`（`plugins_raw.json`、`stats.json`、`candidates.csv`、`probe.json`、`browse.html`、`audit.json` 等，可复现）。

---

## 3. 重点候选对比表（最终 19 个 + 淘汰理由）

> 详细 8 点分析见 `candidates/` 下两份深度报告。星数/下载量**只作辅助**。

### 3.1 流程 / 质量 / 持续执行（A 组）

| 候选 | 精确安装目标 | 类型 | DSH 0.2.2-rc.1 | 外部依赖 | 结论 |
|---|---|---|---|---|---|
| **dsh-doublecheck**（PerryLink） | `dsh-doublecheck@0.9.30` | **执行型**：3 tool + 2 command + 4 skill + 4 阶段闸门 | ✅ **唯一显式适配**（engines 含 `>=0.2.2-0`，README 11-05 适配 rc.1） | 零（复用内置 auto-review 判决，缺失则降级本地 reviewer） | **选** |
| Aegis（GanyuanRan） | `github:GanyuanRan/Aegis` | 提示型：只挂 skills 目录 + 启动注入，**0 tool** | ⚠️ 无 engines 声明 | 运行期无（doctor 需 python3） | 备选"读本"，不装 |
| superpowers-dsh（LayneChai） | `superpowers-dsh@0.5.0` | 提示型：14 个 skill | ⚠️ 无 engines | 无 | 淘汰（被 Aegis 覆盖） |
| loopx（loopx-project） | release `.tgz` | 执行型 | ❌ **硬阻断**（作者排除未鉴定 prerelease，安装器会拒 0.2.2-rc.1） | 重（Node 22.22+/pnpm/Python+pip/联网） | 淘汰（且与 goal+task_board+schedule 三重重复） |
| dsh-pua（MichengAI） | `@michengai/dsh-pua@1.0.8` | 执行型（host + Web UI） | ⚠️ 半确定（严格 semver 可能自挡） | 无 | 淘汰（与 auto-review + gate 重叠） |
| dsh-auto-continue | `dsh-client-auto-continue@0.17.4` | 执行型（hook + UI） | ⚠️ 未验证（没测 0.2.2） | 无 | 淘汰（goal 已覆盖续跑） |
| dsh-task-ledger（cq-guojia） | `dsh-task-ledger@0.1.10` | 提示型 + 看板 | ⚠️ 无 engines.dsh | 引非官方 `dsh-plugin-core` | 淘汰（task_board 更强） |

### 3.2 代码 / 测试 / 审查（B 组代码部分）

| 候选 | 精确安装目标 | 类型 | 兼容 | 外部依赖 | 结论 |
|---|---|---|---|---|---|
| **dsh-diff-approval**（9087） | `dsh-diff-approval@0.37.4` | 真执行 + Web 面板（Keep/Revert） | ✅ 无 engines 门禁；peer react 18 | 无 | **选**（注意 react peer 验证面板能渲染） |
| @feng0531/dsh-code-review | `@feng0531/dsh-code-review` | 真执行 + 7 工具（预览→确认→执行） | ✅ 直接写 0.2.2-rc.1 | 无 | 备选（**非商业许可**，商用需书面授权） |
| @michengai/dsh-code-review | `@michengai/dsh-code-review@1.0.8` | 真执行 + `/review` 子代理 | ✅ 验证过 rc.1 | 无 | 备选（Apache-2.0；与上面二选一） |
| dsh-test-autofix（raysnows） | `dsh-test-autofix@0.1.3` | 真执行（run_tests + 失败结构化） | ⚠️ 无 peer/engines（不可证） | 无 | 备选，先实测 |
| brooks-lint | `brooks-lint@1.9.1` | 纯 skill 包 + CLI | ⚠️ 仅按 0.2.1 验证过 | CI 模式需 key（不用） | 备选（**禁用 `/brooks-sweep`** 自动改码） |
| dsh-lsp-actions（PerryLink） | `dsh-lsp-actions@0.5.19` | 真执行（LSP 动作面） | ✅ 显式支持 | **需 pyright**（本机未装） | 备选（愿装 pyright 才值） |
| dsh-codegraph（jiangzhenguo） | `@jiangzhenguo/dsh-codegraph@1.2.2` | 真执行（包外部 CLI） | ✅ | **需 codegraph CLI**、改系统提示词 | 淘汰 |
| dsh-tool-lens | `@trench-xinxin/dsh-tool-lens` | 真执行（AST，自带第二套 Web UI） | ⚠️ 未验证 | npx 自起 127.0.0.1:3080 | 淘汰 |

### 3.3 桌面 / 视觉 / 浏览器（B 组桌面部分）

| 候选 | 精确安装目标 | 类型 | 关键事实 | 结论 |
|---|---|---|---|---|
| **dsh-computer-use-win**（Yu-tao-Li） | `dsh-computer-use-win@0.5.5` | 真执行：25 个工具 + MCP stdio + 常驻 PowerShell UIA | 不依赖 Windows-MCP 产品；**依赖 DSH 官方 MCP 桥**（当前 0 MCP 在跑，需验证）；Qt6 标准控件大概率可读可点，**`QGraphicsView` 画布图元读不到**；Esc 硬停止、`sent/observed` 两态、50 套回归测试 | **选（只读起步）** |
| dsh-vision-router（ysr666） | `dsh-vision-router@3.1.x` | 真执行：15 个 vision_* + 免 Key 云链 | 零 Key = OVHcloud 匿名端点（法国）；**必须联网、图片出境**、2 RPM/模型；`engines.node>=24.9`（PATH 22.20，但 DSH 自带 24.21 需确认） | **唯一视觉备选** |
| @anionex/dsh-vision-toolkit | `@anionex/dsh-vision-toolkit` | 真执行 | 免 Key = 作者自建服务 100 张/天/机；图片上传作者服务器；下 35MB Python | 不推荐 |
| dsh-browser（wqty123） | `dsh-builtin-browser@0.5.8` | 真执行（Electron/CDP） | 只管浏览器窗口，**对本地 PyQt 零帮助**；Desktop 需注入 app.asar bridge | 淘汰 |
| dsh-windows-mcp | — | — | 本轮未查到清单（时间/抓取限制） | 未评估 |

### 3.4 主要来源链接（均于 2026-11-09 抓取）

- 市场入口（静态页）：<https://dshmarket.com/browse/>
- 全量目录（真正数据源）：<https://awesome-dsh-plugin.com/plugins.json>
- 候选详情页示例：<https://awesome-dsh-plugin.com/p/PerryLink/dsh-doublecheck/>
- 作者仓库：<https://github.com/PerryLink/dsh-doublecheck>、<https://github.com/GanyuanRan/Aegis>、<https://github.com/PerryLink/dsh-lsp-actions>、<https://github.com/jiangzhenguo/dsh-codegraph>、<https://github.com/liustack/modlens>
- npm 元数据：`https://registry.npmjs.org/<包名>/latest`（engines/version 以此为准；**目录元数据会滞后于 npm**，例如 superpowers-dsh 目录写 0.4.0、npm 实际 0.5.0；dsh-task-ledger 目录 0.1.7、npm 0.1.10）
- 本机 modlens 文档：`C:\Users\20441\.dsh\profiles\desktop\node_modules\@liustack\modlens\README.zh-CN.md`（provider/故障转移/安全边界）

---

## 4. 当前已装组合：保留 / 调整 / 重复 / 不适合

| 处置 | 项目 | 理由 |
|---|---|---|
| **保留直接用** | dsh-ops、dsh-better-sidebar、dsh-context、dsh-git-graph、dsh-skill-explorer、dshmarket | 已在承担文件/终端/上下文/Git/技能/市场职责，无替代必要 |
| **保留直接用** | task-board | 卡片→真实会话 + cron + 验收门，是"任务规划/验收/定时"的底座 |
| **保留直接用** | cc-safety-net、dsh-rewind-plugin | 危险命令拦截 + 改后回滚，与新增的 diff-approval 互补（**改前看/改后撤**） |
| **保留但必须调整** | **@liustack/modlens** | 工具已加载但调用失败；修 provider（登录 Claude Code 或改 openai/local）。不修等于没有"眼" |
| **保留但需注意** | dsh-ops（engines 钉 `<0.2.3-0`）、dsh-context（兼容声明未覆盖 rc.1） | **不要贸然升级 DSH**，否则工具层可能直接消失 |
| **已装未启用（保持）** | dsh-pet 0.4.1、dsh-whale-widget 0.4.2 | 装饰类，启用只会增加界面噪声；若想清爽可考虑卸载（非必须） |
| **功能重复、建议择一** | 内置 `plugin-market` vs `dshmarket` | 前者 `indexes: []` 基本空转，保留 dshmarket 即可；不必卸载，但**不要两处都配索引** |
| **功能重复、不要新增** | loopx / dsh-pua / dsh-auto-continue / dsh-task-ledger / superpowers-dsh | 与 goal + task_board + agent-team + auto-review 重复；loopx 还硬不兼容 |
| **不适合本项目** | dsh-browser、dsh-codegraph、dsh-tool-lens、vision-toolkit、brooks-lint 的 sweep 功能 | 见第 3 节理由 |
| **兼容/实际状态未确定** | dsh-comp*（未装）、diff-approval 的 react 18 peer、computer-use-win 依赖的 MCP 桥是否可用、dsh-context 在 rc.1 的长期稳定性 | 见第 7 节 |
| **确有能力缺口、需要新增** | 流程纪律（doublecheck）、改动逐块确认（diff-approval）、真实 GUI 操作（computer-use-win） | 见第 5 节 |

---

## 5. 最终推荐组合（最小实用集）

### 5.1 组合清单

| 角色 | 组件 | 来源 | 负责什么 |
|---|---|---|---|
| 底座：文件/命令 | dsh-ops | 已装 | 读写文件、跑命令、搜索 |
| 底座：任务与验收 | task-board + 内置 goal | 已装/内置 | 卡片开真实会话、cron、验收门、续跑轮数上限 |
| 底座：并行与复核 | 内置 agent-team + subagent + workflow | 内置 | 派子代理查资料/写代码/独立复核 |
| 底座：安全与回滚 | cc-safety-net + dsh-rewind-plugin | 已装 | 危险命令拦截、整轮回退 |
| **流程纪律** | **dsh-doublecheck 0.9.30** | **新增** | 需求审讯 → 六维验收标准 → 红/绿测试证据 → 对抗评审 → 交付闸门（remind/warn/block 三档） |
| **改动确认** | **dsh-diff-approval 0.37.4** | **新增** | 每次改动逐文件/逐块 Keep / Revert（对 23 个脏文件尤其重要） |
| **桌面操作** | **dsh-computer-use-win 0.5.5（只读起步）** | **新增** | 读控件树/截图/OCR/点击/等待，真正驱动 X-AnyLabeling 窗口 |
| **视觉理解** | **@liustack/modlens 3.27.2（修配置）** | 已装 | 截图 → 结构化 OCR/版面/语义证据 |
| 备选（不默认装） | dsh-vision-router / @michengai(or @feng0531) dsh-code-review / dsh-test-autofix / dsh-lsp-actions | 市场 | 视觉零 Key 方案 / 独立代码审查 / 结构化测试 / 真 LSP |

### 5.2 彼此如何交接（一条需求怎么走完）

```
① 我提需求（自然语言）
   └─ 主会话：ask_user_question（内置）+ dsh-doublecheck 需求审讯
      → 产出：验收标准（六维 spec）+ 明确"什么算完成"

② 拆任务 / 排期
   └─ task-board 建卡（可 cron）或 内置 goal（长任务自动续跑，轮数有上限）
      细则走 openspec（项目既有流程），doublecheck 只登记验收维度

③ 实施
   └─ agent-team 派子代理 / 主会话直接改
      每次写入 → diff-approval 侧栏逐块 Keep / Revert
      改坏了 → rewind 整轮回滚（已装）

④ 跑测试（真跑，可追溯）
   └─ 固定命令：
      PYTHONPATH=.tooling\pytest-shim
      QT_QPA_PLATFORM=offscreen
      conda python -m pytest <目标文件> -q --basetemp=<仓库内绝对路径>
      → 失败进 doublecheck 的"红灯"，修复后才允许转绿
      → 失败信息若太吵，可用 dsh-test-autofix（备选）把它结构化

⑤ 实机界面验证（双轨）
   └─ 确定性轨（证据）：offscreen QWidget.grab() 截图 + Pillow 像素/尺寸断言
                          ffmpeg gdigrab / PowerShell CopyFromScreen 抓真窗口
   └─ 模型轨（解释）：modlens 读 1–3 张关键截图 → 结构化描述
   └─ 交互轨（可选）：computer-use-win 只读（列窗口/快照控件树/截图/等待），
                         确认无误后再做非破坏性动作（切窗口、开对话框）

⑥ 复核与交付
   └─ doublecheck /gate：红/绿证据 + 对抗评审 → deliverable 或 rework
      task-board 验收门通过 → 状态 done
      present 交付物 + reports/ 留证据（项目既有习惯）
      （可选）forge 建变更请求 / gh CLI 提 PR
```

### 5.3 这套组合怎么防止你担心的四件事

| 风险 | 谁负责拦住 |
|---|---|
| 无限重试 | 内置 goal 的 `max_goal_rounds` + doublecheck 的"warning/skip 永不翻转判决" + computer-use-win 的 Esc 硬停止/busy 锁 |
| 重复调度 | 只用一个任务入口（task-board / goal），**不装** loopx、auto-continue、pua 这类"再来一套续跑" |
| 未验证就宣布完成 | doublecheck `/gate`（无绿灯证据不能交付）+ task-board 验收门 + 我的交付前固定跑测试/截图 |
| AI 乱改看不懂 | diff-approval 逐块确认 + rewind 整轮回滚 + cc-safety-net 危险命令拦截 |

---

## 6. 具体配置方案 + 一次端到端验证方案（等待你批准后执行）

### 6.1 安装（3 个新插件）—— 只在 GUI 市场里点，或退出 DSH 后用 CLI

> 本机 `dsh plugin --profile desktop ...` 在桌面端运行时**会 EPERM 失败**（profile 被 Electron 独占）。两条可行路径：
> **A（推荐）**：DSH 界面 → 插件市场（dshmarket）→ 按包名搜 → 安装 → 重启 DSH。
> **B**：托盘右键**退出 DSH**，再执行：
> ```
> D:\DeepSeek Harness\resources\runtime\cli\bin\dsh.cmd plugin --profile desktop add dsh-doublecheck
> D:\DeepSeek Harness\resources\runtime\cli\bin\dsh.cmd plugin --profile desktop add dsh-diff-approval
> D:\DeepSeek Harness\resources\runtime\cli\bin\dsh.cmd plugin --profile desktop add dsh-computer-use-win
> ```

装完**重启 DSH**（不是刷新页面）。

### 6.2 配置修复（不改代码，只改配置）

1. **modlens（必做）**：二选一
   - 若你有 Claude 订阅：在终端跑一次 `claude` 完成登录（`~/.claude.json` 出现 `oauthAccount` 即成功）；
   - 或改用其他 provider：`modlens config set openai.baseUrl ... / openai.apiKey ... / openai.model ...`，或 `modlens config set provider local`（本地 Ollama/LM Studio，完全离线，但需要一套可用的本地视觉模型）。
   - **本机 `modlens doctor` 实测（2026-11-09，追加核查）**：node v22.20.0 ≥22.19 ✅、node:sqlite ✅；`claude-cli` ready=True（`C:\nvm4w\nodejs\claude.CMD`，**sign-in not verified**）、`kimi-cli` ready=True（`C:\Users\20441\.local\bin\kimi.EXE`）、`antigravity-cli` / `gemini-api` / `openai` / `anthropic` 全部 missing；`reuse.decisions.claude = granted`；`~/.modlens/config.json` **不存在**（等于没配过任何 provider）。
   - **关键追加发现（最省的一条路）**：本机 Kimi Code CLI **已登录**（存在 `C:\Users\20441\.kimi\credentials\kimi-code.json`），且其模型 `kimi-code/kimi-for-coding` 在 `config.toml` 里声明 `capabilities = ["video_in","thinking","image_in"]`（display_name Kimi-k2.6）→ **本来就有一套支持看图输入的订阅**。modlens 的 `kimi-cli` provider 正是"复用现有 Kimi Code 订阅、只在被点名时运行、绝不作为故障转移备选"。
     ⇒ 推荐先试：`modlens config set provider kimi-cli`（或单次 `-p kimi-cli`），零新增订阅/零 Key/零新插件；代价 15–45 秒/张、消耗 Kimi 订阅额度、图片上传到 `api.kimi.com`。
   - **次选（零新增订阅的另一条）**：DSH 当前走的 `commandcode` 通道里有 `z-ai/glm-5.3-flash`（原生多模态），可用 modlens `openai` provider 指到 `https://api.commandcode.ai/provider/v1`；但 key 存在 DSH 凭据库里（`refs: COMMANDCODE_API_KEY`），需先取出再配。
   - **Claude 路线不适用**：本机只装了 Claude Code（2.1.177）、**没有订阅、未登录**（`~/.claude.json` 无 `oauthAccount`），`claude-cli` 不可用。
   - 验收：`modlens doctor --json` 报告 provider ready；新会话里 `modlens_read_image` 读一张 `.tmp/dsh-sel-20261109/offscreen-probe.png` 不再报错。
2. **测试环境变量（必做，写入启动脚本或 setx）**：
   ```
   setx PYTHONPATH "D:\X-AnyLabeling-4.2.1\.tooling\pytest-shim"
   setx QT_QPA_PLATFORM "offscreen"
   ```
   （`PYTHONPATH` 会与其它用途冲突时，改成每次命令前缀设置更安全。）
3. **doublecheck 初始强度**：先用默认 `remind`，不直接上 `block`，跑顺 2–3 次后再考虑 `warn`。
4. **computer-use-win**：首轮只读；`vision_screenshot` 类截图工具保持默认关闭（避免两套截图源）。
5. **不新增**：不要同时装两个 review 插件、不要同时装 vision-router 与 modlens（三个视觉桥互斥）。

### 6.3 端到端验证方案（一次真实的小需求，全程留证据）

> 建议第一次验证用一个**只改 UI 文案/加一个只读提示**的需求（低风险、可回退）。

| 步 | 做什么 | 通过标准（证据） |
|---|---|---|
| 1 | 我提需求：「在 Inspector 对话框某个按钮旁加一行提示文字」 | doublecheck 追问 ≤3 个问题并给出六维验收标准 |
| 2 | 生成任务卡/目标 | task-board 出现卡片（或 goal 建立），含验收条件 |
| 3 | 实施改动 | diff-approval 侧栏出现待审块，可逐块 Keep/Revert；我确认只保留预期块 |
| 4 | 跑测试 | `test_inspector_dialog.py`（21 个）+ 相关 settings 测试全绿；输出留档（耗时/结果） |
| 5 | 截图验收 | offscreen `QWidget.grab()` 出 PNG；Pillow 断言关键区域像素/尺寸变化符合预期；modlens 读图描述与预期一致 |
| 6 | 可选真机 | computer-use-win 只读：列出窗口、快照控件树（报告哪些能读/哪些是画布）、截图路径；**不点击** |
| 7 | 交付 | doublecheck `/gate` 给出 deliverable（非 rework）；`present` 交付报告 + 截图证据；task-board 卡片 done |

**预期耗时**：第 1 次约 20–40 分钟（含熟悉插件交互），之后每次 5–15 分钟。

### 6.4 已知会踩的坑（先写在这，省你一次）

1. **测试命令不带头就会假失败**：必须 `PYTHONPATH=.tooling\pytest-shim` + `--basetemp=<仓库内绝对路径>`（相对路径或系统 temp 都会触发沙箱 ACL 报错）。
2. **`test_inspector_dialog.py` 的 21 errors**：**不是 bug**。用 6.1 的命令实测 **21 passed / 54.35s**。
3. **`ops_write_file`/`ops_stat`/`ops_diff` 在本环境恒 `PUBLICATION_DENIED`**：改文件用原生 `write`/`edit` 即可（我本次报告就是这么落盘的）。
4. **`ops_bash` 并发会坏**：同时开多个子代理时只允许一个跑命令；报 `EXECUTOR_UNAVAILABLE` 就等 30 秒重试。
5. **桌宠类插件已装未启用**：不用管，别顺手启用。
6. **不要一次合并跑大目录**：`test_canvas + test_inspection + test_settings` 合跑超过 20 分钟无输出（疑似 GUI 用例互相影响/挂起），**逐文件或逐子目录跑**（单文件 2–55 秒）。

---

## 7. 未确认事项及其对推荐的影响

| # | 未确认 | 影响 | 若为坏结果怎么办 |
|---|---|---|---|
| 1 | dsh-doublecheck 在 0.2.2-rc.1 的真实加载/工具注册**未实测**（本轮只读） | 若加载失败，流程层等于没补 | 作者已声明适配 rc.1 且 engines 匹配，概率低；失败就回退到 Aegis/纯 skill 方案 |
| 2 | dsh-diff-approval 的 `react ^18.2.0` peer 与本机宿主是否匹配（面板能否渲染）**未实测** | 面板不渲染=只剩命令语义 | 改用 rewind + git 手工 diff；或换 dsh-review-checkout 类 |
| 3 | computer-use-win 依赖 **DSH 官方 MCP 桥**，而当前 **0 个 MCP 在跑**（`dsh-mcp-client` 在 asar 但未挂载） | 若是必需且桥不可用，桌面操作装了个空壳 | 先只读验证一次；不行就退回"offscreen pytest + 截图 + Pillow 断言 + 人工看图" |
| 4 | Qt6/PyQt6 在 Windows UIA 下**实际暴露哪些控件**未实测 | 标准控件可读可点、画布图元读不到（推断）；若连标准控件都读不到，价值大减 | 同上；或改用坐标点击 + 截图（但更脆弱） |
| 5 | modlens 修好后 **provider 可用性**（Claude 订阅/本地模型质量） | 视觉链路能否自证 | 退到 vision-router（联网、图片出境）或人工看图 |
| 6 | vision-router 的 `engines.node>=24.9` 与本机 PATH 22.20 冲突（DSH 自带 24.21） | 若用宿主 node 解析则装不上 | 仅作备选，装前确认 |
| 7 | 全量测试基线**未建立**：本次分别验了 `test_settings`（7 passed）、`test_canvas`（71 passed / 1 failed 像素断言）、`test_inspector_dialog`（21 passed）；**三个目录合并运行超过 20 分钟仍无输出（疑似 GUI 用例相互影响/挂起），已终止** | "全绿"暂时不能作为硬门槛 | 用"目标文件子集 + 已知失败清单"作为闸门，**逐文件/逐子目录运行，不要一次合并大目录** |
| 8 | doublecheck 的六维 spec 与项目 `openspec/` **概念重叠** | 可能两份规格打架 | 约定：openspec 出正文，doublecheck 只登记验收维度与证据 |
| 9 | dsh-context 兼容声明未覆盖 rc.1；dsh-ops 钉死 `<0.2.3-0` | **升级 DSH 会破坏当前工具层** | 升级前先备份 profile（已有 `.backup-*`），并等插件跟版 |

---

## 8. 执行清单（A/B 已于 2026-11-09 11:12–11:30 执行，详见 execution_log.md）

### A. 新增安装（3 个）—— ✅ 已全部安装
- [x] `dsh-doublecheck` **0.9.30**（已入 dependencies + bundles，技能已热加载）
- [x] `dsh-diff-approval` **0.37.4**（同上，面板技能已出现）
- [x] `dsh-computer-use-win` **0.5.5**（同上；`wincu` 健康检查实测通过）
- ⏳ 需**重启 DSH** 才能确保 3 个 bundle 完整加载

### B. 配置修复（2 项）
- [ ] **B-1 修 modlens provider —— 阻塞**：Claude 未登录（无订阅）、Kimi 无订阅且 modlens spawn 报 EPERM、其余 provider 无 Key。等用户从 5 个方案里选 1 个（免费 Gemini Key / dsh-vision-router / 本地模型 / 不配视觉 / 切 GLM-5.3-Flash 试）
- [x] **B-2 固定测试环境 —— 完成（改用包装脚本）**：新增 `.tooling/dsh-pytest.cmd` 与 `.tooling/dsh-pytest.sh`，内置 `PYTHONPATH=pytest-shim`、`QT_QPA_PLATFORM=offscreen`、`--basetemp=<仓库>/.tmp/pytest-bt`；实测 `7 passed in 2.12s`。**未使用全局 setx**（避免污染其他 Python 程序/让手动启动的 GUI 变不可见）

### C. 可选（按需，非默认）
- [ ] `@michengai/dsh-code-review` 或 `@feng0531/dsh-code-review`（二选一；后者非商业许可）
- [ ] `dsh-test-autofix`（先实测能否注册工具）
- [ ] `dsh-lsp-actions`（需先 `npm i -g pyright`）
- [ ] `dsh-vision-router`（仅在 modlens 修不好时；介意图片出境就不要）
- [ ] 卸载 `dsh-pet` / `dsh-whale-widget`（纯清爽，非必须）

### D. 不做（已裁决）
- 不装 loopx（硬不兼容）、dsh-browser、dsh-codegraph、dsh-tool-lens、dsh-pua、dsh-auto-continue、dsh-task-ledger、superpowers-dsh、vision-toolkit。
- 不同时装两套流程系统、两套视觉桥、两套代码审查。

### E. 回滚预案
- profile 已有 `.backup-20261103-*` / `.backup-manual-*`；安装前再手动复制一份 `C:\Users\20441\.dsh\profiles\desktop\package.json` + `cordis.patch.yml`。
- 卸插件：GUI 市场里卸载，或退出 DSH 后 `dsh plugin --profile desktop remove <name>`。

---

## 9. 证据与产出索引

| 文件 | 内容 |
|---|---|
| `dsh_selection_20261109/execution_log.md` | **执行记录**：A（3 个插件安装）与 B（modlens 阻塞 / 测试脚本）的实际命令、结果、回滚办法 |
| `dsh_selection_20261109/catalog_scan.md` | 全目录遍历（440 行）：数据源、页面/JSON 对账、9687 条统计、7 类筛选、证据层级 |
| `dsh_selection_20261109/env_audit.md` | 环境审计（250 行）：18 行插件主表、四层结论、工具来源映射、11 项冲突/风险、7+1 环节缺口、18 条一手证据 |
| `dsh_selection_20261109/project_recon.md` | 项目勘察（503 行）：技术栈、规模、测试实测、证据惯例、界面验证可行路径 |
| `dsh_selection_20261109/deep_process.md` | A 组深度核查（540 行）：7 候选 8 点、停止/恢复横向对照、重复矩阵、排序 |
| `dsh_selection_20261109/deep_code_vision.md` | B 组深度核查（571 行）：12 候选 8 点、同名冲突矩阵、视觉/桌面两条链裁决 |
| `.tmp/dsh-sel-20261109/` | 原始数据与可复现脚本（plugins_raw.json、stats.json、candidates.csv、probe.json、browse.html、audit.json、bundles_sel.txt 等） |

### 本轮一手实测记录（便于复核）

1. `dsh --version` → **0.2.2-rc.1**
2. `pytest tests/test_settings/test_schema.py` → **7 passed in 4.23s**
3. `QT_QPA_PLATFORM=offscreen pytest tests/test_canvas/` → **1 failed, 71 passed**（失败为离屏字体/尺寸断言 `179 != 139`）
4. `pytest tests/test_inspection/test_inspector_dialog.py`（默认）→ **21 errors**（沙箱 temp/ACL）
5. 同文件 + `PYTHONPATH=.tooling\pytest-shim` + `--basetemp=<仓库内绝对路径>` → **21 passed in 54.35s** ✅
6. `git status --porcelain | wc -l` → **23**
7. `modlens_read_image` → **失败**（claude-cli provider，根因未登录）
8. `plugin_manager list_plugins` → **222 条** loader 条目；dsh-pet / dsh-whale-widget 不在启用列表
9. `dsh plugin --profile desktop list` → **EPERM（package.json.lock）**，CLI 不能管 desktop profile
10. 市场：`/browse/` 9463 条静态页 vs `plugins.json` 9687（快照）/9714（复核）

---

## 10. 追加核查：`dsh-plugin-teamflow`（2026-11-09 追加，用户点名）

> 该插件**不在原初筛候选表**里（关键词"team/flow"未命中 A–G 的强规则），本轮按用户点名补充核查。

| 项 | 事实 | 证据 |
|---|---|---|
| 身份 | owner **MichaelShii**，npm `dsh-plugin-teamflow` **0.3.3**，MIT，★18，30 天下载 2,916，收录 2026-10-17 | 【源码发现】package.json + 市场页 |
| 类型 | **真执行**：12 个 `teamflow_*` 工具 + `ctx.typert.register` 远程方法 + 浏览器侧工作台（会话内 tab + 全局侧栏面板 + 右栏 run 详情）+ 磁盘 backlog（`$DSH_HOME/teamflow/`） | 【源码发现】 |
| 能力 | 需求 → 分诊 → PRD → 设计 → 技术方案 → **并行开发（默认 3 并发，最多 8）** → QA（P0–P2 缺陷打回，**≤2 轮**）→ 验收；防假交付（要求 `[Verification evidence]`：命令+退出码+断言数）；断点续跑；完成后回报 | 【作者声明】README |
| 兼容 | `engines.dsh = ">=0.2.1-rc.5 <0.3.0"`、`engines.node >=22.18` | 【源码发现】 |
| **兼容风险** | 按严格 semver 的 prerelease 规则（版本带 prerelease 时，必须存在**同一 x.y.z 元组**且带 prerelease 的比较子才算匹配），`0.2.2-rc.1` 的元组是 0.2.2，而范围内唯一的 prerelease 比较子是 `0.2.1-rc.5` → **很可能被判为不满足而被跳过**；作者 README 明确写该字段是**真门禁**（`evaluatePluginCompatibility` 会 skip 并报 `skippedBundles`），可用 `dsh plugin allow-version` 豁免。**未实测** | 【源码发现】+【推断】 |
| 侵入性 | 会往项目里写 `docs/teamflow/`、往 `AGENTS.md` **追加受管区块**、每次运行**自动产生一个提交**（代码+任务目录）；backlog 落在 `$DSH_HOME/teamflow/` | 【作者声明】 |
| 运行前提 | README 写 **web profile**（浏览器侧工作台）；桌面端每个 profile 各装一次；且明确"`teamflow_start` 之后主线程不要自己改代码/跑验证"——实现与验收都交给流水线子代理 | 【作者声明】 |

**裁决：不必要，且当前不建议安装。** 四条理由：
1. **与已有能力三重冲突**：内置 `agent-team`（并行子代理）+ `task_board`（卡片/看板/验收门）+ 拟装的 `dsh-doublecheck`（证据闸门）已经覆盖同一个"需求→实现→QA→验收"链条；再装 = **第二套任务板 + 第二套真相源**，出问题时分不清谁说了算。
2. **使用模型与你相反**：它要求"主线程不自己干活，全部交给流水线子代理"；而你要的是"我在一个会话里提需求，agent 直接改、直接跑测试、直接截图验收"。两者会打架。
3. **对脏仓库有风险**：你的工作区有 23 个未提交改动（其中 97% 是生成物），它会自动提交并改 `AGENTS.md`，一次误提交就可能把你的改动搅进去。
4. **兼容可能直接被跳过**（见上表 semver 分析），且它是为"从零做完整产品"设计的水瀑流水线，对"改一个既有功能/修一个 bug"过重（虽有 patch/lite 档）。

> 如果你将来想做"从零起一个新项目/大改版"，它可以作为**项目级**流水线单独试（先 `allow-version` 豁免 + 在干净分支/worktree 上跑）；但它不该进当前这套日常组合。
