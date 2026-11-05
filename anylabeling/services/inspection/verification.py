"""Verify a loaded report against current files and configuration."""

from __future__ import annotations

import os.path as osp
from dataclasses import dataclass
from typing import Mapping, Optional

from .manifest import file_digest, load_file_snapshot, shape_collection_digest
from .models import (
    FileSnapshot,
    InspectionProfile,
    Manifest,
    RunReport,
    config_rule_versions,
    dataset_identity,
    normalize_path,
    output_identity,
)
from .profiles import RuleCatalog


@dataclass(frozen=True)
class ReportVerification:
    """Context comparison result used before showing historical conclusions."""

    current: bool
    reasons: tuple[str, ...] = ()
    stale_files: tuple[str, ...] = ()
    pending_files: tuple[str, ...] = ()
    missing_manifest: bool = False
    dataset_changed: bool = False
    output_changed: bool = False
    config_changed: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "current": self.current,
            "reasons": list(self.reasons),
            "stale_files": list(self.stale_files),
            "pending_files": list(self.pending_files),
            "missing_manifest": self.missing_manifest,
            "dataset_changed": self.dataset_changed,
            "output_changed": self.output_changed,
            "config_changed": self.config_changed,
        }


def _shape_digest(file: FileSnapshot) -> str:
    return file.shape_digest or shape_collection_digest(file.shapes)


def _normalized_digest(file: FileSnapshot) -> str:
    return file.annotation_normalized_digest or _shape_digest(file)


def _normalization_only(file: FileSnapshot, current: FileSnapshot) -> bool:
    """Return whether only the serialized form changed, not the content.

    Re-saving a file rewrites point order and formatting; the normalized
    digest is identical in that case, so the report must stay valid instead
    of being reported as an external modification.
    """
    return bool(
        file.annotation_digest
        and current.annotation_digest
        and file.annotation_digest != current.annotation_digest
        and _normalized_digest(file) == _normalized_digest(current)
    )


def _dimensions_changed(file: FileSnapshot, current: FileSnapshot) -> bool:
    return bool(
        (
            file.image_width
            and current.image_width
            and file.image_width != current.image_width
        )
        or (
            file.image_height
            and current.image_height
            and file.image_height != current.image_height
        )
    )


def _report_image_digest_kind(file: FileSnapshot) -> str:
    # Older reports stored a stat digest without recording the kind.
    return file.image_digest_kind or ("stat" if file.image_digest else "")


def _image_problem(
    file: FileSnapshot,
    current: FileSnapshot,
    image_path: str,
) -> tuple[str, str]:
    """Compare image identity even when the report came from the canvas."""
    if not file.image_digest:
        return "stale", "报告缺少可核验的图片身份"
    kind = _report_image_digest_kind(file)
    actual = file_digest(image_path, content=(kind != "stat"))
    if not actual:
        return "stale", "图片缺失或不可读，无法核验图片身份"
    if actual != file.image_digest:
        return "stale", "图片内容已变化"
    if (
        file.image_orientation
        and file.image_orientation != current.image_orientation
    ):
        return "stale", "图片 EXIF 方向已变化或无法核验"
    if _dimensions_changed(file, current):
        return "stale", "图片尺寸已变化"
    return "", ""


def _memory_problem(
    file: FileSnapshot, current: FileSnapshot
) -> tuple[str, str]:
    if _shape_digest(file) != _shape_digest(current):
        if current.unsaved:
            return "pending", "当前未保存画布内容与报告不一致"
        return "stale", "当前画布内容与报告不一致"
    if _dimensions_changed(file, current):
        return "stale", "图片尺寸已变化"
    return "", ""


def _disk_problem(
    file: FileSnapshot,
    current: FileSnapshot,
    image_path: str,
) -> tuple[str, str]:
    if current.annotation_state != "present":
        return "stale", "标注缺失或损坏"
    if file.annotation_state == "memory":
        # The report was taken from unsaved canvas content: the disk
        # annotation is not the recorded input and must not be compared.
        return _image_problem(file, current, image_path)
    if current.annotation_digest != file.annotation_digest:
        if not _normalization_only(file, current):
            return "stale", "标注内容已变化"
    return _image_problem(file, current, image_path)


