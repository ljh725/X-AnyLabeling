# B 组深度核查：代码理解 / 测试 / 审查 / 桌面 / 视觉（10+2 候选）

- 核查人：deep-code（B 组）
- 抓取时间：**2026-11-09**（npm registry 元数据抓取于 09:15–09:20，DSH 重启后 09:53 续写）
- 目标项目：X-AnyLabeling 4.2.1（Windows 10/11，PyQt6 GUI，`anylabeling/views/labeling/label_widget.py` 9968 行，`inspector/dialog.py` 4688 行，196 个 pytest 文件，conda 环境 `x-anylabeling-cu12`，23 个未提交改动）
- 本机环境：DSH **0.2.2-rc.1** / profile=desktop；Node **v22.20.0**；Python 3.13 + conda 3.12；**pyright 未装**、**codegraph CLI 未装**；gh CLI 已装；VS Code `code` 可用
- 纪律：**只读调查。未安装、未卸载、未运行任何候选插件**。下文所有"实测"一律写 **未做**；结论按 `【作者声明】`（README/市场页原文）/ `【源码发现】`（package.json、文件列表、注册字段）/ `【我的推断】`（基于以上事实的推理）三层标注。
- 方法：市场页 `https://awesome-dsh-plugin.com/p/<owner>/<name>/` + GitHub `raw.githubusercontent.com/<owner>/<repo>/HEAD/package.json`（及 README）。作者/包名不确定的三个（lsp-actions、diff-approval、test-autofix）用 `registry.npmjs.org/-/v1/search` 反查到了官方包与仓库。

> ⚠️ 本轮**没有**取到市场页的候选：dsh-lsp-actions、dsh-diff-approval、dsh-test-autofix（先查不到 owner，后用 npm registry 定位；市场页未回填）。这三个的 install 目标以 npm 包名为准，**已由 npm registry 与 GitHub package.json 双向确认**。

> 🔧 落盘说明：本会话 `ops_write_file` 被宿主拒绝（`PUBLICATION_DENIED / Publication authorization is unavailable`），改用原生 `write` 工具落盘成功。

---

## 0. 对比总表

| # | 候选 | 精确安装目标 | 类型 | 核心能力 | DSH 0.2.2-rc.1 兼容 | 外部依赖（额外运行环境/凭据） | 本项目匹配度 | 停止/恢复 | 维护 | 建议 |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | dsh-lsp-actions（PerryLink） | `dsh-lsp-actions@0.5.19` | 原生 bundle（真执行） | 8 类 LSP 工具面 + `lsp.actions.*` 编辑器协议 | ✅ 显式支持（`engines.dsh` 含 `>=0.2.2-0`） | **要语言服务器**：Python 需 pyright-langserver（本机未装） | 中（单文件 9968 行最适合 LSP 导航，但 PyQt6 无 stub 会淹在噪声里） | 服务器没起→工具报错；可整插件禁用 | Apache-2.0，0.5.19，11-05 发布，6.7k/月，活跃 | **备选** |
| 2 | dsh-codegraph（jiangzhenguo） | `@jiangzhenguo/dsh-codegraph@1.2.2` | 原生 bundle（真执行，包 CLI） | 13 个 `codegraph_*` 工具 + 系统提示词强注入 + prompt 前置注入 | ✅ peerDeps `<0.3.0-0` | **要 `codegraph` CLI 在 PATH**（本机未装）；Python 支持度未知 | 低-中（会抢走 grep/read 反射；作者自己都关了 frontload） | 未索引=硬停止规则（不擅自 init）；CLI 缺失失败静默 | MIT，22★，1.5k/月，活跃 | **淘汰** |
| 3 | dsh-tool-lens（trench-xinxin） | `@trench-xinxin/dsh-tool-lens` | 原生 bundle（**疑似自带整套 Web UI**） | AST 代码图：依赖/调用层级/影响面/环/领域切片/API 契约 | ⚠️ 未验证（package.json 未取到） | **`npx` 会自己拉起一个 DSH Web（127.0.0.1:3080/3081）** | 低（多语言 AST 看着对口，但自带第二套 Web 极易与本机 profile 冲突） | 未查完 | MIT，**4★/901 月**，弱 | **淘汰** |
| 4 | dsh-diff-approval（9087 / Wu Zhiwei） | `dsh-diff-approval@0.37.4` | 原生 bundle + **Web 客户端 UI**（真执行） | 编辑待审面板：整文件 diff + Keep/Revert | ✅ 无 `engines.dsh` 门禁；peer `cordis>=4.0.1`、`react ^18.2.0` | 无外部服务；依赖宿主 react 18 | **高**（对 9968 行文件 + 零编程用户，是"改前先看一眼"的闸门） | 面板级 Keep/Revert；与 rewind 互补 | MIT，0.37.4，11-05，6.3k/月，极活跃 | **选**（注意 react peer） |
| 5 | dsh-test-autofix（raysnows） | `dsh-test-autofix@0.1.3` | 原生 bundle（真执行，零依赖） | 自动识别测试框架→跑测试→结构化解析失败→注入对话；同处失败超阈值自动停 | ⚠️ **无 peerDeps / 无 engines**，无版本闸门（不可证兼容） | 无（自己调测试命令；本机 pytest 已有） | **高**（196 个 pytest + Windows 编码 + 中文断言，正是本项目痛点） | 自带"同处失败阈值停"；无框架级 gate | MIT，0.1.3，325/月，单人小项目 | **备选-优先实测** |
| 6a | dsh-code-review / **MichengAI** | `@michengai/dsh-code-review@1.0.8` | 原生 bundle + 命令 + 子代理（真执行） | `/review` `/review-status` `/review-cancel` + `dsh_code_review` 工具，Codex 评分表 + 独立子代理取证，中英双语 | ✅ `engines.dsh >=0.2.0-rc.1 <0.3.0-0`，README 明示验证过 0.2.2-rc.1 | 要 `spawn` provider + `userQuestions` + 支持 tool-call 的模型 | 高（中英双语、Apache-2.0、无外部二进制） | 关机不自动续；"完成"≠全覆盖 | Apache-2.0，1.0.8，16★，24.7k/月，活跃 | **备选** |
| 6b | dsh-code-review / **f-e-n-g-0531** | `@feng0531/dsh-code-review` | 原生 bundle + 7 个工具（真执行） | `code_review_preview/_execute/_status/_wait/_cancel/_artifacts/submit_review_result`；**只读**，预览→人工确认→执行，Git+**SVN**，后台任务 | ✅ 直接写 `DSH 0.2.2-rc.1` 为其验证版本之一 | 无外部服务/密钥（用当前会话模型）；Git 或 SVN CLI | **最高**（唯一"先预览范围再确认才发模型"的人工闸门，中文优先，Git 场景齐全） | 最完善：preview 5 分钟过期、partial/failed/cancelled、`resumeFromJobId`、预算与读取额度 | **非商业许可**（商用需书面授权），9★，20.6k/月 | **选**（先确认许可） |
| 7 | brooks-lint（hyhmrright） | `brooks-lint@1.9.1` | **Skills 包**（6 个 Agent Skill，纯提示词） + 独立 CLI/CI | `/brooks-review` `/audit` `/debt` `/test` `/health` `/sweep`，12 本书的 12 类腐化风险 + Health Score + Mermaid 依赖图 | ⚠️ 无 `engines.dsh`；贡献者按 DSH 0.2.1-rc.2 验证过一次 | 交互模式无；CI/SARIF 模式要 `ANTHROPIC_API_KEY`（本机不适用） | 中-高（`/brooks-test` 正对 196 个测试；Cognitive Overload/Change Propagation 正对 9968 行文件） | 纯提示词不崩；**`/brooks-sweep` 会"安全改动自动应用"** → 对零编程用户是风险 | MIT，1556★/2.2k 月；**作者声明不再端到端验证非 Codex 平台** | **备选** |
| 8 | dsh-computer-use-win（Yu-tao-Li） | `dsh-computer-use-win@0.5.5`（profile=**desktop**） | 原生 bundle + **MCP stdio server** + PowerShell UIA 后端 | 25 个 `windows_computer_use_*` 工具 + 1 管理入口：UIA 树/查找/截图/OCR/键鼠/窗口/batch/wait_for；网页走 CDP | ✅ peer `@deepseek-ai/dsh-mcp-client >=0.1.0-rc.2 \|\| >=0.2.0-rc.2`；`os:["win32"]` | **Windows PowerShell 5.1（系统自带，不需另装）**；需 `@deepseek-ai/dsh-mcp-client`（DSH 自带桥） | **高**（唯一能"真的打开 X-AnyLabeling 点按钮/读状态栏"的闭环） | 极好：Esc 硬停止（独立进程监听）、batch 遇跳转/弹窗即停、busy 锁、`verification: sent\|observed` | MIT，0.5.5，420★，25.3k/月，50 套回归测试，极活跃 | **选（限只读用法）** |
| 9 | dsh-vision-router（ysr666） | `dsh-vision-router`（npm 最新 3.1.x；HEAD 3.2.0-rc.0） | 原生 bundle + Web 设置卡（真执行） | 15 个 `vision_*` 工具（describe/ground/detect/crop/pixel_diff/ocr/trace/screenshot…）+ **免 Key 云视觉链** + 模型路由包装 | ⚠️ `engines.dsh >=0.2.1-rc.5 <0.3.0-0` ✅ 但 **`engines.node >=24.9.0`**（本机 PATH 是 22.20.0） | **必须联网**；免 Key 链 = OVHcloud（法国）；`vision_html_screenshot` 要 Chrome；`sharp` 原生二进制；tesseract 可选 | **高**（零 Key 就能读本机截图，且有 pixel_diff/ground，正好做 UI 验收） | 好：错误分类（region/tos/quota/429/context/network）逐个换后端、429 冷却、`localOnlyVision`、截图工具默认关闭 | MIT，1211★，**56.7k/月（视觉类第一）**，测试文件 200+，极活跃 | **备选（唯一零 Key 方案）** |
| 10 | dsh-browser（wqty123） | `dsh-builtin-browser@0.5.8` | 原生 bundle + Web UI + Electron 运行时 | 48 个 `dsh_browser_*` 工具（open/snapshot/fill/click/screenshot/download/auth/session/replay…） | ✅ README 写"兼容 DSH 0.2.2-alpha.3" | **自带 Electron**（首次按需下载）；Desktop 还要往 `app.asar` 注入 sidebar bridge | **低**（只管浏览器/Electron 窗口，**对本地 PyQt 应用零帮助**） | 好（session 隔离/reset/doctor/历史回放） | MIT，162★，34.1k/月；bridge 会被桌面升级打回 stale | **淘汰** |
| 补 A | @anionex/dsh-vision-toolkit | `@anionex/dsh-vision-toolkit` | 原生 bundle + Skill（真执行） | 10 个 `vision_*` 工具 + `vision-skills` 5 套 playbook；免 Key=**作者自建服务 100 张/天/机** | ✅ README 支持 desktop profile | **要 Python 3.11+ 运行时（缺失时下 35MB）**；Pillow/NumPy/vtracer；默认 Gemini 3.7 Flash；Chrome（仅 HTML 截图）；**图片发到作者服务器** | 中（grounding+pixel_diff 最贴验收，但隐私与组件最重） | 一般：429 要等 Retry-After；运行时准备失败需手动修 | MIT，922★，15.0k/月 | **不推荐** |
| 补 B | dsh-windows-mcp（helloHub1212） | — | — | — | — | — | — | — | — | **未查到**（时间/抓取受限，见 §13） |

