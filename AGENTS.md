# X-AnyLabeling — Agent Guide

> High-signal notes only. Omit anything obvious from filenames or standard Python/PyQt conventions.

## Thinking posture
- 不要只回答用户字面上的问题。
- 判断用户的问题是不是问窄了。
- 将用户的问题改写成更高层、更本质的问题。
- 指出用户可能因为知识边界而遗漏了哪些角度。

## One-line summary
PyQt6 desktop app for AI-powered image/video annotation. Entry point: `xanylabeling = anylabeling.app:main`.

## Install (pick one — mutually exclusive onnxruntime variants)
```bash
pip install -e ".[cpu,dev]"       # CPU inference
pip install -e ".[gpu,dev]"       # CUDA 12.x
pip install -e ".[gpu-cu11,dev]"  # CUDA 11.x
```
- **Critical**: `onnxruntime` and `onnxruntime-gpu` must never be installed together. `pyproject.toml` declares `[tool.uv]` conflict blocks for this.
- Dev deps include `PySide6` (needed for `pyside6-rcc` fallback in `compile_languages.py`, even though runtime uses PyQt6).

## Dev commands
```powershell
$ErrorActionPreference = 'Stop'
$py = "$env:USERPROFILE\.conda\envs\x-anylabeling-cu12\python.exe"

& $py -m pytest                              # Run tests (add --slow for slow tests)
$env:BLACK_CACHE_DIR = Join-Path $env:TEMP "xanylabeling-black-cache"
& $py -m black -l 79 anylabeling             # Format code
& $py -m flake8 anylabeling/                 # Lint (max complexity 18)
pre-commit run --all-files                   # Pre-commit gate
& $py scripts/compile_languages.py           # Rebuild .qm + resources.py after .ts changes
```

### Windows / PowerShell command rules

All agent-run CLI work in this repo should use PowerShell syntax. Do not mix in
Bash-only forms such as `source activate`, `cmd /c`, heredocs, or `&&` command
chains.

Use this shape for commands:

```powershell
$ErrorActionPreference = 'Stop'
& 'C:\Users\20441\.conda\envs\x-anylabeling-cu12\python.exe' -m pytest tests/test_rect_edge_alignment.py -q
```

Practical rules:

- Put `$ErrorActionPreference = 'Stop'` at the top of every multi-line command.
- Use PowerShell invocation `& 'path\to\tool.exe' ...` for paths with spaces or explicit interpreters.
- Prefer object commands (`Get-ChildItem`, `Select-Object`, `Where-Object`, `Select-String`) over text parsing.
- Use `Get-Content -Encoding UTF8` / `Set-Content -Encoding UTF8` when reading or writing text with Chinese.
- Do not rely on `conda run` in Codex shell sessions; it has repeatedly hung here.
- Do not rely on interactive `conda activate` inside one-off tool commands; activation does not reliably persist.
- Set `BLACK_CACHE_DIR` to a writable temporary directory before running Black
  in a sandbox; its default cache under `LOCALAPPDATA` may be read-only and make
  `tempfile` retry without visible output.
- For tests and Python utilities, call the env interpreter directly:

```powershell
$ErrorActionPreference = 'Stop'
$py = "$env:USERPROFILE\.conda\envs\x-anylabeling-cu12\python.exe"
& $py -m pytest tests/test_rect_edge_alignment.py -q
& $py -m py_compile anylabeling\views\labeling\widgets\canvas.py
```

If PyQt6 fails inside the sandbox with a Qt DLL access error, rerun the same
command with approval outside the sandbox instead of changing the environment.

### opencode Integration
- opencode must be started **after** activating the conda environment
- Use the provided script: `start-opencode-conda.bat` (auto-activates conda)
- Or manually: `conda activate x-anylabeling-cu12 && opencode`

## Code style
- **Black**: line length `79`. Excludes: `tests/`, `anylabeling/resources/resources.py`, `venv/`.
- **Flake8**: max complexity `18`. Excludes **only** `anylabeling/resources/resources.py` — **tests are linted**.
- **Mandatory**: Google-style docstrings + type hints on all functions/classes (`flake8-docstrings` enforced).
- Imports: `os.path` as `osp`, Qt as `from PyQt6 import QtCore, QtGui, QtWidgets`, relative imports inside sub-packages.

## Architecture gotchas
- `anylabeling/app.py` sets `MKL_NUM_THREADS=1`, `NUMEXPR_NUM_THREADS=1`, `OMP_NUM_THREADS=1` at the very top (macOS M1 bus-error fix) and suppresses Qt ICC warnings via `QT_LOGGING_RULES`. It also injects the repo root into `sys.path`.
- `anylabeling/app.py` imports `anylabeling.resources.resources` solely to load translations (marked `# noqa: F401`). Do not remove.
- `anylabeling/app_info.py` holds static `__version__`, but `__preferred_device__` is dynamic via `__getattr__` (calls `device_manager.get_preferred_device()`). The release script `scripts/build_and_publish_pypi.sh` attempts to `sed` it as if it were static — this is stale.
- Version is loaded dynamically in `pyproject.toml`: `version = {attr = "anylabeling.app_info.__version__"}`.

