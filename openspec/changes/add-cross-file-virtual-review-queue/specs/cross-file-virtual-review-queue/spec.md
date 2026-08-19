## Purpose

Provides a deterministic, safe dataset-level review queue that reuses image-local virtual tasks and smart pages while allowing reviewers to continue naturally across file boundaries.

## ADDED Requirements

### Requirement: Queue construction uses the loaded dataset
The system SHALL build a cross-file queue from the ordered image set currently loaded in the application, the effective label-file mapping, one validated virtual-task criteria snapshot, and one validated packing-options snapshot. Each generated page SHALL contain tasks from exactly one image, and images with no matching tasks SHALL contribute no pages.

#### Scenario: Dataset produces an ordered queue
- **WHEN** the reviewer builds a queue from a loaded dataset and valid options
- **THEN** the system scans files in dataset order and stores image-local pages in a deterministic global order

#### Scenario: A file has no matching task
- **WHEN** one scanned file contains no anchor matching the criteria
- **THEN** the system omits that file from the queue without treating it as an error

#### Scenario: Dirty current file exists before construction
- **WHEN** the reviewer requests queue construction while the current annotation has unsaved changes
- **THEN** the system resolves the existing save, discard, or cancel guard before reading the on-disk dataset and creates no queue if the operation is cancelled

### Requirement: Queue construction is cancellable and commits as a whole
The system SHALL expose construction progress for multi-file queues, SHALL allow cancellation, and SHALL activate and persist a new queue only after the complete queue snapshot has been built successfully.

#### Scenario: Reviewer cancels a long scan
- **WHEN** the reviewer cancels queue construction before completion
- **THEN** the system discards the partial result and leaves the previously active queue or local review session unchanged

#### Scenario: One source file cannot be parsed
- **WHEN** a source annotation cannot be read during construction
- **THEN** the system reports the file-level failure and requires the reviewer to cancel or explicitly continue with that file recorded as excluded

### Requirement: Queue membership remains frozen
The system SHALL keep the queue's file order, atomic-task membership, and page membership frozen until the reviewer explicitly reconciles or rebuilds the queue. File edits, window resizing, and ordinary navigation SHALL NOT silently insert, remove, reorder, or repack queue entries.

#### Scenario: Annotation changes during review
- **WHEN** a reviewer edits labels, group ids, or geometry in the current file
- **THEN** the current queue snapshot and cursor remain stable until an explicit queue operation occurs

#### Scenario: New files appear in the dataset
- **WHEN** files are added after queue construction
- **THEN** the active queue does not include them automatically and reports them only through an explicit reconcile or rebuild check

### Requirement: Navigation crosses file boundaries safely
The system SHALL use the existing next and previous virtual-review actions to navigate eligible queue pages. Before leaving a dirty image, it SHALL complete the normal save, discard, or cancel guard; it SHALL commit the new cursor only after the destination image loads and its page activates successfully.

#### Scenario: Next page is in another file
- **WHEN** the reviewer requests the next eligible page and it belongs to another image
- **THEN** the system safely resolves current-file changes, loads the destination image, activates the stored image-local page, and then persists the destination cursor

#### Scenario: Reviewer cancels the file transition
- **WHEN** the reviewer chooses cancel in the dirty-file guard
- **THEN** the current image, page, queue cursor, and review outcomes remain unchanged

#### Scenario: Destination load fails
- **WHEN** the destination image or annotation cannot be loaded
- **THEN** the system keeps the prior committed cursor, records an availability warning for the destination, and does not mark the destination reviewed

### Requirement: Visiting and reviewing are separate actions
The system SHALL NOT infer completion from page display, selection, navigation, or time spent. It SHALL expose the current page's atomic tasks and provide explicit actions that apply a review outcome to selected, live-bound tasks or to all live-bound tasks on the page.

#### Scenario: Reviewer only visits a page
- **WHEN** a page is displayed and the reviewer navigates away without choosing an outcome
- **THEN** its atomic tasks retain their prior review states

#### Scenario: Reviewer completes a page containing several tasks
- **WHEN** the reviewer explicitly marks the current page completed
- **THEN** every live-bound, non-completed atomic task on that page is recorded as completed only after any dirty annotation save succeeds, while unresolved tasks retain their prior state

#### Scenario: Reviewer marks one task for rework
- **WHEN** a smart page contains several atomic tasks and the reviewer selects one task before choosing needs rework
- **THEN** only the selected live-bound task receives the needs-rework outcome

#### Scenario: Annotation save fails during completion
- **WHEN** the reviewer requests completion after editing and the annotation save fails
- **THEN** the system does not record the completion outcome or automatically advance

### Requirement: Queue navigation honors review-state filters
The system SHALL let reviewers navigate all entries or a filtered set based on atomic-task outcomes and review freshness. The default resumable view SHALL exclude fresh completed and skipped work while including pending, needs-rework, and stale-completed work, and queue boundaries SHALL be reported without wrapping silently.

#### Scenario: Resume chooses actionable work
- **WHEN** a stored queue is opened with completed entries before its saved cursor
- **THEN** the system activates the saved page if it remains eligible or the next eligible pending or needs-rework page otherwise

#### Scenario: No eligible work remains
- **WHEN** every queue task is freshly completed or skipped under the default filter
- **THEN** the system reports that no actionable work remains and retains access to the all-items view

### Requirement: Source changes are reconciled conservatively
The system SHALL classify queue entries whose source file or target task has changed as ready, changed-but-resolved, missing, orphaned, or ambiguous. It SHALL never transfer a pending target or its outcome to an ambiguous live shape without explicit reviewer confirmation.

#### Scenario: Source file is unchanged
- **WHEN** the stored source signature matches the current annotation file
- **THEN** the system restores the stored page through its exact frozen locators

#### Scenario: One high-confidence target survives an edit
- **WHEN** a source signature changed but an existing task locator has exactly one high-confidence live match
- **THEN** the system may bind the entry to that match and records a changed-but-resolved diagnostic

#### Scenario: Several targets are plausible
- **WHEN** reconciliation finds more than one plausible target for a stored task
- **THEN** the system marks the entry ambiguous, excludes it from automatic navigation, and requests explicit resolution

#### Scenario: File is missing
- **WHEN** an image or annotation referenced by the queue no longer exists
- **THEN** the system preserves its progress record, marks the entry unavailable, and continues to other eligible entries

### Requirement: Reconcile and rebuild have distinct effects
The system SHALL provide an in-place reconcile operation that preserves the frozen queue and updates availability bindings, and a rebuild operation that creates a new queue revision from current files. A rebuild SHALL carry outcomes forward only for atomic tasks matched unambiguously.

#### Scenario: Reviewer reconciles after moving the dataset
- **WHEN** relative paths resolve under a newly selected dataset root
- **THEN** the system updates root binding without changing queue order, page membership, or outcomes

#### Scenario: Reviewer rebuilds after adding annotations
- **WHEN** the reviewer explicitly rebuilds the queue
- **THEN** current candidates are regenerated and prior outcomes are copied only to unambiguously matched atomic tasks while unmatched work remains pending or archived in reconciliation history

### Requirement: Local and dataset review modes are mutually exclusive
The system SHALL keep the existing current-image review flow available and SHALL prevent a local review session and a cross-file queue session from controlling Canvas focus or navigation simultaneously.

#### Scenario: Dataset queue starts during local review
- **WHEN** the reviewer activates a dataset queue while a current-image review session is active
- **THEN** the system cleanly exits the local session before activating the queue without losing annotation edits
