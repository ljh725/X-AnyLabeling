"""Task 2.2 -- image content identity and dataset identity (service layer).

The digest used to be computed by the Qt controller; it now lives in
``core.image_content_digest`` so the labeling window and batch prediction cannot
disagree about "the same image version".  These cases are Qt-free.

Covers spec ``BASE-1`` (content identity plus stable object IDs) and
``BASE-8`` (a changed image version must be disclosed, not silently reused).
"""

from __future__ import annotations

import os

from anylabeling.services.correction_metrics.core import (
    dataset_identity,
    image_content_digest,
)
from anylabeling.views.labeling.correction_metrics.controller import (
    content_digest,
)


def test_same_bytes_in_different_directories_share_one_content_identity(tmp_path):
    """2.2：图片内容身份与路径无关，同名不同目录的相同内容视为同一版本。"""
    first = tmp_path / "dataset-a" / "scene.jpg"
    second = tmp_path / "dataset-b" / "scene.jpg"
    for path in (first, second):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"identical-image-bytes")

    assert image_content_digest(first) == image_content_digest(second)
    # The controller keeps the historical name as a thin alias.
    assert content_digest(first) == image_content_digest(first)


def test_changed_bytes_produce_a_different_content_identity(tmp_path):
    """2.2：内容变化必须得到不同摘要，供轮次判定 image-content-changed。"""
    path = tmp_path / "scene.jpg"
    path.write_bytes(b"first-version")
    before = image_content_digest(path)

    path.write_bytes(b"second-version")

    assert image_content_digest(path) != before
    assert image_content_digest(path) != ""


def test_missing_image_is_unknown_instead_of_a_shared_constant(tmp_path):
    """2.2：读不到的图片是"未知版本"，不能与另一张读不到的图片混为一谈。"""
    missing = image_content_digest(tmp_path / "missing.jpg")

    assert missing == ""
    assert image_content_digest(str(tmp_path / "missing.jpg")) == ""


def test_oversized_image_falls_back_to_size_and_mtime(tmp_path):
    """2.2：超大图片走 size/mtime 回退，既不阻塞也不返回空摘要。"""
    path = tmp_path / "huge.jpg"
    path.write_bytes(b"x" * 32)
    os.utime(path, (1_000_000, 1_000_000))
    first = image_content_digest(path, limit=8)
    assert first.startswith("size:32:mtime:")

    os.utime(path, (2_000_000, 2_000_000))
    assert image_content_digest(path, limit=8) != first


def test_same_named_images_in_different_roots_keep_distinct_dataset_identity(
    tmp_path,
):
    """2.2：同名图片位于不同根目录时数据集身份不同，轮次不会互相合并。"""
    shared_name = tmp_path / "images"
    other_root = tmp_path / "other-images"

    first = dataset_identity(str(shared_name), str(tmp_path / "labels"))
    same = dataset_identity(str(shared_name), str(tmp_path / "labels"))
    other = dataset_identity(str(other_root), str(tmp_path / "labels"))

    assert first == same
    assert first != other
