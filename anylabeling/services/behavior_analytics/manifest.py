"""Read-only diagnostics and rebuild helpers for local event manifests."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

_HOURLY_RE = re.compile(r"^events-\d{4}-\d{2}-\d{2}-\d{2}\.jsonl$")


@dataclass(frozen=True)
class ManifestDiagnostic:
    """Validation facts for one hourly JSONL shard."""

    path: Path
    manifest_path: Path
    issues: tuple[str, ...]
    event_count: int
    file_size_bytes: int
    sha256: str

    @property
    def status(self) -> str:
        """Return ``ok`` or a stable diagnostic status."""
        if not self.issues:
            return "ok"
        if "missing_manifest" in self.issues:
            return "missing_manifest"
        return "inconsistent"

    @property
    def rebuildable(self) -> bool:
        """Return whether the source is readable enough to rebuild."""
        return self.event_count >= 0 and "unreadable_source" not in self.issues


def iter_hourly_shards(source: str | Path) -> Iterable[Path]:
    """Yield only new UTC-hour JSONL shards without changing the source."""
    path = Path(source)
    if path.is_file():
        if _HOURLY_RE.match(path.name):
            yield path
        return
    if path.is_dir():
        yield from sorted(
            candidate
            for candidate in path.rglob("*.jsonl")
            if _HOURLY_RE.match(candidate.name)
        )


def _scan_source(
    path: Path,
) -> tuple[int, str | None, str | None, dict[str, int]]:
    """Count parseable lines and collect bounded manifest facts."""
    count = 0
    first = None
    last = None
    versions: dict[str, int] = {}
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            data = json.loads(line)
            count += 1
            occurred = data.get("occurred_at_utc")
            if occurred:
                first = occurred if first is None else min(first, occurred)
                last = occurred if last is None else max(last, occurred)
            version = str(data.get("schema_version", "unknown"))
            versions[version] = versions.get(version, 0) + 1
    return count, first, last, versions


def diagnose_event_shards(source: str | Path) -> list[ManifestDiagnostic]:
    """Diagnose missing, stale, corrupt and active hourly manifests."""
    diagnostics: list[ManifestDiagnostic] = []
    for path in iter_hourly_shards(source):
        manifest_path = path.with_name(f"{path.stem}.manifest.json")
        file_bytes = path.read_bytes()
        digest = hashlib.sha256(file_bytes).hexdigest()
        issues: list[str] = []
        try:
            count, first, last, versions = _scan_source(path)
        except (OSError, UnicodeError, json.JSONDecodeError):
            count, first, last, versions = -1, None, None, {}
            issues.append("unreadable_source")
        manifest = None
        if not manifest_path.exists():
            issues.append("missing_manifest")
        else:
            try:
                manifest = json.loads(
                    manifest_path.read_text(encoding="utf-8")
                )
            except (OSError, UnicodeError, json.JSONDecodeError):
                issues.append("invalid_manifest")
        if isinstance(manifest, dict):
            if not manifest.get("manifest_complete", False):
                issues.append("active_shard")
            checks = {
                "event_count": count,
                "file_size_bytes": len(file_bytes),
                "sha256": digest,
            }
            for key, expected in checks.items():
                if key in manifest and manifest[key] != expected:
                    issues.append(f"stale_{key}")
            if manifest.get("first_utc") not in (None, first):
                issues.append("stale_first_utc")
            if manifest.get("last_utc") not in (None, last):
                issues.append("stale_last_utc")
            if manifest.get("schema_versions") not in (None, versions):
                issues.append("stale_schema_versions")
        diagnostics.append(
            ManifestDiagnostic(
                path=path,
                manifest_path=manifest_path,
                issues=tuple(dict.fromkeys(issues)),
                event_count=count,
                file_size_bytes=len(file_bytes),
                sha256=digest,
            )
        )
    return diagnostics


def rebuild_event_shard_manifest(path: str | Path) -> Path:
    """Rebuild one hourly manifest atomically from its read-only JSONL source."""
    source = Path(path)
    if not _HOURLY_RE.match(source.name):
        raise ValueError("manifest rebuild requires an hourly JSONL shard")
    count, first, last, versions = _scan_source(source)
    file_bytes = source.read_bytes()
    manifest_path = source.with_name(f"{source.stem}.manifest.json")
    manifest = {
        "manifest_complete": True,
        "file_name": source.name,
        "event_count": count,
        "first_utc": first,
        "last_utc": last,
        "schema_versions": versions,
        "file_size_bytes": len(file_bytes),
        "sha256": hashlib.sha256(file_bytes).hexdigest(),
    }
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{manifest_path.name}.",
        suffix=".tmp",
        dir=source.parent,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(manifest, stream, ensure_ascii=False, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, manifest_path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return manifest_path
