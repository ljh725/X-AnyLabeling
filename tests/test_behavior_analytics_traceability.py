"""Checks that every machine action row has an audited traceability row."""

import re
from pathlib import Path

from anylabeling.services.behavior_analytics import ACTION_CATALOG


def test_traceability_document_covers_every_catalog_row_once():
    """The audit document cannot silently omit a newly registered action."""
    path = Path("docs/behavior_analytics_action_traceability.md")
    text = path.read_text(encoding="utf-8")
    assert "动作目录版本：`1.0`" in text
    rows = [line for line in text.splitlines() if line.startswith("|")]
    body = rows[2:]
    ids = [row.split("|", 2)[1].strip() for row in body]
    expected = [entry.catalog_id for entry in ACTION_CATALOG]
    assert ids == expected
    assert all(
        len(re.findall(r"\| (covered|partial|missing|legacy) \|", row)) == 1
        for row in body
    )
