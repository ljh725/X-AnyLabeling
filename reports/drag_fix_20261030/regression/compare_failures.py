"""Turn the JUnit XMLs of both trees into failure node-ID sets and diff them.

Usage:
  python compare_failures.py <regression-dir> [--out-prefix fixed|baseline]

Reads every XML in the directory and derives the label from the file name
(`<label>_<scope>.xml`).  Writes `<label>_failures.txt`, `<label>_counts.txt`
and, when both labels exist, `failure_diff.txt`.
"""
import json
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path


def node_id(case):
    file = case.attrib.get("file", "")
    name = case.attrib.get("name", "")
    classname = case.attrib.get("classname", "")
    if file:
        return f"{file.replace(chr(92), '/')}::{name}"
    return f"{classname.replace('.', '/')}::{name}"


def parse(directory):
    results = {}
    for xml in sorted(Path(directory).glob("*.xml")):
        # Naming convention: <scope>_<label>.xml, e.g. core_fixed.xml
        label = xml.stem.rsplit("_", 1)[-1]
        try:
            tree = ET.parse(xml)
        except ET.ParseError:
            results.setdefault(label, {"broken": []})["broken"].append(xml.name)
            continue
        bucket = results.setdefault(
            label, {"tests": 0, "passed": 0, "failed": 0, "skipped": 0, "failures": {}}
        )
        for case in tree.iter("testcase"):
            bucket["tests"] += 1
            failure = case.find("failure")
            error = case.find("error")
            skipped = case.find("skipped")
            if skipped is not None:
                bucket["skipped"] += 1
            elif failure is not None or error is not None:
                bucket["failed"] += 1
                kind = "failure" if failure is not None else "error"
                element = failure if failure is not None else error
                message = (element.attrib.get("message") or "").splitlines()
                bucket["failures"][node_id(case)] = {
                    "kind": kind,
                    "scope": xml.stem,
                    "message": message[0][:200] if message else "",
                }
            else:
                bucket["passed"] += 1
    return results


def main():
    directory = Path(sys.argv[1])
    results = parse(directory)
    summary = {}
    for label, bucket in sorted(results.items()):
        failures = bucket.get("failures", {})
        lines = [f"{node}\t{info['kind']}\t{info['message']}" for node, info in sorted(failures.items())]
        (directory / f"{label}_failures.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        counts = {
            "tests": bucket.get("tests", 0),
            "passed": bucket.get("passed", 0),
            "failed": bucket.get("failed", 0),
            "skipped": bucket.get("skipped", 0),
            "broken_xml": bucket.get("broken", []),
        }
        (directory / f"{label}_counts.json").write_text(json.dumps(counts, indent=2), encoding="utf-8")
        summary[label] = {"counts": counts, "failures": failures}
        print(f"{label}: {counts}")

    if "fixed" in summary and "baseline" in summary:
        fixed = set(summary["fixed"]["failures"])
        base = set(summary["baseline"]["failures"])
        only_fixed = sorted(fixed - base)
        only_base = sorted(base - fixed)
        diff = [
            "# failure set diff",
            "",
            f"fixed failures: {len(fixed)}",
            f"baseline failures: {len(base)}",
            "",
            "## only in fixed (potential regressions)",
            *([f"- {node}" for node in only_fixed] or ["- (none)"]),
            "",
            "## only in baseline (fixed or flaky)",
            *([f"- {node}" for node in only_base] or ["- (none)"]),
            "",
            "## shared (pre-existing)",
            *[f"- {node}" for node in sorted(fixed & base)],
        ]
        (directory / "failure_diff.txt").write_text("\n".join(diff) + "\n", encoding="utf-8")
        print("\n".join(diff))


if __name__ == "__main__":
    main()
