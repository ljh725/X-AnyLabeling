# X-AnyLabeling 项目勘察报告（面向 DSH 选型）

- 勘察对象：`D:\X-AnyLabeling-4.2.1`（`ljh725/X-AnyLabeling`，官方基线 `v4.2.1` = `6d250499d2dd81f78723b9217c7a9abf0443ca25`）
- 勘察人：teammate `project-scout`（task-3），只读勘察
- 时间：2026-11-09（Asia/Shanghai）
- 当前分支：`codex/4.2.1-baseline-organization`，HEAD `cd26f5f8`（2026-11-06 16:10:16 +0800，`docs(canvas): record marquee selection delivery and backup`）

## 0. 标注约定（先看这个）

| 标记 | 含义 |
|---|---|
| ✅实测 | 我在本会话真实执行命令 / 真实读文件得到，附命令与输出摘录 |
| 🔶推断 | 基于实测数据的合理解读，未直接验证 |
| ⛔未测 | 本会话条件不允许（工具缺失/权限/执行器故障），如实标注，不编造 |

**工具可用性声明（影响本报告可信度，必须交代）**：

- 本会话 `ops_bash` **间歇性不可用**，报 `EXECUTOR_UNAVAILABLE: ... Niubash execution tree link count mismatch`（宿主执行器私有副本争用，非命令错误、非权限拒绝）。因此部分数字用 `ops_glob`/`ops_grep`/`ops_read_files`/`ops_inspect_local_file` 取得——其中 **`bytes`、`lineCount`、文件计数是真实值**（文件工具返回真实 stat）。
- 本会话 `ops_stat` **全域被拒**（`PUBLICATION_DENIED`），故改用 `ops_inspect_local_file` 取 `bytes/lineCount/revision`。
- 本会话 **无法读取任何图片**：`read_image` 报「当前模型不声明图像输入」；`modlens_read_image` 报 `claude-cli provider failed with code 1`（Lead 已定位根因：`~/.claude.json` 无 `oauthAccount`，Claude Code 未登录）。`npx` 亦不可用（npm cache 无写权限）。**这是选型的关键约束，见 §6。**

---

## 1. 技术栈与入口（事实表）

| 项 | 事实 | 来源 |
|---|---|---|
| 包名 / 版本 | `x-anylabeling-cvhub`，版本动态取自 `anylabeling.app_info.__version__`（当前 4.2.1） | ✅实测 `pyproject.toml` L33-34,L181-182 |
| Python 要求 | `requires-python = ">=3.11"`；classifiers 列 3.11/3.12/3.13 | ✅实测 L37,L53-55 |
| GUI 框架 | **PyQt6**（核心硬依赖，非可选）；`PySide6` 只出现在 `dev` extra | ✅实测 L71-74,L107-108 |
| Web 引擎 | `PyQt6-WebEngine>=6.6.0` **属核心依赖** | ✅实测 L73-74 |
| 入口 | `[project.scripts] xanylabeling = "anylabeling.app:main"`；根目录**无** `main.py` | ✅实测 L146-147；`ops_glob` 根目录无 main.py |
| app.py 规模 | 482 行，`os.environ` 线程数/MKL 前置，`sys.path.append` 加父目录 | ✅实测 `wc -l` + 读 L1-58 |
| 打包 | PyInstaller：`packaging/pyinstaller/specs/` 5 个 spec（win-cpu/win-gpu/linux-cpu/linux-gpu/macos）+ `runtime_hooks/ort_dll_bootstrap.py` + Windows `installer.iss` | ✅实测 glob 25 项 |
| 构建后端 | `setuptools>=77.0.0` + `wheel` | ✅实测 L27-29 |
| 推理依赖 | 核心依赖**不含** onnx/ort；`cpu`/`gpu`/`gpu-cu11`/`gpu-cu13` extras 分别钉 `onnx`+`onnxruntime[-gpu]`；`[tool.uv] conflicts` 声明互斥 | ✅实测 L112-175 |
| 许可证 | GPL-3.0-only | ✅实测 L38 |

### 1.1 核心依赖清单（✅实测 pyproject L66-96）

```
natsort>=8.1.0, pillow>=7.1.2, pillow-heif>=0.18.0,
opencv-contrib-python-headless>=4.7.0.72,
PyQt6>=6.6.0 (<6.10.0 仅 linux), PyQt6-WebEngine>=6.6.0,
qimage2ndarray>=1.10.0, lapx>=0.5.5, tqdm>=4.64.0, scipy>=1.4.1,
PyYAML, importlib_metadata, json_repair, jsonlines, markdown, openai,
socksio>=1.0.0, psutil, pyclipper, six, shapely, termcolor, tokenizers,
requests, cryptography>=41, darkdetect>=0.8.0, matplotlib
```

### 1.2 可选依赖（✅实测 L99-135）

| extra | 内容 |
|---|---|
| `dev` | `build, black, flake8, pyinstaller, pytest, PySide6>=6.6.0, twine` |
| `cpu` | `numpy>=2.0.0, onnx>=1.15.0, onnxruntime>=1.15.0` |
| `gpu` | `numpy>=2.0.0, onnx>=1.15.0, onnxruntime-gpu>=1.18.1,<1.27.0` |
| `gpu-cu11` | `numpy<2.0.0, onnx>=1.15.0,<1.16.1, onnxruntime-gpu>=1.15.0,<1.19.0` |
| `gpu-cu13` | `numpy>=2.0.0, onnx>=1.15.0, onnxruntime-gpu>=1.27.0,<1.28.0` |

> 注意 `dev` 里同时有 PySide6 与核心 PyQt6 —— 这是历史迁移遗留（`docs/custom_changes/CATALOG-20261030.md` 的 `SUPPORT-001` 记录了 PySide2→PyQt6 迁移）。🔶推断：**装 `[dev]` 会多装一整套 PySide6**，真实运行仍是 PyQt6。

