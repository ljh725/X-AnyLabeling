"""Durable thumbnail operations and guarded per-field revision evidence."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import os.path as osp
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

ID_FIELD = "xanylabeling_shape_id"


def document_digest(data: dict) -> str:
    """Fingerprint all annotation content independent of JSON whitespace."""
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def read_document(path: str) -> dict:
    """Read an authoritative JSON document, rejecting invalid roots."""
    with open(path, encoding="utf-8") as stream:
        data = json.load(stream)
    if not isinstance(data, dict) or not isinstance(data.get("shapes"), list):
        raise ValueError("Invalid annotation document")
    return data


def labels_of(data: dict) -> dict:
    """Capture labels with duplicate identities represented as conflicts."""
    labels = {}
    for shape in data.get("shapes", []):
        key = shape.get(ID_FIELD) if isinstance(shape, dict) else None
        if key:
            labels[key] = shape.get("label") if key not in labels else None
    return labels


def write_journal(record: dict) -> None:
    """Atomically persist a recoverable operation before updating its index."""
    path = record.get("journal_path")
    if not path:
        return
    os.makedirs(osp.dirname(path), exist_ok=True)
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as stream:
        json.dump(record, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


class HistoryStore:
    """Use the review connection so review edits and history commit together."""

    def __init__(self, connection: sqlite3.Connection, path: str) -> None:
        """Create additive versioned tables without touching legacy marks."""
        self.connection = connection
        self.path = path
        self.directory = (
            None if path.startswith("file:") else path + ".operations"
        )
        connection.executescript(
            "CREATE TABLE IF NOT EXISTS thumbnail_history ("
            "id TEXT PRIMARY KEY, created TEXT NOT NULL, kind TEXT NOT NULL,"
            "state TEXT NOT NULL, parent TEXT NOT NULL, payload TEXT NOT NULL);"
            "CREATE INDEX IF NOT EXISTS thumbnail_history_time ON thumbnail_history(created DESC);"
            "CREATE TABLE IF NOT EXISTS thumbnail_observations ("
            "path TEXT PRIMARY KEY, digest TEXT NOT NULL, labels TEXT NOT NULL, versions TEXT NOT NULL);"
            "CREATE TABLE IF NOT EXISTS thumbnail_consumed ("
            "parent TEXT NOT NULL, image TEXT NOT NULL, shape TEXT NOT NULL,"
            "child TEXT NOT NULL, PRIMARY KEY(parent,image,shape));"
            "CREATE TABLE IF NOT EXISTS thumbnail_history_schema (version INTEGER PRIMARY KEY);"
            "INSERT OR IGNORE INTO thumbnail_history_schema VALUES (1);"
        )

    def begin(
        self, kind: str, items: list, view: dict, parent: str = ""
    ) -> dict:
        """Persist a frozen request before any annotation write starts."""
        operation_id = uuid.uuid4().hex
        record = dict(
            id=operation_id,
            created=datetime.now(timezone.utc).isoformat(),
            kind=kind,
            state="pending",
            parent=parent,
            items=copy.deepcopy(items),
            view=copy.deepcopy(view),
            manifest_path="",
            transaction_id="",
        )
        if self.directory:
            record["journal_path"] = osp.join(
                self.directory, operation_id + ".json"
            )
        write_journal(record)
        with self.connection:
            self.put(record)
        return record

    def put(self, record: dict) -> None:
        """Update the query projection inside the caller's transaction."""
        self.connection.execute(
            "INSERT OR REPLACE INTO thumbnail_history VALUES (?,?,?,?,?,?)",
            (
                record["id"],
                record["created"],
                record["kind"],
                record["state"],
                record.get("parent", ""),
                json.dumps(record, ensure_ascii=False),
            ),
        )

    def get(self, operation_id: str) -> dict | None:
        """Return one full operation without modifying its state."""
        row = self.connection.execute(
            "SELECT payload FROM thumbnail_history WHERE id=?", (operation_id,)
        ).fetchone()
        return json.loads(row[0]) if row else None

    def query(
        self,
        text: str = "",
        state: str = "",
        since: str = "",
        until: str = "",
        offset: int = 0,
        limit: int = 50,
    ) -> list:
        """Search paginated operations using parameterized literal matching."""
        conditions = ["instr(payload, ?) > 0"]
        values = [text]
        for column, operator, value in (
            ("state", "=", state),
            ("created", ">=", since),
            ("created", "<=", until),
        ):
            if value:
                conditions.append(f"{column} {operator} ?")
                values.append(value)
        rows = self.connection.execute(
            "SELECT payload FROM thumbnail_history WHERE "
            + " AND ".join(conditions)
            + " ORDER BY created DESC,id DESC LIMIT ? OFFSET ?",
            (*values, min(100, max(1, limit)), max(0, offset)),
        )
        return [json.loads(row[0]) for row in rows]

    def observe(self, path: str, before_digest: str, after: dict) -> dict:
        """Track known saves; unknown intervening writes invalidate evidence."""
        return self.observe_values(
            path, before_digest, document_digest(after), labels_of(after)
        )

    def observe_values(
        self, path: str, before_digest: str, after_digest: str, labels: dict
    ) -> dict:
        """Store compact field evidence without copying embedded image data."""
        path = osp.normcase(osp.abspath(path))
        row = self.connection.execute(
            "SELECT digest,labels,versions FROM thumbnail_observations WHERE path=?",
            (path,),
        ).fetchone()
        old_labels = json.loads(row[1]) if row else {}
        versions = json.loads(row[2]) if row else {}
        unknown = bool(row and row[0] != before_digest)
        for key in old_labels.keys() | labels.keys():
            if unknown or old_labels.get(key) != labels.get(key):
                versions[key] = versions.get(key, 0) + 1
        self.connection.execute(
            "INSERT OR REPLACE INTO thumbnail_observations VALUES (?,?,?,?)",
            (path, after_digest, json.dumps(labels), json.dumps(versions)),
        )
        return versions

    def guard(self, parent: str, item: dict, current: dict) -> str:
        """Explain why an inverse is unsafe, or return an empty string."""
        if item.get("status") != "succeeded" or item.get("before") == item.get(
            "after"
        ):
            return "No successful change to revert"
        if self.consumed(parent, item):
            return "Already reverted"
        matches = [
            s
            for s in current["shapes"]
            if isinstance(s, dict) and s.get(ID_FIELD) == item["shape_id"]
        ]
        if len(matches) != 1:
            return "Object missing or identity is not unique"
        if matches[0].get("label") != item["after"]:
            return "Label changed after this operation"
        row = self.connection.execute(
            "SELECT digest,versions FROM thumbnail_observations WHERE path=?",
            (osp.normcase(osp.abspath(item["json_path"])),),
        ).fetchone()
        if not row or row[0] != document_digest(current):
            return "Unverified external changes"
        if json.loads(row[1]).get(item["shape_id"], 0) != item.get("version"):
            return "Label changed again after this operation"
        return ""

    def consumed(self, parent: str, item: dict) -> bool:
        """Return whether this exact historical effect was already reversed."""
        return (
            self.connection.execute(
                "SELECT 1 FROM thumbnail_consumed WHERE parent=? AND image=? AND shape=?",
                (parent, item["image_path"], item["shape_id"]),
            ).fetchone()
            is not None
        )

    def finish(self, record: dict) -> None:
        """Persist the authoritative result and atomically project revisions."""
        write_journal(record)
        existing = self.get(record["id"])
        if existing and existing["state"] not in ("pending", "unverified"):
            return
        with self.connection:
            versions = {}
            for path, evidence in record.get("documents", {}).items():
                newer = self.connection.execute(
                    "SELECT 1 FROM thumbnail_history h,json_each(h.payload,'$.items') i "
                    "WHERE h.created>? AND h.kind NOT IN ('review','review-revert') "
                    "AND json_extract(i.value,'$.json_path')=? "
                    "AND json_extract(i.value,'$.status')='succeeded' LIMIT 1",
                    (record["created"], path),
                ).fetchone()
                if newer:
                    continue
                versions[path] = self.observe_values(
                    path,
                    evidence["before_digest"],
                    evidence["after_digest"],
                    evidence["labels"],
                )
            for item in record["items"]:
                if item.get("status") == "succeeded":
                    if item["json_path"] in versions:
                        item["version"] = versions[item["json_path"]].get(
                            item["shape_id"], 0
                        )
                    if record.get("parent"):
                        self.connection.execute(
                            "INSERT OR IGNORE INTO thumbnail_consumed VALUES (?,?,?,?)",
                            (
                                record["parent"],
                                item["image_path"],
                                item["shape_id"],
                                record["id"],
                            ),
                        )
            record.pop("documents", None)
            self.put(record)

    def reconcile(self) -> list[str]:
        """Recover only confirmed outcomes from durable journals and manifests."""
        errors = []
        if not self.directory or not osp.isdir(self.directory):
            return errors
        for path in Path(self.directory).glob("*.json"):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
                old = self.get(record["id"])
                if old and old["state"] not in ("pending", "unverified"):
                    continue
                if record["state"] == "pending":
                    record = reconcile_manifest(record)
                self.finish(record)
            except (
                OSError,
                ValueError,
                KeyError,
                TypeError,
                sqlite3.Error,
            ) as exc:
                errors.append(f"{path.name}: {exc}")
        return errors

    def import_backups(self, root: str, image_resolver: object) -> int:
        """Import verified legacy manifests without inventing historical fields."""
        count = 0
        root = osp.normcase(osp.abspath(root))
        for path in Path(root).glob("*/manifest.json"):
            with path.open(encoding="utf-8") as stream:
                payload = json.load(stream)
            domain = payload.get("domain", {})
            if domain.get("kind") != "object-relabel" or osp.normcase(osp.abspath(domain.get("project_id", ""))) != root:
                continue
            transaction_id = payload.get("transaction_id", "")
            if not transaction_id or self.connection.execute(
                "SELECT 1 FROM thumbnail_history WHERE json_extract(payload,'$.transaction_id')=?",
                (transaction_id,),
            ).fetchone():
                continue
            items = []
            for entry in payload.get("entries", []):
                source = osp.normcase(osp.abspath(entry["source_path"]))
                if osp.commonpath((root, source)) != root:
                    raise ValueError("Backup source is outside the dataset")
                details = entry.get("domain_metadata", {}).get("history_changes", {})
                ids = domain.get("paths", {}).get(entry["source_path"], [""])
                for shape_id in ids:
                    info = details.get(shape_id, {})
                    items.append(dict(image_path=image_resolver(source) or "", json_path=source,
                                      shape_id=shape_id, before=info.get("before"), after=info.get("after"),
                                      status=entry.get("status", "unverified"), message="Imported backup; field-level recovery is unavailable."))
            record = dict(id="legacy-" + transaction_id, transaction_id=transaction_id,
                          created=datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
                          kind="relabel", state="completed", parent="", items=items, view={},
                          manifest_path=str(path), legacy=True, time_basis="manifest_mtime")
            with self.connection:
                self.put(record)
            count += 1
        return count


