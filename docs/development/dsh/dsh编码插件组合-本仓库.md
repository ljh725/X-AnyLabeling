# DSH 写代码插件组合（针对 X-AnyLabeling 本仓库）

> 目标：支撑两类工作 —— **① 原始功能修改**（回归风险高）、**② 全新功能扩展**（需要规格与实施纪律）。
> 依据：本仓库实测（2026-11-07）：`anylabeling/` 486 个模块 / 12.8 MB、`tests/` 196 个 `test_*.py`、15 个测试子目录、pytest 开 `--doctest-modules`、`label_widget.py` 9948 行、`inspector/dialog.py` 4688 行、PyQt6 + conda 环境 `x-anylabeling-cu12`、工作区约 3.3 GB（`.local` 1.6 GB / `backups` 688 MB / `.tmp` 268 MB）、已有 openspec（proposal/design/tasks）流程与 pre-commit（black 79 / flake8）。

## 一、组合（5 件套）

| # | 插件 | 角色 | 主要服务哪个需求 | 在本仓库的理由 |
|---|---|---|---|---|
| 1 | **dsh-lsp-actions** `0.5.19` | 真实语言服务器动作面：诊断 / 重命名 / 符号 / 代码动作 / 签名 / 补全 / 格式化 | 改旧 + 加新 | 9948 行的 `label_widget.py` 里改方法名、找符号、看诊断，靠 grep 不可靠；重命名带冲突检测并走 `fs/write-intent` 审批 |
| 2 | **dsh-diff-approval** `0.37.4` | 每次 `edit`/`write` 自动汇总，逐块 / 选区 / 整文件「保留 / 回退」，可导入未提交改动 | 改旧 + 加新 | 当前工作区已有约 20 个未提交文件；改旧功能时逐 hunk 审、新功能时只留想要的改动，不靠 git 兜底 |
| 3 | **dsh-codegraph** `1.2.2` | CodeGraph 代码图谱：`explore` / `impact` / `callers` / `callees` / `affected`（改动 → 该跑的测试） | 改旧为主，加新为辅 | CodeGraph 原生支持 Python（Rust 内核 + tree-sitter，20 种语言），有文件监听自动同步；改一个符号前先算影响面，改完直接拿到受影响测试清单 |
| 4 | **dsh-test-autofix** `0.1.3` | `run_tests` 工具：自动识别 pytest、结构化给 file/line/断言、同一失败反复出现即熔断 | 改旧 + 加新 | 196 个测试文件 + doctest，全量跑很慢；它能定点跑并把失败变成精准上下文，避免几千行 traceback |
| 5 | **superpowers-dsh** `0.4.0` | 15 个工程技能：`brainstorming` / `writing-plans` / `executing-plans` / `test-driven-development` / `systematic-debugging` / `verification-before-completion` / `requesting-code-review` … | 加新为主 | 仓库已有 openspec 管「规格与验收」，缺的是执行纪律；纯技能增量、不改 agent preset，与 openspec 互补 |

**可选第 6 个**：`@michengai/dsh-code-review` `1.0.8` —— `/review` 起独立子 Agent 审查指定 Git 范围（基准分支 / 未提交 / 某次提交），官方标注已验证 `0.2.2-rc.1`。适合提交前二审，不想多一次往返可以先不装。

**已装可复用，不要重复买**：`dsh-better-sidebar`（文件树 + 编辑器 + 终端）、`@linxin666/dsh-client-ui-git-graph`（分支 + 提交图）、`cc-safety-net`（危险命令拦截）。

## 二、两个需求怎么跑

### A. 原始功能修改（例如改 `label_widget.py` 里某段交互）

1. `codegraph_status` → 未索引则 `codegraph_init`（只索引一次，之后 `codegraph_sync` 增量）。
2. `codegraph_impact` / `codegraph_callers`：先确认这个函数被 `views/labeling/*`、`tests/test_canvas/*` 里谁调用，避免漏改。
3. `lsp_symbols` 看该文件的大纲定位目标；跨文件改名用 `lsp_rename`（冲突会被拒绝）。
4. 改完用 **diff-approval** 逐块看差异，只保留预期的块。
5. `codegraph_affected` 拿到受影响测试 → `run_tests(path_filter="test_rectangle_size")` 定点跑。
6. 收口：`systematic-debugging`（失败时找根因）/ `verification-before-completion`（声称完成前拿证据）。

### B. 全新功能扩展（例如新增一个 inspection 类工作流）

1. 先用 openspec 写 `proposal.md` / `design.md` / `tasks.md`（仓库既有流程）。
2. `skill` 加载 `brainstorming` → 对齐需求与边界；`writing-plans` → 出可执行计划。
3. `codegraph_explore` 找同类实现（`anylabeling/services/dense_review`、`services/inspection` 的服务注册与视图挂载方式），照着既有模式落位。
4. TDD：先写 `tests/test_xxx/...` → `run_tests` 见红 → 实现 → 见绿。
5. 提交前 `/review`（可选）或 `requesting-code-review`；最后用 diff-approval 收干净改动，跑 pre-commit（black / flake8 已配置）。

## 三、安装与配置（本机）

DSH 0.2.2-rc.1，profile 为 `desktop`，`dsh` 不在 PATH，用桌面端自带 CLI：

