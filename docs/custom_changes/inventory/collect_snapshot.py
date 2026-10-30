"""Record source provenance and select reviewable implementation backup files."""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
BASE = "6d250499d2dd81f78723b9217c7a9abf0443ca25"


def git(*args):
    return subprocess.check_output(["git", "-c", "core.quotePath=false", *args], cwd=ROOT).decode("utf-8").strip()


rows = []
for line in git("diff", "--name-status", BASE, "--", "anylabeling", "tests", "scripts").splitlines():
    status, path = line.split("\t", 1)
    rows.append({"status_vs_upstream": status, "path": path})
untracked = git("ls-files", "--others", "--exclude-standard").splitlines()
for path in untracked:
    if path.startswith(("anylabeling/", "tests/", "scripts/")):
        rows.append({"status_vs_upstream": "A", "path": path})
for row in rows:
    p = ROOT / row["path"]
    row["file_category"] = "upstream_file_modified" if row["status_vs_upstream"] == "M" else "local_file_added"
    row["sha256"] = hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None
    row["bytes"] = p.stat().st_size if p.is_file() else None
    row["layer"] = "test" if row["path"].startswith("tests/") else "generated_or_translation" if "/resources/" in row["path"] else "source_or_build"
payload = {"date": "2026-10-30", "upstream_baseline": BASE, "previous_snapshot": git("rev-parse", "HEAD"),
           "note": "File A/M is distinct from feature classification. Existing tests are not revalidated by this inventory.", "files": rows}
(HERE / "source-files.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
selected = set(git("diff", "--name-only", "HEAD").splitlines())
for path in git("ls-files", "--others", "--exclude-standard").splitlines():
    p = Path(path)
    if path.startswith(("anylabeling/", "tests/", "docs/custom_changes/", "openspec/")):
        selected.add(path)
    elif p.parent.as_posix() in ("reports/drag_diagnosis_20261029", "reports/staged_annotation_loading") and p.suffix in (".py", ".md", ".json"):
        if p.name != "real_background_partial.json":
            selected.add(path)
selected.add("backups/.gitignore")
selected.add("docs/custom_changes/inventory/snapshot-paths.json")
paths = sorted(selected)
(HERE / "snapshot-paths.json").write_text(json.dumps(paths, ensure_ascii=False, indent=2), encoding="utf-8")
(ROOT / "backups" / "pre-drag-pathspec.nul").write_bytes(b"\0".join(p.encode("utf-8") for p in paths) + b"\0")
print(json.dumps({"source_files": len(rows), "modified_upstream_files": sum(r["status_vs_upstream"] == "M" for r in rows),
                  "added_local_files": sum(r["status_vs_upstream"] == "A" for r in rows), "snapshot_paths": len(paths),
                  "snapshot_new_bytes": sum((ROOT / p).stat().st_size for p in paths)}, ensure_ascii=False))
