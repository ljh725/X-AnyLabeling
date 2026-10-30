#!/usr/bin/env bash
# Per-directory regression run for CUSTOM-003.
# A single `pytest tests` process dies around 59% on this machine, so each
# target is run in its own process. Every run keeps its raw log and JUnit XML
# so failure node IDs can be diffed between the pre-fix and fixed trees.
#
# usage: run_regression.sh <tree-root> <label> <out-dir> [pytest-extra-args...]
set -u

ROOT="$1"
LABEL="$2"
OUT="$3"
shift 3
EXTRA=("$@")

PY="C:/Users/20441/.conda/envs/x-anylabeling-cu12/python.exe"
# These two tests kill the interpreter (exit 127, no traceback) in this
# environment on both the pre-fix and the fixed tree, so they are excluded
# from the run instead of silently truncating a directory.  See SUMMARY.md.
DESELECT=(
  "tests/test_pointcloud/test_cuboids.py::test_side_view_expand_button_hover_and_layout_restore"
  "tests/test_settings/test_dialog_layout.py::TestSettingsDialogLayout::test_canvas_label_font_size_editor_uses_supported_range"
)
TARGETS=(
  tests/test_auto_labeling
  tests/test_auto_training
  tests/test_canvas
  tests/test_config
  tests/test_labeling
  tests/test_models
  tests/test_pointcloud
  tests/test_ppocr
  tests/test_settings
  tests/test_utils
  tests/test_updates
  tests/test_widgets
  tests/test_staged_annotation_metadata.py
  tests/test_staged_output_window.py
  tests/test_ui_density_extremes_repair.py
)

mkdir -p "$OUT"
: >"$OUT/${LABEL}_exitcodes.txt"
DESELECT_ARGS=()
for node in "${DESELECT[@]}"; do
  DESELECT_ARGS+=(--deselect "$node")
done
for target in "${TARGETS[@]}"; do
  name=$(printf '%s' "$target" | sed 's#^tests/##; s#/#_#g; s#\.py$##')
  (
    cd "$ROOT" || exit 99
    QT_QPA_PLATFORM=offscreen timeout 600 "$PY" -m pytest "$target" \
      -p no:cacheprovider -q --tb=no -rfE --color=no \
      --junitxml="$OUT/${LABEL}_${name}.xml" \
      "${DESELECT_ARGS[@]}" "${EXTRA[@]}" >"$OUT/${LABEL}_${name}.log" 2>&1
  )
  code=$?
  printf '%s %s exit=%s\n' "$LABEL" "$target" "$code" >>"$OUT/${LABEL}_exitcodes.txt"
  tail -n 1 "$OUT/${LABEL}_${name}.log" | tr -d '\n'
  printf '  <- %s (%s)\n' "$target" "$code"
done