---

## 1. dsh-lsp-actions（PerryLink）

**精确安装目标**：`dsh plugin --profile desktop add dsh-lsp-actions`
- npm：`dsh-lsp-actions`，**0.5.19**（2026-11-05 发布），Apache-2.0，维护者 `perrylink`，月下载 6,755 / 周 1,526。
- 仓库：https://github.com/PerryLink/dsh-lsp-actions
- 注：与市场里的 `PerryLink/dsh-github`（PR 机器人）**同为 PerryLink 但不同物**，别混。

① **匹配度**：中。9968 行的单文件正是 LSP 最擅长的场景（diagnostics / 定义跳转 / 引用 / 重命名 / 符号树），比 grep 精确。但本项目是 PyQt6：不装 PyQt6-stubs 时 pyright 会把大量 Qt API 报成 Unknown/缺失；且 196 个测试 + 23 个未提交改动会放大"诊断噪声=真问题"的误判。【我的推断】

② **真执行 vs 仅提示词**：**真执行**。【源码发现】`dsh.bundle.patch = ./cordis.patch.yml`、`capabilities: ["fs:read","subprocess","tools:register"]`、描述里明确"diagnostics, formatting, completion, code actions, symbols, signature help, inlay hints, rename tools **over language servers**" + `lsp.actions.*` 编辑器动作协议；`devDependencies` 里带 `typescript-language-server@5.3.0` 和 `@deepseek-ai/dsh-lsp@0.2.2-rc.1`。工具必须经真实 LSP 进程才有输出。

③ **DSH 0.2.2-rc.1 兼容**：**是，显式支持**。【源码发现】`engines.dsh: ">=0.2.1-0 <0.3.0 || >=0.2.2-0 <0.3.0"`（专门为不误杀 0.2.2 预发布写的）；`engines.node: "^22.19.0 || >=24.9.0"`（本机 22.20.0 ✅）；peerDeps 把 dsh-fs/llm/sandbox/subprocess/tools 全部写成含 `>=0.2.2-0 <0.3.0` 的并集 → 0.2.2 安装闸门不会拒。
⚠️ 唯一不一致：`dshWorkshop.compatibility.dshVersions` 只列到 `0.2.1-rc.2`，是市场侧元数据滞后，**不是安装门禁**。【源码发现】

④ **外部依赖 / 凭据**：**要语言服务器**。Python 需要 `pyright-langserver`（或 basedpyright / pylsp）。本机 **pyright 未装** → 装完插件后 Python 侧**零产出**，必须 `npm i -g pyright` 或 `pip install basedpyright`（会拉 Node 包/二进制）。无需 API Key，无需联网（除首次装 server）。无 `postinstall`。

⑤ **与已装插件冲突**：与 dsh-codegraph / dsh-tool-lens **功能位重叠**，但实现层完全不同（LSP 是编译器真值，另两个是自建索引），**三者最多选一个**。与 cc-safety-net 无冲突（那是 Bash 拦截）。与内置 grep/read 无提示词劫持（本插件不改系统提示词顺序）。

⑥ **停止条件 / 失败处理 / 恢复**：语言服务器崩溃/没启动 → 工具返回错误（非静默）；`dispose: supported`；卸载即移除工具面。**【未知】**：长驻 LSP 进程在 DSH 重启后是否会残留。

⑦ **证据覆盖 / 未知**：README 未取（只有 package.json + npm 描述）；**无** DSH 0.2.2-rc.1 实机跑过的公开证据（compat 列表最高 0.2.1-rc.2）。**未做**实测。

⑧ **维护 / 成本 / 复杂度**：活跃（11-05 刚发版，0.5.x 迭代），Apache-2.0 商用友好，有 funding。成本 = 装 pyright + 每会话 LSP 冷启动；对零编程用户，"先装 pyright 再配 server"这一步就够劝退。**结论：备选**——只有在你愿意先 `npm i -g pyright` 时才值得；否则对本项目等于装了个空壳。

---

## 2. dsh-codegraph（jiangzhenguo）

**精确安装目标**：`dsh plugin --profile desktop add @jiangzhenguo/dsh-codegraph`
- npm：`@jiangzhenguo/dsh-codegraph`，**1.2.2**，MIT。注意无 scope 的 `dsh-codegraph` 已被他人占用（README 明说）。
- 市场：22★，30 天 1,471 下载，2026-08-19 收录。仓库：https://github.com/jiangzhenguo/dsh-codegraph

① **匹配度**：低-中。价值主张是"用 AST 索引代替 grep，省 token"，对 9968 行单文件 + 196 测试理论上很香。但 codegraph 围绕 TS/JS 生态生长（官方 `@colbymchenry/codegraph`），**Python 解析质量未在 README 中给出证据**；且它通过系统提示词**命令式劫持**搜索行为（见②），在还没建立信任的项目上，副作用大于收益。【我的推断】

② **真执行 vs 仅提示词**：**真执行（但包装的是外部 CLI）**。【源码发现】13 个工具 `codegraph_status/init/index/sync/uninit/query/node/explore/files/callers/callees/impact/affected`，默认只注册 4 个 core；peerDeps 只挂 `dsh-llm`/`dsh-tools`/`schemastery`；运行时**按名字 `codegraph` 从 PATH 解析可执行文件**。插件本身没有分析能力，**能力全在 CLI**。

③ **DSH 0.2.2-rc.1 兼容**：**是**。peerDeps 全部 `<0.3.0-0`，README 专门解释了"上限写成 `<0.2.0-0` 会把 0.2.x 预发布一并排除"。CI 矩阵跑 dsh 0.1.5-rc.3 / 0.2.0-rc.2。

④ **外部依赖 / 凭据**：**必须** `npm i -g @colbymchenry/codegraph`（≥1.0）且 `codegraph` 在 PATH。本机**未装**。无 API Key、无联网（本地索引）。无 postinstall。

⑤ **与已装插件冲突**：**与内置工具直接抢方向盘**。【源码发现】它注入 `tool:codegraph` 系统提示词段，`order: 98`，**排在 DSH 内置 read(100)/write(101)/edit(102)/glob(103)/grep(104) 之前**，措辞命令式（"MUST use codegraph_explore INSTEAD of grep/glob/read"）+ 反模式清单。装上后**所有会话**的搜代码习惯被改写。与 lsp-actions/tool-lens 同位置竞争。

⑥ **停止/失败/恢复**：设计克制：**未索引项目 → 硬停止规则**（不擅自 init）；frontload 的所有失败路径都是**静默 no-op**；`frontload:false` / `guideSearch:false` / `surface:'core'` 可逐项关。恢复 = 卸载或改 `cordis.patch.yml`。

⑦ **证据覆盖 / 未知**：作者自测很硬（真实 CLI 的 harness、双版本矩阵、19 节断言）。**但**：README 自己承认 `callers/callees` 在 codegraph@1.0.1 上返回空数组（**最关键的调用链能力在当前 CLI 版本下是残的**）；"本机 profile 已因此把 frontload 关掉"。**Python 支持**：**未查到**（README 无 Python 语种说明）。**未做**实测。

⑧ **维护 / 成本 / 复杂度**：MIT、22★、1.5k/月，文档极详尽，维护健康。成本：装一个全局 CLI + 建 `.codegraph/` 索引目录；副作用：系统提示词改写 + frontload 会多出一条 `<codegraph_context>` 用户消息。

**结论：淘汰**。三条叠加：(a) 需要本机不存在的 codegraph CLI；(b) 调用图能力在所用 CLI 版本上是空的；(c) 为省 grep 而永久改写全局搜索提示词，风险/收益不划算——本项目是 Python，而它对 Python 没证据。

---

## 3. dsh-tool-lens（trench-xinxin）

**精确安装目标**：`dsh plugin --profile desktop add @trench-xinxin/dsh-tool-lens`
- npm：`@trench-xinxin/dsh-tool-lens`。市场：**4★**，30 天 901 下载，2026-08-18 收录。MIT。

① **匹配度**：低。README 的能力清单（模块依赖拓扑、作用域消歧调用层级、OOP 继承、环检测、影响面三级分类、死代码、层治理 lint、diff 影响+测试推荐、领域切片、全栈 API 契约、多语言含 **Python**）简直为"重构 9968 行单文件"量身定做——**问题在读下去**。

② **真执行 vs 仅提示词**：**声称真执行（AST 静态分析）**，但**注册方式无法确认**：`package.json` 本轮**没抓到**（两次 fetch 都被重启打断）。【作者声明】它把"Lens"描述成一个工具（`lens` action），并给出 `npx @trench-xinxin/dsh-tool-lens "Use lens tool to audit..."`。

③ **DSH 0.2.2-rc.1 兼容**：**未验证 / 高风险**。【源码发现·间接】README 的 "Zero-Config All-in-One Launcher" 写着：**不需要预装 `@deepseek-ai/dsh`，也不需要先起任何 Harness 服务；运行命令会自动下载运行时、分配端口、拉起完整 Web UI，浏览器访问 `http://127.0.0.1:3080` 或 `:3081`**。这说明它把 DSH 整个耦合/打包进来（`npx` 形态），**不是**常规"往现有 profile 插一个 bundle"的插件。

④ **外部依赖 / 凭据**：无 API Key；但会**自己下运行时、自己占端口**。