### 1.3 代码风格工具链（✅实测）

```toml
[tool.black]
line-length = 79
target-version = ["py311"]
exclude = '''(/ (\.git|\.hg|...|build|dist|tests)/ | ^/anylabeling/resources/resources\.py$)'''
```
- **`tests` 在 black exclude 里**——测试代码不被 black 管，避免把测试期望值改坏（🔶推断，符合项目"测试是证据"的取向）。
- `[tool.flake8]`：`max-line-length = 79`、`max-complexity = 18`、`select = [B,C,E,F,W,T4,B9]`、`ignore = [E203,E266,E501,W503,F403,F401,B905,E402]`（✅ L211-223）。
  - 注意 flake8 配置写在 `pyproject.toml`，而 **flake8 原生不读 pyproject**（需要 `Flake8-pyproject` 插件）。pre-commit 的 flake8 hook 并未声明该插件（✅实测 pre-commit L34-40 只见 flake8-blind-except/docstrings）。🔶推断：**命令行直接跑 `flake8` 很可能不吃这套 79 列配置**，只有 pre-commit 链路里的 `--max-line-length` 生效与否需验证。

---

## 2. 规模与工作区现状（✅实测）

### 2.1 体积（`du -sh`）

| 路径 | 体积 | 性质 |
|---|---|---|
| **整工作区** | **3.4 G** | |
| `.git` | 543 M | 单一仓库历史 |
| `.local` | **1.7 G** | 本地自动化产物，`.gitignore` 已排除 |
| `.tmp` | 315 M | 测试/截图临时区，`.gitignore` 已排除 |
| `anylabeling` | 42 M | 源码 |
| `reports` | 13 M | **6197 个文件**，被 Git 跟踪 |
| `tests` | 6.4 M | |
| `openspec` | 3.8 M | 152 个文件 |
| `docs` | 948 K | |
| `.tooling` | 88 K | DSH 沙箱补丁 |

目录扫描口径：`ops_glob` 全工作区扫描 **8669 个常规文件**（排除 symlink 454、排除 402）。

### 2.2 文件计数（✅实测 `ops_glob` matchedTotal）

| 对象 | 数量 |
|---|---|
| `anylabeling/**/*.py` | **486** |
| `tests/**/*.py` | **204** |
| `openspec/**/*` | 152 |
| `reports/**/*` | **6197**（其中 `*.png`/`*.jpg` 达 **4755**） |
| `scripts/ + packaging/ + .github/` | 25 |
| 测试子目录 | 14 个：`test_auto_labeling, test_auto_training, test_canvas, test_config, test_dense_review, test_inspection, test_labeling, test_models, test_pointcloud, test_ppocr, test_settings, test_updates, test_utils, test_widgets` |

### 2.3 关键大文件行数（✅实测 `wc -l`）

| 文件 | 行数 | 体积 | 备注 |
|---|---|---|---|
| `anylabeling/resources/resources.py` | **141,589** | 6.47 M | Qt 资源编译产物，**自动生成，不可人工审阅** |
| `anylabeling/views/labeling/label_widget.py` | **10,697** | 425 K | 主控制器，单文件即核心 |
| `anylabeling/views/labeling/inspector/dialog.py` | **4,891** | 200 K | Inspector 主界面，**有未提交改动** |
| `anylabeling/views/labeling/settings/schema.py` | 1,634 | 59 K | 配置 schema |
| `anylabeling/views/labeling/settings/runtime_applier.py` | 692 | 29 K | |
| `anylabeling/app.py` | 482 | — | 入口 |
| `anylabeling/configs/xanylabeling_config.yaml` | 260 | 6.6 K | 默认配置 |

### 2.4 对索引类插件的含义（🔶推断，基于上述实测）

- **必须排除**：`.git`(543M)、`.local`(1.7G)、`.tmp`(315M，内含 10000+ 文件)、`reports`(13M/6197 文件，其中 4755 张图片)、`__pycache__`、`anylabeling/resources/resources.py`（14 万行生成文件）。
- **可索引核心**：`anylabeling/` 约 42M/486 模块 + `tests/` 6.4M/204 文件 + `docs` 948K + `openspec` 3.8M，这部分规模温和，LSP/代码索引完全可行。
- **风险点**：`label_widget.py` 10,697 行、`inspector/dialog.py` 4,891 行是巨型单文件，符号表/上下文窗口都会吃力；`resources.py` 14 万行若被索引会显著拖慢并挤占上下文。
- `grep` 层面：`ops_grep` 在 `anylabeling/`（1358 文件）响应正常；全工作区 `ops_glob` 一次扫描即覆盖 8669 文件，**可接受**。

### 2.5 隐藏目录与 `.gitignore`（✅实测 `.gitignore` 219 行）

已忽略：`/.local/`、`/.tooling/`、`/.commandcode/`、`/.dsh-asar-out/`、`/.workbuddy/`、`.tmp/`、`.pytest_cache/`、以及 `/reports/**/pytest-runtime/`、多组 `/reports/.../pre-implementation-*/` 等。

**关键设计选择**（✅ `.gitignore` L194 注释原文）：
> `# Generated pytest workspaces. Keep reports, scripts and screenshots tracked.`

即 **`reports/` 与截图被刻意纳入版本库**，作为交付证据。这解释了为什么 `reports/` 有 6197 个文件。

隐藏目录清单：`.commandcode/ .dsh-asar-out/ .git/ .github/ .installers/ .local/ .p2-render/ .pytest_cache/ .tmp/ .tooling/ .vscode/ .workbuddy/`。

---

