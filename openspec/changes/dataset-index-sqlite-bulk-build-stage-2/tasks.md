## 1. Bulk-Build Lifecycle

- [x] 1.1 Split table creation from the six query-index definitions while
  preserving eager index creation for normal database opens
- [x] 1.2 Add staging-only deferred query-index construction after full row
  insertion
- [x] 1.3 Make deferred index construction transactional and cancellation-aware
- [x] 1.4 Preserve existing SQLite settings after experimental fast PRAGMAs
  showed no material benefit

## 2. Validation and Measurement

- [x] 2.1 Add query-index build, integrity-check, and foreign-key-check timing
  fields to rebuild results
- [x] 2.2 Run and enforce SQLite integrity and foreign-key checks before staging
  installation
- [x] 2.3 Extend the read-only benchmark CLI to compare eager and deferred
  query-index construction
- [x] 2.4 Benchmark the representative 14,468-file dataset and retain only the
  optimization with measurable end-to-end benefit

## 3. Compatibility and Safety

- [x] 3.1 Keep source images and JSON annotations read-only during rebuild and
  benchmarking
- [x] 3.2 Verify the rebuild path does not modify source images, JSON files, or
  interactive label-loading behavior
- [x] 3.3 Preserve live database, incremental refresh, query ordering, staging
  installation, and cancellation behavior
- [x] 3.4 Export compatibility symbols from both the dataset-index package and
  the legacy module path

## 4. Verification

- [x] 4.1 Add tests for default eager indexes, completed deferred indexes, and
  cancellation during index construction
- [x] 4.2 Run Black and Flake8 on all affected files
- [x] 4.3 Run the 51 targeted dataset-index, worker, controller, JSON-stream,
  widget-semantics, and navigation tests