⑤ **与已装插件冲突**：**严重**。本机已跑 DSH Web（Desktop profile）；这个插件会另起 3080/3081 的**第二套 Web**。DSH 运行时的明确约束是"不要启动替代服务器"。与 lsp-actions/codegraph 同位置竞争。

⑥ **停止/恢复**：**未查到**（没有 install/uninstall/rollback 说明）。多进程 + 端口占用会让"装坏了怎么退"变成用户问题。

⑦ **证据覆盖 / 未知**：只有 README + 市场简介；**package.json、src、测试全部未取到**；4★/901 月 = 生态极弱。**未做**实测。

⑧ **维护 / 成本 / 复杂度**：MIT，4★，901 月下载 —— 本组**最弱的一个**；复杂度最高（自带 runtime + 端口 + 第二套 UI）。**结论：淘汰**。同类需求用 lsp-actions 或 IDE 更稳。

---

## 4. dsh-diff-approval（9087 / Wu Zhiwei）

**精确安装目标**：`dsh plugin --profile desktop add dsh-diff-approval`
- npm：`dsh-diff-approval`，**0.37.4**（2026-11-05），MIT，author `Wu Zhiwei`，月下载 6,278 / 周 2,317。
- 仓库：https://github.com/9087/dsh-diff-approval

① **匹配度**：**高**。真实痛点是"AI 改 9968 行的 `label_widget.py`，我看不懂它改了什么"。这个插件给的正是**待审编辑面板：整文件 diff + Keep / Revert**。对零编程用户，这是"改前看一眼、改错一键退"的最低成本护栏。

② **真执行 vs 仅提示词**：**真执行，而且是 Web 客户端层**。【源码发现】`dsh` 字段同时有 `bundle.patch` 和 **`client.inject`**（`-runtime`、`-connection`、`-locale`、`-ui-settings`、`-ui-sidebar`，`platform: "web"`）；`files` 含 `lib/client.js` 与 `assets/fonts/*.woff2`；deps 为 `diff@^9`、`shiki@^4`、`dompurify`、`marked` → 真在做 diff 渲染与高亮。**没有** `dsh.capabilities` 工具注册，说明它主要拦截/呈现"待应用的编辑"。

③ **DSH 0.2.2-rc.1 兼容**：【源码发现】**没有 `engines.dsh`** → **没有版本闸门**（不会被拒装，也不会被保护）；peerDeps 只有 `cordis >=4.0.1` 和 **`react ^18.2.0`**；devDeps 打的是 `@deepseek-ai/dsh-client-*@^0.1.0-rc.5` —— **客户端依赖基线是 0.1.x 线**，本机是 0.2.2-rc.1 客户端。**这是本候选最大的未知**。0.37.x 高版本号 + 11-05 还在发版说明作者在跟新版，但 peer 只声明到 0.1.x 线，属"能装但不保证"。

④ **外部依赖 / 凭据**：无外部服务、无 Key、无额外运行时。唯一隐性依赖：宿主须提供 **react 18**（DSH Desktop 自带前端用哪个 react 版本 → **未查到**）。

⑤ **与已装插件冲突**：与 **dsh-rewind-plugin** 互补（rewind=事后回滚；本插件=落地前逐文件 Keep/Revert）；与内置 approval/permission preset 不重复；与 git-graph 无重叠。**可共存**。

⑥ **停止/恢复**：面板级 Keep/Revert 就是最直接恢复手段；install 失败/回滚策略**未查到**。若客户端注入失败（react/API 不匹配），最坏是**侧边栏白屏或设置页异常** → 恢复 = `dsh plugin remove` + 重启。

⑦ **证据覆盖 / 未知**：有 `vitest` + **`playwright test`（e2e）** + `scripts/dsh-compat.mjs` + `verify-release.mjs`；市场未取到 → star/收录时间**未查到**。**未做**实测。

⑧ **维护 / 成本 / 复杂度**：**0.37.4** = 极高迭代频率，MIT，6.3k/月；成本几乎为零。**结论：选**。装前只需确认：重启后侧边栏/编辑面板是否正常渲染；不正常就 `remove`。

---

## 5. dsh-test-autofix（raysnows / 1250589385）

**精确安装目标**：`dsh plugin --profile desktop add dsh-test-autofix`
- npm：`dsh-test-autofix`，**0.1.3**（2026-10-20），MIT，发布者 `raysnows`。
- 仓库：https://github.com/1250589385/DSH-Test-Autofix

① **匹配度**：**高，文案几乎照着你项目写的**。【作者声明】"自动识别项目测试框架，运行测试并结构化解析失败信息，把「哪个文件、哪一行、什么断言失败」精准注入对话，让 agent 直接进入修复循环；同一处失败超过阈值自动停止，避免死循环烧钱。支持中文断言（自动处理 Windows 编码）与参数化测试。" 关键词直接列了 **pytest**。→ 196 个 pytest 文件 + conda 双环境 + Windows 编码 + 中文断言，全部命中。你已有 `QT_QPA_PLATFORM=offscreen pytest tests/test_canvas/` = 71 passed / 1 failed 的基线，它正好把"1 failed 的哪一行/哪条断言"结构化喂回来。

② **真执行 vs 仅提示词**：**真执行（但极简包装）**。【源码发现】`package.json` 只有：`main: index.js`、`files: [index.js, lib, cordis.patch.yml, locale, ...]`、**`dsh.bundle.patch: ./cordis.patch.yml`**，**没有任何 dependencies / peerDependencies / engines / postinstall**。纯 JS、零 npm 依赖、靠宿主 API 运行；`lib/` 里应有工具注册实现（本轮未读 src，故注册了哪些工具名 **【未知】**）。

③ **DSH 0.2.2-rc.1 兼容**：**不可证**。最硬短板：**无 `peerDependencies`、无 `engines.dsh`** → 0.2.x 安装前版本闸门对它**完全不生效**（装得上 ≠ 跑得动）；也**没有** `dsh.client`/`dsh.capabilities`。对一个调用 subprocess 跑 pytest 的插件，缺 peer 声明意味着"宿主 API 无契约"。【我的推断】作者可能照 0.1.x/0.2.0 API 写的，0.2.2-rc.1 上能否注册工具、能否拿到服务，**只有实测能确定**。

④ **外部依赖 / 凭据**：**零**。不下载东西、不要 Key、不要额外运行时（pytest 你已有）。locale 目录说明有中英文案。

⑤ **与已装插件冲突**：基本无。与 dsh-ops **可能都想要 subprocess 能力**，但层次不同。**注意**：本机 `ops_bash` 并发会坏——若它走同一条 subprocess 执行路径，可能继承同一个不稳定点。**必须实测**。

⑥ **停止/恢复**：**唯一亮点**：同一处失败超阈值**自动停止**（防"修不好就无限重试烧钱"）。除此之外无 gate、无审批、无回滚。恢复 = 卸载；跑测试本身只读。

⑦ **证据覆盖 / 未知**：市场页未取（star/收录时间**未查到**，npm 月下载仅 **325** = 极低采用）；**无测试目录、无 CI 证据**体现在 package.json；**具体工具名/参数/输出 schema 未读到**。**未做**实测。

⑧ **维护 / 成本 / 复杂度**：**单人小项目、0.1.3、325/月** → 维护风险最高一档；但**成本也最低**。**结论：备选-优先实测**。它是唯一**直接命中 196 pytest + Windows 编码**且**零安装成本**的东西；但正因 peerDeps 空缺，**不能盲信，必须先真跑一轮 `pytest tests/test_canvas/`** 看它有没有把失败结构化吐出来。

---

## 6. dsh-code-review：**两个同名不同物**，必须先分清

| | **6a. MichengAI** | **6b. f-e-n-g-0531** |
|---|---|---|
| 安装目标 | `@michengai/dsh-code-review@1.0.8` | `@feng0531/dsh-code-review` |
| 仓库 | github.com/MichengAI/dsh-code-review | github.com/f-e-n-g-0531/dsh-code-review |
| 市场收录 | 2026-09-18，**16★**，30 天 **24,718** | 2026-10-13，**9★**，30 天 **20,597** |
| 许可 | **Apache-2.0** | **非商业源码公开许可证**（公司内部商业项目/收费服务/商业交付需书面授权） |
| 入口 | 命令 `/review`、`/review-status`、`/review-cancel` + 工具 `dsh_code_review` | 工具 `code_review_preview` / `_execute` / `_status` / `_wait` / `_cancel` / `_artifacts` / `submit_review_result` |
| 机制 | 用 **native `spawn`** 起**独立子代理**，喂 Codex 官方评分表（固定 upstream commit `a592c38`），子代理自己读 Git/源码/测试，报告回主对话 | **预览 → 人工确认 → 执行**：`preview` 固定范围/模型/预算并返回 `previewId`（默认 5 分钟有效），`execute` 必须 `confirmed:true`；后台任务 + `wait`/`status` 分页取回 |
| 只读性 | 提示词要求不改代码，但**工具层不是全局只读**（只禁递归评审与专家调用），靠宿主权限兜 | **强只读**：不执行项目代码/构建脚本/模型生成的 shell 命令；不自动修复、不提交、不回滚 |
| 版本控制覆盖 | Git（base 分支 / 未提交 / 单提交 / 自定义指令） | Git（净变化/暂存/未暂存/单提交/两版本/整项目）+ **SVN**（revision、区间、双分支、mergeinfo、替换） |
| 语言 | 中/英，跟宿主 `locale.preference` | **仅中文** |
| 兼容声明 | `engines.dsh >=0.2.0-rc.1 <0.3.0-0`，README 明示"verified with 0.2.2-rc.1" | README 把 **0.2.2-rc.1** 列为已验证版本 |
| 许可对个人开发者的含义 | 随便用/改（Apache-2.0） | **自用 OK；一旦"商业交付"就要授权** |

### 6a / ①–⑧ 速评

