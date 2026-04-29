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
pytest                              # Run tests (add --slow for slow tests)
bash scripts/format_code.sh         # black -l 79
flake8 anylabeling/                 # Lint (max complexity 18)
pre-commit run --all-files          # Pre-commit gate
python scripts/compile_languages.py # Rebuild .qm + resources.py after .ts changes
```

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

## Agent tasks
- **Add auto-labeling model**: wrapper in `anylabeling/services/auto_labeling/` (or `__base__/` for family bases), YAML config in `anylabeling/configs/auto_labeling/`, entry in `anylabeling/configs/models.yaml`, ONNX export script in `tools/onnx_exporter/` if needed.
- **Add label converter**: extend `BaseLabelConverter` in `tools/label_converter.py`, wire into `anylabeling/views/common/converter.py` for CLI access.
- **Add UI strings**: wrap with `QCoreApplication.translate("Context", "text")`, update `.ts` files, run `python scripts/compile_languages.py`.

## Security note
Model downloads from GitHub releases disable SSL cert verification (`ssl._create_unverified_context`) to allow downloads behind corporate proxies.
