"""External model candidate import, validation and acceptance intents."""

from __future__ import annotations

import hashlib
import json
import math
import os
import os.path as osp
from dataclasses import dataclass, replace
from typing import Any, Iterable, Mapping, Optional, Sequence

from .models import (
    CANDIDATE_SCHEMA_VERSION,
    Candidate,
    CandidateStatus,
    Manifest,
    utc_now_iso,
)
from .storage import (
    RevisionConflict,
    StorageError,
    _exclusive_lock,
    atomic_write_json,
    read_json,
)


@dataclass(frozen=True)
class CandidateImportResult:
    """Validated candidates plus explicit rejected records."""

    candidates: tuple[Candidate, ...]
    errors: tuple[Mapping[str, Any], ...] = ()
    ambiguous: tuple[Mapping[str, Any], ...] = ()
    source: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "imported": len(self.candidates),
            "errors": [dict(item) for item in self.errors],
            "ambiguous": [dict(item) for item in self.ambiguous],
        }


def _candidate_id(
    source: str,
    source_version: str,
    relative_path: str,
    label: str,
    region: Sequence[float],
    score: Optional[float],
) -> str:
    raw = json.dumps(
        {
            "source": source,
            "source_version": source_version,
            "path": relative_path,
            "label": label,
            "region": [round(float(item), 4) for item in region[:4]],
            "score": None if score is None else round(float(score), 6),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _resolve_file(
    raw_path: str, manifest: Optional[Manifest]
) -> tuple[Optional[str], bool, str]:
    if manifest is None:
        return raw_path.replace("\\", "/"), True, "没有文件清单，无法核验图片"
    normalized = raw_path.replace("\\", "/")
    matches = {}
    for file in manifest.files:
        if normalized in (
            file.relative_path,
            file.image_path.replace("\\", "/"),
        ):
            matches[file.relative_path] = file
            continue
        if osp.basename(normalized) in (
            osp.basename(file.relative_path),
            osp.basename(file.image_path),
        ):
            matches[file.relative_path] = file
    if len(matches) == 1:
        return next(iter(matches)), False, ""
    if not matches:
        return raw_path.replace("\\", "/"), True, "清单中找不到候选图片"
    return raw_path.replace("\\", "/"), True, "多个同名图片，无法唯一映射"


def load_candidates(
    path: str,
    *,
    manifest: Optional[Manifest] = None,
    allowed_labels: Optional[Iterable[str]] = None,
    source: str = "",
) -> CandidateImportResult:
    """Load external candidates without creating or deleting formal shapes."""
    source = source or osp.splitext(osp.basename(path))[0]
    payload = read_json(path)
    raw_candidates = (
        payload.get("candidates", [])
        if isinstance(payload, Mapping)
        else payload
    )
    if not isinstance(raw_candidates, list):
        return CandidateImportResult(
            (),
            ({"error": "候选 JSON 必须包含 candidates 数组"},),
            source=source,
        )
    allowed = (
        {str(item) for item in allowed_labels}
        if allowed_labels is not None
        else None
    )
    candidates: list[Candidate] = []
    errors: list[Mapping[str, Any]] = []
    ambiguous: list[Mapping[str, Any]] = []
    for index, raw in enumerate(raw_candidates):
        if not isinstance(raw, Mapping):
            errors.append({"index": index, "error": "候选记录不是对象"})
            continue
        raw_path = str(
            raw.get("relative_path")
            or raw.get("image_path")
            or raw.get("image")
            or ""
        ).strip()
        if not raw_path:
            errors.append({"index": index, "error": "候选缺少图片路径"})
            continue
        relative, is_ambiguous, reason = _resolve_file(raw_path, manifest)
        if is_ambiguous:
            ambiguous.append(
                {
                    "index": index,
                    "raw_path": raw_path,
                    "relative_path": relative,
                    "reason": reason,
                }
            )
        label = str(raw.get("label", "") or "").strip()
        if not label:
            errors.append({"index": index, "error": "候选缺少类别"})
            continue
        if allowed is not None and label not in allowed:
            errors.append(
                {
                    "index": index,
                    "error": f"候选类别不在当前方案标签集中: {label}",
                }
            )
            continue
        region_raw = raw.get("region") or raw.get("bbox")
        if not isinstance(region_raw, (list, tuple)) or len(region_raw) < 4:
            errors.append({"index": index, "error": "候选区域必须是四个数值"})
            continue
        try:
            region = tuple(float(item) for item in region_raw[:4])
        except (TypeError, ValueError):
            errors.append({"index": index, "error": "候选区域包含非数值"})
            continue
        if not all(math.isfinite(item) for item in region):
            errors.append({"index": index, "error": "候选区域包含非有限数"})
            continue
        if region[2] <= region[0] or region[3] <= region[1]:
            errors.append({"index": index, "error": "候选区域面积必须大于零"})
            continue
        try:
            width = int(raw.get("image_width", 0) or 0)
            height = int(raw.get("image_height", 0) or 0)
        except (ValueError, TypeError):
            errors.append({"index": index, "error": "候选图片尺寸必须为整数"})
            continue
        if width > 0 and (region[0] < 0 or region[2] > width):
            errors.append({"index": index, "error": "候选区域超出图片宽度"})
            continue
        if height > 0 and (region[1] < 0 or region[3] > height):
            errors.append({"index": index, "error": "候选区域超出图片高度"})
            continue
        file = None
        if manifest is not None and not is_ambiguous:
            file = next(
                (
                    item
                    for item in manifest.files
                    if item.relative_path == relative
                ),
                None,
            )
            if file and (
                (file.image_width and width and file.image_width != width)
                or (
                    file.image_height
                    and height
                    and file.image_height != height
                )
            ):
                errors.append(
                    {
                        "index": index,
                        "error": "候选图片尺寸与当前清单不一致",
                    }
                )
                continue
            candidate_orientation = str(
                raw.get("orientation", "") or ""
            ).strip()
            if (
                file
                and file.image_orientation
                and candidate_orientation
                and str(file.image_orientation) != candidate_orientation
            ):
                errors.append(
                    {
                        "index": index,
                        "error": "候选图片方向与当前清单不一致",
                    }
                )
                continue
            if file and file.annotation_state == "error":
                errors.append(
                    {
                        "index": index,
                        "error": "候选图片缺少可核验的标注文件",
                    }
                )
                continue
        digest = str(raw.get("image_digest", "") or "")
        digest_kind = str(raw.get("image_digest_kind", "content") or "content")
        if file is not None:
            from .manifest import file_digest

            if digest and digest != file_digest(
                file.image_path, content=(digest_kind != "stat")
            ):
                errors.append(
                    {"index": index, "error": "候选图片内容与当前图片不一致"}
                )
                continue
            digest = file_digest(file.image_path, content=True)
            digest_kind = "content" if digest else ""
        source_version = str(
            raw.get("source_version", raw.get("version", "unversioned"))
        )
        score_raw = raw.get("score")
        score = (
            float(score_raw)
            if isinstance(score_raw, (int, float))
            and not isinstance(score_raw, bool)
            and math.isfinite(float(score_raw))
            else None
        )
        candidate_id = str(raw.get("candidate_id", "") or "") or _candidate_id(
            source,
            source_version,
            relative,
            label,
            region,
            score,
        )
        candidates.append(
            Candidate(
                candidate_id=candidate_id,
                source=str(raw.get("source", source)),
                source_version=source_version,
                relative_path=relative,
                image_path=(
                    file.image_path if file else str(raw.get("image_path", ""))
                ),
                label=label,
                region=region,
                image_width=width,
                image_height=height,
                orientation=str(raw.get("orientation", "")),
                score=score,
                status=CandidateStatus.PENDING,
                reason=reason,
                schema_version=CANDIDATE_SCHEMA_VERSION,
                image_digest=digest,
                image_digest_kind=digest_kind,
            )
        )
    return CandidateImportResult(
        candidates=tuple(candidates),
        errors=tuple(errors),
        ambiguous=tuple(ambiguous),
        source=source,
    )


def candidate_shape_payload(candidate: Candidate) -> dict[str, Any]:
    """Return a canvas payload for an explicitly accepted candidate."""
    return {
        "label": candidate.label,
        "shape_type": "rectangle",
        "points": [
            [candidate.region[0], candidate.region[1]],
            [candidate.region[2], candidate.region[3]],
        ],
        "group_id": None,
        "flags": {},
        "attributes": {
            "inspection_candidate_id": candidate.candidate_id,
            "inspection_candidate_source": candidate.source,
        },
        "description": f"外部候选 {candidate.source}",
    }


class CandidateStore:
    """Revision-safe sidecar for candidate status and acceptance intents."""

    def __init__(self, root: str, dataset_key: str = "") -> None:
        self.root = root
        self.dataset_key = str(dataset_key)
        self.path = os.path.join(root, "candidate_state.json")
        self.lock_path = os.path.join(root, "candidate_state.lock")

    def load(self) -> tuple[int, dict[str, Candidate]]:
        if not os.path.isfile(self.path):
            return 0, {}
        try:
            payload = read_json(self.path)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise StorageError(f"候选状态文件损坏: {error}") from error
        if not isinstance(payload, Mapping):
            raise StorageError("candidate store root must be an object")
        if str(payload.get("schema_version", "")) != CANDIDATE_SCHEMA_VERSION:
            raise StorageError("unsupported candidate store schema")
        candidates = {}
        for key, item in (payload.get("candidates", {}) or {}).items():
            if not isinstance(item, Mapping):
                continue
            try:
                candidate = Candidate.from_dict(item)
            except (TypeError, ValueError, AttributeError) as error:
                raise StorageError(
                    f"候选状态记录无效 {key}: {error}"
                ) from error
            if candidate.schema_version != CANDIDATE_SCHEMA_VERSION:
                raise StorageError(
                    f"候选状态版本不可恢复: {candidate.schema_version}"
                )
            if (
                candidate.dataset_key
                and self.dataset_key
                and candidate.dataset_key != self.dataset_key
            ):
                continue
            candidates[str(key)] = candidate
        return int(payload.get("revision", 0) or 0), candidates

    def save(
        self,
        candidates: Mapping[str, Candidate],
        expected_revision: int,
    ) -> int:
        with _exclusive_lock(self.lock_path):
            revision, _ = self.load()
            if revision != int(expected_revision):
                raise RevisionConflict(
                    "candidate revision changed; reload before saving"
                )
            next_revision = revision + 1
            atomic_write_json(
                self.path,
                {
                    "schema_version": CANDIDATE_SCHEMA_VERSION,
                    "revision": next_revision,
                    "updated_at": utc_now_iso(),
                    "candidates": {
                        key: self._stamp(value).to_dict()
                        for key, value in sorted(candidates.items())
                    },
                },
            )
            return next_revision

    def _stamp(self, candidate: Candidate) -> Candidate:
        if not self.dataset_key or candidate.dataset_key == self.dataset_key:
            return candidate
        return replace(candidate, dataset_key=self.dataset_key)

    def mark(
        self,
        candidate: Candidate,
        status: CandidateStatus,
        *,
        accepted_shape_id: str = "",
    ) -> Candidate:
        revision, candidates = self.load()
        updated = replace(
            candidate,
            status=status,
            accepted_shape_id=accepted_shape_id,
            accepted_at=(
                utc_now_iso()
                if status is CandidateStatus.ACCEPTED
                else candidate.accepted_at
            ),
            dataset_key=self.dataset_key or candidate.dataset_key,
        )
        candidates[candidate.candidate_id] = updated
        self.save(candidates, revision)
        return updated


class AlreadyAccepted(StorageError):
    """Raised when the same candidate is accepted a second time."""


class AcceptIntentStore:
    """Pre-allocate a formal identity before a candidate becomes a shape."""

    def __init__(self, root: str) -> None:
        self.root = root
        self.path = os.path.join(root, "candidate_intents.json")
        self.lock_path = os.path.join(root, "candidate_intents.lock")

    def load(self) -> dict[str, Mapping[str, Any]]:
        if not os.path.isfile(self.path):
            return {}
        try:
            payload = read_json(self.path)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise StorageError(f"候选接受意图无法读取: {error}") from error
        if not isinstance(payload, Mapping):
            raise StorageError("accept intent root must be an object")
        entries = payload.get("intents", {})
        if not isinstance(entries, Mapping):
            raise StorageError("accept intents must be an object")
        for key, value in entries.items():
            if (
                not isinstance(value, Mapping)
                or not value.get("preallocated_shape_id")
                or not value.get("relative_path")
                or value.get("status")
                not in ("pending", "applied", "confirmed", "abandoned")
            ):
                raise StorageError(f"候选接受意图记录无效: {key}")
        return {
            str(key): dict(value)
            for key, value in entries.items()
            if isinstance(value, Mapping)
        }

    def create(
        self,
        candidate_id: str,
        relative_path: str,
        preallocated_shape_id: str,
    ) -> Mapping[str, Any]:
        with _exclusive_lock(self.lock_path):
            return self._create(
                candidate_id, relative_path, preallocated_shape_id
            )

    def _create(
        self, candidate_id: str, relative_path: str, preallocated_shape_id: str
    ) -> Mapping[str, Any]:
        intents = self.load()
        existing = intents.get(candidate_id)
        if existing and existing.get("status") in (
            "pending",
            "applied",
            "confirmed",
        ):
            if existing.get("status") in ("applied", "confirmed"):
                raise AlreadyAccepted("candidate already has a formal shape")
            return existing
        intent = {
            "candidate_id": candidate_id,
            "relative_path": relative_path,
            "preallocated_shape_id": preallocated_shape_id,
            "status": "pending",
            "updated_at": utc_now_iso(),
        }
        intents[candidate_id] = intent
        self._write(intents)
        return intent

    def applied(self, candidate_id: str) -> Mapping[str, Any]:
        """The object exists in the document but has not been saved yet."""
        return self._transition(candidate_id, "applied")

    def confirm(self, candidate_id: str) -> Mapping[str, Any]:
        return self._transition(candidate_id, "confirmed")

    def abandon(self, candidate_id: str) -> Mapping[str, Any]:
        return self._transition(candidate_id, "abandoned")

    def _transition(self, candidate_id: str, status: str) -> Mapping[str, Any]:
        with _exclusive_lock(self.lock_path):
            intents = self.load()
            intent = dict(intents.get(candidate_id, {}))
            if not intent:
                if status == "abandoned":
                    return {}
                raise StorageError("accept intent not found")
            intent["status"] = status
            intent["updated_at"] = utc_now_iso()
            intents[candidate_id] = intent
            self._write(intents)
            return intent

    def _write(self, intents: Mapping[str, Mapping[str, Any]]) -> None:
        atomic_write_json(
            self.path,
            {
                "updated_at": utc_now_iso(),
                "intents": {
                    key: dict(value) for key, value in sorted(intents.items())
                },
            },
        )