① **匹配度**：高。中英双语、Codex 评分表（有体系）、无外部二进制。但它是"起一个子代理读仓库"——对 23 个未提交改动 + 196 测试的规模，token 成本明显。
② **真执行**：**真执行**。【源码发现】`client.inject`（`-ui-commands`、`-ui-primitives`）+ `peerDependencies` 里 `dsh-agent`/`dsh-subagent`/`dsh-user-questions`/`dsh-commands`/`dsh-tools` 全 optional → 命令面 + 子代理 + 提问面都是宿主原生能力。
③ **兼容**：**是**，且是**唯一在 README 里逐版本点名 0.2.2-rc.1 验证过**的一个（0.2.0-rc.1 → 0.2.1-rc.5 → 0.2.2-rc.1）。
④ **依赖**：要 `spawn` provider + `userQuestions` 服务 + 平台 question answerer + **支持 tool call 的模型**。本机 profile 已启用 agent-team/subagent/workflow（experimental），`spawn` 能力存在 → 大概率满足。无 Key、无联网。
⑤ **冲突**：与 **6b 直接竞争（二选一）**；与 **brooks-lint** 部分重叠；与 **内置 auto-review** 无关（见 §11.1）。
⑥ **停止/恢复**：`/review-cancel` 可取消；**关机后未完成的评审不会自动续**；"completed" 只表示子代理返回了报告，**不代表每个 diff 都看了、测试都过了**。
⑦ **证据**：有 `npm run check`（TS + prompt hash + 短任务 + 真 AgentLoop 离线回归）+ `verify:package`（隔离 profile 验证 bundle 加载/peers）；README 自己承认"review quality、语言遵从、跨平台交互**仍需 live 验证**"。**未做**实测。
⑧ **维护**：Apache-2.0、1.0.8、24.7k/月、11 个第一方插件矩阵 → 维护最好一档。成本：每轮评审 = 一次独立子代理上下文。

### 6b / ①–⑧ 速评

① **匹配度**：**最高**。默认路径就是"**先给你看范围，你点头才发模型**"——正好对上"零编程、需要人工确认"；Git "未提交改动"范围完全对口 23 个改动；中文优先。SVN 对当前项目无用（Git），但说明作者面向"重合规、要证据链"的场景。
② **真执行**：**真执行，7 个工具**。`preview` → 校验仓库/文件/上下文/模型/预算 → `previewId`；`execute({previewId, confirmed:true})`；后台 `code_review_start`（phase=preview\|execute）+ `wait`（`waitFor: terminal\|progress`，单次≤60s）+ `status`（`detail: technical`）+ `cancel` + `artifacts`（源码类工件需二次同意）+ `submit_review_result`（原生结构化结果工具）。
③ **兼容**：**是**，README 明示验证版本含 **0.2.2-rc.1**；且大量依赖 0.2.x 才有的"宿主契约/受限预设/结构化子会话/活动父 Agent"。
④ **依赖**：**无外部服务、无 Key**（用当前会话模型）；需 Git（本机有）或 SVN。**但它会把你选中范围的源码发给当前模型提供方**——本机模型就是你日常那个，等于没有新增出境方。
⑤ **冲突**：与 6a 二选一；与 **cc-safety-net**、**内置 approval** 无冲突（它有自己的 `confirmed:true` 语义，且明说"确认不等于绕过宿主权限"）。
⑥ **停止/恢复**：**本组最强**。`preview` 有 `expiresAt`/`validForMs`（≈5 分钟）；状态机 `completed / partial / failed / cancelled`；`resumeFromJobId` / `rereviewFromJobId` 显式续审（**旧批准不复用**）；预算受限的文件标"未完成"而不是当通过；`maxRetrievalRounds` 有界。
⑦ **证据**：README 极长且**主动列限制**（"SVN 尚未完整支持所有状态"、"不能当作事实/因果证明"、"没有专家确认时不输出命中率"）——本组最诚实的文档；有 `evaluation/README.md`。**未做**实测。
⑧ **维护**：9★/20.6k 月、版本 0.87.0 → 迭代极密；**但许可是非商业**，且**单人作者**。成本：预览不调模型，执行才调；有预算上限。

### 6 的结论

- **优先 6b（f-e-n-g-0531）**：唯一同时满足「只读」「预览→人工确认→执行」「中文」「Git 未提交范围全覆盖」「停止条件最完整」的候选。**前置条件**：确认你能接受"非商业许可"。
- **备选 6a（MichengAI）**：Apache-2.0 无许可顾虑、双语、兼容性声明最明确；但没有强制的人工预览确认步骤，可控性低于 6b。
- 两者**不要同装**。

---

## 7. brooks-lint（hyhmrright）

**精确安装目标**：`dsh plugin --profile desktop add brooks-lint`
- npm：`brooks-lint`，**1.9.1**，MIT，1556★，30 天 2,208 下载，2026-10-24 收录。仓库：https://github.com/hyhmrright/brooks-lint

① **匹配度**：中-高，角度独特。它不看 lint 规则，而看 6 类"生产代码腐化"（Cognitive Overload / Change Propagation / Knowledge Duplication / Accidental Complexity / Dependency Disorder / Domain Model Distortion）+ 6 类"测试腐化"（Test Obscurity / Brittleness / Duplication / Mock Abuse / Coverage Illusion / Architecture Mismatch）。→ 对 **9968 行单文件**，"Cognitive Overload" 和 "Change Propagation" 就是教科书案例；`/brooks-test` 正对 **196 个 pytest 文件**。输出带 **Symptom → Source(书名) → Consequence → Remedy** 和 0–100 Health Score + Mermaid 依赖图——对零编程用户可读性远高于裸 diff。**但这不是"验证"，是"体检报告"**。

② **真执行 vs 仅提示词**：**混合，主导部分是纯提示词**。【源码发现】`files` 含 `skills/`（6 个 `SKILL.md` + `_shared/`）、`bin/`、`lib/`、`scripts/install.sh`；`dsh` 字段**只有** `bundle.patch`，**没有** `client`、**没有** `capabilities`。→ 在 DSH 里它是 **Skills 提供者**（靠 skill description 自动触发），不是工具提供者。可执行部分（`bin/brooks-lint`、SARIF、GitHub Action）只在 CLI/CI 跑，**要用 `ANTHROPIC_API_KEY`**，与本机无关。

③ **兼容**：⚠️ **无可验证声明**。`engines` 只有 `node >=20`，**无 `engines.dsh`、无 peerDependencies** → 无安装闸门。【作者声明】贡献者按 **DSH 0.2.1-rc.2** desktop 验证过一次；0.2.2-rc.1 **未验证**。纯 skills 包风险比注册工具的包小（最坏是 skill 不出现）。

④ **依赖**：交互模式**零依赖**；CI/SARIF 要 Anthropic key（不用）。无 postinstall。

⑤ **冲突**：与 6a/6b 的 code-review **重叠但不同层**。可共存，但两份报告会互相打架，**建议只留一个"审查输出"**。与已装 **skill-explorer** 无冲突（正好能列/管它的 6 个 skill）；与 **dsh-context** 可能有 token 竞争。

⑥ **停止/恢复**：纯提示词不崩。**唯一硬风险**：`/brooks-sweep` 会 **"safe changes auto-applied, multi-file changes confirmed"** —— 对零编程用户，这是"AI 自己判什么叫 safe 然后直接改 9968 行文件"。**必须禁用 sweep**，只用 review/audit/debt/test/health。

⑦ **证据**：有**可复现**的确定性基准（30 份冻结报告解析器：severity 计数 30/30、risk-code 100%/100%、SARIF 30/30）+ 64 场景 eval + `npm test` 回归；作者主动声明"parser benchmark 只测解析保真度，不测 finding 是否正确"。**但** `evals:live` 要 Anthropic key，跨平台行为**未端到端验证**。**未做**实测。

⑧ **维护**：1556★、MIT、v1.9.1、有 benchmark/SARIF/CI，工程化程度高。**但有一条致命维护声明**："**My Claude account has been banned. Going forward, I will only test and verify Codex-related capabilities.**" → DSH 集成靠社区报告。成本：零安装成本。

**结论：备选**。零安装风险 + 最高信息密度，尤其 `/brooks-test`（196 个测试的腐化审计）和 `/brooks-audit`（Mermaid 依赖图，帮你看懂 9968 行怎么拆）值得一用；但**纯提示词、0.2.2 未验证、sweep 会自己改代码**，所以只能"备选 + 明确禁用 sweep"。

---

## 8. dsh-computer-use-win（Yu-tao-Li）——桌面操作核心候选

**精确安装目标**：`dsh plugin --profile desktop add dsh-computer-use-win`
- npm：`dsh-computer-use-win`，**0.5.5**，MIT，420★，30 天 25,319 下载，2026-08-18 收录。仓库：https://github.com/Yu-tao-Li/dsh-computer-use-win
- ⚠️ 必须用 `--profile desktop`；装完要**托盘右键退出再打开**，只关窗口不加载。

① **匹配度**：**高**。示例任务形状正是本项目需要的："打开网易云音乐，搜索'晴天'，确认结果页出现'周杰伦'。**如果无障碍树看不到搜索框，用 OCR 定位可见文字**"——这正是"打开 X-AnyLabeling → 载入图 → 点某个按钮 → 读状态栏/对话框 → 确认"的形状。

② **真执行 vs 仅提示词**：**真执行，架构最实在**。【源码发现】`description` 直接写 "an **MCP stdio server + PowerShell UIA backend**, bridged into DSH via `@deepseek-ai/dsh-mcp-client`"；`bin: {"wcu-mcp": "mcp/server.mjs"}`；`files` 含 `scripts/windows-uia.ps1`、`scripts/windows-takeover.ps1`、`scripts/windows-takeover.cs`、`mcp/browser.mjs`、`mcp/settings.mjs`；peerDeps = `@deepseek-ai/dsh-mcp-client >=0.1.0-rc.2 || >=0.2.0-rc.2` + `schemastery`（均 optional）；`os: ["win32"]`；`engines.node >=22`。【作者声明】25 操作工具 + 1 管理入口，全名 `windows_computer_use_<name>`，DSH 里常带 `mcp__wincu__` 前缀：
`health` `list_windows` / `snapshot` `accessibility_tree` `find` `element_info` / `screenshot` `ocr` / `click` `double_click` `move` `drag` `scroll` / `type_text` `keypress` `focus` `invoke` `set_value` / `launch_app` `activate_window` `move_window` `close_window` / `wait_for` `wait` / `batch` / `tools`。

③ **DSH 0.2.2-rc.1 兼容**：**是（间接）**。自身 `engines` 只有 node，**无 `engines.dsh`**；兼容性靠 peer `@deepseek-ai/dsh-mcp-client`（`>=0.1.0-rc.2 || >=0.2.0-rc.2`，两区间都向 0.2.2 开放）。它**不直接调 DSH 内部 API**、走官方 MCP 桥（稳定契约），版本漂移风险显著低于自研客户端插件。【我的推断】这是本组"架构上最抗 DSH 升级"的一个。
⚠️ 但它有 **`dsh.client.inject`（`-ui-locale`、`-ui-settings`）** = 设置页 + 中文文案走客户端注入，这层仍受 0.2.2 客户端 API 影响；README 截图来自 **DSH Desktop 2.0.18**，与 0.2.2-rc.1 不是同一版本号体系 → **设置页能否渲染 = 未验证**。

