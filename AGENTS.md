# X-AnyLabeling — Agent Guide

> High-signal notes only. Omit anything obvious from filenames or standard Python/PyQt conventions.

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
```bash
# IMPORTANT: Use conda environment 'x-anylabeling-cu12' for all operations
conda activate x-anylabeling-cu12

pytest                              # Run tests (add --slow for slow tests)
bash scripts/format_code.sh         # black -l 79
flake8 anylabeling/                 # Lint (max complexity 18)
pre-commit run --all-files          # Pre-commit gate
python scripts/compile_languages.py # Rebuild .qm + resources.py after .ts changes
```

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

## Agent tasks
- **Add auto-labeling model**: wrapper in `anylabeling/services/auto_labeling/` (or `__base__/` for family bases), YAML config in `anylabeling/configs/auto_labeling/`, entry in `anylabeling/configs/models.yaml`, ONNX export script in `tools/onnx_exporter/` if needed.
- **Add label converter**: extend `BaseLabelConverter` in `tools/label_converter.py`, wire into `anylabeling/views/common/converter.py` for CLI access.
- **Add UI strings**: wrap with `QCoreApplication.translate("Context", "text")`, update `.ts` files, run `python scripts/compile_languages.py`.

## Security note
Model downloads from GitHub releases disable SSL cert verification (`ssl._create_unverified_context`) to allow downloads behind corporate proxies.
