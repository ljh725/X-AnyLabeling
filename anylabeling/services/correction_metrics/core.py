"""Data contracts for correction metrics.  No Qt objects are retained."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import threading
import uuid
from collections import Counter
from pathlib import Path


SCHEMA_VERSION = 1
ORIGINS = {"unknown-existing", "replacement", "additive"}
ORIGIN_FIELDS = {
    "run_id", "model", "model_name", "model_type", "model_version",
    "weight_version", "config_digest", "prompt", "thresholds",
    "category_version", "elapsed_s", "inference_seconds", "status",
    "started_at", "ended_at", "mode", "replace",
}
SHAPE_ID = "xanylabeling_shape_id"

# ``unknown-origin`` only discloses that the starting labels predate
# the statistics.  Events spec lets scope, identity, storage and timing
# gaps invalidate a full comparison, but not an unknown provenance, so
# every other issue stays blocking (fail closed).
DISCLOSURE_ISSUES = frozenset({"unknown-origin"})


def uid():
    return uuid.uuid4().hex


def encode(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    )


def digest(value):
    return hashlib.sha256(encode(value).encode("utf-8")).hexdigest()


def path_identity(path):
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def dataset_identity(image_root, label_root=None):
    """Stable database key even for identically named files on different roots."""
    paths = [path_identity(image_root), path_identity(label_root or image_root)]
    return str(uuid.uuid5(uuid.NAMESPACE_URL, encode(paths)))


def safe_provenance(value):
    """Keep only explicit prediction metadata, never arbitrary request/config data."""
    result = {}
    for key, item in (value or {}).items():
        if key not in ORIGIN_FIELDS or item is None:
            continue
        if key == "thresholds" and isinstance(item, dict):
            result[key] = {
                str(k): v for k, v in item.items()
                if type(v) in (int, float) and math.isfinite(v)
            }
        elif type(item) in (str, bool, int, float):
            if isinstance(item, str) and "://" in item:
                continue
            if type(item) is float and not math.isfinite(item):
                continue
            result[key] = item
    return result


def _points(data):
    pairs = []
    for point in data:
        x, y = (point.x(), point.y()) if hasattr(point, "x") else point[:2]
        x, y = float(x), float(y)
        if not (math.isfinite(x) and math.isfinite(y)):
            raise ValueError("non-finite coordinate")
        pairs.append([x or 0.0, y or 0.0])
    return pairs


def snapshot(shapes, metadata=None):
    """Return an owned JSON-compatible semantic snapshot of shapes or shape dicts."""
    if isinstance(shapes, dict) and "objects" in shapes:
        return shapes
    objects, issues = {}, set()
    for number, shape in enumerate(shapes):
        raw = shape if isinstance(shape, dict) else shape.to_dict()
        key = raw.get(SHAPE_ID)
        if not isinstance(key, str) or not key or key in objects:
            issues.add("shape-identity-conflict")
            key = f"?unmatched:{number}"
            while key in objects:
                key += "?"
        kind = raw.get("shape_type") or "polygon"
        try:
            geometry = _points(raw.get("points", ()))
            if kind == "rectangle":
                if len(geometry) < 2:
                    raise ValueError("incomplete rectangle")
                xs, ys = zip(*geometry)
                geometry = [min(xs), min(ys), max(xs), max(ys)]
        except (TypeError, ValueError, IndexError):
            geometry = []
            issues.add("invalid-geometry")
        # Missing/default fields from a legacy file are equivalent to Shape
        # defaults written by save_labels. Flags which are false are data.
        defaults = {
            "flags": {}, "attributes": {}, "kie_linking": [],
            "description": "", "difficult": False, "group_id": None,
            "score": None,
        }
        details = {
            k: v for k, v in raw.items()
            if k not in (SHAPE_ID, "points", "label", "shape_type", "locked")
            and v is not None and v != defaults.get(k, object())
        }
        objects[key] = {
            "kind": kind, "label": raw.get("label") or "",
            "geometry": geometry,
        }
        if details:
            objects[key]["details"] = copy.deepcopy(details)
    return {"objects": objects, "issues": sorted(issues),
            "metadata": copy.deepcopy(metadata or {})}


def safe_snapshot(value):
    return snapshot(value)


def _rectangles(data):
    return {k: v for k, v in data["objects"].items()
            if v["kind"] == "rectangle"}


def differences(baseline, final, aliases=None, class_comparable=True):
    """Summarise one round. All rates use baseline rectangle count."""
    aliases = aliases or {}
    b, f = _rectangles(baseline), _rectangles(final)
    common = b.keys() & f.keys()
    # A change of shape type is a scope transition rather than a new/deleted ID.
    added = f.keys() - baseline["objects"].keys()
    deleted = b.keys() - final["objects"].keys()
    converted = (b.keys() - f.keys() - deleted) | (f.keys() - b.keys() - added)
    g = {k for k in common if b[k]["geometry"] != f[k]["geometry"]}
    c = {k for k in common if aliases.get(b[k]["label"], b[k]["label"])
         != f[k]["label"]} if class_comparable else None
    modified = len(deleted | g | c) if c is not None else None
    unchanged = len(common - g - c) if c is not None else None
    counts = Counter()
    for k, v in b.items():
        counts[("initial", v["label"], "")] += 1
    for k, v in f.items():
        counts[("final", "", v["label"])] += 1
    for k in added:
        counts[("added", "", f[k]["label"])] += 1
    for k in deleted:
        counts[("deleted", b[k]["label"], "")] += 1
    for k in g:
        counts[("geometry", b[k]["label"], "")] += 1
    for k in c or ():
        counts[("class_changed", b[k]["label"], f[k]["label"])] += 1
    return {
        "baseline_count": len(b), "final_count": len(f),
        "added": len(added), "deleted": len(deleted),
        "geometry_changed": len(g), "class_changed": len(c) if c is not None else None,
        "modified_original": modified, "unchanged": unchanged,
        "modified_rate": modified / len(b) if b and modified is not None else None,
        "unchanged_rate": unchanged / len(b) if b and unchanged is not None else None,
        "unsupported_count": len(final["objects"]) - len(f),
        "scope_changes": len(converted),
        "classes": [
            {"kind": kind, "initial_class": old, "final_class": new,
             "count": n,
             "denominator": (counts[("initial", old, "")]
                              if kind in ("initial", "geometry", "deleted",
                                          "class_changed")
                              else len(b)) or None}
            for (kind, old, new), n in sorted(counts.items())
        ],
    }


def initialise_state(dataset, image, label, content, data, origin, provenance,
                     predicted, saved, phase):
    if origin not in ORIGINS:
        raise ValueError(f"unknown correction baseline origin: {origin}")
    issues = set(data["issues"])
    if not content:
        issues.add("unknown-image-version")
    if any(x["kind"] != "rectangle" for x in data["objects"].values()):
        issues.add("partial-scope")
    known = set(predicted) & data["objects"].keys()
    return {
        "schema_version": SCHEMA_VERSION, "dataset_id": dataset,
        "image_path": path_identity(image), "label_path": path_identity(label),
        "image_digest": content, "round_id": uid(), "phase": phase,
        "origin": origin, "provenance": safe_provenance(provenance),
        "predicted_ids": sorted(known), "baseline": data, "draft": data,
        "saved": data if saved else None, "revision": digest(data) if saved else "",
        "pending": None, "seq": 0, "saved_seq": 0, "issues": sorted(issues),
        "counts": {}, "touched": [], "touches": 0, "alias": {},
        "comparable_classes": True, "sessions": {}, "completed": False,
        "completion": None, "current": True, "active": True,
        "undo_stack": [], "quality": "not-assessed", "quality_source": None,
        "saved_alias": {}, "saved_classes": True,
    }


def report_row(state, draft=False):
    selected = state["draft"] if draft else state["saved"]
    base = state["baseline"]
    aliases = state["alias"] if draft else state["saved_alias"]
    comparable = state["comparable_classes"] if draft else state["saved_classes"]
    net = differences(base, selected or base, aliases, comparable)
    issues = set(state["issues"])
    if selected is None:
        issues.add("unsaved-result")
        for field in net:
            if field != "baseline_count":
                net[field] = [] if field == "classes" else None
    if (net["unsupported_count"] or net["scope_changes"] or
            len(base["objects"]) != net["baseline_count"]):
        issues.add("partial-scope")
    if not comparable:
        issues.add("class-incomparable")
    prov = state["provenance"]
    if state["origin"] == "unknown-existing":
        issues.add("unknown-origin")
    if "shape-identity-conflict" in issues or "invalid-geometry" in issues:
        for field in ("added", "deleted", "geometry_changed", "class_changed",
                      "modified_original", "unchanged", "modified_rate", "unchanged_rate"):
            net[field] = None
        net["classes"] = [v for v in net["classes"] if v["kind"] in ("initial", "final")]
    counts = state["counts"]
    totals = Counter()
    for record in state["sessions"].values():
        totals.update(record["totals"])
    return {
        **{key: state[key] for key in (
            "schema_version", "dataset_id", "image_path", "label_path",
            "image_digest", "round_id", "phase", "origin", "revision",
            "completed", "current", "quality", "quality_source",
        )}, **net, "session_ids": list(state["sessions"]),
        "completion": state["completion"],
        "run_id": prov.get("run_id"), "model": prov.get("model") or prov.get("model_name"),
        "model_version": prov.get("model_version") or prov.get("weight_version"),
        "config_digest": prov.get("config_digest"), "prompt": prov.get("prompt"),
        "thresholds": prov.get("thresholds"), "category_version": prov.get("category_version"),
        "inference_seconds": prov.get("inference_seconds", prov.get("elapsed_s")),
        "ai_count": sum(1 for k in state["predicted_ids"] if
                        base["objects"].get(k, {}).get("kind") == "rectangle")
        if state["origin"] != "unknown-existing" else None,
        "transactions": sum(v for k, v in counts.items() if k not in
                            ("review-confirm", "review-undo", "taxonomy",
                             "discard", "undo", "redo")),
        "undo_count": counts.get("undo", 0), "redo_count": counts.get("redo", 0), "operation_counts": dict(counts),
        "touches": state["touches"], "unique_objects": len(state["touched"]),
        "time": dict(totals), "issues": sorted(issues),
        "comparable": not (issues - DISCLOSURE_ISSUES),
        "is_draft": draft and selected != state["saved"],
    }


class CorrectionRound:
    """A single image, immutable starting state and an append-only work journal."""

    def __init__(self, store, state, seen=()):
        self.store = store
        self._state = state
        self._seen = set(seen)
        self._lock = threading.RLock()

    @property
    def round_id(self):
        return self._state["round_id"]

    @property
    def completed(self):
        return self._state["completed"]

    @property
    def saved_revision(self):
        return self._state["revision"]

    @property
    def image_path(self):
        return self._state["image_path"]

    @property
    def label_path(self):
        return self._state["label_path"]

    @property
    def dirty(self):
        return self._state["saved"] != self._state["draft"]

    def row(self, draft=False):
        with self._lock:
            state = self._state.copy()
            gaps = set(self.store.gaps(self.round_id))
            target = getattr(self.store, "gaps_for", None)
            if target is not None:
                gaps |= set(target(self.image_path, self.label_path))
            state["issues"] = sorted(set(state["issues"]) | gaps)
            return report_row(state, draft)

    def _persist(self, **operations):
        # State values use copy-on-write so the writer never sees a later edit.
        return self.store._enqueue(self._state.copy(), operations)

    def mark_gap(self, reason):
        with self._lock:
            s = self._state
            if reason not in s["issues"]:
                s["issues"] = sorted({*s["issues"], reason})
                self._persist()

    def _event(self, kind, source, before, after, *, tx=None, undo_of=None,
               count_touches=True):
        tx = tx or uid()
        if tx in self._seen:
            return None
        self._seen.add(tx)
        s = self._state
        ids = set(before) | set(after)
        s["seq"] += 1
        counts = s["counts"].copy()
        counts[kind] = counts.get(kind, 0) + 1
        s["counts"] = counts
        if count_touches:
            s["touches"] += len(ids)
            s["touched"] = sorted(set(s["touched"]) | ids)
        return {
            "id": tx, "seq": s["seq"], "kind": kind,
            "session_id": self.store.session_id, "source": source,
            "before": before, "after": after, "undo_of": undo_of,
        }

    def sync(self, shapes, kind="edit", source="manual", transaction_id=None,
             undo_of=None):
        with self._lock:
            if transaction_id and transaction_id in self._seen:
                return False
            old = self._state["draft"]
            new = snapshot(shapes)
            keys = old["objects"].keys() | new["objects"].keys()
            return self._replace(new, keys, kind, source, transaction_id, undo_of)

    def patch(self, shapes=(), removed_ids=(), kind="edit", source="manual",
              transaction_id=None, undo_of=None):
        """Record a completed transaction from just the affected objects."""
        with self._lock:
            if transaction_id and transaction_id in self._seen:
                return False
            old = self._state["draft"]
            changed = snapshot(shapes)
            objects = old["objects"].copy()
            removed = set(removed_ids)
            for key in removed:
                objects.pop(key, None)
            objects.update(changed["objects"])
            new = {**old, "objects": objects,
                   "issues": sorted(set(old["issues"]) | set(changed["issues"]))}
            return self._replace(new, removed | changed["objects"].keys(),
                                 kind, source, transaction_id, undo_of)

    def _replace(self, new, keys, kind, source, tx, undo_of):
        s = self._state
        old = s["draft"]
        a, b = old["objects"], new["objects"]
        changed = {k for k in keys if a.get(k) != b.get(k)}
        meta_changed = new["metadata"] != old["metadata"]
        if not changed and not meta_changed and old["issues"] == new["issues"]:
            return False
        s["draft"] = new
        s["completed"] = False
        if s.get("quality", "not-assessed") != "not-assessed":
            # A quality conclusion belongs to the revision it was made on; a
            # real content change invalidates it instead of silently carrying
            # an old verdict onto new content.
            s["quality"] = "not-assessed"
            s["quality_source"] = None
        issues = set(s["issues"]) | set(new["issues"])
        if any(k in b and b[k]["kind"] != "rectangle" for k in changed):
            issues.add("partial-scope")
        scope_changed = any(k in a and k in b and a[k]["kind"] != b[k]["kind"]
                            for k in changed)
        if scope_changed:
            issues.add("type-conversion")
        s["issues"] = sorted(issues)
        rects = {k for k in changed if any(
            k in group and group[k]["kind"] == "rectangle" for group in (a, b))}
        if not rects and kind != "undo":
            kind = "other-content"
        elif scope_changed:
            kind = "scope-change"
        elif kind == "edit":
            if all(k not in a for k in rects):
                kind = "create"
            elif all(k not in b for k in rects):
                kind = "delete"
            elif all(k in a and k in b and a[k]["label"] != b[k]["label"]
                     and a[k]["geometry"] == b[k]["geometry"] for k in rects):
                kind = "relabel"
            elif all(k in a and k in b and a[k]["label"] == b[k]["label"]
                     and a[k]["geometry"] != b[k]["geometry"] for k in rects):
                kind = "geometry"
        stack = s["undo_stack"]
        if kind == "undo" and not undo_of and stack:
            undo_of = stack[-1]
        event = self._event(
            kind, source, {k: a[k] for k in rects if k in a},
            {k: b[k] for k in rects if k in b},
            tx=tx, undo_of=undo_of, count_touches=kind != "taxonomy",
        )
        if kind == "undo" and undo_of in stack:
            s["undo_stack"] = [key for key in stack if key != undo_of]
        elif kind not in ("undo", "taxonomy", "scope-change"):
            s["undo_stack"] = [*stack[-255:], event["id"]]
        self._persist(event=event)
        return True

    def review_event(self, kind, affected_ids=(), transaction_id=None):
        with self._lock:
            if transaction_id and transaction_id in self._seen:
                return False
            event = self._event(
                kind, "review", {}, dict.fromkeys(affected_ids), tx=transaction_id,
                count_touches=False,
            )
            self._persist(event=event)
            return True

    def taxonomy(self, mapping, *, comparable=True, shapes=None):
        """Apply an explicit class-system migration without a personal relabel."""
        with self._lock:
            s = self._state
            old = s["draft"]
            labels = {v["label"] for v in old["objects"].values()}
            mapped = {label: mapping.get(label, label) for label in labels}
            unique = all(isinstance(v, str) for v in mapped.values())
            if unique:
                unique = len(set(mapped.values())) == len(labels)
            s["comparable_classes"] = bool(s["comparable_classes"] and comparable and unique)
            old_names = {o["label"] for o in s["baseline"]["objects"].values()}
            aliases = {}
            for label in old_names:
                previous = s["alias"].get(label, label)
                target = mapping.get(previous, previous)
                if isinstance(target, str):
                    aliases[label] = target
            s["alias"] = aliases
            new = snapshot(shapes) if shapes is not None else {
                **old,
                "objects": {
                    k: {**v, "label": mapped[v["label"]]} if
                    isinstance(mapped[v["label"]], str) else v
                    for k, v in old["objects"].items()
                },
            }
            changed = self._replace(new, old["objects"].keys() | new["objects"].keys(),
                                    "taxonomy", "taxonomy_change", None, None)
            if not changed:
                self._persist()
            return changed

    def prepare_save(self, shapes, label_path=None):
        with self._lock:
            s = self._state
            new = snapshot(shapes)
            if new != s["draft"]:
                # Never invent a user transaction to explain an unmatched checkpoint.
                s["draft"] = new
                s["completed"] = False
                s["issues"] = sorted({*s["issues"], "unobserved-content-change"})
            token = {
                "id": uid(), "round_id": self.round_id,
                "target": path_identity(label_path or self.label_path),
                "digest": digest(new), "snapshot": new, "seq": s["seq"],
                "alias": s["alias"], "classes": s["comparable_classes"],
            }
            s["pending"] = token
            self._persist()
            return token

    def saved(self, token):
        with self._lock:
            s = self._state
            if not token or token["round_id"] != self.round_id:
                return False
            pending = s["pending"]
            if not pending or token["id"] != pending["id"]:
                return False
            if token["target"] != self.label_path:
                # Save As forks, preserving the old target and its saved version.
                self.store.open_round(
                    self.image_path, token["target"], s["image_digest"], token["snapshot"],
                    origin="unknown-existing", saved=True, force_new=True, phase=s["phase"],
                )
                s["pending"] = None
                self._persist()
                return True
            s.update(saved=token["snapshot"], revision=token["digest"],
                     saved_seq=token["seq"], saved_alias=token["alias"],
                     saved_classes=token["classes"], pending=None)
            self._persist(revision=token)
            return True

    def save_failed(self, token):
        with self._lock:
            if token and (self._state["pending"] or {}).get("id") == token.get("id"):
                self._state["pending"] = None
                self._persist()

    def discard(self):
        with self._lock:
            s = self._state
            if s["draft"] == s["saved"] and not s["pending"]:
                return False
            s.update(draft=s["saved"] or s["baseline"], pending=None,
                     alias=s["saved_alias"], comparable_classes=s["saved_classes"],
                     completed=False, undo_stack=[])
            if s["saved"] is None:
                s.update(active=False, current=False)
            event = self._event("discard", "manual", {}, {}, count_touches=False)
            self._persist(event=event, discard_through=s["seq"])
            return True

    def finish(self):
        with self._lock:
            s = self._state
            if not s["revision"] or self.dirty or s["pending"] or not s["active"]:
                return False
            if s["completed"]:
                return True
            if not self.store.flush():
                return False
            s["completed"] = True
            completion = {"id": uid(), "revision": s["revision"],
                          "seq": s["seq"], "cost": report_row(s)}
            s["completion"] = completion["id"]
            if self._persist(completion=completion) and self.store.flush():
                return True
            s.update(completed=False, completion=None)
            return False

    def resume(self):
        with self._lock:
            if not self.completed:
                return False
            self._state["completed"] = False
            self._persist()
            return True

    def set_quality(self, value, source=None):
        """Record an explicit, sourced quality conclusion.

        Completion and "everything left unchanged" are not quality evidence, so
        this is only called by an explicit quality action; the source records
        where the conclusion came from so the report can check it.
        """
        with self._lock:
            s = self._state
            value = str(value or "").strip() or "not-assessed"
            if value != "not-assessed" and not source:
                # Only an explicit, sourced conclusion may stand in for quality.
                return False
            s["quality"] = value
            s["quality_source"] = (
                copy.deepcopy(source) if value != "not-assessed" else None
            )
            self._persist()
            return True

    def set_time(self, session_id, totals, *, closed=False, audit=None):
        """Absolute seconds for a session: a repeated heartbeat never doubles time."""
        with self._lock:
            s = self._state
            record = {
                "totals": {str(k): float(v) for k, v in totals.items()
                           if type(v) in (int, float) and math.isfinite(v) and v >= 0},
                "closed": closed, "audit": copy.deepcopy(audit),
            }
            s["sessions"] = {**s["sessions"], session_id: record}
            self._persist()