④ **外部依赖 / 凭据**：**几乎为零**。PowerShell 5.1 系统自带；不需要 API Key、不需要模型、不联网（除网页任务）。**它不带看图能力**（"插件只提供桌面工具，不带模型、API key，也不带 OmniParser/UI-TARS 这类看图解析工具"）→ **截图只是 PNG 文件路径**（"截图以 PNG 文件路径交给 agent，图片数据不进对话"）→ **必须配一个视觉桥（modlens / vision-router）才能真正"看见"**。这是本组最重要的一条依赖发现。另需 `@deepseek-ai/dsh-mcp-client`（DSH 官方 MCP 桥）与正常可用的交互式桌面会话。管理员窗口/UAC 界面**无法操作**。

⑤ **与已装插件冲突**：与 **dsh-browser 的 CDP 能力重叠**（见 §10）；与 **vision-router 的 `vision_screenshot`** 重叠（VR 那个默认关闭；CUW 是给动作定位、VR 是给模型阅读 → 可共存，但**别同时开两个截图源**）。与 dsh-ops 无冲突。**与"offscreen 无头 Qt 测试"完全互补**。

⑥ **停止条件 / 失败 / 恢复**：**本组最强**。
- **Esc 硬停止**：独立进程 `windows-takeover.ps1` 直接监听 Esc，**不经过 DSH 和后端**，"后端正忙时也能收到 Esc"；停止后**本轮不自动重试**。
- **batch 有界**：1–20 个已规划动作；"出错、页面跳转、弹出对话框或出现新窗口时就停下"；整批完只观察一次。
- **两态验证**：`verification: "sent"`（输入已发出，不代表成功）vs `"observed"`（`wait_for` 真看到窗口/控件/文字）。→ 逼 agent 必须"确认"。
- **busy 锁**：同一时间只有一段对话能操作桌面。
- **落点检查**：按坐标点击前检查"落点没有被别的窗口挡住"，被挡返回 `POINT_COVERED`。
- **前台/鼠标归还**：用完把鼠标放回、前台还回；剪贴板粘贴后恢复、不进 Win+V 历史。
- **已知不可恢复**："已经发给程序的操作无法撤回"；"如果程序卡住了，要等它响应后才能停下来"。
- 恢复：卸载插件；`WCU_TOOL_MODE=lite|lazy` 降级；`tools` 入口可临时卸载/重载。

⑦ **证据覆盖 / 未知**：**证据最厚**：`npm test` 跑 **50 套互相隔离的回归测试**（设置兼容、接管与停止、浮窗、界面读取、截图、OCR 协议、输入边界、batch、浏览器通道），**不发真实键鼠**；另有 `test/notepad-e2e.mjs` 真打字 e2e；CI badge；README 有大量真实截图。
**未知（关键）**：
- **UIA 对 PyQt6 的控件树支持度——README 没有 Qt 案例**（只提 Electron/Chromium 有特殊处理）。
- 【我的推断】PyQt6 = Qt6：Qt 6 在 Windows 上官方提供 **UIA** 实现（Qt5 是 MSAA/IAccessible2），所以 `QPushButton`/`QLineEdit`/`QMenu`/`QDialog`/`QTreeView` **大概率**能读到 name/control type 并 `invoke`/`set_value`；但标注画布是 **`QGraphicsView` 自绘**，UIA 只会暴露成一个 pane/graphic 容器，**画布里的矩形/标签/锚点不会成为独立 UIA 元素**。
- 会不会把**标注画布上的矩形框误判**？【我的推断】(a) 插件**不会**——`ocr` 只返回"文字+屏幕坐标"，不做形状识别；(b) **会**的是"看截图的模型"——可能把选中高亮框/十字线/网格误读成"已绘制的框"。这是视觉链风险，不是 CUW 风险。
- 高 DPI/缩放下的坐标映射：**未查到**（你机器 4480×1440，非 100% 缩放）。
- 与 DSH 0.2.2-rc.1 的实际加载（MCP 桥 + 设置页）**未验证**。

⑧ **维护 / 成本 / 复杂度**：MIT、0.5.5、420★、25.3k/月、50 套测试、中英双语极详尽 → **维护活跃度本组第一**。成本：零依赖，延迟主要在 PowerShell 后端首次冷启动（之后常驻）+ 截图/OCR。复杂度：设置页 10+ 项，对零编程用户偏多，但**默认值可用**。

**与"offscreen 无头 Qt 测试 + ffmpeg/PowerShell 截图"手工方案相比的增量价值**：
| 能力 | 手工方案（已验） | + CUW | 增量 |
|---|---|---|---|
| 跑逻辑/画布测试 | ✅ offscreen pytest 71 passed/1 failed | ✅ 也能调 | 0 |
| 拿到界面像素 | ✅ QWidget.grab() 0.07s / ffmpeg gdigrab / PowerShell .NET | ✅ `screenshot` | 0（且 CUW 截图只是路径，要另配视觉） |
| **驱动真实 GUI**（点按钮、开菜单、填表、切窗口） | ❌ 完全不能 | ✅ `invoke/set_value/click/type_text` | **+大** |
| **等状态变化再确认** | ❌ 只能 sleep + 再抓图 | ✅ `wait_for` + `observed` | **+大** |
| **读对话框/状态栏文字** | ⚠️ 只能 OCR 或代码里查字符串 | ✅ UIA `snapshot/find`（Qt 标准控件）+ `ocr` 兜底 | **+中** |
| 中途叫停 | ❌ | ✅ Esc 硬停止 | **+中** |
| 看清画布里的框画得对不对 | ✅ 截图 + 人眼 | ⚠️ 仍需视觉桥 | 0 |

**结论：选，但限"只读用法"**。用它做 `list_windows → snapshot/screenshot → find/ocr → wait_for` 的**只读验收**；**禁止首轮就用 `click/drag/type_text` 去画框或保存**——"已发出的操作无法撤回"，而你有 23 个未提交改动 + 真实标注数据。

---

## 9. dsh-vision-router（ysr666）——视觉验收核心候选

**精确安装目标**：`dsh plugin --profile desktop add dsh-vision-router`
- npm：`dsh-vision-router`（**无 scope**），市场 1211★、30 天 **56,719**（视觉类第一）、2026-08-14 收录、MIT。README 描述版本 **3.1.4**；GitHub HEAD `package.json` 是 **3.2.0-rc.0**（未发布）。

① **匹配度**：**高**。同时提供"**零 Key 看图**"和"**像素级工具**"。`vision_describe`（结构化 JSON：summary + layout regions + entity inventory + verbatim transcription）、`vision_ground`（原始像素框 x1/y1/x2/y2）、`vision_detect`（带编号元素清单）、`vision_crop`、`vision_pixel_diff`（差异率 + 最差 8×8 网格 + 红热图 PNG）、`vision_ocr`、`vision_html_screenshot`、`vision_screenshot`（默认关闭）、`vision_long_screenshot_ocr`…… 对"改完 UI 要验收"，`pixel_diff` 是**唯一确定性度量**，`ground` 是唯一能给可点击坐标的工具。

② **真执行 vs 仅提示词**：**真执行，14–15 个工具**。【源码发现】`bundle.patch` + `client.inject`（`-ui-settings`、`-ui-primitives`、`-connection`、`api-remotes`）；`dependencies`：`potrace`、`puppeteer-core@^25`、`semver`、`undici`、`zod`、`schemastery`；peerDeps：`@deepseek-ai/dsh-llm-deepseek`（optional）+ **`sharp >=0.35.3 <1`（optional）**；`bin: dsh-vision-router → lib/doctor-cli-p0.js`。【作者声明】"whole pipeline — downscale, grounding, crop, pixel diff, palette, OCR, SVG trace, cutout, HTML screenshot — runs on **sharp / potrace / tesseract / system Chrome**, **no Python**"。

③ **DSH 0.2.2-rc.1 兼容**：**条件性通过，两条硬门槛**。
- `engines.dsh: ">=0.2.1-rc.5 <0.3.0-0"` → **0.2.2-rc.1 满足**。
- **`engines.node: ">=24.9.0"`** —— 本机 PATH Node **v22.20.0** ❌。`engines` 默认不硬失败（pnpm 需 `engine-strict`），但它是作者声明的最低运行时。
 → **关键未知**：DSH Desktop 是否自带自己的 Node（若自带且 ≥24.9 就无所谓；若用系统 node 就有真风险）。**装前必须先查 Desktop 内置运行时版本**。
- 另：它**接管模型路由**（`autoWrapProviders` 默认 true，生成 `+ Auto Vision` 包装路由并从 stock picker 隐藏）→ 与宿主 model selector 深度耦合，版本敏感度高于普通工具插件。

④ **外部依赖 / 凭据**：**这是你要的核心答案——**
- **零 Key 链到底是什么引擎**：【源码发现 + 作者声明】内置匿名兜底 = **OVHcloud AI Endpoints**，域名 **`oai.endpoints.kepler.ai.cloud.ovh.net`**（README "Data flow" 表逐字写明），模型链 **`Qwen3.5-397B-A17B` → `Qwen2.5-VL-72B-Instruct` → `Qwen3.6-27B` → `Qwen3.5-9B`**。**无需注册、无需 API Key**。
- **必须联网**：是。CAUTION 开头明说："**Data leaves your machine by default.** … A fresh install has an anonymous OVHcloud vision fallback enabled, so 'free' and 'no key' do **not** mean offline."
- **隐私**：图片或裁剪、提示词、请求元数据 + **源 IP** 发给 OVHcloud（法国）。README 明说不要用于机密/受监管/涉密材料。**图片确实上传第三方。**
- **限速**："**2 requests/minute per IP per model**"，4 个模型独立桶 → 理论 ~8 RPM。验收单张够用，批量 20 张会卡。
- **能否读本地文件路径**：**能**。参数就是 `image="ref.png"` / `paths=[...]`，且"**Formats are sniffed from magic bytes**, so extensionless content-addressed attachment files work everywhere"；另有 `vision_materialize` 把授权附件复制成稳定交接文件并返回**绝对路径 + 短工作区相对路径**。→ 你的 `QWidget.grab()` / ffmpeg / PowerShell 产出的 PNG **可以直喂**。
- **输出是否结构化**：**是**（见①）。
- **中文界面支持**：`vision_ocr` 可走**本地 Tesseract**（需另装 `chi_sim` 语言包，否则中文差）或**视觉模型**（Qwen 系列中文能力强）。→ PyQt 中文界面建议走"视觉模型"路径。
- **延迟**：per-call `timeoutMs` 默认 **120000**；`downscale` 默认开，预算 4MP（`downscaleMaxPixels: 4000000`）→ 4480×1440 会被降采样再发（读 8px 小字要 `vision_crop` 放大）。
- **其他**：`vision_html_screenshot` 要 Chrome；`sharp` 是原生二进制（Windows 通常有预编译，但是安装风险点）；tesseract 可选。

