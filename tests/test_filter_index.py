"""Tests for pure in-memory shape filter index helpers."""

from types import SimpleNamespace

from anylabeling.views.labeling.filter_index import build_shape_filter_index


class _Item:
    """Minimal label-list item stand-in."""

    def __init__(self, shape):
        self._shape = shape

    def shape(self):
        """Return the wrapped shape."""
        return self._shape


def test_build_shape_filter_index_buckets_items_by_shape_fields():
    """Items should be indexed by label, gid, shape_type, and all."""
    person = _Item(
        SimpleNamespace(label="person", group_id=7, shape_type="rectangle")
    )
    point = _Item(
        SimpleNamespace(label="nose", group_id=7, shape_type="point")
    )
    no_gid = _Item(
        SimpleNamespace(label="face", group_id=None, shape_type="rectangle")
    )

    index = build_shape_filter_index([person, point, no_gid])

    assert index["all"] == [person, point, no_gid]
    assert index["label"]["person"] == [person]
    assert index["label"]["nose"] == [point]
    assert index["gid"]["7"] == [person, point]
    assert "None" not in index["gid"]
    assert index["shape_type"]["rectangle"] == [person, no_gid]
    assert index["shape_type"]["point"] == [point]