def reconcile_manifest(record: dict) -> dict:
    """Use persisted per-file commit evidence, never infer success from staging."""
    record = copy.deepcopy(record)
    record["state"] = "unverified"
    manifest = record.get("manifest_path")
    if not manifest or not osp.isfile(manifest):
        return record
    with open(manifest, encoding="utf-8") as stream:
        payload = json.load(stream)
    record["documents"] = {}
    entries = {e["source_path"]: e for e in payload.get("entries", [])}
    unresolved = False
    for item in record["items"]:
        entry = entries.get(osp.abspath(item["json_path"]))
        if not entry:
            item["status"] = "unverified"
            unresolved = True
            continue
        item["status"] = entry.get("status", "unverified")
        if record.get("kind") == "restore":
            item["status"] = (
                "succeeded"
                if entry.get("status") == "restored"
                else "unverified"
            )
            unresolved = unresolved or item["status"] == "unverified"
            continue
        metadata = entry.get("domain_metadata", {})
        details = metadata.get("history_changes", {})
        detail = details.get(item["shape_id"])
        if detail:
            item.update(detail)
        if entry.get("status") == "succeeded" and entry.get(
            "committed_fingerprint"
        ):
            if detail and detail.get("status") == "changeable":
                item["status"] = "succeeded"
            evidence = metadata.get("history_document")
            if evidence:
                record["documents"][item["json_path"]] = evidence
        elif entry.get("status") == "failed":
            item["status"] = "failed"
        else:
            item["status"] = "unverified"
            unresolved = True
    record["transaction_id"] = payload.get("transaction_id", "")
    record["state"] = "unverified" if unresolved else "completed"
    return record


