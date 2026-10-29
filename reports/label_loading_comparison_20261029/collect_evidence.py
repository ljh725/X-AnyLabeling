"""Collect read-only source snapshots and loading-change Git evidence."""

import ast
import difflib
import hashlib
import json
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
ROOTS = {
    "original_beta4": Path(r"D:\X-AnyLabeling-4.0.0-beta.4"),
    "modified_beta4": Path(r"D:\xinjiegou-X-AnyLabeling-4.0.0-beta.4"),
    "current_421": Path(r"D:\X-AnyLabeling-4.2.1"),
}
TARGETS = {
    "anylabeling/views/labeling/label_widget.py": {
        "LabelingWidget": ["_label_file_checked", "_create_file_list_item", "import_image_folder", "change_output_dir_dialog", "load_shapes", "load_file", "_apply_cached_dataset_statuses", "_start_label_check_worker"],
        "LabelCheckWorker": ["run"],
    },
    "anylabeling/views/labeling/label_file.py": {"LabelFile": ["_check_image_height_and_width", "load"]},
    "anylabeling/views/labeling/widgets/canvas.py": {"Canvas": ["load_shapes", "store_shapes"]},
    "anylabeling/views/labeling/shape.py": {"Shape": ["make_path", "bounding_rect"]},
}


def git(*args):
    result = subprocess.run(
        ["git", "-c", "safe.directory=" + ROOTS["modified_beta4"].as_posix(), "-C", str(ROOTS["modified_beta4"]), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=True,
    )
    return result.stdout


report = {"date": "2026-10-29 Asia/Shanghai", "scope": "Current on-disk source in the three named directories; original_beta4 is the user-named local snapshot, not independently authenticated to an upstream release tag. Modified fork has uncommitted source changes, so Git history explains origins while current files define current behavior.", "sources": {}, "commits": {}}
methods = {}
for label, root in ROOTS.items():
    files = {}
    for relative, classes in TARGETS.items():
        path = root / relative
        source = path.read_text(encoding="utf-8")
        lines = source.splitlines()
        tree = ast.parse(source)
        file_record = {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "methods": {}}
        for class_name, names in classes.items():
            owner = next((node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name), None)
            if owner is None:
                continue
            for node in owner.body:
                if isinstance(node, ast.FunctionDef) and node.name in names:
                    key = class_name + "." + node.name
                    text = "\n".join(lines[node.lineno-1:node.end_lineno])
                    file_record["methods"][key] = {"line": node.lineno, "end_line": node.end_lineno, "source": text}
                    methods[label, key] = text
        files[relative] = file_record
    report["sources"][label] = {"root": str(root), "files": files}

for short in ("476ad1fa", "3c13fbce", "951ba30a", "09fe8807", "b45af4ad"):
    report["commits"][short] = git("show", "-s", "--format=%H%n%cs%n%B", short).strip()
    patch = git("show", "--format=", "--unified=3", short, "--", "anylabeling/views/labeling/label_widget.py")
    (HERE / f"{short}_label_widget.diff").write_text(patch, encoding="utf-8")
report["modified_beta4_status"] = git("status", "--short", "--untracked-files=no", "--", *TARGETS)
(HERE / "source_evidence.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
(HERE / "commit_records.txt").write_text("\n\n".join(report["commits"].values()), encoding="utf-8")
for left, right in (("original_beta4", "current_421"), ("modified_beta4", "current_421")):
    chunks = []
    for key in ("LabelingWidget.import_image_folder", "LabelingWidget._create_file_list_item", "LabelingWidget.load_shapes", "Canvas.load_shapes", "LabelFile._check_image_height_and_width"):
        chunks.extend(difflib.unified_diff(methods[left, key].splitlines(True), methods[right, key].splitlines(True), fromfile=left+":"+key, tofile=right+":"+key))
        chunks.append("\n\n")
    (HERE / f"{left}_vs_{right}.diff").write_text("".join(chunks), encoding="utf-8")
print(json.dumps({"commits": list(report["commits"]), "roots": list(ROOTS), "modified_worktree": report["modified_beta4_status"]}, ensure_ascii=False))