## Generated code / i18n
- `anylabeling/resources/resources.py` is auto-generated. Never edit manually.
- `scripts/compile_languages.py` compiles `.ts` → `.qm` and tries multiple RCC compilers (`pyrcc6`, `pyside6-rcc`, `rcc -g python`). It forces `--compress-algo zlib` because zstd compression is unreadable on some Windows Qt runtimes. It also rewrites `PySide6` imports to `PyQt6` in the generated file.

## Pre-commit hooks
- Standard hooks: large files (8 MB max), merge conflicts, trailing whitespace, EOF fixer, debug-statements (excl. tests).
- `black` (format + check), `flake8` (+ bugbear, docstrings, comprehensions, blind-except, implicit-str-concat, pydocstyle).
- `rstcheck`, `codespell`.

## Config system
- User config: `~/.xanylabelingrc` (YAML). Legacy `.anylabelingrc` is auto-migrated on load.
- Default config: `anylabeling/configs/xanylabeling_config.yaml`.

## Key files
| File | Purpose |
|------|---------|
| `anylabeling/app.py` | CLI parsing, env setup, QApplication bootstrap |
| `anylabeling/app_info.py` | Version, help text, dynamic preferred device |
| `anylabeling/config.py` | Config load, merge, validation, legacy migration |
| `anylabeling/views/mainwindow.py` | Top-level QMainWindow |
| `anylabeling/views/labeling/label_widget.py` | Core labeling UI (~6.6 k lines) |
| `anylabeling/services/auto_labeling/model.py` | Abstract Model class + download/cache logic |
| `pyproject.toml` | Build system, deps, black/flake8/pytest config |
| `.pre-commit-config.yaml` | Hook definitions |
| `scripts/compile_languages.py` | lrelease + pyrcc6 compiler with zlib fallback |
| `scripts/format_code.sh` | Black wrapper |

### Inspector module (`anylabeling/views/labeling/widgets/inspector/`)

8 文件，4 个 Tab（数据检查 / 数据表格 / 规则配置 / 导出），3 阶段实现。

| 文件 | 职责 | 阶段 |
|------|------|------|
| `flat_index.py` | `FlattenedRecord` + `FlatIndex`（内存索引，~500文件/批次） | 1 |
| `validation_engine.py` | 8 条规则（见速查表）+ `ValidationEngine` | 1 |
| `issue_list_widget.py` | `QTreeWidget` 问题列表，按规则分组，颜色编码 | 1 |
| `editable_table_widget.py` | `QTableView` + `EditableTableModel`，可编辑 label/gid/desc | 2 |
| `rule_config_widget.py` | 共享标签集 + 8 规则 checkbox + 参数编辑器 + `build_rules()` | 3 |
| `export_manager.py` | `ExportManager.export()` — 按规则名分目录复制 JSON+图片 | 3 |
| `inspector_panel.py` | `QDockWidget` 4-tab 容器，信号：`issue_navigate_requested` / `shape_edit_requested` | 集成 |
| `__init__.py` | 导出 `InspectorPanel`, `FlatIndex`, `FlattenedRecord`, `ValidationEngine`, `Issue`, `ValidationRule` | — |

**8 条内置规则速查**：

| # | 规则类 | 检查层级 | 简介 | sev |
|---|--------|----------|------|-----|
| R1 | `LabelInAllowlist` | per-shape | label 必须在共享标签集内 | err |
| R2 | `GroupLabelUniqueness` | per-group | 同 gid 内标签不可重复 | err |
| R3 | `PersonRectRequiresGroupId` | per-shape | person 矩形框 gid 必须为 int | err |
| R4 | `LabelShapeTypeBinding` | per-shape | label 必须匹配预期 shape_type | err |
| R5 | `GroupIdKeypointIntegrity` | per-group | 有关键点的 gid 必须有 person | warn |
| R6 | `RequiredFieldNotEmpty` | per-shape | label + points 非空 | err |
| R7 | `GroupIdUniqueness` | per-group | 可配唯一类型（默认空） | err |
| R8 | `AttributeConsistency` | per-shape | difficult/orphan_head 一致性（默认关） | warn |

**新增规则步骤**：
1. `validation_engine.py` — 添加 `ValidationRule` 子类，实现 `check()`（per-shape）或 `check_all()`（per-group）
2. `rule_config_widget.py` — `_RULE_REGISTRY` 追加一行 meta
3. `rule_config_widget.py` — `_instantiate_rule()` 添加实例化分支
4. `rule_config_widget.py` — 如有参数，在 `_read_param()` / `_extract_rule_param()` 处理

**关键注意**：
- `setdefault` 是有效的 Python `dict` 方法（非笔误）
- 表格刷新时检查 `table_widget.is_editing` 防止模型重置杀掉编辑器
- `_json_path_to_image()` 通过 basename（非完整路径）匹配 JSON → 图片，支持图片/JSON 分目录存放

### 阶段一 L1/L2 质检模块 (`anylabeling/views/labeling/widgets/inspector/quality/`)