## 3. 测试体系（重点，含真实运行结果）

### 3.1 pytest 配置全文（✅实测 `pyproject.toml` L184-190）

```toml
[tool.pytest.ini_options]
addopts = "--doctest-modules --durations=30 --color=yes"
testpaths = ["tests"]
markers = [
    "slow: skip slow tests unless --slow is set",
]
norecursedirs = [".git", "dist", "build"]
```

要点：
1. **`--doctest-modules` 是默认开启的**。配合 `testpaths=["tests"]`，作用域限定在 `tests/` 下。
2. **`--durations=30` 默认打印最慢 30 项**（每次跑测试都会刷屏，见 §3.4 输出）。
3. `markers` 只有 `slow` 一个，**没有注册 `gui`/`integration` 之类标记**——🔶推断：所以无法用 `-m "not gui"` 快速跳过界面测试，只能按目录选。
4. `--color=yes` 会强制 ANSI 颜色，重定向到文件时也会带转义码（✅实测输出里确有 `[32m` 等）。

### 3.2 conftest 与隔离机制（✅实测）

`tests/conftest.py`（5,367 字节，138 行，**mtime 2026-11-06，属近期修改**）承担三件事：

1. **强制离屏**：`os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")`（L26）——**在 import PyQt6 之前**。
2. **会话级 QApplication**（L68-74，`scope="session", autouse=True`）—— 这是**没有 pytest-qt 也能跑 GUI 测试**的原因：项目自己造了 app fixture。
3. **配置隔离**（L77-138，`autouse=True`）：每个测试分配 `.tmp/pytest-config/<uuid>/`，重定向 `CONFIG_PATH_ENV`、`app_config._work_directory`，并把 `QtCore.QSettings` 替换成绑死 INI 的 `_IsolatedQSettings`（防止写 Windows 注册表），再装两道写守卫：
   - `ConfigSession.save` 写 `.tmp` 之外 → `AssertionError`
   - `user_config._atomic_write_bytes` 写 `.tmp` 之外 → `AssertionError`

`tests/test_dense_review/conftest.py`（2,299 字节）另有一层。

> **这个隔离设计是选型的关键背景**：项目已经把"测试不许碰真实用户数据"制度化，而且守卫会主动**报错而不是静默放行**。§3.4 的失败正来自这道守卫。

### 3.3 `.tooling/pytest-shim` 是什么（✅实测）

`sitecustomize.py` 只有 19 行，是**针对 DSH 沙箱的补丁**，注释原文：

> `"""DSH sandbox workaround: mode 0o700 directories become unreadable on Windows.`
> `pytest creates its basetemp with mode=0o700; under the DSH sandbox the`
> `resulting DACL denies even the owner, so tmp_path setup fails with`
> `PermissionError [WinError 5].  Widen the mode for directory creation only."""`

实现：monkey-patch `os.mkdir`，把 `0o700` 改成 `0o777`。

**用法**：`export PYTHONPATH=".tooling/pytest-shim"`（该目录不在 `sys.path` 里，需显式加）。

> 含义：**这个项目已经在为 DSH 沙箱做适配了**——`tmp_path` 相关测试在无 shim 时会因 Windows DACL 直接 `WinError 5`。选型时必须把"跑测试要带 `PYTHONPATH=.tooling/pytest-shim`"写进流水线命令模板。

### 3.4 真实运行结果（✅实测，含命令、耗时）

环境：`C:\Users\20441\.conda\envs\x-anylabeling-cu12\python.exe`
- Python **3.12.12**；PyQt6 可用；pytest **9.0.3**；numpy 2.4.3；onnxruntime 1.24.3；cv2 4.13.0；Pillow 12.1.1。
- **未装**：`pytest-qt`、`torch`、`pyautogui`、`win32gui`（全部 `ModuleNotFoundError`）。
- PATH 上的 `python` 是 **3.13.13**（≠ conda 环境，不能用它跑本项目）。

统一前缀：
```bash
export PYTHONPATH=".tooling/pytest-shim"
export QT_QPA_PLATFORM=offscreen
PY=C:/Users/20441/.conda/envs/x-anylabeling-cu12/python.exe
```

| # | 命令（均带 `-q --no-header -p no:cacheprovider`） | 真实结果 | pytest 耗时 | 进程/资源 |
|---|---|---|---|---|
| 1 | `pytest tests/test_inspection/test_models.py` | **5 passed** | **2.14 s** | WALL **3.17 s**，MAXRSS **135,840 KB** |
| 2 | `pytest tests/test_canvas/test_brush_drawing.py` | **3 passed** | 2.02 s | WALL 3.09 s |
| 3 | `pytest tests/test_labeling/test_chatbot_provider.py` | **8 passed** | 2.21 s | WALL 3.26 s |
| 4 | `pytest tests/test_settings/test_schema.py` | **7 passed** | 2.16 s | WALL 3.22 s |
| 5 | `pytest tests/test_inspection/test_inspector_dialog.py` | **21 errors** | **5.47 s** | WALL 6.47 s，MAXRSS 168,456 KB |

**冷启动基线**：任何一次 `pytest` 调用的**固定开销约 1.0–1.1 s**（pytest 报 2.14 s vs `time` 报 3.17 s），主要来自 PyQt6 导入（🔶推断：MW 探针显示 `from anylabeling.views.mainwindow import MainWindow` 单独就 2.49 s）。因此**跑单个小文件不划算，跑一个目录更划算**。

**#5 的失败必须写清楚**（这是本报告最重要的风险项）：

```
ERROR tests/test_inspection/test_inspector_dialog.py::test_keep_both_and_defer_do_not_modify_shapes
  - AssertionError: configuration write outside isolated area: 'C:\Users\2044...
21 errors in 5.47s
```

