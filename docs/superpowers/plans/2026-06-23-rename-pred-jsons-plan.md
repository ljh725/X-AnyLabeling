# Rename `_pred.json` 标注文件 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 创建一个独立脚本 `scripts/rename_pred_jsons.py`，将 JSON 标注目录中所有以 `_pred.json` 结尾的文件，按同名图片的 stem 去掉 `_pred` 后缀后复制到输出目录；没有对应图片的 JSON 跳过。

**Architecture:** 脚本基于 `pathlib` 和 `argparse`，先收集图片 stem 集合，再遍历 JSON 文件做后缀匹配和存在性检查，最后输出统计信息。逻辑与现有 `scripts/align_image_json_pairs.py`、`scripts/label_rename_converter.py` 风格保持一致。

**Tech Stack:** Python 3.10+, pathlib, argparse, shutil, csv

---

### Task 1: Create `scripts/rename_pred_jsons.py`

**Files:**
- Create: `scripts/rename_pred_jsons.py`

- [ ] **Step 1: Write the script header and imports**

```python
#!/usr/bin/env python3
"""Rename `_pred.json` annotations to match image stems.

For every JSON file in `json_dir` ending with `{suffix}.json`, check whether an
image with the same stem exists in `images_dir`. If so, copy the JSON to
`output_dir` with the suffix removed.
"""

import argparse
import csv
import shutil
import sys
from pathlib import Path
```

- [ ] **Step 2: Define constants and helper functions**

```python
IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".bmp",
    ".webp",
    ".tif",
    ".tiff",
    ".gif",
}


def validate_directory(path: Path, label: str) -> Path:
    """Resolve and validate an input directory."""
    directory = path.expanduser().resolve()
    if not directory.is_dir():
        print(f"Error: {label} is not a directory: {directory}", file=sys.stderr)
        sys.exit(1)
    return directory


def collect_image_stems(images_dir: Path) -> set[str]:
    """Return filename stems for all image files in the directory."""
    stems = set()
    for path in images_dir.iterdir():
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
            stems.add(path.stem)
    return stems
```

- [ ] **Step 3: Implement core rename logic**

```python
def rename_pred_jsons(
    images_dir: Path,
    json_dir: Path,
    output_dir: Path,
    suffix: str = "_pred",
    dry_run: bool = False,
) -> list[dict]:
    """Copy matched `_pred.json` files to output_dir without the suffix."""
    image_stems = collect_image_stems(images_dir)
    if not image_stems:
        print("Error: no image files found.", file=sys.stderr)
        sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    copied = 0
    skipped_no_image = 0
    skipped_exists = 0
    seen_targets = set()

    for json_path in sorted(json_dir.iterdir(), key=lambda p: p.name.lower()):
        if not json_path.is_file() or json_path.suffix.lower() != ".json":
            continue

        name = json_path.stem
        suffix_part = f"{suffix}"
        if not name.endswith(suffix_part):
            continue

        stem = name[: -len(suffix_part)]
        if stem not in image_stems:
            skipped_no_image += 1
            rows.append(
                {
                    "source": str(json_path),
                    "target": "",
                    "status": "skipped_no_image",
                    "note": f"no image for stem '{stem}'",
                }
            )
            continue

        target_name = f"{stem}.json"
        target_path = output_dir / target_name

        if target_name in seen_targets:
            skipped_exists += 1
            rows.append(
                {
                    "source": str(json_path),
                    "target": str(target_path),
                    "status": "skipped_duplicate_target",
                    "note": f"target '{target_name}' already used",
                }
            )
            continue

        if target_path.exists():
            skipped_exists += 1
            rows.append(
                {
                    "source": str(json_path),
                    "target": str(target_path),
                    "status": "skipped_target_exists",
                    "note": f"target file already exists",
                }
            )
            continue

        seen_targets.add(target_name)
        if not dry_run:
            shutil.copy2(str(json_path), str(target_path))

        copied += 1
        rows.append(
            {
                "source": str(json_path),
                "target": str(target_path),
                "status": "copied" if not dry_run else "would_copy",
                "note": "",
            }
        )

    print(f"Image stems found: {len(image_stems)}")
    print(f"JSON files scanned: {sum(1 for r in rows if r['status'] != 'skipped_no_image') + skipped_no_image}")
    print(f"Copied: {copied}")
    print(f"Skipped (no matching image): {skipped_no_image}")
    print(f"Skipped (target exists/duplicate): {skipped_exists}")

    return rows
```

- [ ] **Step 4: Add report writer and CLI entry point**