纯 Python（不依赖 PyQt6），可独立 import。规格见 `docs/阶段一L1_L2质检规则阈值与输出规格_v0.md`。

| 文件 | 职责 |
|------|------|
| `threshold_profile.py` | YAML loader + schema 校验（direction/error_requires/two_sided） |
| `quality_issue.py` | `QcShape`/`QcFile`/`QcShapeLoader`（保留原始 points）+ `QualityIssue`/`QualityReport` |
| `geometry.py` | bbox/overlap/containment/overflow/expand/归一化距离/y_rel/body band |
| `matching.py` | face→head（严格）+ head→person（宽松）硬过滤+打分+ambiguous |
| `severity_eval.py` | 共享阈值评估：direction + `error_requires` 二次确认 |
| `l1_rules.py` | L1 硬规则（label/shape_type/points/group_id/bbox 合法性） |
| `l2_rules.py` | 12 条 L2 规则（L2-01~L2-12），按 `_L2_RUNNERS` 注册 |
| `report_writer.py` | `run_quality_check()` 主驱动 → `review.tsv` + `report.json` |
| `feedback.py` | 读 `review_feedback.tsv`，校验 decision/final_action 枚举 |
| `threshold_suggestion.py` | 9 级优先级触发 → `threshold_suggestion.json`（恒 pending） |

**关键约束**：
- 质检只读，绝不写回 JSON；`qa_entity_id` 不写入正式 shape。
- 跨类 face/head/person 关系只是 QA 临时推断，不绑定正式 `group_id`。
- `error_requires` 未满足时 error 自动降级为 warning。
- `threshold_suggestion.json` 的 `approval.status` 恒为 `pending`，不自动改 YAML。
- 现有 `FlattenedRecord` 只存 `points_count` 不存原始 points，故质检用独立 `QcShapeLoader`。
- 阈值配置：`anylabeling/configs/quality/l1_l2_threshold_profile_v0.yaml`（`profile_id: v0_default`）。
- CLI：`scripts/run_l1l2_qc.py`（生成 review.tsv+report.json）、`scripts/gen_threshold_suggestion.py`（生成建议）。
- 测试：`tests/test_quality_{geometry,matching,thresholds,output,suggestion}.py`（101 用例）。

### 质检复核队列（Inspector 第 2 个 Tab「质检复核」）

把 L1/L2 质检接入 Inspector，形成人工复核工作台。**纯 Python 与 PyQt 严格分层**。

| 文件 | 类型 | 职责 |
|------|------|------|
| `inspector/quality/quality_review_queue.py` | **纯 Python** | `QualityReviewItem` + `QualityReviewQueue`：加载 report.json/review.tsv、合并 feedback、筛选/排序、upsert、写回 TSV、复扫合并（标 `resolved_after_rescan`） |
| `inspector/quality_scan_worker.py` | PyQt | `QualityScanThread(QThread)` 后台 worker，复用 `run_quality_check` 核心 |
| `inspector/quality_review_widget.py` | PyQt | `QualityReviewWidget(QWidget)`：树表+筛选+复核动作+备注+进度摘要。信号 `issue_clicked(str,int)` 与现有导航契约一致 |
| `inspector/inspector_panel.py`（扩展） | PyQt | 第 5 Tab 插在 index 1（`数据检查 \| 质检复核 \| 数据表格 \| 规则配置 \| 导出`），导入/复扫/阈值建议入口 |

**关键约束**：
- `quality/` 子包**绝不引 PyQt**（质量验收硬约束）；PyQt 文件在 `inspector/` 层。
- 复核队列是 view，逻辑全在纯 Python `QualityReviewQueue`（可无 Qt 单测）。
- 复核动作自动写 `review_feedback.tsv`（保留已有反馈，按 `issue_id` 合并）。
- 复扫当前文件后：消失 issue 标 `resolved_after_rescan`（不删反馈），新 issue 追加为 pending。
- 阈值建议入口调 `generate_threshold_suggestion`，UI 文案明确「建议未生效」。
- 导航信号转发到现有 `issue_navigate_requested(str,int)`，`label_widget` 无需改。
- 不破坏现有 `数据检查` Tab（8 条基础规则不变）。
- 测试：`tests/test_quality_review_queue.py`（22 用例）+ `tests/test_quality_review_widget.py`（11 用例，PyQt offscreen）。

## Agent tasks
- **Add auto-labeling model**: wrapper in `anylabeling/services/auto_labeling/` (or `__base__/` for family bases), YAML config in `anylabeling/configs/auto_labeling/`, entry in `anylabeling/configs/models.yaml`, ONNX export script in `tools/onnx_exporter/` if needed.
- **Add label converter**: extend `BaseLabelConverter` in `tools/label_converter.py`, wire into `anylabeling/views/common/converter.py` for CLI access.
- **Add UI strings**: wrap with `QCoreApplication.translate("Context", "text")`, update `.ts` files, run `python scripts/compile_languages.py`.

## Security note
Model downloads from GitHub releases disable SSL cert verification (`ssl._create_unverified_context`) to allow downloads behind corporate proxies.