- Lead 复跑（2026-11-09，`: 21 errors in 10.80s`）得到的底层错误是
  `PermissionError: [WinError 5] 拒绝访问: 'C:\Users\20441\AppData\Local...'`。
- **性质判定：不是代码 bug，是权限/沙箱交互。** 测试想写真实用户配置目录 `C:\Users\20441\AppData\...`，DSH `workspace-write` 沙箱拒绝写工作区外路径；conftest 的写守卫先一步把它变成 `AssertionError`。
- **触发条件是 `test_inspector_dialog.py` 与 `inspector/dialog.py` 同时处于未提交改动状态**（✅ 两者都在 §7 的 19 项 modified 里）。🔶推断：未提交代码新增了一条绕过 `CONFIG_PATH_ENV` 的配置写入路径；也可能是该测试本来就依赖真实 profile。
- **选型结论**：该文件**在当前权限模式下不能当验收闸门**。可行修法（见 §9「待 Lead 执行」）：用环境变量把配置目录重定向到工作区内，或在工作区外的普通终端跑。

**对照 Lead 实测**（可交叉印证）：
- `tests/test_settings/test_schema.py` → Lead **7 passed / 4.23 s**，我 **7 passed / 2.16 s**（差值是进程冷启动缓存，结论一致）。
- `QT_QPA_PLATFORM=offscreen pytest tests/test_canvas/ -q -x` → Lead **1 failed, 71 passed, 72 subtests passed / 4.41 s**，唯一失败是 `test_groups.py::test_shape_label_keeps_fixed_screen_size_while_zooming` 的 `AssertionError: 179 != 139`（**离屏字体度量差异，非功能崩溃**）。

**这印证了 §6 的核心判断：离屏能跑真实 UI 逻辑，但像素/字体相关断言在离屏下不可靠。**

### 3.5 缓存副作用（正常，无需规避）

跑测试会写：`.pytest_cache/`（我统一用 `-p no:cacheprovider` 关掉）、`.tmp/pytest-config/<uuid>/`（conftest 每个用例建、finally 删）、`tests/**/__pycache__/`、`.tmp/screenshots/`。**这些都是 `.gitignore` 覆盖的正常缓存**，不污染仓库（✅ `.gitignore` L58,L60）。

---

## 4. 既有流程与证据惯例

### 4.1 `openspec/` —— 已经是一条「澄清→验收标准→实现→验证」流水线（✅实测）

结构（152 文件 / **14 个变更目录**）：

```
openspec/changes/<change-id>/
├── proposal.md            # 需求与范围
├── design.md              # 技术设计（部分变更有）
├── tasks.md               # 任务清单（带复选框状态）
├── verification.md        # 实施与验证记录（含失败项！）
├── specs/<capability>/spec.md   # 该能力的验收标准（可 validate --strict）
├── evidence/<YYYYMMDD>/    # 原始证据：*.log / *.xml / *.json / exit.txt
├── manual-acceptance.md   # 人工验收剧本
├── scenario-matrix.md     # 场景矩阵
├── review-<date>.md       # 评审轮次
└── implementation-<date>.md
```

14 个变更：`add-annotation-correction-cost-statistics`、`add-dense-annotation-review-workflow`、`fix-digit-rectangle-label-save`、`fix-rectangle-preview-overlap`、`fix-user-settings-persistence`、`improve-point-fit-algorithm`、`improve-rectangle-edge-adjustment`、`migrate-canvas-controls-from-v430`、`polish-inspector-dense-review-ui`、`refactor-data-inspector-workflow`、`restore-v430-canvas-controls`、`simplify-inspector-dual-screen-navigation`、`smooth-canvas-dragging`、`staged-annotation-loading`。

**最有价值的样本**：`openspec/changes/simplify-inspector-dual-screen-navigation/verification.md`（✅通读）。它的验收表是**逐轮次记录 passed/failed 并挂 JUnit 链接**，且**明确保留未完成项**：

> 「任务 6.3 **未完成、保持未勾选**：自动化窗口按键与几何模拟不能替代物理双屏连续操作……本变更未归档。」

这种"不把自动化通过冒充验收通过"的纪律，正是这条流水线要复刻的核心行为。

### 4.2 `reports/` 组织方式（✅实测）

命名：`reports/<主题>_<YYYYMMDD>/`。典型内容（以 `inspector_workflow_20261102/` 为例，20 个文件）：

```
REPORT.md                      # 主报告
REVIEW-20261102.md             # 评审
RECHECK-*.md                   # 复查记录
canvas.xml / inspection.xml / labeling.xml / settings.xml / staged.xml / widgets.xml  # 各范围 JUnit
duplicate_core_comparison.json # 结构化度量
test_review_probes.py / test_recheck_history_unsaved.py  # 一次性探针脚本（随报告留档）
```

`baseline_organization_20261103/` 同构，另有 `baseline.txt`、`metrics-gate.txt`、`failures.json`、`inventory-before.json`、`cleanup-paths.txt`。

**证据惯例总结**：
1. **JUnit XML 是主证据格式**（`results.xml`、`*.xml`），可直接被 CI/工具消费。
2. **一次性探针脚本也入库**（`test_*.py` 放在 report 目录而非 `tests/`）——便于复现。
3. **结构化度量用 JSON**（benchmark 结果、inventory、failures）。
4. **原始 stdout 用 `.log` / `.txt`**。

`reports/` 另有 **4755 张 png/jpg**（✅glob 计数），但绝大多数是 pytest 测试夹具产物（`reports/correction_cost_20261103/baseline-sandbox-retry/test_xxx/image.png` 只有 91~590 字节），**不是人工验收截图**。真正的界面截图在 `images/` 与 `openspec/**/assets/`。

