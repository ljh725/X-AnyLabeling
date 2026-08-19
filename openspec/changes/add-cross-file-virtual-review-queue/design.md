## Context

The current implementation has two image-local layers:

```text
shapes -> VirtualTask (atomic group/single target)
       -> VirtualReviewPage (one to three compatible atomic tasks)
       -> VirtualReviewSession (frozen pages for the current image)
```

`VirtualReviewController` owns Canvas focus, primary-anchor selection, and transient viewport fitting. It rebuilds image-local pages when an image loads. `LabelWidget` owns the dataset image order, label-file mapping, dirty-file protection, annotation saving, and actual file loading. Runtime shape ids deliberately do not enter annotation JSON and therefore cannot identify a task after application restart.

The dataset can be substantially larger than the 25–30 objects in one image. The existing dataset index demonstrates that background JSON scanning and staged SQLite construction are established project patterns, but that index is a disposable query cache and must not become the authority for non-derivable review outcomes.

## Goals / Non-Goals

**Goals:**

- Add a third orchestration layer above existing image-local pages instead of replacing task building or packing.
- Make explicit review decisions durable at atomic-task granularity and cheap to update.
- Resume safely when runtime ids, dataset roots, or annotation content have changed.
- Preserve the current dirty-file, save, viewport, Canvas interaction, undo, and autosave behavior.
- Make ambiguous reconciliation visible and conservative.
- Keep long scans cancellable and never expose a partial queue as active work.

**Non-Goals:**

- Combining targets from different images on one visual page.
- Writing review ids or states into annotation JSON.
- Collaborative merging between several reviewers or a cloud review service.
- Replacing the L1/L2 quality-review queue or merging its issue semantics into target review.
- Automatically accepting model predictions, changing labels, or assigning group ids.
- Reusing the disposable dataset-filter SQLite database as durable progress storage.
- Automatically adding new files or repacking pages while a queue is active.

## Decisions

### Decision 1: Add a dataset queue above image-local pages

Introduce a pure-Python dataset queue whose entries reference one image-local `VirtualReviewPage`. Existing criteria and packers remain the only definitions of atomic task membership and compatible page membership:

```text
ordered dataset files
  -> per-file shape snapshots
  -> build_virtual_tasks(criteria)
  -> pack_virtual_tasks(options, reference_viewport)
  -> frozen DatasetReviewQueue revision
```

The queue stores a file id for every page and forbids a page from containing tasks belonging to different files. At runtime a dataset controller loads the page's file and delegates page focus and viewport work to the existing image-local controller.

This keeps the three concepts separate:

- atomic task: what must not be split;
- visual page: what can be reviewed together in one image;
- dataset queue: the order in which image-local pages are visited.

Building cross-file “mega pages” or moving packing into the dataset controller was rejected because Canvas can show only one image and because it would duplicate the proven first- and second-stage rules.

### Decision 2: Persist outcomes per atomic task, not per page

Each queue revision receives stable external UUIDs for source files, atomic tasks, and pages. A page-to-task relation records page membership, while outcome, reviewed timestamp, reviewed signature, and optional note belong to the atomic task.

The UI provides both a fast `complete all live tasks on this page` action and per-task selection for `completed`, `needs_rework`, `skipped`, or `pending`. Page status is derived:

- fresh completed: every task is freshly completed;
- skipped: every task is skipped;
- actionable: at least one task is pending, needs rework, or stale completed;
- mixed: member outcomes differ;
- unresolved: at least one member lacks a trustworthy live binding.

Per-task persistence costs slightly more schema work than page-level persistence, but it avoids losing progress when an explicit rebuild changes packing. It also avoids falsely assigning one outcome to all targets on a two- or three-task smart page.

### Decision 3: Use a dedicated SQLite sidecar as the durable authority

The reviewer chooses a `.xreview.sqlite3` path when creating or saving a queue. The UI suggests a name based on the loaded dataset but does not silently create workflow files beside annotations. The standard-library `sqlite3` module is sufficient; no new runtime dependency is required.

The initial schema contains these logical tables:

- `queue_meta`: queue id, schema version, active revision, created/updated timestamps, application version, and dataset-root hint;
- `queue_revision`: frozen criteria, packing options, reference viewport, revision state, and build diagnostics;
- `source_file`: ordered image/label relative paths, source signatures, availability, and exclusion diagnostics;
- `atomic_task`: external task id, source file, original order, locator/snapshot payloads, outcome, review freshness, timestamps, and carried-from id;
- `review_page`: page id, file id, page order, frozen geometry and packing diagnostics;
- `page_task`: ordered many-to-many membership between pages and atomic tasks;
- `cursor`: last successfully activated page and current state filter;
- `outcome_event`: append-only outcome history for audit and recovery diagnostics;
- `reconciliation_event`: binding decisions, warnings, and explicit reviewer resolutions;
- `writer_lease`: instance id, process/host details, and heartbeat;
- `migration_history`: applied schema migrations and backup path.

Flexible locator, criteria, and packing payloads can be canonical JSON text inside typed SQLite rows. JSON is an encoding for bounded fields, not the persistence transaction boundary.

SQLite transactions make each cursor or outcome update proportional to the changed rows rather than the whole queue. Use `foreign_keys=ON`, a bounded busy timeout, WAL journaling, and full synchronous durability for this user-authored progress database. Checkpoint WAL on clean close and use the SQLite backup API for explicit backups and before migrations.

A single large JSON document was rejected because a queue containing thousands of tasks would require repeated full-file rewrites on every navigation and would need custom crash, concurrency, and migration logic. The disposable dataset index was rejected as the authority because it can be deleted and rebuilt from annotations, while review decisions cannot.

### Decision 4: Build new revisions through staging and publish atomically

Queue construction runs outside the GUI thread and reads one annotation file at a time. It captures the current ordered `image_list`, effective label path for each image, criteria, packing options, and one reference viewport size before starting. The reference viewport makes packing deterministic across files; opening the queue on another monitor refits frozen membership but does not silently repack it.

The worker writes a uniquely named staging SQLite database in the target directory. It reports file count, generated task/page count, exclusions, and cancellation. Parse failures are accumulated in the draft result; the user chooses either to cancel or to publish with those files explicitly recorded as excluded.

Before publication the worker validates schema version, foreign keys, integrity, counts, and the invariant that each page belongs to exactly one source file. For a new queue, the validated staging database is installed as the selected sidecar. For a rebuild, the validated candidate revision is imported into the existing database and `active_revision` flips in one transaction. Cancellation or validation failure removes only the staging database and leaves the current session and revision untouched.

Keeping an in-memory list until the scan finishes was considered. It is simpler for small datasets but increases memory use, loses resumable diagnostics, and duplicates the project's proven staged-SQLite pattern.

### Decision 5: Separate persistent ids, source locators, and runtime ids

An external task UUID identifies progress within the sidecar. A `TaskLocator` identifies the intended content in a source file. Runtime shape ids are assigned again after each JSON load and are used only to install the current Canvas predicate.

Each file stores normalized relative image and label paths plus a fast source signature. Each atomic task locator stores:

- grouped or ungrouped kind;
- normalized group id when present;
- anchor/member original ordinals;
- label and shape type snapshots;
- normalized point and bbox fingerprints;
- member count and ordered member fingerprints;
- image dimensions used for normalized geometry.

Rehydration uses a conservative ladder:

1. If the file signature is unchanged, verify the stored ordinals and exact task fingerprints.
2. Otherwise match an exact normalized group id and compatible member signature.
3. Otherwise match an exact member-content fingerprint.
4. Otherwise score candidates using hard shape-type compatibility plus normalized geometry overlap/centre distance, member count, group structure, and label as a soft signal.
5. Auto-bind only one candidate above the confidence threshold and sufficiently ahead of the second candidate.
6. Mark zero matches orphaned and multiple plausible matches ambiguous.

Group-id or label edits therefore do not automatically destroy identity, while repeated nearby objects cannot silently inherit each other's progress. Manual resolution records the chosen live locator in `reconciliation_event`; it does not alter annotation JSON.

A deterministic hash made directly from current label and points was rejected as the sole id because the very edits performed during review would change it. Persisting a UUID inside every shape was rejected because it changes the annotation format and existing data.

