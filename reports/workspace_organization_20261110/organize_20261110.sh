#!/usr/bin/env bash
# 2026-11-10 工作区数据整理（一次性执行记录）
# 用法：bash organize_20261110.sh <phase>
#   阶段 A：归档无关/过期材料、建立 docs/development/dsh 归位
#   阶段 B：清理可重建的缓存与临时目录
# 说明：需要提升的写权限（.git、reports、docs、.installers 等在受限模式下不可写）。
set -u

ROOT='/d/X-AnyLabeling-4.2.1'
cd "$ROOT" || { echo "FATAL cannot cd $ROOT"; exit 1; }

ARC='.local/workspace-archive/20261110'
REP='reports/workspace_organization_20261110'
LOG="$REP/organize.log"
PHASE="${1:-a}"

mkdir -p "$ARC/unrelated" "$ARC/local-work" "$ARC/dsh-selection-scripts" "$REP" "docs/development/dsh"
: >> "$LOG"

say() { printf '%s\n' "$*" | tee -a "$LOG"; }

move_item() {
  local src="$1" dst="$2"
  if [ ! -e "$src" ] && [ ! -L "$src" ]; then say "SKIP   missing  $src"; return 0; fi
  mkdir -p "$(dirname "$dst")"
  if mv -- "$src" "$dst" 2>>"$LOG"; then say "MOVED  $src  ->  $dst"; else say "FAIL   move     $src"; fi
}

case "$PHASE" in
a)
  say "===== PHASE A $(date '+%F %T') ====="
  # 与项目无关的本机研究材料
  move_item '_chair_research'            "$ARC/unrelated/_chair_research"
  move_item '_t_jd.py'                   "$ARC/unrelated/_t_jd.py"
  # 空目录
  if [ -d 'dsh选型-20261109' ]; then
    if rmdir 'dsh选型-20261109' 2>>"$LOG"; then say "RMDIR  dsh选型-20261109 (empty)"; else say "SKIP   not-empty dsh选型-20261109"; fi
  fi
  # DSH 开发工具文档归位（可入库）
  move_item 'dsh写代码插件清单.md'        'docs/development/dsh/dsh写代码插件清单.md'
  move_item 'dsh编码插件组合-本仓库.md'   'docs/development/dsh/dsh编码插件组合-本仓库.md'
  move_item 'dsh_selection_20261109'      'docs/development/dsh/selection-20261109'
  # 过期本机工作副本（结论已进入 reports/ 与 openspec/）
  move_item '.local/restore-v430-20261104'        "$ARC/local-work/restore-v430-20261104"
  move_item '.local/canvas-implementation-20261105' "$ARC/local-work/canvas-implementation-20261105"
  move_item '.local/baseline-recovery-check'      "$ARC/local-work/baseline-recovery-check"
  move_item '.local/restore-v430'                 "$ARC/local-work/restore-v430"
  move_item '.installers/deva-test'               "$ARC/local-work/deva-test"
  move_item '.p2-render'                          "$ARC/local-work/p2-render"
  move_item '.dsh-asar-out'                       "$ARC/local-work/dsh-asar-out"
  # 选型脚本与摘要（其余 49M 原始输出随 .tmp 清理）
  for f in analyze_market.py asar_dump.py asar_ls.py asar_sel.py audit.json candidates.csv; do
    move_item ".tmp/dsh-sel-20261109/$f" "$ARC/dsh-selection-scripts/$f"
  done
  ;;
b)
  say "===== PHASE B $(date '+%F %T') ====="
  # 保留可复用的 pytest 沙箱插件到 .tooling（.tmp 将整体清理）
  if [ -f '.tmp/harness/pytest_tmp777.py' ]; then
    mkdir -p .tooling
    if cp -f '.tmp/harness/pytest_tmp777.py' '.tooling/pytest_tmp777.py' 2>>"$LOG"; then say "COPIED .tmp/harness/pytest_tmp777.py -> .tooling/pytest_tmp777.py"; fi
  fi
  # 可重建的临时目录与缓存
  if [ -d '.tmp' ]; then rm -rf .tmp/* 2>>"$LOG" && say "CLEANED .tmp/*"; fi
  for d in 'pytest-of-JJH' '.pytest_cache' '.pytest-bt' '.local/pycache'; do
    if [ -e "$d" ]; then rm -rf -- "$d" 2>>"$LOG" && say "DELETED $d"; fi
  done
  # 仓库内 Python 缓存（跳过归档与本机工具目录；用 Python 显式删除，避免通配误删）
  py='import pathlib,shutil,sys
root=pathlib.Path(".")
skip={".git",".local","backups",".tmp"}
n=0
for p in sorted(root.rglob("__pycache__")):
    rel=p.relative_to(root); 
    if rel.parts and rel.parts[0] in skip: continue
    if not p.is_dir(): continue
    shutil.rmtree(p, ignore_errors=True); n+=1
sys.stdout.write("DELETED __pycache__ dirs: %d\n" % n)'
  printf '%s' "$py" | python - 2>>"$LOG" | tee -a "$LOG"
  ;;
*)
  echo "unknown phase: $PHASE"; exit 2;;
esac

say "===== PHASE $PHASE DONE $(date '+%F %T') ====="