def _read_disk_file(
    report: RunReport,
    file: FileSnapshot,
    dataset_root: str,
    output_dir: str,
) -> Optional[FileSnapshot]:
    image_path = file.image_path or osp.join(dataset_root, file.relative_path)
    try:
        return load_file_snapshot(
            image_path,
            report.dataset_root or dataset_root,
            report.output_root or output_dir,
            relative_path=file.relative_path,
            annotation_path=file.annotation_path,
            read_orientation=True,
        )
    except (OSError, TypeError, ValueError):
        return None


def _verify_files(
    report: RunReport,
    manifest: Manifest,
    dataset_root: str,
    output_dir: str,
    memory_files: Mapping[str, FileSnapshot],
) -> tuple[dict[str, FileSnapshot], set[str], set[str], list[str]]:
    current_files: dict[str, FileSnapshot] = {}
    stale_files: set[str] = set()
    pending_files: set[str] = set()
    reasons: list[str] = []

    def record(relative: str, kind: str, problem: str) -> None:
        if kind == "pending":
            pending_files.add(relative)
            reasons.append(f"{relative} {problem}")
        elif kind == "stale":
            stale_files.add(relative)
            reasons.append(f"{relative} {problem}")

    for file in manifest.files:
        relative = file.relative_path
        memory = memory_files.get(relative)
        disk = _read_disk_file(report, file, dataset_root, output_dir)
        image_path = file.image_path or osp.join(
            manifest.dataset_root or dataset_root, relative
        )
        if file.annotation_state == "memory" and memory is None:
            stale_files.add(relative)
            reasons.append(
                f"{relative} 报告来自未保存画布，当前画布不在此文件，无法核验"
            )
            continue
        if memory is not None:
            current_files[relative] = memory
            record(relative, *_memory_problem(file, memory))
            if disk is None:
                record(relative, "stale", "磁盘标注读取失败")
                continue
            if file.annotation_state != "memory":
                record(relative, *_disk_problem(file, disk, image_path))
            else:
                # Memory report: the image identity still has to match the
                # file on disk; the annotation content is covered above.
                record(relative, *_image_problem(file, disk, image_path))
            continue
        if disk is None:
            stale_files.add(relative)
            reasons.append(f"{relative} 读取失败")
            continue
        current_files[relative] = disk
        record(relative, *_disk_problem(file, disk, image_path))
    return current_files, stale_files, pending_files, reasons


def _verify_issue_objects(
    report: RunReport,
    current_files: Mapping[str, FileSnapshot],
) -> tuple[set[str], set[str], list[str]]:
    stale_files: set[str] = set()
    pending_files: set[str] = set()
    reasons: list[str] = []
    for issue in report.issues:
        relative = issue.location.relative_path
        snapshot = current_files.get(relative)
        if snapshot is None:
            stale_files.add(relative)
            reasons.append(f"{relative} 不在当前历史清单中")
            continue
        if not issue.location.object_ids:
            continue
        current_ids = {shape.shape_id for shape in snapshot.shapes}
        missing = [
            object_id
            for object_id in issue.location.object_ids
            if object_id not in current_ids
        ]
        if missing:
            if snapshot.unsaved:
                pending_files.add(relative)
                reasons.append(
                    f"{relative} 当前未保存画布中对象已变化: "
                    + ", ".join(missing)
                )
            else:
                stale_files.add(relative)
                reasons.append(
                    f"{relative} 对象身份已变化: " + ", ".join(missing)
                )
    return stale_files, pending_files, reasons


def report_context_summary(
    report: RunReport, manifest: Optional[Manifest] = None
) -> dict[str, object]:
    """Return the fingerprints a restored report was produced from.

    The summary covers annotation content, image boundary/orientation,
    effective configuration and rule implementation versions so a caller
    can show exactly what an old conclusion depends on.
    """
    files: list[dict[str, object]] = []
    source = manifest if manifest is not None else None
    for file in (source.files if source is not None else ()):  # type: ignore[union-attr]
        files.append(
            {
                "relative_path": file.relative_path,
                "annotation_state": file.annotation_state,
                "annotation_digest": file.annotation_digest,
                "annotation_normalized_digest": _normalized_digest(file),
                "image_digest": file.image_digest,
                "image_digest_kind": file.image_digest_kind,
                "image_width": file.image_width,
                "image_height": file.image_height,
                "image_orientation": file.image_orientation,
            }
        )
    return {
        "run_id": report.run_id,
        "dataset_root": normalize_path(report.dataset_root),
        "output_root": output_identity(report.output_root),
        "dataset_key": dataset_identity(report.dataset_root),
        "manifest_fingerprint": report.manifest_fingerprint,
        "config_digest": report.config_digest,
        "profile_fingerprint": report.profile_snapshot.get(
            "profile_fingerprint", ""
        ),
        "rule_versions": config_rule_versions(report.profile_snapshot),
        "files": files,
    }