### Decision 6: Track outcome and freshness separately

When a task becomes completed, persist a normalized signature of only that task's reviewed members after the annotation save. On resume or reconcile, compare the current task signature with that reviewed signature:

- unchanged task content: completion remains fresh even if another shape in the JSON changed;
- changed task content: retain outcome history but set freshness to stale;
- unresolved live binding: retain outcome and report unresolved freshness.

The default actionable filter contains pending, needs-rework, and stale-completed tasks. Fresh completed and skipped tasks remain available in explicit filters. This prevents a later annotation edit from leaving a misleading “100% reviewed” result, without erasing the fact that the task was reviewed earlier.

Using only whole-file modification time or hash was rejected because changing one shape would invalidate every completed task in the same file.

### Decision 7: Make file transition and completion two ordered operations

Plain F2/Shift+F2 navigation never changes an outcome. The destination transition is:

1. Resolve any active drawing, drag, or modal-edit guard.
2. Run the existing dirty-file save/discard/cancel decision.
3. Request destination image load without changing the durable queue cursor.
4. Rehydrate and activate the stored page after load success.
5. Commit the new page id as the durable cursor.

Cancel or load failure leaves the prior cursor and page authoritative.

`Complete`, `needs rework`, `skip`, and `reset` are explicit commands. For an edited current image the command first saves annotation JSON successfully, then opens a SQLite transaction that updates selected atomic tasks, appends outcome events, refreshes task signatures, and increments the queue revision counter. A combined `complete and next` convenience action commits completion first and then performs an ordinary transition. If the destination fails, the completion remains valid and the cursor stays on the last activated page.

This ordering avoids both dangerous states: “marked completed but edit was not saved” and “destination failed so a valid completion disappeared.” A distributed transaction across JSON and SQLite was rejected as unnecessary; explicit ordered commits and visible failure states are understandable and testable.

### Decision 8: Use an explicit queue state machine

The dataset controller has these states:

```text
IDLE
  -> BUILDING -> DRAFT_CONFIRMATION -> ACTIVE
  -> OPENING  -> RECONCILING       -> ACTIVE

ACTIVE -> TRANSITIONING -> ACTIVE
ACTIVE -> PERSISTENCE_BLOCKED -> ACTIVE or CLOSED
ACTIVE -> REBUILDING -> ACTIVE
ACTIVE -> CLOSED
```

Only `ACTIVE` accepts navigation or outcome commands. `TRANSITIONING` coalesces repeated navigation input rather than starting concurrent loads. `PERSISTENCE_BLOCKED` keeps the last durable state visible but disables further outcome mutations until retry, save-as, or deliberate close. Building/rebuilding owns one cancellable worker at a time.

Local current-image review and dataset-queue review are mutually exclusive owners of the virtual Canvas focus layer. Activating a dataset queue first exits local review cleanly. Closing a queue restores the pre-session viewport using the existing controller behavior and releases its writer lease.

### Decision 9: Reconcile in place; rebuild explicitly

`Reconcile` and `Rebuild` solve different problems:

- Reconcile rechecks paths, source signatures, live bindings, task freshness, missing files, and new candidate counts. It does not change the active revision's file/page/task membership or order.
- Rebuild reruns criteria and packing against current files, publishes a new frozen revision, and carries prior outcomes only through exact or explicitly confirmed task matches.

Old revision rows and unmatched outcomes remain available as history until an explicit compact/archive operation. New candidates start pending. Removed candidates are not silently deleted from history. This provides an audit trail and makes rollback to the preceding revision possible without copying annotation files.

Automatic incremental insertion was rejected because it would move the cursor denominator and page order during review. Silent fuzzy carry-forward was rejected because progress correctness is more important than maximizing automatic matches.

### Decision 10: Use a separate dataset controller with a narrow host API

Add pure-Python modules under `virtual_review/` for queue models, schema/store, builder, locator matching, reconciliation, and progress filtering. They do not import PyQt.

Add Qt adapters under the Inspector layer:

- a build/reconcile worker that owns its SQLite connection;
- a dataset queue controller that owns lifecycle, writer lease, transition sequencing, and calls the pure store;
- extensions to the existing target-review widget for build/open/close, scan progress, outcome filters, current-page task rows, outcome actions, counters, and warnings.

