#!/usr/bin/env bash
# Isolate the 3D point-cloud tests: one process per file so an access
# violation cannot truncate a whole directory's results.
# usage: run_dir_files.sh <tree-root> <label> <out-dir> <test-subdir>
set -u

ROOT="$1"
LABEL="$2"
OUT="$3"
SUBDIR="$4"
PY="C:/Users/20441/.conda/envs/x-anylabeling-cu12/python.exe"

mkdir -p "$OUT"
for file in "$ROOT/$SUBDIR"/*.py; do
  name=$(basename "$file" .py)
  [ "$name" = "__init__" ] && continue
  rel="$SUBDIR/$name.py"
  (
    cd "$ROOT" || exit 99
    QT_QPA_PLATFORM=offscreen timeout 300 "$PY" -m pytest "$rel" \
      -p no:cacheprovider -q --tb=no -rfE --color=no \
      --junitxml="$OUT/${LABEL}_file_${name}.xml" \
      >"$OUT/${LABEL}_file_${name}.log" 2>&1
  )
  code=$?
  fatal=$(grep -m1 "Most recent call first\|line [0-9]* in test_" -A 2 "$OUT/${LABEL}_file_${name}.log" \
          | grep -m1 "in test_\|in [A-Za-z_]*test" | sed 's/^ *//' | cut -c1-120)
  printf '%s %s exit=%s %s\n' "$LABEL" "$name" "$code" "${fatal:-}"
done
