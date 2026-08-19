## Purpose

Provides a durable external progress ledger for virtual review so work can resume after restarts while annotation JSON remains free of workflow-only metadata.

## ADDED Requirements

### Requirement: Progress uses an explicit versioned sidecar
The system SHALL save each dataset review queue in a reviewer-selected external SQLite sidecar with a recognized `.xreview.sqlite3` extension, schema version, queue id, revision, criteria snapshot, packing snapshot, dataset-root hint, relative source paths, frozen entries, cursor, outcomes, and timestamps. It SHALL NOT add queue or progress fields to annotation JSON.

#### Scenario: Reviewer creates a persistent queue
- **WHEN** queue construction succeeds and the reviewer selects a writable sidecar path
- **THEN** the system writes the complete versioned queue document outside the annotation files

#### Scenario: Dataset folder moves with its sidecar
- **WHEN** stored relative paths remain valid under the sidecar's new dataset root
- **THEN** the queue can be rebound and resumed without changing task outcomes

### Requirement: Progress is stored per atomic task
The system SHALL assign an external stable id to each frozen atomic task and store its outcome independently of page packing. Supported outcomes SHALL be `pending`, `completed`, `needs_rework`, and `skipped`; page state and statistics SHALL be derived from their member task outcomes.

#### Scenario: A completed page is repacked on rebuild
- **WHEN** atomic tasks move into different image-local pages after an explicit rebuild
- **THEN** unambiguously matched task outcomes follow the atomic tasks rather than the old page ids

#### Scenario: Reviewer resets an outcome
- **WHEN** the reviewer explicitly resets a completed, skipped, or needs-rework task page
- **THEN** affected atomic tasks return to pending and the change is persisted with a new timestamp and revision

### Requirement: Stable ids are separate from live runtime shape ids
The system SHALL keep queue ids and atomic-task ids stable within the sidecar and SHALL store sufficient source locators and shape snapshots to rebind them after restart. Runtime-only shape identities SHALL NOT be treated as persistent identifiers.

#### Scenario: Application restarts
- **WHEN** a queue is reopened in a new process where live shapes have new runtime identities
- **THEN** the system resolves frozen tasks from stored file and shape locators before activating a page

#### Scenario: Ungrouped shape changed significantly
- **WHEN** an ungrouped target no longer matches its stored exact or high-confidence locator
- **THEN** its external task id and outcome remain in the ledger but the live binding is marked orphaned or ambiguous rather than reassigned silently

### Requirement: Outcome changes are durably ordered after annotation saves
The system SHALL persist an outcome only after any annotation changes required for that outcome have saved successfully. Outcome mutation and optional automatic navigation SHALL be separate commits so a navigation failure cannot erase an already valid review decision.

#### Scenario: Complete and advance succeeds
- **WHEN** annotation save, sidecar outcome save, and destination activation all succeed
- **THEN** the completed outcome and new cursor are both durable

#### Scenario: Advance fails after completion is saved
- **WHEN** completion persistence succeeds but destination loading fails
- **THEN** the completion remains durable and the stored cursor remains on the last successfully activated page

### Requirement: Review freshness is tracked per atomic task
The system SHALL record a normalized task-content signature when an atomic task receives a completed outcome. If that task's label, shape type, group membership, or geometry later changes, the system SHALL retain the completed outcome but mark it stale and include it in the default actionable view until explicitly reviewed again.

#### Scenario: Unrelated shape in the same file changes
- **WHEN** the annotation file changes but a completed task's normalized content signature is unchanged
- **THEN** that task remains freshly completed

#### Scenario: Completed target changes later
- **WHEN** a completed task's normalized member content no longer matches its reviewed signature
- **THEN** the system preserves its history, marks completion stale, and requires a new explicit completion to make it fresh

### Requirement: Every sidecar update is transactional and recoverable
The system SHALL commit outcome, cursor, lease, and reconciliation changes in SQLite transactions with foreign-key enforcement and SHALL validate schema version and database integrity before editable activation. It SHALL preserve a last-known-good backup before schema migration and provide an explicit backup operation for an active queue.

#### Scenario: Process stops during a write
- **WHEN** the process stops before a progress transaction commits
- **THEN** SQLite rollback leaves the last committed outcome and cursor authoritative when the queue reopens

#### Scenario: Integrity validation fails
- **WHEN** the database fails its schema, foreign-key, or integrity validation
- **THEN** the system refuses editable activation and offers diagnostics, a validated backup, or creation of a separate recovered copy

#### Scenario: Sidecar directory becomes unwritable
- **WHEN** an outcome or cursor update cannot be committed
- **THEN** the system reports a blocking persistence error, retains the last durable state, and prevents further outcome changes until the reviewer retries, selects a new path, or closes without claiming those changes were saved

### Requirement: Schema compatibility is explicit
The system SHALL reject unsupported newer schema versions without modifying them and SHALL migrate supported older versions only inside a transaction after preserving a validated backup of the original.

#### Scenario: Newer application schema is encountered
- **WHEN** the sidecar schema version is newer than the running application supports
- **THEN** the system opens it read-only for diagnostics or refuses activation and does not overwrite it

#### Scenario: Supported migration succeeds
- **WHEN** an older supported schema is opened
- **THEN** the system preserves the original, commits the migration transaction, validates the result, and records the migration version and timestamp

### Requirement: Concurrent writers cannot silently overwrite progress
The system SHALL acquire an explicit single-writer lease for an editable sidecar and SHALL verify ownership before every write. A second application instance SHALL open the queue read-only unless the reviewer explicitly resolves a stale lease or saves a separate copy.

#### Scenario: Queue is already open elsewhere
- **WHEN** another live application instance owns the sidecar lease
- **THEN** the system prevents editable activation and explains the read-only or save-as options

#### Scenario: Stale lease remains after a crash
- **WHEN** lease metadata is older than the configured stale threshold and no active owner can be confirmed
- **THEN** the system allows an explicit reviewer-confirmed takeover and records it in recovery metadata

### Requirement: Resume preserves the last durable position and summaries
The system SHALL persist the last successfully activated page id and SHALL calculate task and page counts by outcome when opening a queue. If the saved page is unavailable or excluded by the current filter, it SHALL select the nearest next eligible entry without changing stored outcomes.

#### Scenario: Normal restart
- **WHEN** the reviewer reopens a valid sidecar whose saved page is ready and eligible
- **THEN** the system restores that file and page and displays durable completion statistics

#### Scenario: Saved page is unavailable
- **WHEN** the saved page refers to a missing or ambiguous target
- **THEN** the system reports the issue and resumes at the next eligible page while retaining the unavailable entry for reconciliation

### Requirement: Persistence failures never alter annotation data
The system SHALL keep queue-storage, recovery, lease, and reconciliation metadata outside annotation JSON, and a sidecar failure SHALL NOT trigger annotation rollback or write workflow metadata into labels.

#### Scenario: Progress write fails after annotation save
- **WHEN** annotation JSON has saved successfully but the sidecar update fails
- **THEN** the annotation edit remains saved, the prior progress state remains authoritative, and the reviewer is told that review completion was not recorded
