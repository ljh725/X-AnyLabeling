"""Global thumbnail filtering and persistent, revision-aware manual review."""

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from anylabeling.views.labeling.dataset_index import DatasetFilterIndex
from anylabeling.views.labeling.dataset_index.thumbnail_query import (
    ThumbnailQuery,
)
from anylabeling.views.labeling.widgets.dataset_thumbnail.review_store import (
    ReviewStore,
)


@pytest.fixture
def catalog(tmp_path: Path) -> Any:
    """Build over two pages so page-local sorting cannot pass."""
    image = tmp_path / "s1902.png"
    image.write_bytes(b"test")
    shapes = [
        dict(
            label="person",
            shape_type="rectangle",
            group_id=i % 2,
            description="inspect me" if i == 204 else "normal",
            difficult=i == 204,
            xanylabeling_shape_id=f"{i + 1:032x}",
            points=[[0, 0], [205 - i, 10]],
        )
        for i in range(205)
    ]
    shapes[204]["score"] = 0.9
    shapes[203]["scoring"] = 0.7
    path = image.with_suffix(".json")
    path.write_text(
        json.dumps(dict(imageWidth=1000, imageHeight=1000, shapes=shapes)),
        encoding="utf-8",
    )
    index = DatasetFilterIndex(str(tmp_path / "index.sqlite"))
    index.rebuild([str(image)], dataset_root=str(tmp_path))
    store = ReviewStore(str(tmp_path / "review.sqlite"))
    yield index, store, image, path
    index.close()
    store.close()


def query(
    catalog: Any, options: ThumbnailQuery = ThumbnailQuery(), offset: int = 0
) -> Any:
    """Execute the production SQL with the separate review database."""
    index, store, _, _ = catalog
    return index.query_thumbnail_review(
        "person", 100, offset, options, store.path
    )


def test_global_sort_and_filter_before_pagination(catalog: Any) -> None:
    """The smallest object on the third original page sorts to the first."""
    original = query(catalog)
    small = query(catalog, ThumbnailQuery(sort="small_pixels"))
    assert original.total == 205 and len(original.items) == 100
    assert original.items[0].shape_index == 0
    assert small.items[0].shape_index == 204
    assert (
        len(query(catalog, ThumbnailQuery(sort="small_pixels"), 200).items)
        == 5
    )
    filtered = query(
        catalog,
        ThumbnailQuery(
            description="inspect",
            score_min=0.8,
            difficult="yes",
            group_id="0",
            shape_type="rectangle",
            filename="1902",
        ),
    )
    assert filtered.total == 1 and filtered.items[0].shape_index == 204
    assert (
        query(catalog, ThumbnailQuery(score_min=0.6, score_max=0.8))
        .items[0]
        .shape_index
        == 203
    )
    assert query(catalog, ThumbnailQuery(filename="' OR 1=1 --")).total == 0
    assert (
        query(catalog, ThumbnailQuery(area_max=10, ratio_max=0.1)).total == 1
    )
    assert query(catalog).items == original.items


def test_pixel_area_and_relative_area_have_different_orders(
    tmp_path: Path,
) -> None:
    """Absolute and relative area cannot be substituted across image sizes."""
    paths = []
    for name, size, box in (
        ("large", 1000, 20),
        ("small", 100, 10),
        ("unknown", None, 5),
    ):
        image = tmp_path / f"{name}.png"
        paths.append(str(image))
        image.with_suffix(".json").write_text(
            json.dumps(
                dict(
                    imageWidth=size,
                    imageHeight=size,
                    shapes=[
                        dict(
                            label="person",
                            shape_type="rectangle",
                            xanylabeling_shape_id=name,
                            points=[[0, 0], [box, box]],
                        )
                    ],
                )
            ),
            encoding="utf-8",
        )
    index = DatasetFilterIndex(":memory:")
    index.rebuild(paths, dataset_root=str(tmp_path))
    try:
        pixels = index.query_thumbnail_review(
            "person", options=ThumbnailQuery(sort="small_pixels")
        )
        relative = index.query_thumbnail_review(
            "person", options=ThumbnailQuery(sort="small_relative")
        )
        assert [r.shape_id for r in pixels.items] == [
            "unknown",
            "small",
            "large",
        ]
        assert [r.shape_id for r in relative.items] == [
            "large",
            "small",
            "unknown",
        ]
        assert (
            index.query_thumbnail_review(
                "person",
                options=ThumbnailQuery(area_unit="percent", area_max=0.05),
            ).total
            == 1
        )
    finally:
        index.close()


