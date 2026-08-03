## Why

Rebuilding the dataset index for large annotation sets spends most warm-cache
time maintaining SQLite query indexes row by row. The rebuild path already
uses a disposable staging database, so query indexes can be created after the
bulk data load without changing annotation data or interactive label loading.

## What Changes

- Build dataset-index query indexes after all `files` and `shapes` rows have
  been loaded into the staging database.
- Keep the live/incremental database schema behavior unchanged.
- Validate completed staging databases with SQLite integrity and foreign-key
  checks before installation.
- Add timing metrics and a read-only benchmark mode for deferred index builds.

## Capabilities

### New Capabilities

- `dataset-index-bulk-build`: Safe and measurable bulk construction of a
  disposable SQLite dataset index without modifying source image or JSON data.

### Modified Capabilities

None.

## Impact

- Affects `anylabeling/views/labeling/dataset_index/index.py`, the rebuild
  worker, compatibility exports, targeted tests, and the dataset-index
  benchmark script.
- Does not change interactive label loading, the JSON label schema, annotation
  save behavior, live database queries, or incremental refresh behavior.
- Adds no external dependency.
