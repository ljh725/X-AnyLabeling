"""Export reviewable source categories without relocating runtime modules."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "code_categories"
BASE = "6d250499d2dd81f78723b9217c7a9abf0443ca25"


def git(*args):
    return subprocess.check_output(["git", "-c", "core.quotePath=false", *args], cwd=ROOT)


def main():
    scope = ["anylabeling", "tests", "scripts", "tools", "packaging", "pyproject.toml", "MANIFEST.in"]
    upstream = set(git("ls-tree", "-r", "--name-only", "-z", BASE).decode().split("\0"))
    changed = set(git("diff", "--name-only", "-z", BASE, "--", *scope).decode().split("\0"))
    untracked = set(git("ls-files", "--others", "--exclude-standard", "-z", "--", *scope).decode().split("\0"))
    changed.discard("")
    untracked.discard("")
    rows = []
    for name in sorted(changed | untracked):
        path = ROOT / name
        if not path.is_file():
            continue
        if name.startswith("anylabeling/resources/"):
            category = "generated_and_translations"
        elif name.startswith(("tests/", "scripts/", "tools/", "packaging/")) or name in {"pyproject.toml", "MANIFEST.in"}:
            category = "tests_and_engineering"
        else:
            category = "source_modifications" if name in upstream else "extension_code"
        payload = path.read_bytes()
        row = {"path": name, "category": category,
               "status_vs_upstream": "M" if name in upstream else "A",
               "untracked": name in untracked, "bytes": len(payload),
               "sha256": hashlib.sha256(payload).hexdigest()}
        rows.append(row)
        if category == "extension_code" or (category == "tests_and_engineering" and name not in upstream):
            target = OUT / category / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
    OUT.mkdir(parents=True, exist_ok=True)
    for category in ("source_modifications", "tests_and_engineering", "generated_and_translations"):
        paths = [r["path"] for r in rows if r["category"] == category and r["path"] in upstream and not r["path"].endswith((".qm", "resources.py"))]
        if paths:
            target = OUT / category / "changes.patch"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(git("diff", "--no-ext-diff", "--binary", BASE, "--", *paths))
    inventory = {"date": "2026-11-02", "upstream_baseline": BASE,
                 "head": git("rev-parse", "HEAD").decode().strip(),
                 "scope": scope, "note": "Current disk snapshot, includes existing uncommitted Inspector work. Classification is by file origin, not feature origin. No runtime source moved or changed.",
                 "counts": {c: sum(r["category"] == c for r in rows) for c in sorted({r["category"] for r in rows})}, "files": rows}
    (OUT / "inventory.json").write_text(json.dumps(inventory, ensure_ascii=False, indent=2), encoding="utf-8")
    labels = {"source_modifications": "源代码修改：上游已有文件的差异补丁",
              "extension_code": "扩展代码：相对上游新增的运行模块",
              "tests_and_engineering": "测试及工程配套",
              "generated_and_translations": "翻译及生成资源"}
    lines = ["# 4.2.1 当前代码分类快照", "", "日期：2026-11-02。基线：`" + BASE + "`。HEAD：`" + inventory["head"] + "`。", "",
             "本目录已实际导出原文件修改补丁与新增模块副本；运行目录和导入路径保持原位。包含当前工作区已有未提交 Inspector 代码，不能据此认定其已完成验收。", "",
             "文件分类与功能分类不同：新增后台模块也可能服务于原功能改造，旧 canvas.py 也会承载新增能力。功能归属见 docs/custom_changes/CATALOG-20261030.md 和 CUSTOM-109 记录。", "",
             "代码副本用于检查和迁移参考；补丁依据指定上游基线生成，不应直接套用到当前已修改工作区。二进制 .qm 和 resources.py 仅登记哈希，迁移时按项目资源流程重新生成。", ""]
    for category, label in labels.items():
        items = [r for r in rows if r["category"] == category]
        lines.extend(["## " + label + f"（{len(items)} 个文件）", "", "| 文件 | 相对上游 | 当前状态 |", "| --- | --- | --- |"])
        lines.extend(f'| `{r["path"]}` | {r["status_vs_upstream"]} | {"未跟踪" if r["untracked"] else "Git 已跟踪，可能另有未提交修改"} |' for r in items)
        lines.append("")
    (OUT / "README.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(inventory["counts"], ensure_ascii=False))


if __name__ == "__main__":
    main()
