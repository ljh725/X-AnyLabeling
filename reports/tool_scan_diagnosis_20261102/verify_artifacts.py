"""Check exported copies, patch syntax, and upstream scan provenance."""
import ast
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent


def main():
    inventory = json.loads((OUT / "code_categories/inventory.json").read_text(encoding="utf-8"))
    checked = 0
    for row in inventory["files"]:
        path = ROOT / row["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == row["sha256"], row["path"]
        copy = OUT / "code_categories" / row["category"] / row["path"]
        if copy.exists():
            assert copy.read_bytes() == path.read_bytes(), copy
            if copy.suffix == ".py":
                ast.parse(copy.read_text(encoding="utf-8-sig"))
            checked += 1
    for patch in (OUT / "code_categories").glob("*/changes.patch"):
        subprocess.check_output(["git", "apply", "--numstat", str(patch)], cwd=ROOT)
    baseline = inventory["upstream_baseline"]
    provenance = {}
    for relative, class_name in [
        ("anylabeling/views/labeling/widgets/overview_dialog.py", "OverviewDialog"),
        ("anylabeling/views/labeling/widgets/label_dialog.py", "LabelModifyDialog"),
    ]:
        previous = subprocess.check_output(["git", "show", baseline + ":" + relative], cwd=ROOT).decode("utf-8-sig")
        current = (ROOT / relative).read_text(encoding="utf-8-sig")
        def definition(text):
            return next(node for node in ast.parse(text).body if isinstance(node, ast.ClassDef) and node.name == class_name)
        same = ast.dump(definition(previous), include_attributes=False) == ast.dump(definition(current), include_attributes=False)
        provenance[class_name] = {"path": relative, "class_ast_identical_to_upstream_baseline": same}
        assert same, class_name
    result = {"verified_inventory_files": len(inventory["files"]), "verified_exported_copies": checked,
              "patches_parsed": 3, "provenance": provenance,
              "note": "Artifact checks only; this task does not change runtime behavior or claim performance fixed."}
    (OUT / "verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