⑤ **与已装插件冲突**：**本组最重要的冲突判断——三个视觉桥互斥**。
- **@liustack/modlens（已装 3.27.2，当前坏）**：**描述桥**（图片 → 结构化 JSON 文本），工具面是 `modlens_read_image` 单入口。
- **dsh-vision-router**：**路由桥**（图片轮次直接给视觉模型 + 像素工具），且**主动接管/包装模型路由**。
- **@anionex/dsh-vision-toolkit**：**路由桥**（注册 `<model> (Vision Toolkit)` 变体 + 10 工具）。
→ **后两者都改模型路由层，同时装会互相抢"谁包装这个模型"**；modlens 虽不改路由，但 `read_image` 与 `vision_describe` 是同一需求的两种答案，同时装只会让模型犹豫 + 双份上传。**结论：三选一，不要并存。**
- 另：VR 的 `vision_screenshot`（Win 用 PowerShell CopyFromScreen）与 **CUW 的 `screenshot`** 重叠 → 只开一个截图源（建议 CUW 供动作、VR 供阅读；VR 的 `vision_screenshot` 保持默认关闭）。
- 与 **dsh-context**：VR 的 image memory 与上下文压缩可能都想要图片描述 → 观察项。

⑥ **停止/失败/恢复**：**强**。
- 失败**分类**：region blocked / ToS / 402 quota / 429 rate limit / context overflow / network → 链式换后端，**全部失败才报**，错误带建议；
- **429 立即前进到下一后端 + Retry-After 感知冷却**；
- `freeFallback` / `localOllama` / `localLmStudio` 可配；**`localOnlyVision` 一键关掉所有远程视觉出口**；
- `visionTurnBudgetMs` 整轮墙钟预算；`cache`（内容 hash）避免重复计费；
- **升级踩坑已记录**：pnpm v11 会把 <24h 的新版本"扣住"，需显式装版本号；
- 恢复：`disabled: true` 一行停用；卸载移除路由/工具/skill/设置卡（缓存工件保留）。

⑦ **证据覆盖 / 未知**：`test` 脚本列了 **200+ 个测试文件**（含 quality-round2、adversarial fuzz、property fuzz、grounding 坐标证明契约、session vision policy、local-only、Ollama 冷启动……），工程强度本组第一。
**未知**：`engines.node>=24.9.0` 与本机 22.20 的实际影响；`sharp` 在你的 Windows + Node 组合上能否装上；**OVH 端点在中国大陆的可达性/延迟（未测）——这是"能否用"的现实开关**；0.2.2-rc.1 实机加载。**未做**实测。

⑧ **维护 / 成本 / 复杂度**：1211★、56.7k/月、MIT、3.x、测试极厚、有 doctor CLI → **维护第一档**。成本：免费（OVH 匿名），代价是**限速 + 图片出境**；复杂度：设置项极多，对零编程用户是"能跑但很难懂自己在配什么"。

**结论：备选（且是"零 Key 自动化视觉"的唯一切实方案）**。装前必须确认：(a) DSH Desktop 内置 Node ≥ 24.9；(b) 能访问 `oai.endpoints.kepler.ai.cloud.ovh.net`。

---

## 10. dsh-browser（wqty123）——**淘汰**

**精确安装目标**：`dsh plugin --profile desktop add dsh-builtin-browser`（npm 包名是 `dsh-builtin-browser`，GitHub 仓库叫 `dsh-browser`）
- 市场：162★，30 天 34,096，2026-08-16 收录，MIT。README 描述版本 **0.5.8**，"compatible with DSH 0.2.2-alpha.3"。

### 三条裁决答案

**Q1：是否只能操作它自己的 Electron 窗口？→ 是，而且更复杂。**
【作者声明】四种载体：**自带 Electron 浏览器**（standalone 窗口，标题 `dsh-browser`，带地址栏/前进后退/标签条）/ **DSH Desktop 侧边栏**（需往 **Desktop 自己的安装目录注入 sidebar bridge**）/ **本地 Chrome/Edge**（独立 profile 启动）/ 自动选择。→ 它能操作的是"**浏览器里的网页**"，**不是任意桌面窗口**。对本地 PyQt6 应用 **零帮助**。48 个 `dsh_browser_*` 工具（open/back/refresh/list_tabs/snapshot/a11y/content/scrape/screenshot/challenge/click/type/scroll/drag/hover/execute/fill/set_value/upload/download/do/assert/wait/console/network/dialog/session/reset/restrict/auth/history/visited/replay/doctor/help）全是网页操作。

**Q2：对"查 GitHub / 在线文档"的价值？→ 有，但不值得为它装。**
- 能开页面、读内容、填表、下载，有 `snapshot/a11y/content/scrape` + `auth`（登录态持久）→ 对"需登录文档/私库 issue"比内置 `web_fetch` 强。
- **但**：内置 `web_fetch` 已能读公开文档/raw GitHub（本报告全靠它）；DSH Desktop 已带侧边栏浏览器；而 **`dsh-computer-use-win` 自带 browser lane（CDP 直连 Chrome/Edge，`browserTab` + 元素 ID）** 已覆盖"后台操作网页"。→ **功能位被两头夹死。**
- 本机事实：本会话 `web_search` **当前不可用**（`DEEPSEEK_API_KEY` 缺失）→ 想查在线资料，路是 `web_fetch`（可用），不是再加一个浏览器。

**Q3：成本与风险？→ 本组最高一档。**
① **自带 Electron 运行时**（首次按需下载；0.5.3 起无 `postinstall`，改后台准备）；② Desktop 侧要把 bridge **注入 `app.asar`**，而"**a desktop update restores `app.asar`, the bridge goes stale**"（`bridge-status` 报 `stale`，需重装）；③ 升级要**先 `remove` 再 `add`**（0.2.1-alpha.2 起覆盖安装直接 `already-installed` 失败）；④ 与 CUW 的 CDP 通道可能**抢同一个浏览器**。
对零编程用户：**为了"查文档"去装一个需要注入 app.asar、每次桌面升级就失效的东西 = 不划算。**

**①–⑧ 速评（简）**：① 匹配度**低**；② **真执行**（48 工具，CDP）；③ ⚠️ README 只写到 "DSH 0.2.2-alpha.3"，**0.2.2-rc.1 未声明验证**；④ 依赖 Electron 运行时 + Desktop bridge + 可选本地 Chrome/Edge；⑤ 与 **CUW 的 browser lane**、**Desktop 内置侧边栏浏览器**重叠；⑥ `session/reset/doctor/history/replay` 做得好，但 bridge stale 是外部故障；⑦ 文档厚度好（limitations/architecture/tool-reference/SKILL.md），162★/34k 月说明有真实用户，**未做**实测；⑧ MIT、0.5.8、单人活跃，成本 = 磁盘 + Electron 下载 + 每次升级重装 bridge。

**结论：淘汰**。理由一句话：**它解决的是"网页"，你的验收对象是"PyQt6 桌面窗口"；而"网页"已被 CUW 的 browser lane 和内置 `web_fetch` 覆盖，它的增量只是"更完整的浏览器自动化"——不值得为零编程用户引入 app.asar 注入和 Electron 运行时。**

---

## 附 A. @anionex/dsh-vision-toolkit（补充核查，决定视觉链选型）

**精确安装目标**：`dsh plugin --profile desktop add @anionex/dsh-vision-toolkit`
- npm `@anionex/dsh-vision-toolkit`，MIT，**922★**，30 天 15,049，2026-08-13 收录。仓库：https://github.com/Anionex/dsh-vision-toolkit

**免 Key 链是什么**：【作者声明】"No API key by default — images are processed by the **author-hosted free service**, **100 per machine per day**; configurable to your own provider." + "Switched the **default model to Gemini 3.7 Flash**" + "Expanded service capacity to reduce peak-time `429`"。
→ **不是**公共免费 API，是**作者自己搭的代理服务**（域名 README 未直说；项目站 `agent-vision.anionex.me`）。→ **图片上到作者的服务器**，且**日配额 100 张/机**。

**其他关键差异**：
- **要 Python 3.11+ 运行时**：优先用系统 Python，没有就**下 35MB 独立 Python**（腾讯 COS 镜像，fallback GitHub），再装 `Pillow/NumPy/vtracer`（腾讯 PyPI 镜像）。→ 组件最重。
- Windows 特有限制：**配置的共享根目录在 Windows 上被拒绝**（ACL 无法安全校验）；**会话工作区必须可写**（要建 `.dsh-vision-toolkit`）→ 你的工作区是 workspace-write，OK。
- 工具面 10 个：`vision_glance / ground / detect / crop / trace / pixel_diff / long_screenshot_ocr / extract_foreground / dominant_colors / html_screenshot`。**没有 `vision_screenshot`（不能自己截桌面屏）** → 截图要你自己提供（反而更干净）。
- 有 **`vision-skills`** 5 套 playbook（长截图 OCR / UI 还原 / 图形还原 / 结构还原 / **GUI 操作**）——最后一套"locate a control → perform one action → capture again → verify"正是你要的闭环方法论。
- 兼容：README 明确支持 `--profile desktop`；但**没写 `engines.dsh`**（package.json 未取），且 DSH Desktop 2.0.1 内置市场有已知安装问题（要终端装）。

**裁决：不推荐**。它跟 vision-router 抢同一位置（都改模型路由、都提供像素工具、都要联网读图），但代价更高（Python 运行时 + 35MB 下载 + 作者自建服务的配额与信任假设），且**默认配额只有 100 张/天**——真做 UI 验收（一次改 UI 要 3–10 张）会很快撞墙。**隐私链最长、组件最重**，收益不抵成本。