def test_automatic_aspect_outlier_order_is_stable(catalog: Any) -> None:
    """Optional ratio bounds are independent of the automatic ranking."""
    ranked = query(catalog, ThumbnailQuery(sort="aspect_outliers"))
    assert ranked.items[0].shape_index == 204
    assert (
        ranked.items
        == query(catalog, ThumbnailQuery(sort="aspect_outliers")).items
    )
    bounded = query(catalog, ThumbnailQuery(ratio_min=10, ratio_max=11))
    assert bounded.total == 11


@pytest.mark.parametrize(
    "options",
    [
        ThumbnailQuery(area_min=2, area_max=1),
        ThumbnailQuery(ratio_min=-1),
        ThumbnailQuery(score_max=float("nan")),
        ThumbnailQuery(sort="sql"),
        ThumbnailQuery(review="auto_pass"),
    ],
)
def test_invalid_queries_are_rejected(
    catalog: Any, options: ThumbnailQuery
) -> None:
    """Malformed fields never become SQL or silently change the filter."""
    with pytest.raises(ValueError):
        query(catalog, options)


def test_manual_states_survive_rebuild_and_expire_after_edit(
    catalog: Any,
) -> None:
    """Review is durable metadata but a changed shape needs review again."""
    index, store, image, path = catalog
    refs = query(catalog).items[:2]
    original_bytes = path.read_bytes()
    store.set_status(refs, "confirmed")
    assert path.read_bytes() == original_bytes
    assert query(catalog, ThumbnailQuery(review="confirmed")).total == 2
    assert query(catalog, ThumbnailQuery(review="unreviewed")).total == 203
    index.rebuild([str(image)], dataset_root=str(image.parent))
    assert query(catalog, ThumbnailQuery(review="confirmed")).total == 2
    document = json.loads(original_bytes)
    document["shapes"][0]["description"] = "edited after confirming"
    path.write_text(json.dumps(document), encoding="utf-8")
    index.refresh_file(str(image))
    assert query(catalog, ThumbnailQuery(review="confirmed")).total == 1
    assert query(catalog).items[0].review_status == "unreviewed"
    with ReviewStoreForTest(store.path) as reopened:
        assert (
            reopened.connection.execute(
                "SELECT COUNT(*) FROM marks"
            ).fetchone()[0]
            == 2
        )


class ReviewStoreForTest(ReviewStore):
    """Close a second connection without touching the fixture's writer."""

    def __enter__(self) -> Any:
        """Return the newly opened persisted review store."""
        return self

    def __exit__(self, *args: Any) -> None:
        """Close the independent connection."""
        self.close()


def test_duplicate_identity_cannot_be_marked(catalog: Any) -> None:
    """Ambiguous IDs are neither editable review targets nor confirmed."""
    index, store, image, path = catalog
    document = json.loads(path.read_text(encoding="utf-8"))
    document["shapes"][1]["xanylabeling_shape_id"] = document["shapes"][0][
        "xanylabeling_shape_id"
    ]
    path.write_text(json.dumps(document), encoding="utf-8")
    index.refresh_file(str(image))
    ref = query(catalog).items[0]
    assert not ref.unique_identity
    with pytest.raises(ValueError):
        store.set_status([ref], "confirmed")


def test_restore_anchor_resolves_under_new_order(catalog: Any) -> None:
    """Restore an object's ranked page without relying on old array offsets."""
    index, store, _, _ = catalog
    ref = query(catalog).items[0]
    restored = index.query_thumbnail_review(
        "person",
        100,
        0,
        ThumbnailQuery(sort="small_pixels"),
        store.path,
        (ref.image_path, ref.shape_id),
    )
    assert restored.offset == 200
    assert any(item.shape_id == ref.shape_id for item in restored.items)


def test_schema_upgrade_preserves_independent_review(catalog: Any) -> None:
    """Discard the old derived schema without deleting manual decisions."""
    index, store, image, _ = catalog
    store.set_status(query(catalog).items[:1], "confirmed")
    index.close()
    with sqlite3.connect(index.db_path) as connection:
        connection.execute(
            "UPDATE dataset_meta SET value='3' WHERE key='schema_version'"
        )
    assert index.open()
    assert query(catalog).total == 0
    index.rebuild([str(image)], dataset_root=str(image.parent))
    assert query(catalog, ThumbnailQuery(review="confirmed")).total == 1


def test_session_only_review_store_is_queryable(catalog: Any) -> None:
    """A window without settings uses a shared memory store, never a file."""
    index, _, _, _ = catalog
    with ReviewStoreForTest() as store:
        refs = index.query_thumbnail_review("person", review_db=store.path)
        store.set_status(refs.items[:1], "confirmed")
        assert (
            index.query_thumbnail_review(
                "person",
                options=ThumbnailQuery(review="confirmed"),
                review_db=store.path,
            ).total
            == 1
        )