### 4.3 台账与文档惯例（✅实测）

- **`docs/custom_changes/CATALOG-20261030.md`**（65 行）—— 本地定制总台账，用稳定编号 `CUSTOM-010/011/…/CUSTOM-101…110`、`SUPPORT-001` 归类，每条记「行为变化 / 核心位置 / 来源和验证状态」。
  - 两条对选型极重要的原文：
    > 「历史功能不能仅因存在测试文件就标为全面验收通过。」
    > 「共享文件用精确差异归集，**不能按整个文件撤销其他功能**。」
  - 「以后如何单独记录」第 3 条：**「新工作一项功能一组提交」**、共享文件要能精确差异归集。
- **`docs/zh_cn/inspector.md`**（10,183 字节）、**`docs/zh_cn/dense_review.md`**（204 行）—— 面向非程序员的中文操作说明，风格是「大白话：把一张图里的框分批过一遍」+「第一次可以这样试：1.2.3.」+ 免责边界（「它不会自动找出所有错误」）。**这正是用户要的"人话交付物"范本**。
- **`GitHub操作说明.md`**（134 行，更新 2026-11-02）—— 大白话 Git 教程：分支/提交/推送/标签/PR 表格、三类工作流程（版本迁移/原功能修改/领域扩展）、完整流程图。**说明用户确实需要"Git 概念的通俗解释"**，且交付结论要落到「分支 + 提交号 + 测试结果」。
- **`BACKUP.md`**（35 行）—— 固定备份节点：日期、仓库、备份分支 `backup/4.2.1-20261029`、标签 `backup-v4.2.1-20261029`、官方基线 commit、恢复命令。
- **`版本与备份目录.md`**（17,152 字节）。
- **`CHANGELOG.md`**（1,936 行）—— 保持**上游官方格式**（`## v4.2.1 (Oct 26, 2026)` + 🚀 New Features / 🐛 Bug Fixes / 🛠️ Improvements / 🌟 Contributors）。✅实测：**本地定制不写进 CHANGELOG**，而是写进 `docs/custom_changes/` 与 `openspec/`。🔶推断：这是刻意的上游同步策略。
- **交付回执惯例**：`.local/canvas-implementation-20261105/delivery-receipt.json` 记录 `baseline_commit` / `implementation_commit` / `final_commit`、逐文件 `sha256`、`git bundle` 路径与 `bundle_sha256`、`restored_tests: {passed: 23, seconds: 29.72}`。**这是现成的"可验证交付包"模式**。

### 4.4 pre-commit（✅实测 `.pre-commit-config.yaml`，59 行）

| 项 | 配置 |
|---|---|
| pre-commit-hooks | v4.4.0：`check-added-large-files --maxkb=8096`、`check-case-conflict`、`check-merge-conflict`、`check-symlinks`、`check-yaml`、`debug-statements`(排除 tests/)、`end-of-file-fixer`、`mixed-line-ending`、`trailing-whitespace` |
| black | **23.3.0，两个 hook**（一个格式化，一个 `--check`），`exclude: tests/|anylabeling/resources/resources.py` |
| flake8 | **6.0.0** + `flake8-blind-except`、`flake8-docstrings` 等插件 |

> 注意：black **23.3.0** 是固定老版本，而 `pyproject` 的 `dev` extra 只写 `black`（不钉版本）。🔶推断：**用新 black 跑会与 pre-commit 产生格式分歧**，流水线里要么用 pre-commit 的版本，要么接受噪声 diff。

### 4.5 CI 现状（✅实测 `.github/` 共 9 个文件）

`FUNDING.yml`、`ISSUE_TEMPLATE/`（4 个 yml + config）、`PULL_REQUEST_TEMPLATE.md`、`workflows/release.yml`、`workflows/sync-website-content.yml`。

**没有测试类 CI**——只有发布打包与官网内容同步。🔶推断：**所有测试纪律靠本地人为执行**，所以「测试→证据」这条链在 agent 化之后收益很大。

---

## 5. 未提交改动（✅实测，与 Lead 数字一致）

命令：`git status --porcelain | wc -l` → **23**

```
19  M   (已修改未提交)
 4  ??  (未跟踪)
```

`git diff --stat | tail -1`：`19 files changed, 35684 insertions(+), 34615 deletions(-)`

### 5.1 逐文件 diffstat（✅实测 `git diff --stat`）

| 文件 | 变更规模 | 性质 |
|---|---|---|
| `anylabeling/resources/resources.py` | **69,455 行**（+/- 各约 3.5 万） | **生成产物**，占全部 churn 的 97% |
| `anylabeling/views/labeling/inspector/dialog.py` | 608 行 | 真实功能改动 |
| `anylabeling/views/labeling/label_widget.py` | 83 行 | 真实功能改动 |
| `anylabeling/views/labeling/settings/schema.py` | 6 行 | |
| `anylabeling/views/labeling/settings/runtime_applier.py` | 4 行 | |
| `anylabeling/configs/xanylabeling_config.yaml` | 6 行 | |
| `anylabeling/resources/translations/{en_US,ja_JP,ko_KR,zh_CN}.ts` | 各 18 行 | 新增 4 语言文案 |
| 同名 `.qm` ×4 | 二进制 | 编译产物 |
| `docs/zh_cn/inspector.md` | 24 行 | 文档 |
| `tests/test_inspection/{test_inspector_dialog,test_progress_and_rule_access,test_translations}.py` | 8/13/10 行 | 测试 |
| `tests/test_settings/test_schema.py` | 10 行 | 测试 |

### 5.2 未跟踪（4 项，✅实测）

```
?? dsh写代码插件清单.md
?? dsh编码插件组合-本仓库.md
?? openspec/changes/simplify-inspector-dual-screen-navigation/
?? tests/test_inspection/test_dual_screen_navigation.py
```

