"""Verify a loaded report against current files and configuration."""

from __future__ import annotations

import os.path as osp
from dataclasses import dataclass
from typing import Mapping, Optional

from .manifest import load_file_snapshot, shape_collection_digest
from .models import FileSnapshot, InspectionProfile, Manifest, RunReport
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
    file: FileSnapshot, current: FileSnapshot
) -> tuple[str, str]:
    if current.annotation_state != "present":
        return "stale", "标注缺失或损坏"
    if file.annotation_state == "memory":
        if _shape_digest(file) != _shape_digest(current):
            return "stale", "标注内容已变化"
    elif current.annotation_digest != file.annotation_digest:
        return "stale", "标注内容已变化"
    if file.image_digest and current.image_digest != file.image_digest:
        return "stale", "图片内容已变化"
    if _dimensions_changed(file, current):
        return "stale", "图片尺寸已变化"
    return "", ""


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
        if memory is not None:
            current_files[relative] = memory
            if file.annotation_state != "memory":
                if disk is None:
                    stale_files.add(relative)
                    reasons.append(f"{relative} 磁盘标注读取失败")
                else:
                    record(relative, *_disk_problem(file, disk))
            record(relative, *_memory_problem(file, memory))
            continue
        if disk is None:
            stale_files.add(relative)
            reasons.append(f"{relative} 读取失败")
            continue
        current_files[relative] = disk
        record(relative, *_disk_problem(file, disk))
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
    dataset_changed = bool(
        report.dataset_root
        and dataset_root
        and osp.abspath(report.dataset_root) != osp.abspath(dataset_root)
    )
    if dataset_changed:
        reasons.append("数据集根与报告不一致")
    output_changed = bool(
        report.output_root
        and output_dir
        and osp.abspath(report.output_root) != osp.abspath(output_dir)
    )
    if output_changed:
        reasons.append("标注输出目录与报告不一致")
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
