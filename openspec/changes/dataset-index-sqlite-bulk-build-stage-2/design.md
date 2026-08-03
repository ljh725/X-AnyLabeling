## Context

The dataset-index path scans annotations in a background worker and projects
query fields plus file metadata into a disposable SQLite cache. Full rebuilds
already use a uniquely named staging database that is installed only after the
worker completes. Interactive label loading is outside this change and must
remain unaffected.

On the representative dataset of 14,468 JSON files and 703,465 shapes, the
warm-cache baseline was 20.16 seconds and SQLite writes accounted for about
96.8 percent of rebuild time.

## Goals / Non-Goals

**Goals:**

- Reduce full staging rebuild time without changing query results.
- Preserve the single-writer SQLite model and bounded parallel JSON reads.
- Keep source images and JSON annotations read-only.
- Make index construction and staging validation independently measurable.
- Preserve cancellation and atomic staging installation behavior.

**Non-Goals:**

- Replacing `LabelFile.load()` or using SQLite as editable annotation storage.
- Changing incremental refresh, annotation save, or JSON schema behavior.
- Removing query indexes or changing filter semantics.
- Optimizing cold filesystem cache behavior.

## Decisions

### Defer query-index construction only for staging rebuilds

Schema creation is split into table creation and query-index creation. Normal
and incremental database opens retain eager index creation. The rebuild worker
explicitly requests deferred indexes for its disposable staging database,
loads all rows, and creates the six existing indexes in one transaction.

This avoids maintaining several index trees for every inserted shape while
preserving the final schema. Applying the behavior only to staging prevents an
incomplete live database from being queried without its indexes.

Alternative considered: remove redundant or low-value indexes. Rejected for
this stage because it changes query-planner behavior and is unnecessary to
obtain a measurable gain.

### Validate both storage integrity and relationships

After row and index construction, the worker measures and runs
`integrity_check` and `foreign_key_check`. Failure follows the existing worker
failure path, which closes and removes staging while leaving the live database
unchanged.

### Retain existing SQLite durability settings

An experimental staging profile using disabled journaling and synchronization
measured 16.91 seconds versus 16.99 seconds for deferred indexes alone, about a
0.5 percent difference. The risk and additional configuration surface were
not justified, so the profile was removed.

### Do not retain cross-file shape buffering

Combining per-file shape writes into 10,000-row batches reduced the number of
write calls but measured 17.05 seconds, slightly slower than deferred indexes
alone. The buffering code was removed to avoid complexity without net benefit.

### Record phase timings without persisting them

Planning, pipeline wall time, aggregate read work, SQLite writes, commit,
query-index construction, finalization, integrity validation, foreign-key
validation, bytes read, and maximum in-flight work are attached to the rebuild
result. Benchmark runs use temporary databases and do not write reports unless
an explicit output path is supplied.

## Risks / Trade-offs

- [Cold-cache rebuilds remain dominated by filesystem reads] → Keep bounded
  parallel reads and report cold and warm runs separately.
- [Index construction cannot be interrupted inside one SQLite statement] →
  Check cancellation before and after each individual index build; discard the
  staging database if cancellation is observed.
- [Deferred construction temporarily leaves staging tables unindexed] → Never
  expose or install staging until all indexes and validations complete.
- [Extra validation adds time after rebuild] → Report validation separately
  and retain it because staging safety is more important than hiding latency.

## Migration Plan

1. Deploy the schema split and worker opt-in together.
2. Run targeted schema, cancellation, worker, controller, and query tests.
3. Benchmark against representative source data using temporary databases.
4. Roll back by removing the worker opt-in; normal eager schema creation
   remains available and the SQLite cache can always be rebuilt from JSON.
