"""Capture the committed baseline and an explicit generated-file cleanup list."""

import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
GENERATED = (
    "reports/correction_cost_20261103/baseline-sandbox-retry/",
    "reports/inspector_workflow_20261102/recheck-four-20261102/",
    "reports/inspector_workflow_20261102/review-nov02-elevated/",
    "reports/inspector_workflow_20261102/review-probes-final/",
    "reports/inspector_workflow_20261102/review-probes-confirmed/",
    "reports/correction_cost_20261103/pre-implementation-20261103-132221/",
    "reports/drag_diagnosis_20261029/profile/",
    "reports/drag_fix_20261030/profile/",
    "benchmarks/canvas_drawing_20261029/profile/",
    "reports/ui_review_20261103/.xanylabelingrc",
)


def git(*args):
    result = subprocess.run(
        ["git", "-c", "core.quotepath=false", *args],
        cwd=ROOT, capture_output=True, encoding="utf-8", errors="replace",
        check=True,
    )
    return result.stdout.strip()


def main():
    tracked = git("ls-files").splitlines()
    cleanup = [p for p in tracked if any(
        p.startswith(prefix) if prefix.endswith("/") else p == prefix
        for prefix in GENERATED
    )]
    bundle = ROOT / "backups/4.2.1-20261103-pre-baseline-cleanup.bundle"
    bundle_hash = None
    if bundle.exists():
        with bundle.open("rb") as stream:
            bundle_hash = hashlib.file_digest(stream, "sha256").hexdigest()
    inventory = {
        "date": "2026-11-03", "timezone": "Asia/Shanghai",
        "branch": git("branch", "--show-current"),
        "head": git("rev-parse", "HEAD"),
        "source_branch": "feat/ui-polish-p2",
        "source_ui_commit": git("rev-parse", "6b98b76e"),
        "mixed_snapshot_commit": git("rev-parse", "9673d3b9"),
        "backup_tag": "backup/4.2.1-20261103-pre-baseline-cleanup",
        "bundle": str(bundle.relative_to(ROOT)).replace("\\", "/"),
        "bundle_sha256": bundle_hash,
        "status_before": git("status", "--porcelain", "--untracked-files=normal").splitlines(),
        "cleanup_kind": "remove from index only; retain local contents and Git history",
        "cleanup_paths": cleanup,
        "retained_evidence": [
            p for p in tracked if p.startswith("reports/") and p not in cleanup
        ],
        "correction_metrics": {
            "state": "partial implementation; not ready for use",
            "missing": [str(p) for p in (
                "anylabeling/views/labeling/correction_metrics/controller.py",
                "anylabeling/views/labeling/correction_metrics/panel.py",
                "anylabeling/views/labeling/correction_metrics/report_dialog.py",
            ) if not (ROOT / p).exists()],
        },
    }
    (OUT / "inventory-before.json").write_text(
        json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (OUT / "cleanup-paths.txt").write_text("\n".join(cleanup) + "\n", encoding="utf-8")
    print(json.dumps({"cleanup_files": len(cleanup), "bundle_sha256": bundle_hash,
                      "retained_report_files": len(inventory["retained_evidence"])}, indent=2))


if __name__ == "__main__":
    main()