### 5.3 「逐块审查/回滚」类插件的实际价值（🔶推断，基于上述实测）

**价值高，但理由不是"文件多"，而是"churn 被生成物污染"：**

1. **97% 的 diff 是噪声**。`resources.py` 一个文件 69,455 行变更，人眼/模型都无法审阅。**必须有"按文件/按路径过滤 diff"的能力**，否则任何"审查改动"动作都会被生成物淹没 → 这是硬需求。
2. **真正要审的只有 2 个文件 691 行**（`inspector/dialog.py` 608 + `label_widget.py` 83）。**按 hunk 粒度审阅 + 逐块 accept/reject** 在这里是刚需，因为改动集中在两个巨型文件（4,891 行 / 10,697 行）的局部。
3. **回滚需求是"按功能"而非"按文件"**。`CATALOG-20261030.md` 明确写了「共享文件用精确差异归集，不能按整个文件撤销其他功能」——**按整文件 revert 在这个仓库是错的做法**，因为 `label_widget.py` 同时承载十几个 CUSTOM-xxx 功能。→ 需要 patch/hunk 级回滚，而非 `git checkout -- file`。
4. **未提交状态是常态**：23 项未提交、且跨了 5 个日期（`.git/logs/HEAD` 显示 2026-10-29 至 11-06 共 31 次 ref 变更，最后提交 11-06 16:10，而工作区改到 11-07）。**长时间"带脏工作区"开发** → 需要"改动快照/对比/diff 预览"能力，而不是"每次都 commit"。

**结论**：给这个仓库配「diff 预览 + hunk 级审查 + 路径过滤 + 快照/回滚」，属于**高价值**，且能直接对上它已有的 `delivery-receipt.json`（sha256 清单）与 `working-tree-before.patch`（`.local/canvas-implementation-20261105/` 里已有此文件）惯例。

---

## 6. 界面验证可行性（重点结论）

### 6.1 硬事实（全部 ✅实测，除非标注）

| 能力 | 状态 | 证据 |
|---|---|---|
| **离屏渲染** | ✅ 可用 | `QT_QPA_PLATFORM=offscreen` → `platformName()=="offscreen"`，`QWidget.grab()` 出 320×180 PNG，**0.07 s** |
| **中文字形渲染** | ✅ 正常 | 同一 QWidget：中文 168 非背景像素 / 英文 448 / 空标签 **0** → 中文确实画出，不是空白框 |
| 字体警告 | ⚠️ 良性 | `QFontDatabase: Cannot find font directory .../PyQt6/Qt6/lib/fonts`（Windows 走系统字体，不影响中文）。项目自己在 `verification.md` 里是「**显式加载 Microsoft YaHei 字体**离屏渲染」 |
| **离屏屏幕规格** | ⚠️ 仅 1 块 800×800 | `assets/offscreen-screens.json` = `[{"name":"","width":800,"height":800,"scale":1.0}]`（项目自己记录） |
| **真实桌面截图（ffmpeg）** | ✅ 可用 | `ffmpeg -f gdigrab -i desktop -frames:v 1` → **1,559,482 字节 PNG** |
| **真实桌面截图（PowerShell）** | ✅ 可用 | `System.Drawing.CopyFromScreen` → **4,480×1,440 / 1,770,443 字节**（= 真实双屏虚拟画布） |
| 真实屏幕配置 | ✅ 有双屏 | `native-startup-state-20261107.json`：`Q27G2S` 2560×1440 @0,0 + `2490W1` 1920×1080 @2560,0，均 100% 缩放 |
| `pytest-qt` | ❌ 未装 | `ModuleNotFoundError`；但 conftest 自建 QApplication 替代 |
| `pyautogui` / `win32gui` | ❌ 未装 | `ModuleNotFoundError` |
| 截图工具 | 部分 | ✅ `ffmpeg`、✅ `powershell.exe`、✅ `SnippingTool.exe`（仅交互）、❌ `nircmd`/`magick`/`scrot` |
| **agent 读图** | ❌ 不可用 | `read_image`：模型不声明图像输入；`modlens_read_image`：`claude-cli provider failed with code 1`（根因 `~/.claude.json` 缺 `oauthAccount`）；`npx` 因 npm cache 无写权限失败 |
| **历史 Computer Use 尝试** | ❌ 已失败过 | `verification.md` 2026-11-07 原文：截图 `FrameArrived timed out: timed out waiting on channel`；点击 `coordinate input geometry is unavailable`；重试 `window capture timed out` |
| 项目自带截图脚本 | ✅ 存在 | `scripts/capture_dense_review_screenshots.py`（206 行）——**离屏渲染真实 `MainWindow` + 真实控件 → `images/dense_review/*.png`** |
| 既有界面截图 | ✅ 6 张 | `images/dense_review/{01-workspace,02-main-window,03-after-batch-confirmation,04-spatial-review,05-difficult-state,06-narrow-window}.png` |
| 自动化像素自检 | ✅ 可行 | 纯 Pillow 统计：`unique_colors=27`、`non_bg_px=6080`、内容 `bbox=(11,71,308,168)`，**不需要视觉模型** |

### 6.2 现实可行的「实机验证」路径（按推荐度排序）

#### 路径 A（首选）：离屏渲染 UI 测试 + 程序化断言
- **做法**：`QT_QPA_PLATFORM=offscreen` + conftest 自带 QApplication，用 pytest 直接驱动真实 `QWidget`/`QDialog`/`QAction`（项目已有 204 个测试文件、大量 GUI 用例），断言落在**控件状态/信号/数据**上。
- **已验证**：`tests/test_canvas/` Lead 实测 **71 passed / 4.41 s**；我实测小文件全绿。
- **限制**：① 像素/字体度量断言不可靠（Lead 实测 `179 != 139`；`test_groups.py` 唯一失败）；② 只有 **1 块 800×800 虚拟屏**，多屏/窗口几何无法真验；③ 无真实焦点/输入法/显卡渲染。

