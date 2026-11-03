"""Local dense-review configuration file handling."""

from __future__ import annotations

import json
import os
import os.path as osp
import tempfile
from typing import Any, Mapping, Optional

from .models import ReviewConfig

CONFIG_DIRECTORY = ".xanylabeling/dense_review"
CONFIG_FILENAME = "config.json"


class ReviewConfigFileError(ValueError):
    """Raised when a review configuration file cannot be trusted."""

    def __init__(self, message: str, path: str = ""):
        super().__init__(message)
        self.path = path


def config_directory(root: str) -> str:
    return osp.join(str(root), *CONFIG_DIRECTORY.split("/"))


def config_path(root: str) -> str:
    return osp.join(config_directory(root), CONFIG_FILENAME)


def load_config(root: str) -> ReviewConfig:
    """Load the optional review configuration for one dataset/output root."""
    path = config_path(root)
    if not osp.isfile(path):
        return ReviewConfig()
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as error:
        raise ReviewConfigFileError(
            f"无法读取复核配置：{error}", path
        ) from error
    if not isinstance(data, Mapping):
        raise ReviewConfigFileError("复核配置必须是 JSON 对象", path)
    config = ReviewConfig.from_dict(data)
    issues = config.validate()
    if issues:
        messages = "；".join(issue.message for issue in issues)
        raise ReviewConfigFileError(f"复核配置存在冲突：{messages}", path)
    return config


def save_config(root: str, config: ReviewConfig) -> str:
    """Atomically save the review configuration next to the dataset."""
    issues = config.validate()
    if issues:
        messages = "；".join(issue.message for issue in issues)
        raise ReviewConfigFileError(f"复核配置存在冲突：{messages}")
    directory = config_directory(root)
    os.makedirs(directory, exist_ok=True)
    path = config_path(root)
    payload = config.to_dict()
    temporary = None
    try:
        descriptor, temporary = tempfile.mkstemp(
            prefix=".dense_review_", suffix=".json", dir=directory
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except OSError as error:
        raise ReviewConfigFileError(
            f"无法保存复核配置：{error}", path
        ) from error
    finally:
        if temporary and osp.exists(temporary):
            try:
                os.remove(temporary)
            except OSError:
                pass
    return path


def config_root_for(dataset_root: str, output_dir: str = "") -> str:
    """Choose the output directory first, then the dataset root."""
    return str(output_dir or dataset_root or "")


def resolve_config(
    dataset_root: str,
    output_dir: str = "",
) -> tuple[ReviewConfig, Optional[str]]:
    """Return the effective config and a human-readable load warning."""
    root = config_root_for(dataset_root, output_dir)
    if not root:
        return ReviewConfig(), None
    try:
        return load_config(root), None
    except ReviewConfigFileError as error:
        return ReviewConfig(), str(error)