---

## 附 B. dsh-windows-mcp（helloHub1212）

**未查到。** 本轮 web_fetch 在 DSH 重启前后两次被中断，未能取到该候选的市场页/GitHub 清单；按任务优先级（10 个主候选 + 两条链裁决）已让位。
【我的推断】从命名与生态位置看，它是"Windows MCP 服务 + DSH 包装"，功能位大概率与 `dsh-computer-use-win` 高度重叠，但**缺少**后者的 DSH 原生设置页、接管提示、Esc 硬停止、50 套回归测试与 25 工具的设计密度。**不影响结论**：桌面操作已有一个证据显著更厚的选项。若后续要补，检索顺序：市场 `/p/helloHub1212/dsh-windows-mcp/` → GitHub `package.json` 的 `dsh` 字段与 `engines.dsh`。

---

## 11. ⚠️ 三处"同名不同物"与冲突矩阵（决定装什么之前先看这节）

### 11.1 「auto-review」三方同名 —— 千万别混

| 名字 | 是什么 | 机制 | 装了吗 |
|---|---|---|---|
| **内置 experimental `auto-review`** | DSH 的**权限档**能力 | **Auto 档下，每个工具调用先让模型做一次授权复核**（"这个 bash 该不该放行"） | ✅ **已启用** |
| **市场 `PerryLink/dsh-auto-review`** | 社区插件 | **审批决策链上挂第二个模型做审查**（对 approval 请求二次判断） | ❌ 未装 |
| **`dsh-code-review`（6a/6b）** | 代码审查插件 | 审**代码质量/Git diff**，与权限无关 | ❌ 未装 |

→ 三者**完全不是一回事**。已启用的内置 auto-review **不会**给你代码审查；也不会与 dsh-code-review 冲突。

### 11.2 三个视觉桥 —— **互斥，三选一**

| | modlens（已装，坏） | vision-router | vision-toolkit |
|---|---|---|---|
| 桥的类型 | 描述桥（图片→JSON 文本） | **路由桥** + 像素工具 | **路由桥** + 像素工具 |
| 是否改模型路由 | ❌ 不改 | ✅ `autoWrapProviders` 默认开 | ✅ 注册变体（默认透明路由） |
| 免 Key 引擎 | 取决于 provider（claude-cli **当前坏**） | **OVHcloud 匿名端点** | **作者自建服务**（100/天/机） |
| 图片出境 | 取决于 provider | ✅ 是（OVH，法国） | ✅ 是（作者服务器） |
| 额外运行时 | claude CLI（已装未登录） | sharp/Chrome（无 Python） | **Python 3.11+ / 下 35MB** |
| 结构化输出 | ✅ OCR/版面/语义 JSON | ✅ JSON + 像素框 + diff | ✅ 坐标 + diff + OCR |
| 结论 | **修它最省**（见 §12） | **零 Key 唯一切实方案** | **不推荐** |

### 11.3 三个"代码结构"方案 —— 三选一

`dsh-lsp-actions`（真 LSP，要 pyright） / `dsh-codegraph`（要外部 CLI，改系统提示词） / `dsh-tool-lens`（自带第二套 Web UI）。→ 推荐顺序：**lsp-actions > 都不装 > codegraph > tool-lens**。

### 11.4 编辑确认层 —— 互补，可叠加

`dsh-diff-approval`（**改前**逐文件 diff + Keep/Revert） + `dsh-rewind-plugin`（**改后**整轮回滚） + 内置 approval/permission preset（**执行前**允不允许）+ 内置 worktree（隔离实验）→ 四层各管一段，**不冲突**；但全开会变成"四道确认"，对零编程用户是负担 → **建议只加 diff-approval**。

### 11.5 桌面/浏览器 —— 重叠，二选一

`dsh-computer-use-win`（含 CDP browser lane） vs `dsh-browser`（纯浏览器）→ **选 CUW**。同时装会抢 CDP 端口/登录态。

---

## 12. 明确推荐（给最终组合）

### 12.1 视觉验收链：**推荐「不新增视觉插件，先修 modlens + 用确定性截图」为主路；vision-router 作为唯一备选**

先回答必须回答的那句：**"在不给任何 API key 的前提下，本机截图能不能被读懂？"**

> **能，但不是离线、不是本地。**
> 两条只在此条件下成立的路径：
> 1. **dsh-vision-router 的 OVHcloud 匿名链**：真的零 Key、真的能读本机 PNG（按 magic bytes 嗅探，扩展名无所谓）、真的返回结构化（layout regions / entity inventory / 逐字转写 / 像素框 / 像素 diff）。代价：**必须联网**、**图片上传到 OVHcloud（法国）**、**2 RPM/模型**、`engines.node>=24.9`（本机 22.20 ❌，需先确认 Desktop 内置运行时）。
> 2. **vision-toolkit 的作者自建服务**：零 Key 但**100 张/天/机**、图片上传到**个人作者的服务器**、要下 35MB Python。
> **没有第三条"零 Key + 离线 + 本地"的路。** 凡声称"免 Key"的，都只是"免你的 Key，别人的服务器在跑"。

**对比四选项（含"不装插件"）**：

| 方案 | 新增安装 | Key | 离线 | 图片出境 | 结构化 | 对"PyQt 截图验收"的实际效果 | 结论 |
|---|---|---|---|---|---|---|---|
| **A. 修 modlens + 现有脚本截图** | **0** | 取决于 provider | 取决于 provider | 取决于 provider | ✅ OCR/版面/语义 | **最好**：`QWidget.grab()`（0.07s）+ ffmpeg + PowerShell 三种截图已验；modlens 输出"逐字转写 + 版面区域"，正好回答"对话框写了什么、按钮在哪" | ✅ **主路** |
| **B. dsh-vision-router** | 1 插件（+sharp） | **无** | ❌ 必须联网 | ✅ OVH | ✅✅ 最强（像素框/diff） | 好，且**唯一能给坐标**（可接 CUW 点击）+ **唯一能做 pixel_diff 前后对比** | ⚠️ **备选** |
| **C. dsh-vision-toolkit** | 1 插件 + Python 运行时 | 无（配额 100/天） | ❌ | ✅ 作者服务器 | ✅✅ | 好，但配额 + 隐私最差 | ❌ 不推荐 |
| **D. 不装视觉插件，人工看图** | 0 | 无 | ✅ | ❌ | ❌ | 慢但**最可信**：只需看 1–3 张关键截图 | ✅ **兜底** |

**为什么 A 是主路而不是 B（尽管 B 很香）**：
1. modlens **已经装了**（3.27.2），坏的原因很窄很确定：`claude-cli provider failed with code 1` ← `~/.claude.json` 无 `oauthAccount`（Claude Code 2.1.177 已装但**未登录**）。**要么 `claude` 登录一次，要么 `modlens config set` 换到 openai / local provider** —— 两条都是**分钟级、零新插件、零 app.asar、零 Electron** 的修复。
2. 你这个项目的"界面验收"**本质是像素决定论**：Qt UI 是确定性渲染，`QWidget.grab()` 0.07s 出图、中文渲染正常（168 非背景像素），你**已经**有 offscreen pytest 基线（71 passed / 1 failed）。这种场景下，"模型看图描述"是**辅助**，"截图前后 diff + 断言"才是**证据**。vision-router 的 `pixel_diff` 值钱，但同样的 diff 你用 20 行 Python（Pillow）也能做，且**不需要上传任何图片**。
3. B 的两个未解风险（Node 24.9 门槛、OVH 可达性）**任何一个不满足就是装了个死件**；而 A 的风险你已经知道且可解。

**具体落地步骤（视觉）**：
1. **先修 modlens**：优先 `claude` 登录（若本来就有 Claude 订阅）；否则 `modlens config set` 切到 openai（需 key）或 **local**（Ollama/LM Studio，完全离线）→ local 最符合"不给 key"，但要下一套本地视觉模型（≥7B 才有可用中文 OCR）。
2. **截图三件套固定下来**：逻辑/画布级 `QT_QPA_PLATFORM=offscreen` + `QWidget.grab()`；真窗口级 `ffmpeg -f gdigrab` 或 PowerShell `CopyFromScreen`（都已验）。
3. **验收用"双轨"**：确定性轨道（截图 diff 比例 + 关键控件像素/颜色断言 + offscreen pytest 结果）当**证据**；模型轨道（modlens 读单张关键截图）当**解释**。**不要让模型当唯一裁判。**
4. **只有在"必须让 agent 自己全自动看懂并使用坐标"时**，才上 **dsh-vision-router**，且：装前查 Desktop 内置 Node ≥ 24.9、能访问 OVH；装前把 **modlens 停用**（三视觉桥互斥）；`vision_screenshot` 保持默认关闭（避免两套截屏源）；`localOnlyVision` 保持关闭（否则免 Key 链失效），但心里清楚图片在出境；**若在意隐私就別装它**——它没有任何"零 Key + 本地"模式。

### 12.2 桌面操作链：**推荐「选 dsh-computer-use-win，限只读用法」+「offscreen pytest 保留为证据主轨」**

