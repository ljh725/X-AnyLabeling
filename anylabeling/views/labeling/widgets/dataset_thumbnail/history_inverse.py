"""Pure field-level inverse plans using the shared annotation transaction."""

import copy
import os.path as osp
import sqlite3
from collections import Counter
from types import MappingProxyType

from .history_store import HistoryStore, ID_FIELD
from ..object_relabel import (
    MarkedObjectRef,
    ObjectRelabelPlan,
    ObjectTransformation,
)


def build_inverse_plan(
    store: HistoryStore, parent: dict, selected: list, project: str, view: dict
) -> ObjectRelabelPlan:
    """Freeze only actual members of one verified persisted operation."""
    saved = store.get(parent["id"])
    if not saved or saved["state"] in ("pending", "unverified"):
        raise ValueError("Operation needs verification")
    keys = {(i["image_path"], i["shape_id"]) for i in selected}
    items = [
        i for i in saved["items"] if (i["image_path"], i["shape_id"]) in keys
    ]
    if len(items) != len(keys) or not items:
        raise ValueError("Select objects from one verified operation")
    targets = {}
    for item in items:
        if (
            not isinstance(item.get("before"), str)
            or not item["before"].strip()
        ):
            raise ValueError("Historical label is missing")
        targets.setdefault(item["json_path"], []).append(
            MarkedObjectRef(
                project,
                item["image_path"],
                item["shape_id"],
                f'{item.get("after")} → {item["before"]}',
            )
        )
    context = store.begin(
        "revert",
        [
            dict(
                i,
                before=i.get("after"),
                after=i.get("before"),
                status="pending",
            )
            for i in items
        ],
        view,
        parent["id"],
    )
    context["history_db"] = store.path
    return ObjectRelabelPlan(
        project,
        "↶",
        MappingProxyType({p: tuple(v) for p, v in targets.items()}),
        history_context=context,
        inverse_items=tuple(copy.deepcopy(items)),
    )


def transform_inverse(
    plan: ObjectRelabelPlan, path: str, original: dict
) -> tuple:
    """Guard each selected field and preserve all unrelated document content."""
    targets = [
        i
        for i in plan.inverse_items
        if osp.abspath(i["json_path"]) == osp.abspath(path)
    ]
    counts = Counter(
        s.get(ID_FIELD) for s in original["shapes"] if isinstance(s, dict)
    )
    result = copy.deepcopy(original)
    statuses, messages = {}, {}
    connection = sqlite3.connect(plan.history_context["history_db"], uri=True)
    try:
        store = HistoryStore(connection, plan.history_context["history_db"])
        duplicate = any(counts[i["shape_id"]] > 1 for i in targets)
        for item in targets:
            error = (
                "Duplicate object identity in file"
                if duplicate
                else store.guard(
                    plan.history_context["parent"], item, original
                )
            )
            key = item["shape_id"]
            if error:
                statuses[key], messages[key] = "conflict", error
                continue
            shape = next(s for s in result["shapes"] if s.get(ID_FIELD) == key)
            shape["label"] = item["before"]
            statuses[key] = "changed"
    finally:
        connection.close()
    return (
        ObjectTransformation(
            result, "changed" in statuses.values(), MappingProxyType(statuses)
        ),
        messages,
    )