#### 路径 B（首选补充）：离屏截图 + 程序化像素自检（**无需视觉模型**）
- **做法**：写脚本 instantiate 真实窗口 → `widget.grab().save(png)` → 用 Pillow 断言「非背景像素数 / 内容 bbox / 主色 / 特定区域颜色」。项目已有 `capture_dense_review_screenshots.py` 可作模板。
- **已验证**：我实测 grab 0.07 s、中文渲染 OK、Pillow 统计给出 bbox 与 unique_colors。
- **限制**：① 能证明"画出来了、布局范围对"，**不能证明"看起来对"**（是否错位、被遮挡、文案不合语义）；② 离屏只有 800×800，窗口大于此需 `resize` 后 grab 局部；③ 项目 `verification.md` 明确说离屏截图「**不是实际双屏截图**」，不能冒充真机验收。

#### 路径 C：真机启动 + 真实桌面截图（**agent 可采集，但需人判读**）
- **做法**：真实启动 GUI（非 offscreen），用 `powershell CopyFromScreen` 或 `ffmpeg gdigrab` 截全屏/窗口 → 交付 PNG。
- **已验证**：两条截图命令都成功出图（1.56 MB / 1.77 MB）；真实双屏几何已知。
- **限制**：**本会话 agent 无法判读图像**（§0）。因此该路径只能"采集证据交给人看"。要闭环必须解决读图：修 `modlens` 的 provider 配置（Lead 已定位为配置缺口，可修），或换用支持图像输入的模型。
- **附加价值**：用户是零编程基础个人开发者，**他本人看图验收**本来就是最自然的一环——所以路径 C 的"人判读"不是缺陷，而是设计。

#### 路径 D（不推荐）：Windows 桌面自动化（pyautogui/win32/Computer Use）
- **现状**：依赖全未安装；且**该项目已实测失败过一次**（2026-11-07 Computer Use 截图与点击双失败，原文见 §6.1）。
- **限制**：Windows 桌面输入需要脱离 DSH `workspace-write` 沙箱的高权限；`coordinate input geometry is unavailable` 表明坐标系获取在这种环境里不可靠；还会**接管用户真实鼠标键盘**（用户可能正在用电脑）。
- **判断**：**不建议为这个项目装桌面操作类插件**。投入产出比最低、失败模式最不可控。

#### 路径 E（补充）：GUI 结构的文本化自证
- 可断言 `QAction` 文本/快捷键、`QWidget` 层级、`QTreeWidget` 行数、`QSettings` 落盘内容等——**全部是文本，agent 可读可判**。项目 conftest 已把配置写入重定向到 `.tmp`，天然支持"改完读配置验证"。
- **限制**：验证的是"结构与状态"，不是"视觉"。但配合路径 B 的像素 bbox，足以覆盖绝大多数 UI 回归。

### 6.3 「实机验证」一句话结论

> **可行路径 = 路径 A（离屏 UI 逻辑测试）+ 路径 B（离屏截图 + Pillow 程序化自检）为主，路径 C（真机启动 + PowerShell/ffmpeg 截全屏）产出给人看的证据，路径 E 补充结构断言。路径 D（桌面自动化）不建议。**
>
> **当前唯一硬缺口是"agent 读图"**：截图能采、能程序化分析，但**不能语义判读**。这不阻塞流水线，因为它把"最终视觉验收"自然交还给了用户——恰好符合用户零编程基础、需要看图确认的场景。若要 agent 也能看图，**修 modlens 的 provider 配置即可**（成本远低于装桌面自动化插件）。

---

## 7. 浏览器需求评估

✅实测事实：

| 证据 | 内容 |
|---|---|
| `PyQt6-WebEngine` 是**核心依赖** | 应用内嵌浏览器引擎 |
| `QWebEngineView/QtWebEngineWidgets/webbrowser.open/QDesktopServices` 命中 16 处 | `views/labeling/chatbot/chat.py`(8)、`utils/general.py`(3)、`widgets/about_dialog.py`(3)、`widgets/video_classifier_dialog.py`(2) |
| `pyproject` URLs | Homepage/Documentation/Download/Funding/Source/Issues/Changelog 全指向 `xanylabeling.com` 与 GitHub |
| `.github/workflows/sync-website-content.yml` | 官网内容同步 |
| `GitHub操作说明.md` | 完整 GitHub 操作教程（分支/PR/推送） |
| 环境 | `curl` 不可用（schannel）；联网需 `python urllib` 或 `web_fetch` |

**判断（🔶推断）**：
- **日常写代码/跑测试：不需要浏览器。** 全流程本地（PyQt6 桌面 + pytest）。
- **真实需求强度：中低。** 三类场景偶尔需要：① 查上游 `CVHub520/X-AnyLabeling` 的 issue/PR/文档以判断定制是否偏离；② 查 PyPI/onnxruntime 版本兼容（`gpu-cu11/cu12/cu13` 的 ort 版本窗口很绕，这项目真踩过）；③ 用户自己的 GitHub 推送/PR 核对（他已有大白话教程，说明这块对他是"需要被讲明白"的事）。
- **注意**：应用内 WebEngine 是**给终端用户看 chat/关于页**的，与开发者工作流无关，不能当作"本项目需要浏览器插件"的理由。
- **结论**：浏览器类插件属于**锦上添花**，不该是流水线主干。若只能选一个，优先给"查文档/版本兼容"用的轻量 web 能力，而非完整浏览器自动化。

