"""Persistence helpers for the optional dense-review namespace."""

from __future__ import annotations

import hashlib
import json
import os
import os.path as osp
from dataclasses import dataclass
from typing import Any, Mapping, Optional

from .models import (
    REVIEW_FIELD,
    REVIEW_VERSION,
    IncompatibleReviewState,
)

DENSE_REVIEW_FIELD = REVIEW_FIELD


@dataclass(frozen=True)
class AnnotationFileState:
    """Minimal disk identity used to detect external annotation edits."""

    exists: bool
    mtime_ns: int = 0
    size: int = 0
    sha256: str = ""

    def changed_from(self, other: Optional["AnnotationFileState"]) -> bool:
        if other is None:
            return False
        return (
            self.exists != other.exists
            or self.mtime_ns != other.mtime_ns
            or self.size != other.size
            or self.sha256 != other.sha256
        )


def load_payload(
    other_data: Mapping[str, Any],
) -> Optional[Mapping[str, Any]]:
    """Return the optional namespace without interpreting its version."""
    if not isinstance(other_data, Mapping):
        return None
    payload = other_data.get(DENSE_REVIEW_FIELD)
    if payload is None:
        return None
    if not isinstance(payload, Mapping):
        raise IncompatibleReviewState("密集复核进度必须是 JSON 对象")
    return payload


def payload_version(payload: Optional[Mapping[str, Any]]) -> Optional[int]:
    if not isinstance(payload, Mapping):
        return None
    version = payload.get("version")
    if isinstance(version, bool) or not isinstance(version, int):
        return None
    return version


def is_supported_payload(payload: Optional[Mapping[str, Any]]) -> bool:
    return payload_version(payload) == REVIEW_VERSION


def image_fingerprint(image_data: bytes) -> str:
    """Hash exact image bytes once per load, never on mouse movement."""
    return hashlib.sha256(image_data).hexdigest()


def image_fingerprint_from_path(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def annotation_state(path: str) -> AnnotationFileState:
    """Return a content-aware snapshot of one annotation file."""
    if not path or not osp.isfile(path):
        return AnnotationFileState(exists=False)
    try:
        stat = os.stat(path)
        with open(path, "rb") as handle:
            data = handle.read()
    except OSError:
        return AnnotationFileState(exists=True)
    return AnnotationFileState(
        exists=True,
        mtime_ns=int(stat.st_mtime_ns),
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
    )


def annotation_payload(path: str) -> Optional[Mapping[str, Any]]:
    """Read only the dense-review namespace from a label file."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    if not isinstance(data, Mapping):
        return None
    payload = data.get(DENSE_REVIEW_FIELD)
    return payload if isinstance(payload, Mapping) else None
