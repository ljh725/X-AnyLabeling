"""Tests for thumbnail cache identity and bounded memory behavior."""

import os

import pytest

from anylabeling.views.labeling.dataset_index import DatasetThumbnailRef
from anylabeling.views.labeling.widgets.dataset_thumbnail.cache import (
    ThumbnailCacheKey,
    ThumbnailDiskCache,
    ThumbnailMemoryCache,
)
from anylabeling.views.labeling.widgets.dataset_thumbnail.pipeline import (
    thumbnail_crop_rect,
)


def _ref(tmp_path, shape_id="a" * 32, bbox=(1, 2, 8, 10)):
    """Build a thumbnail reference with a local image path."""
    image_path = tmp_path / "image.jpg"
    image_path.write_bytes(b"image")
    return DatasetThumbnailRef(
        str(image_path),
        str(tmp_path / "image.json"),
        0,
        0,
        shape_id,
        "person",
        bbox,
    )


def test_cache_key_changes_when_bbox_or_image_changes(tmp_path):
    """A changed source or crop cannot reuse the old rendered bytes."""
    ref = _ref(tmp_path)
    first = ThumbnailCacheKey.for_ref(ref, 1, 10, (180, 140))
    changed_bbox = _ref(tmp_path, bbox=(1, 2, 9, 10))
    second = ThumbnailCacheKey.for_ref(changed_bbox, 1, 10, (180, 140))
    changed_image = ThumbnailCacheKey.for_ref(ref, 2, 10, (180, 140))

    assert (
        first is not None and second is not None and changed_image is not None
    )
    assert first.token != second.token
    assert first.token != changed_image.token


def test_cache_key_changes_with_crop_policy_version(tmp_path):
    """A crop-policy change cannot reuse bytes from an older geometry."""
    ref = _ref(tmp_path)
    padded = ThumbnailCacheKey.for_ref(
        ref, 1, 10, (180, 140), "horizontal-padding-15-v1"
    )
    unpadded = ThumbnailCacheKey.for_ref(
        ref, 1, 10, (180, 140), "no-padding-v1"
    )

    assert padded is not None and unpadded is not None
    assert padded.token != unpadded.token


@pytest.mark.parametrize(
    ("bbox", "image_size", "expected"),
    [
        ((20.0, 10.0, 60.0, 30.0), (100, 80), (14, 10, 52, 20)),
        ((2.0, 10.0, 42.0, 30.0), (100, 80), (0, 10, 48, 20)),
        ((60.0, 10.0, 98.0, 30.0), (100, 80), (54, 10, 46, 20)),
        ((10.0, 20.0, 10.0, 30.0), (100, 80), None),
        ((10.0, 30.0, 20.0, 20.0), (100, 80), None),
    ],
)
def test_crop_adds_only_horizontal_padding_and_clamps(
    bbox, image_size, expected
):
    """Crop padding expands x only and remains inside source bounds."""
    assert thumbnail_crop_rect(bbox, image_size) == expected


def test_memory_cache_is_lru_bounded(tmp_path):
    """The oldest entry is evicted once the configured bound is exceeded."""
    cache = ThumbnailMemoryCache(max_items=2)
    refs = [_ref(tmp_path, shape_id=f"{index:032x}") for index in range(3)]
    keys = [ThumbnailCacheKey.for_ref(ref, 1, 10, (180, 140)) for ref in refs]
    assert all(key is not None for key in keys)
    cache.put(keys[0], b"one")
    cache.put(keys[1], b"two")
    assert cache.get(keys[0]) == b"one"
    cache.put(keys[2], b"three")
    assert cache.get(keys[1]) is None
    assert cache.get(keys[0]) == b"one"
    assert len(cache) == 2


def test_disk_cache_round_trip_uses_content_addressed_path(tmp_path):
    """Disk cache writes are readable and isolated below the supplied root."""
    cache = ThumbnailDiskCache(str(tmp_path / "cache"))
    ref = _ref(tmp_path)
    key = ThumbnailCacheKey.for_ref(
        ref, os.stat(ref.image_path).st_mtime_ns, 5, (64, 64)
    )
    assert key is not None
    cache.put(key, b"png-bytes")
    assert cache.get(key) == b"png-bytes"
