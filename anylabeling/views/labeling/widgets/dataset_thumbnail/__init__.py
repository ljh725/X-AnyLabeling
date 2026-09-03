"""Dataset-level label thumbnail browser components."""

from importlib import import_module

from .cache import ThumbnailCacheKey, ThumbnailDiskCache, ThumbnailMemoryCache

_LAZY_IMPORTS = {
    "ThumbnailRenderResult": ("pipeline", "ThumbnailRenderResult"),
    "ThumbnailRenderer": ("pipeline", "ThumbnailRenderer"),
    "DatasetLabelThumbnailWindow": ("browser", "DatasetLabelThumbnailWindow"),
    "ThumbnailItemModel": ("browser", "ThumbnailItemModel"),
}


def __getattr__(name: str):
    """Load Qt-dependent components only when explicitly requested."""
    target = _LAZY_IMPORTS.get(name)
    if target is None:
        raise AttributeError(name)
    module = import_module(f"{__name__}.{target[0]}")
    value = getattr(module, target[1])
    globals()[name] = value
    return value


__all__ = [
    "ThumbnailCacheKey",
    "ThumbnailDiskCache",
    "ThumbnailMemoryCache",
    *_LAZY_IMPORTS,
]