```python
def write_report(report_path: Path, rows: list[dict]) -> None:
    """Write operation report as UTF-8 CSV."""
    fieldnames = ["source", "target", "status", "note"]
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    """Parse arguments and run the rename workflow."""
    parser = argparse.ArgumentParser(
        description=(
            "Copy JSON files ending with `{suffix}.json` to output_dir, "
            "removing the suffix when a matching image stem exists."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  %(prog)s --images-dir ./images --json-dir ./json --output-dir ./out
  %(prog)s --images-dir ./images --json-dir ./json --output-dir ./out --dry-run
""",
    )
    parser.add_argument(
        "--images-dir", required=True, type=Path, help="Directory containing images."
    )
    parser.add_argument(
        "--json-dir", required=True, type=Path, help="Directory containing JSON files."
    )
    parser.add_argument(
        "--output-dir", required=True, type=Path, help="Directory for renamed JSON files."
    )
    parser.add_argument(
        "--suffix",
        default="_pred",
        help="Suffix before .json to remove (default: _pred).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without copying files.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Optional CSV report path.",
    )

    args = parser.parse_args()

    images_dir = validate_directory(args.images_dir, "--images-dir")
    json_dir = validate_directory(args.json_dir, "--json-dir")

    rows = rename_pred_jsons(
        images_dir,
        json_dir,
        args.output_dir,
        suffix=args.suffix,
        dry_run=args.dry_run,
    )

    if args.report:
        write_report(args.report, rows)
        print(f"Report saved to: {args.report}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Add inline usage comment at the bottom**

Append a triple-quoted Chinese usage comment block (matching the style of other scripts) summarizing the purpose and example commands.

---

### Task 2: Run syntax and lint checks

**Files:**
- Create: `scripts/rename_pred_jsons.py`

- [ ] **Step 1: Check Python syntax**

Run: `python -m py_compile scripts/rename_pred_jsons.py`
Expected: No output (success).

- [ ] **Step 2: Run black**

Run: `bash scripts/format_code.sh` (or `black -l 79 scripts/rename_pred_jsons.py`)
Expected: File reformatted if needed.

- [ ] **Step 3: Run flake8**

Run: `flake8 scripts/rename_pred_jsons.py`
Expected: No errors.

---

### Task 3: Manual dry-run verification

**Files:**
- Create: `scripts/rename_pred_jsons.py`

- [ ] **Step 1: Create a temporary test directory**

Run:
```bash
mkdir -p /tmp/rename_test/images /tmp/rename_test/json /tmp/rename_test/out
touch /tmp/rename_test/images/0001.jpg
touch /tmp/rename_test/images/0002.png
echo '{}' > /tmp/rename_test/json/0001_pred.json
echo '{}' > /tmp/rename_test/json/0002_pred.json
echo '{}' > /tmp/rename_test/json/0003_pred.json
```

- [ ] **Step 2: Run the script in dry-run mode**

Run:
```bash
python scripts/rename_pred_jsons.py \
    --images-dir /tmp/rename_test/images \
    --json-dir /tmp/rename_test/json \
    --output-dir /tmp/rename_test/out \
    --dry-run
```

Expected output:
```
Image stems found: 2
JSON files scanned: 3
Copied: 2
Skipped (no matching image): 1
Skipped (target exists/duplicate): 0
```

- [ ] **Step 3: Verify output directory is empty**

Run: `ls /tmp/rename_test/out`
Expected: Empty.

- [ ] **Step 4: Run the script for real**

Run the same command without `--dry-run`.

Expected: `out/0001.json` and `out/0002.json` exist, `0003_pred.json` skipped.

---

### Task 4: Commit

**Files:**
- Create: `scripts/rename_pred_jsons.py`

- [ ] **Step 1: Stage and commit**

Run:
```bash
git add scripts/rename_pred_jsons.py
git commit -m "feat: add script to rename _pred.json annotations to image stems"
```

---

## Self-Review

1. **Spec coverage:**
   - 图片目录获取 stem ✅ Task 1 Step 2
   - JSON `_pred` 后缀识别与去掉 ✅ Task 1 Step 3
   - 无对应图片跳过 ✅ Task 1 Step 3
   - 仅输出 JSON 到指定目录 ✅ Task 1 Step 3
   - 命令行参数 ✅ Task 1 Step 4
   - 脚本内部参数通过默认常量/IDE 风格 ✅ Task 1 Step 4 (可后续补充 IDE 默认值块)

2. **Placeholder scan:** 无 TBD/TODO/"implement later"。
3. **Type consistency:** 使用 `Path`、`set[str]`、`list[dict]`，与其他脚本一致。