The existing image-local controller gains a narrow method to activate externally supplied frozen pages and a queue-owned mode that suppresses its current automatic rebuild-on-image-load behavior. `LabelWidget` exposes narrow callbacks for ordered dataset files, effective label paths, dirty-safe asynchronous file loading, save-current-file, and load completion. It does not absorb queue algorithms or database access.

This split avoids making the already large `LabelWidget` or `VirtualReviewController` a second persistence subsystem. It also preserves pure-Python unit testing for the high-risk identity and transaction logic.

### Decision 11: Use a single-writer lease plus optimistic revision checks

SQLite protects individual writes but does not prevent two application windows from alternately committing valid yet confusing reviewer decisions. Editable open therefore claims a `writer_lease` row in an immediate transaction. The row contains instance UUID, pid, host, opened time, and heartbeat. Every mutation verifies the lease and the last observed logical revision.

A second instance may inspect summaries read-only or save a separate copy. Stale takeover is never automatic: after a heartbeat timeout, same-host process check and explicit confirmation, the new owner records a takeover event. If the logical revision changes unexpectedly, the current writer enters `PERSISTENCE_BLOCKED` rather than overwriting newer state.

An operating-system lock file was considered but leaves additional cleanup and path-move edge cases. A database lease is inspectable, migratable, and can be updated in the same transaction as progress metadata; SQLite remains the low-level serialization mechanism.

### Decision 12: Keep shortcuts configurable and preserve existing F2 semantics

F2 remains next eligible page and Shift+F2 remains previous eligible page; at an image boundary they invoke the safe file transition. Outcome actions are exposed as buttons first and can receive defaults only through the existing shortcut settings and conflict validator. No hard-coded key may bypass current F1/F2 conflict handling or trigger while drawing, dragging, or a modal editor is active.

## Risks / Trade-offs

- **[Ungrouped objects have no permanent id in annotation JSON]** -> Store rich external locators, require a unique confidence margin, and expose ambiguous/manual reconciliation rather than guessing.
- **[A large initial scan can take noticeable time]** -> Stream files in a cancellable worker, publish only a validated staging result, and report exclusions before activation.
- **[SQLite sidecars are less human-readable than JSON]** -> Provide summary/export diagnostics later if needed; favor transaction cost and correctness for the operational format.
- **[WAL produces temporary `-wal`/`-shm` files while open]** -> Use SQLite backup for copying, checkpoint on clean close, and explain that the database should not be manually moved while editable.
- **[Completion plus JSON save cannot be one atomic cross-file transaction]** -> Enforce save-first ordering; if progress fails afterward, keep annotation saved and report that completion remains unrecorded.
- **[Fuzzy reconciliation can still be wrong in repeated-object scenes]** -> Treat label as soft evidence, require geometry/group compatibility and a winner margin, and route close candidates to manual resolution.
- **[A frozen packed page may become awkward after edits or monitor changes]** -> Refit its frozen bbox, permit image-local page regeneration only through explicit queue rebuild, and retain single-task packing as a queue-build option.
- **[Partially unresolved smart pages can mislead batch actions]** -> Show task-level binding states; page-wide outcomes apply only to live-bound tasks and never mutate unresolved members.
- **[Multiple application instances can produce semantic conflicts]** -> Use a database writer lease, heartbeat, logical revision check, read-only fallback, and explicit stale takeover.
- **[The queue database contains paths and review history]** -> Create it only at a reviewer-selected location and never upload or embed it automatically.

## Migration Plan

1. Introduce the pure SQLite schema/store, models, identity locators, and reconciliation tests without changing current-image review.
2. Add staging queue construction and verify deterministic equivalence with direct per-file task building and packing.
3. Add dataset controller and guarded file-transition host API behind an inactive UI path.
4. Add outcome controls, filters, lease/recovery UI, and restart tests.
5. Enable queue creation/opening in the target-review tab while keeping local review as the immediate fallback.
6. Roll back by disabling dataset-queue actions. Annotation JSON remains unchanged; `.xreview.sqlite3` files are independent and can be retained for a later compatible build.