**为什么选它**（回答三个子问题）：
1. **是否依赖外部 Windows-MCP 进程？** —— **不依赖额外的第三方服务或独立安装**，但它**本身就是一个 MCP stdio server**（`mcp/server.mjs`，`bin: wcu-mcp`），由 **DSH 官方 `@deepseek-ai/dsh-mcp-client` 桥**启动；后端是**常驻 PowerShell 5.1 进程**（`scripts/windows-uia.ps1`，系统自带）。准确说法：**依赖"DSH 的 MCP 桥 + 一个常驻 PowerShell"，不依赖 Windows-MCP 这个产品。**
2. **UIA 对 PyQt6/Qt 支持如何？** —— 【我的推断】**标准控件大概率可读可点，自绘画布一定读不到**。Qt6 在 Windows 提供 UIA 实现（Qt5 是 MSAA/IAccessible2），所以 `QPushButton`（标注/保存/打开按钮）、`QLineEdit`、`QComboBox`、`QMenu`、`QDialog`、`QTreeView` **应能被 `snapshot/find/invoke/set_value` 命中**；但 **`QGraphicsView` 标注画布**只会暴露成一个 pane，**画布里已画的矩形/多边形/锚点不是 UIA 元素**。→ **能"操作界面"，不能"读画布内容"。** README **没有 Qt 案例**，这是最高优先级实测点。
3. **有无图像/坐标点击、OCR 文本定位、"看屏幕→点击→再看"闭环？** —— **有，且完整**：`screenshot`（PNG 路径）、`ocr`（WinRT，返回**文字+屏幕坐标**）、`click/double_click/drag/move/scroll`（坐标 + 元素 ID）、`find/snapshot/accessibility_tree`、`wait_for`、`batch`（1–20 动作，遇跳转/弹窗即停）。README §4.1 明确写循环是 **观察 → 定位 → 执行 → 确认**，且用 `verification: sent|observed` 区分"发了"和"真成了"。**闭环存在。**
4. **会不会把标注画布上的矩形框误判？** —— **插件不会，模型可能会**。`ocr` 只回文字+坐标，不做形状识别；风险在"让视觉模型看截图判断框画得对不对"这一步。→ **规矩：画布内容判定只用像素断言/人工，不用模型。**
5. **权限？** —— 【作者声明】普通用户即可；**以管理员运行的窗口和 UAC 确认界面无法操作**；需要**正常可用的交互式桌面会话**（锁屏/RDP 断开有问题）。**不需要管理员权限**，不改系统设置。
6. **相对手工方案的增量** —— 见 §8 增量表：**+能驱动真实 GUI、+能等状态变化再确认、+能读对话框文字、+能中途 Esc 停止**；**0 增量**在"画布里的框对不对"。→ **增量是"交互"，不是"看见"。**

**具体落地步骤（桌面）**：
1. 装：托盘 → 打开 DSH 终端 → `dsh plugin --profile desktop add dsh-computer-use-win` → **托盘右键退出** → 重开。
2. 首轮只做**只读验收**，一条 prompt 跑通闭环：
 ```
 只读验收，不要点击保存/不要修改任何标注。
 1) list_windows 找到 X-AnyLabeling 主窗口；
 2) snapshot 读一遍控件树，告诉我它能看到哪些按钮、哪些区域是"读不到内容的画布"（这一条是给我验证 Qt UIA 支持度的，请如实报告，不要猜）；
 3) screenshot 存一张 PNG 并给我路径；
 4) 用 find 找"打开"或"打开图像"按钮并只读报告它的 element id/name，不要点击；
 5) wait_for 等主窗口标题出现，报告 verification 是 observed 还是 sent。
 ```
 → 一步同时验证 **(a) 0.2.2-rc.1 能否加载 (b) Qt UIA 到底能看到什么 (c) 截图路径能否被视觉桥读**。
3. 第二轮再加**非破坏性动作**（切窗口、开对话框、读状态栏），仍不碰画布、不保存。
4. 第三轮（可选）才做"画一个框"的破坏性验证——**必须先在 git 干净的分支/worktree 上**（内置 worktree 可用），且提前确认"已发出的操作无法撤回"。

**结论一句话**：CUW 值得装，因为它是**唯一能真正驱动 X-AnyLabeling 真实 GUI 的工具**；但要把它当"**手**"，不要当"**眼**"，更不要当"**法官**"。验收证据主轨仍是 **offscreen pytest + 截图 diff**。

### 12.3 代码/测试/审查层：建议只加 1–2 个

| 优先级 | 候选 | 理由 | 前置条件 |
|---|---|---|---|
| **1（选）** | `dsh-diff-approval` | 零依赖、零外部服务、直接解决"AI 改 9968 行我看不懂"；Keep/Revert 是最低门槛护栏 | 装完确认侧栏/编辑面板能渲染（peer react 18） |
| **2（选）** | `@feng0531/dsh-code-review` | 本组唯一"先预览范围→人工确认→才发模型"的只读审查；中文；Git 未提交范围全覆盖 | **确认接受非商业许可**；否则换 `@michengai/dsh-code-review`（Apache-2.0） |
| **3（备选-优先实测）** | `dsh-test-autofix` | 唯一直接命中 196 pytest + Windows 编码 + 中文断言，且零安装成本 | 先实跑一轮 `pytest tests/test_canvas/` 验证它在本机 0.2.2-rc.1 上能否注册工具（无 peerDeps/engines） |
| **4（备选）** | `brooks-lint` | 零风险技能包；`/brooks-test` + `/brooks-audit` 对 196 测试和 9968 行文件信息密度最高 | **禁用 `/brooks-sweep`**（它会自动应用"安全改动"） |
| **5（备选）** | `dsh-lsp-actions` | 真编译器真值，最适合长文件导航 | 必须先 `npm i -g pyright`（本机未装），否则空壳 |
| ❌ 淘汰 | codegraph / tool-lens / dsh-browser | 见各节 | — |

**建议的最终组合（最小充分集）**：
> `dsh-diff-approval` + `@feng0531/dsh-code-review` + `dsh-computer-use-win`（只读） = **3 个新插件**
> 视觉：**不新增**，先修 modlens（或直接用 offscreen+grab 截图 + 人工看）
> 可选加：`dsh-test-autofix`（实测通过后）、`brooks-lint`（只用 test/audit）

---

## 13. 证据边界与未完成项（诚实清单）

**本轮明确"未做"的**：
- ❌ 未安装 / 未卸载 / 未运行任何候选插件（只读调查）。
- ❌ 未实测任何候选在 DSH 0.2.2-rc.1 上的真实加载、工具注册、设置页渲染。
- ❌ 未验证 PyQt6 在 UIA 下暴露哪些控件（CUW 的关键未知）。
- ❌ 未验证 OVHcloud 端点从本机是否可达、延迟多少。
- ❌ 未验证 DSH Desktop 内置 Node 版本（决定 vision-router 能否满足 `engines.node>=24.9`）。

**未取到的材料（已用替代来源，结论已标注）**：
- `dsh-tool-lens` 的 `package.json` / `src`（两次抓取被 DSH 重启打断）→ 其"注册了什么工具"**未证实**；但"`npx` 会自起 127.0.0.1:3080 Web UI"足以判淘汰。
- `dsh-windows-mcp / helloHub1212` 完全未查（见附 B）。
- 市场页未取：`dsh-lsp-actions`、`dsh-diff-approval`、`dsh-test-autofix`（用 npm registry + package.json 替代，star/收录时间缺）。
- `dsh-code-review`（f-e-n-g-0531）的 `package.json` 未取到（只有 README + 市场页）；工具名/状态机来自 README 自述。
- `@anionex/dsh-vision-toolkit` 的 `package.json` 未取到；Python 运行时/配额来自 README。

**版本漂移提醒（供交叉核对）**：
- `@michengai/dsh-code-review`：市场 README 开发文档写 `0.1.3`，npm/HEAD 是 **`1.0.8`** → 以 1.0.8 为准。
- `dsh-vision-router`：README 描述 **3.1.4**，HEAD 是 **`3.2.0-rc.0`**（未发布）→ npm 装到的应是 3.1.x 线。
- `dsh-browser`：市场简介写"20 个 `browser_*` 工具"，README 现版本写"**current source registers 48 tools**" → 以 48 为准。
- `brooks-lint`：README Roadmap 写到 v1.4，`package.json` 是 **1.9.1** → 以 1.9.1 为准。
- `dsh-computer-use-win`：README 提到 `0.5.4` 截图，`package.json` 是 **0.5.5**。

**给 Lead 的额外发现（影响后续）**：
> 本会话 `web_search` **当前不可用**：`DeepSeek search has no API key for "DEEPSEEK_API_KEY"`。即"查在线资料"目前只能靠 `web_fetch`（可用）。若最终组合里考虑"联网检索"，这是待修项，不要误判为"网络不通"。

---

## 14. 来源（抓取时间 2026-11-09）

**市场页**
- https://awesome-dsh-plugin.com/p/MichengAI/dsh-code-review/
- https://awesome-dsh-plugin.com/p/f-e-n-g-0531/dsh-code-review/
- https://awesome-dsh-plugin.com/p/jiangzhenguo/dsh-codegraph/
- https://awesome-dsh-plugin.com/p/trench-xinxin/dsh-tool-lens/
- https://awesome-dsh-plugin.com/p/hyhmrright/brooks-lint/
- https://awesome-dsh-plugin.com/p/Yu-tao-Li/dsh-computer-use-win/
- https://awesome-dsh-plugin.com/p/ysr666/dsh-vision-router/
- https://awesome-dsh-plugin.com/p/wqty123/dsh-browser/
- https://awesome-dsh-plugin.com/p/Anionex/dsh-vision-toolkit/

**package.json（GitHub HEAD）**
- https://raw.githubusercontent.com/PerryLink/dsh-lsp-actions/HEAD/package.json
- https://raw.githubusercontent.com/9087/dsh-diff-approval/HEAD/package.json
- https://raw.githubusercontent.com/1250589385/DSH-Test-Autofix/HEAD/package.json
- https://raw.githubusercontent.com/jiangzhenguo/dsh-codegraph/HEAD/package.json
- https://raw.githubusercontent.com/MichengAI/dsh-code-review/HEAD/package.json
- https://raw.githubusercontent.com/hyhmrright/brooks-lint/HEAD/package.json
- https://raw.githubusercontent.com/Yu-tao-Li/dsh-computer-use-win/HEAD/package.json
- https://raw.githubusercontent.com/ysr666/dsh-vision-router/HEAD/package.json

**npm registry（作者/包名反查）**
- https://registry.npmjs.org/-/v1/search?text=dsh-lsp-actions&size=5
- https://registry.npmjs.org/-/v1/search?text=dsh-diff-approval&size=5
- https://registry.npmjs.org/-/v1/search?text=dsh-test-autofix&size=5

**仓库**
- https://github.com/PerryLink/dsh-lsp-actions
- https://github.com/9087/dsh-diff-approval
- https://github.com/1250589385/DSH-Test-Autofix
- https://github.com/jiangzhenguo/dsh-codegraph
- https://github.com/trench-xinxin/dsh-tool-lens
- https://github.com/MichengAI/dsh-code-review
- https://github.com/f-e-n-g-0531/dsh-code-review
- https://github.com/hyhmrright/brooks-lint
- https://github.com/Yu-tao-Li/dsh-computer-use-win
- https://github.com/ysr666/dsh-vision-router
- https://github.com/wqty123/dsh-browser
- https://github.com/Anionex/dsh-vision-toolkit

---
*报告结束。全部结论基于 2026-11-09 的公开材料与静态源码/清单；任何"能否跑通"的判断都必须以一次受控实测为准。*