```powershell
$dsh = 'D:\DeepSeek Harness\resources\runtime\cli\bin\dsh.cmd'

& $dsh plugin --profile desktop add dsh-lsp-actions
& $dsh plugin --profile desktop add @jiangzhenguo/dsh-codegraph
& $dsh plugin --profile desktop add dsh-diff-approval
& $dsh plugin --profile desktop add dsh-test-autofix
& $dsh plugin --profile desktop add superpowers-dsh
# 可选
& $dsh plugin --profile desktop add @michengai/dsh-code-review
```

也可以在界面插件市场里按包名逐个装。装完**重启 DSH**。

### 1）语言服务器（给 dsh-lsp-actions）

本机没有任何 Python LSP，装 pyright（npm 全局目录 `C:\nvm4w\nodejs` 在 PATH 上）：

```powershell
npm i -g pyright        # 提供 pyright-langserver
```

在仓库根建 `pyrightconfig.json`（**必须排除备份目录**，否则会去分析 `.local` / `.tmp` / `backups` 里的上万份副本）：

```json
{
  "include": ["anylabeling", "tests", "scripts", "tools", "benchmarks"],
  "exclude": [".local", ".tmp", "backups", "reports", ".git", "dist", "build", "**/__pycache__"],
  "venvPath": "C:\\Users\\20441\\.conda\\envs",
  "venv": "x-anylabeling-cu12",
  "pythonVersion": "3.12",
  "typeCheckingMode": "basic",
  "useLibraryCodeForTypes": true
}
```

再在 `~/.dsh/profiles/desktop/cordis.patch.yml` 追加（id 以插件文档为准）：

```yaml
- id: lsp-actions
  name: dsh-lsp-actions
  config:
    servers:
      pyright:
        command: pyright-langserver
        args: ["--stdio"]
        extensionToLanguage: { ".py": python, ".pyi": python }
        projectMarkers: ["pyproject.toml", "pyrightconfig.json"]
```

> pyright 不做格式化，`lsp_format` 会报 `LSP_ACTION_UNSUPPORTED`，属正常；格式仍走仓库的 pre-commit black(79)。

### 2）代码图谱（给 dsh-codegraph）

```powershell
npm i -g @colbymchenry/codegraph     # Rust 单二进制，Windows 支持
codegraph --version                  # ≥ 1.0
```

- CodeGraph 会读 `.gitignore`（`.local` / `.tmp` / `.tooling` / `.commandcode` 已被忽略；`backups/.gitignore` 是 `*` 也被忽略），必要时再在 `codegraph.json` 里加 `exclude`。
- 在仓库根跑一次 `codegraph_init`（约几十秒），之后自动 sync。
- **不要**再跑 `codegraph install` 给 DSH 接 MCP，会和本插件重复。
- 建议配置：`surface: full`（默认 core 只开 4 个工具，拿不到 `impact` / `affected`）、`frontload: false`（避免往对话里注入额外的 user 消息）。

```yaml
- id: dsh-codegraph
  name: dsh-codegraph
  config:
    surface: full
    guideSearch: true
    frontload: false
```

### 3）测试（给 dsh-test-autofix）——本机两个关键点

- 项目没有 `.venv`，PATH 上的 `python` 是 3.13 且**没有 PyQt6**；必须显式指定 conda 环境，否则跑测试会直接 import 失败：

```powershell
setx DSH_PYTHON "C:\Users\20441\.conda\envs\x-anylabeling-cu12\python.exe"
```

- 本仓库 `.tooling/pytest-shim/sitecustomize.py` 就是为 DSH 沙箱下 pytest 的 `0o700` 目录 ACL 问题准备的；让插件子进程也带上它：

```powershell
setx PYTHONPATH "D:\X-AnyLabeling-4.2.1\.tooling\pytest-shim"
```

设置后重启 DSH（`setx` 只对新进程生效）。

## 四、不建议叠加

- `dsh-tool-lens` / `GraphFlow` / `dsh-codegraph-project`：与 codegraph 功能重叠，工具表会膨胀；**若不想装 Rust CLI，可用 `dsh-tool-lens` 平替 codegraph**（原生零依赖、支持 Python AST、`diff_impact` 同样给回归测试建议）。
- `dsh-programming-mode`：它是 agent preset，会接管全局工程纪律；本仓库已有 openspec，`superpowers-dsh` 作为纯技能增量更合适。
- 不需要再装 Git 面板（`dsh-git-panel` / `dsh-ide-git`）：已有 git graph + 真正的评审交给 diff-approval。

## 五、装完怎么验收

1. 新会话问：「用 lsp_symbols 列出 `anylabeling/views/labeling/label_widget.py` 的符号」→ 应返回类/方法大纲。
2. 「codegraph_status」→ 未索引则 `codegraph_init`；再问「`codegraph_impact G`」应返回调用链。
3. 「run_tests path_filter=test_rectangle_size」→ 应返回通过/失败的 file/line 结构，而不是整段日志。
4. 随便让 agent 改一行 → 侧栏出现待审改动，可逐块回退。
5. 技能目录里应出现 `brainstorming` / `writing-plans` / `test-driven-development` 等 15 个技能。

> 兼容性：`dsh-lsp-actions` 声明 `>=0.2.1-0 <0.3.0 || >=0.2.2-0 <0.3.0`，`dsh-code-review` 已验证 `0.2.2-rc.1`；其余 4 个不声明 peer 限制。本机 DSH 为 `0.2.2-rc.1`，均可装。