def journal_restore(context: dict, results: list, completed: bool) -> None:
    """Persist recovery progress without misclassifying a completed file write."""
    statuses = {osp.normcase(osp.abspath(r.source_path)): r for r in results}
    for item in context["items"]:
        result = statuses.get(osp.normcase(osp.abspath(item["json_path"])))
        item["status"] = result.status if result else "unverified"
        item["message"] = result.message if result else ""
    context["state"] = "pending"
    if completed:
        successes = sum(i["status"] == "succeeded" for i in context["items"])
        context["state"] = (
            "completed"
            if successes == len(context["items"])
            else "partial" if successes else "failed"
        )
    try:
        write_journal(context)
    except OSError as exc:
        context["history_error"] = str(exc)


def result_record(context: dict, result: object) -> dict:
    """Merge a definitive domain result with the exact staged field values."""
    record = copy.deepcopy(context)
    record["manifest_path"] = result.manifest_path or ""
    if record["manifest_path"]:
        record = reconcile_manifest(record)
    record["transaction_id"] = result.transaction_id
    record["state"] = "cancelled" if result.cancelled else "completed"
    statuses = {(item.key[1], item.key[2]): item for item in result.objects}
    for item in record["items"]:
        outcome = statuses.get((item["image_path"], item["shape_id"]))
        if outcome:
            item["status"] = outcome.status
            item["message"] = outcome.message
        else:
            item["status"] = "unverified"
        if item["status"] != "succeeded":
            item["after"] = item.get("before")
    if any(
        item["status"] in ("failed", "conflict", "unverified")
        for item in record["items"]
    ):
        record["state"] = (
            "partial"
            if any(item["status"] == "succeeded" for item in record["items"])
            else "failed"
        )
    return record
