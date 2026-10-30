"""Build the authoritative failure set from the pytest logs and diff the trees.

The JUnit XML of this pytest version omits unittest subtests, so the `-rfE`
summary lines are used instead: they carry the real node IDs, including
`SUBFAILED` entries.  Writes failure lists, the diff and the counts that
explain "N failed" (tests + subtest failures).
"""
import re
import sys
from pathlib import Path

FAIL_RE = re.compile(r"^(FAILED|SUBFAILED(?:\([^)]*\))?)\s+(\S+)")
SUMMARY_RE = re.compile(r"^(\d+) failed, (\d+) passed")

directory = Path(sys.argv[1])


def read(label):
    log = directory / f"core_{label}.log"
    text = log.read_text(encoding="utf-8", errors="replace").splitlines()
    tests, subs, sub_names = [], [], set()
    summary = ""
    for line in text:
        match = FAIL_RE.match(line)
        if match:
            kind, node = match.groups()
            if kind == "FAILED":
                tests.append(node)
            else:
                subs.append(node)
                sub_names.add(node)
        elif SUMMARY_RE.match(line):
            summary = line.strip()
    return {
        "tests": sorted(set(tests)),
        "subtest_nodes": sorted(sub_names),
        "subtest_entries": len(subs),
        "summary": summary,
    }


fixed = read("fixed")
baseline = read("baseline")

(directory / "failures_fixed.txt").write_text("\n".join(fixed["tests"]) + "\n", encoding="utf-8")
(directory / "failures_baseline.txt").write_text("\n".join(baseline["tests"]) + "\n", encoding="utf-8")

fixed_set, base_set = set(fixed["tests"]), set(baseline["tests"])
only_fixed = sorted(fixed_set - base_set)
only_base = sorted(base_set - fixed_set)

lines = [
    "# 失败集合对照（CUSTOM-003 全量回归）",
    "",
    f"fixed:    {fixed['summary']}",
    f"baseline: {baseline['summary']}",
    "",
    "计数口径：pytest 的 `N failed` = 用例级失败 + unittest 子测试失败条目数。"
    f"fixed 为 {len(fixed['tests'])} 个用例级失败 + {fixed['subtest_entries']} 条子测试失败；"
    f"baseline 为 {len(baseline['tests'])} + {baseline['subtest_entries']}。",
    "",
    "## 仅修复后失败（潜在回归）",
    *([f"- {node}" for node in only_fixed] or ["- （无）"]),
    "",
    "## 仅基线失败（修复或偶发）",
    *([f"- {node}" for node in only_base] or ["- （无）"]),
    "",
    "## 两树共有（既有失败）",
    *[f"- {node}" for node in sorted(fixed_set & base_set)],
    "",
    "## 子测试失败（两树相同）",
    *[f"- {node}" for node in sorted(set(fixed["subtest_nodes"]) & set(baseline["subtest_nodes"]))],
]
(directory / "failure_diff.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
print("\n".join(lines))