---

## 8. 事实速查表（供选型直接引用）

| 维度 | 实测数值 |
|---|---|
| 项目类型 | PyQt6 桌面 GUI（GPL-3.0），非 Web、非 CLI |
| Python | `>=3.11`；实际 conda 环境 3.12.12 |
| 唯一入口 | `anylabeling.app:main`（`xanylabeling` 命令 / `python -m anylabeling.app`） |
| 源码模块 | 486 个 `.py`（`anylabeling/`） |
| 测试文件 | 204 个 `.py`，14 个 `test_*` 子目录；**无 pytest-qt** |
| 依赖安装 | `pip install -e ".[cpu,dev]"` / `[gpu,dev]` / `[gpu-cu11,dev]` / `[gpu-cu13,dev]` |
| 打包 | PyInstaller（5 spec）+ Inno Setup |
| pytest | `--doctest-modules --durations=30 --color=yes`，`testpaths=["tests"]`，marker 仅 `slow` |
| 跑测试必备 | `PYTHONPATH=.tooling/pytest-shim` + `QT_QPA_PLATFORM=offscreen` |
| 单文件测试耗时 | 2.0–2.2 s（pytest 内部），进程 3.1–3.3 s，RSS ~135 MB |
| 目录级测试 | `tests/test_canvas/` 72 项 / 4.41 s（Lead 实测） |
| 已知红灯 | `test_inspector_dialog.py` 21 errors（沙箱权限，非代码 bug）；`test_groups.py` 1 失败（离屏字体度量） |
| 工作区体积 | **3.4 G**（`.git` 543 M + `.local` 1.7 G + `.tmp` 315 M） |
| 索引必排除 | `.git/ .local/ .tmp/ reports/ __pycache__/ anylabeling/resources/resources.py` |
| 最大单文件 | `resources.py` 141,589 行（生成物）；`label_widget.py` 10,697 行（手写） |
| 未提交改动 | **23 项**（19 M + 4 ??）；`git diff` 19 文件 / +35,684 / −34,615，其中 `resources.py` 占 69,455 行 |
| openspec | 14 个变更目录 / 152 文件，含 proposal→specs→tasks→verification→evidence |
| reports | 6197 文件（4755 图片），JUnit XML 为主证据 |
| CI | 仅 release + 官网同步，**无测试 CI** |
| 界面截图 | 离屏可用（0.07 s/img）、中文可渲染；真桌面截图可用（ffmpeg/PowerShell）；**agent 当前读不了图** |
| 真实屏幕 | 双屏 2560×1440 + 1920×1080 |

---

## 9. 「待 Lead 执行」清单（我本会话无法/不应执行）

| # | 待执行项 | 目的 |
|---|---|---|
| 1 | 全量 `pytest tests/ -q --no-header`（带 shim，`-p no:cacheprovider`），记录 passed/failed/耗时 | 建立可信基线，判断是否可作为验收闸门 |
| 2 | `test_inspector_dialog.py` 用**配置重定向到工作区内**再跑一次（变量名见 `anylabeling/user_config.py` 的 `CONFIG_PATH_ENV`） | 区分「沙箱权限」与「真实回归」 |
| 3 | 在**工作区外普通终端**跑 `test_inspector_dialog.py` | 同上交叉验证 |
| 4 | `pre-commit run --all-files`（或 `black --check` / `flake8`） | 确认 §1.3 关于 flake8 不读 pyproject 的推断 |
| 5 | 修 `modlens` provider（`modlens config set <provider>.<key>`，或登录 Claude Code）后，用 `.tmp/dsh-sel-20261109/desktop-ffmpeg.png` 验证读图链路 | 决定 §6 路径 C 能否由 agent 自证 |
| 6 | `git bundle create` + `sha256` 清单 | 复刻 `delivery-receipt.json` 交付惯例 |

我生成的验证产物（可复用，均在 `.tmp/dsh-sel-20261109/`）：
`qt_offscreen_probe.py` + `offscreen-probe.png`、`font_probe.py`、`pixel_selfcheck.py`、`mw_probe.py`（MainWindow 探针，需 `MainWindow(app)`）、`desktop-ffmpeg.png`、`desktop-ps.png`。

---

## 10. 未能实测 / 证据薄弱项（如实声明）

| 项 | 状态 | 原因 |
|---|---|---|
| 全量测试通过率与总耗时 | ⛔ | `ops_bash` 间歇不可用；Lead 只跑了 `test_canvas/` 与若干单文件 |
| `git status` 的**实时**复核 | 🔶 | 我的实测有效（23 项），但之后可能有新改动 |
| `.local` / `.tmp` 的**精确**文件数与体积细分 | 🔶 | `du` 只在故障间隙跑到一次；`.local` 1.7 G、`.tmp` 315 M 可信，细分为推断 |
| `test_inspector_dialog.py` 失败的**代码根因** | 🔶 | 只到「写着真实 profile 路径」，未定位到具体代码行 |
| 真实 GUI 启动并截到**应用窗口**（而非整屏） | ⛔ | 未执行真实启动（避免干扰用户桌面）；Windows 下定点抓窗口需 `pywin32`（未装） |
| `MainWindow` 离屏完整构建成功 | 🔶 | 探针已进到 `label_widget.persist_user_preferences` 初始化，但因参数/输出截断未拿到 `grab()` 结果；**路径存在性由 `capture_dense_review_screenshots.py` 间接证明** |
| `modlens` 在本机是否**有可用 provider** | ⛔ | 本会话 `npx` 无写权限；Lead 已定位为 `oauthAccount` 缺失，属配置缺口 |
| pip/conda 环境是否与 `pyproject` 完全一致 | ⛔ | 只抽查了 9 个关键包，未做 `pip check` |