def _verify_profile(
    report: RunReport,
    catalog: RuleCatalog,
    current_profile: Optional[InspectionProfile],
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    config_changed = False
    snapshot_profile = report.profile_snapshot.get("profile", {})
    if not isinstance(snapshot_profile, Mapping) or not snapshot_profile:
        return True, ["报告缺少有效方案快照"]
    snapshot_id = str(snapshot_profile.get("profile_id", ""))
    if current_profile is None:
        return True, [f"当前未找到报告方案 {snapshot_id}"]
    if current_profile.profile_id != snapshot_id:
        config_changed = True
        reasons.append(
            f"当前方案 {current_profile.profile_id} 与报告 "
            f"{snapshot_id} 不一致"
        )
    expected_fingerprint = report.profile_snapshot.get(
        "profile_fingerprint", ""
    )
    if (
        expected_fingerprint
        and current_profile.fingerprint() != expected_fingerprint
    ):
        config_changed = True
        reasons.append("当前方案内容与报告冻结配置不一致")
    for rule in report.profile_snapshot.get("rules", []) or []:
        if not isinstance(rule, Mapping):
            continue
        rule_id = str(rule.get("rule_id", ""))
        meta = catalog.meta(rule_id)
        if meta is None:
            config_changed = True
            reasons.append(f"规则 {rule_id} 当前不可用")
            continue
        expected = str(rule.get("implementation_version", ""))
        if expected and meta.implementation_version != expected:
            config_changed = True
            reasons.append(f"规则 {rule_id} 实现版本已变化")
    return config_changed, reasons


def verify_report_context(
    report: RunReport,
    manifest: Optional[Manifest],
    catalog: RuleCatalog,
    dataset_root: str,
    output_dir: str,
    current_profile: Optional[InspectionProfile] = None,
    memory_files: Optional[Mapping[str, FileSnapshot]] = None,
) -> ReportVerification:
    """Compare report inputs/profile with current disk or canvas state."""
    if manifest is None:
        return ReportVerification(
            current=False,
            reasons=("缺少历史文件清单，无法核验当前输入",),
            missing_manifest=True,
        )
    reasons: list[str] = []
    stale_files: set[str] = set()
    pending_files: set[str] = set()
    report_dataset = normalize_path(report.dataset_root)
    current_dataset = normalize_path(dataset_root)
    dataset_changed = bool(
        report_dataset
        and current_dataset
        and report_dataset != current_dataset
    )
    if not report_dataset:
        reasons.append("报告缺少数据集身份，无法核验数据集范围")
    if dataset_changed:
        reasons.append("数据集根与报告不一致")
    # Normalize the default ("annotations beside images") identity before
    # comparing, so an explicit output root that is later cleared is a
    # change instead of being treated as "both empty".
    report_output = output_identity(report.output_root)
    current_output = output_identity(output_dir)
    output_changed = report_output != current_output
    if output_changed:
        reasons.append("标注输出目录与报告不一致")
    if report.dataset_root and not dataset_changed:
        if dataset_identity(report.dataset_root) != dataset_identity(
            dataset_root
        ):
            dataset_changed = True
            reasons.append("数据集身份与报告不一致")
    current_files, file_stale, file_pending, file_reasons = _verify_files(
        report,
        manifest,
        dataset_root,
        output_dir,
        memory_files or {},
    )
    stale_files.update(file_stale)
    pending_files.update(file_pending)
    reasons.extend(file_reasons)
    object_stale, object_pending, object_reasons = _verify_issue_objects(
        report, current_files
    )
    stale_files.update(object_stale)
    pending_files.update(object_pending)
    reasons.extend(object_reasons)
    config_changed, config_reasons = _verify_profile(
        report, catalog, current_profile
    )
    reasons.extend(config_reasons)
    return ReportVerification(
        current=not (
            reasons
            or stale_files
            or pending_files
            or dataset_changed
            or output_changed
            or config_changed
        ),
        reasons=tuple(dict.fromkeys(reasons)),
        stale_files=tuple(sorted(stale_files)),
        pending_files=tuple(sorted(pending_files)),
        dataset_changed=dataset_changed,
        output_changed=output_changed,
        config_changed=config_changed,
    )
