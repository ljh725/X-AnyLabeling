"""Pure-Python cache primitives for dataset thumbnail rendering."""

from __future__ import annotations

import hashlib
import math
import os
import os.path as osp
import tempfile
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Optional

from anylabeling.views.labeling.dataset_index import DatasetThumbnailRef

THUMBNAIL_CROP_POLICY_VERSION = "horizontal-padding-15-v1"


@dataclass(frozen=True)
class ThumbnailCacheKey:
    """Stable cache identity for one rendered object crop."""

    image_path: str
    image_mtime_ns: int
    image_size: int
    shape_id: str
    bbox: tuple[float, float, float, float]
    size: tuple[int, int]
    crop_policy: str

    @classmethod
    def for_ref(
        cls,
        ref: DatasetThumbnailRef,
        image_mtime_ns: int,
        image_size: int,
        size: tuple[int, int],
        crop_policy: str = THUMBNAIL_CROP_POLICY_VERSION,
    ) -> Optional["ThumbnailCacheKey"]:
        """Build a key when the reference has a finite four-value bbox."""
        if ref.bbox is None or len(ref.bbox) != 4:
            return None
        bbox = tuple(float(value) for value in ref.bbox)
        if not all(math.isfinite(value) for value in bbox):
            return None
        return cls(
            osp.normcase(osp.abspath(ref.image_path)),
            int(image_mtime_ns),
            int(image_size),
            str(ref.shape_id),
            bbox,
            (max(1, int(size[0])), max(1, int(size[1]))),
            str(crop_policy),
        )

    @property
    def token(self) -> str:
        """Return a compact content-addressed cache token."""
        payload = repr(
            (
                self.image_path,
                self.image_mtime_ns,
                self.image_size,
                self.shape_id,
                self.bbox,
                self.size,
                self.crop_policy,
            )
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


class ThumbnailMemoryCache:
    """Bounded LRU cache storing PNG bytes."""

    def __init__(self, max_items: int = 512) -> None:
        """Initialize the cache with a positive item limit."""
        self.max_items = max(1, int(max_items))
        self._items: OrderedDict[str, bytes] = OrderedDict()
        self._lock = threading.RLock()

    def get(self, key: ThumbnailCacheKey) -> Optional[bytes]:
        """Return cached bytes and promote them to the most-recent end."""
        token = key.token
        with self._lock:
            value = self._items.get(token)
            if value is not None:
                self._items.move_to_end(token)
            return value

    def put(self, key: ThumbnailCacheKey, value: bytes) -> None:
        """Insert bytes and evict the least-recent entries over the limit."""
        token = key.token
        with self._lock:
            self._items[token] = bytes(value)
            self._items.move_to_end(token)
            while len(self._items) > self.max_items:
                self._items.popitem(last=False)

    def clear(self) -> None:
        """Remove all in-memory entries."""
        with self._lock:
            self._items.clear()

    def __len__(self) -> int:
        """Return the current number of cached entries."""
        with self._lock:
            return len(self._items)


class ThumbnailDiskCache:
    """Disposable per-dataset cache for rendered PNG bytes."""

    def __init__(self, root: str) -> None:
        """Initialize a cache rooted outside the annotation directory."""
        self.root = osp.abspath(root)

    def _path(self, key: ThumbnailCacheKey) -> str:
        """Return the cache file path for a key."""
        return osp.join(self.root, key.token[:2], key.token[2:] + ".png")

    def get(self, key: ThumbnailCacheKey) -> Optional[bytes]:
        """Read a cache entry, treating filesystem errors as a miss."""
        try:
            with open(self._path(key), "rb") as stream:
                value = stream.read()
            return value or None
        except OSError:
            return None

    def put(self, key: ThumbnailCacheKey, value: bytes) -> None:
        """Atomically write a cache entry and leave failures non-fatal."""
        directory = osp.dirname(self._path(key))
        temporary = None
        try:
            os.makedirs(directory, exist_ok=True)
            fd, temporary = tempfile.mkstemp(
                prefix=".thumbnail-", suffix=".tmp", dir=directory
            )
            with os.fdopen(fd, "wb") as stream:
                stream.write(value)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self._path(key))
            temporary = None
        except OSError:
            pass
        finally:
            if temporary:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass


__all__ = [
    "THUMBNAIL_CROP_POLICY_VERSION",
    "ThumbnailCacheKey",
    "ThumbnailDiskCache",
    "ThumbnailMemoryCache",
]
