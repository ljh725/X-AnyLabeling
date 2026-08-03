## Purpose

Defines safe, compatible, and measurable bulk construction of the disposable
dataset-wide query index while preserving source images and JSON annotations
as read-only source data.

## ADDED Requirements

### Requirement: Source annotation data remains read-only

The system SHALL treat source images and JSON annotation files as read-only
inputs during dataset-index rebuild and benchmarking.

#### Scenario: Full dataset-index rebuild

- **WHEN** a user rebuilds the dataset index
- **THEN** the system reads source images and JSON metadata without modifying,
  renaming, or deleting either source

### Requirement: Bulk rebuild uses an isolated staging database

The system SHALL build a full replacement index in an isolated staging
database and SHALL NOT replace the live index until the staging database is
complete and valid.

#### Scenario: Successful rebuild

- **WHEN** all file and shape rows, query indexes, metadata, and validations
  complete successfully
- **THEN** the system makes the staging database eligible for atomic
  installation

#### Scenario: Cancelled or failed rebuild

- **WHEN** rebuilding is cancelled or any build or validation step fails
- **THEN** the system discards the staging database and preserves the
  previously installed live index

### Requirement: Query indexes are complete before installation

The system SHALL create every required query index after bulk row loading and
before staging database installation.

#### Scenario: Deferred index construction succeeds

- **WHEN** bulk file and shape insertion completes
- **THEN** all required label, group, shape-type, file, file-shape, and
  navigation-order indexes exist before validation

#### Scenario: Cancellation during index construction

- **WHEN** cancellation is observed between query-index builds
- **THEN** the partial index transaction is rolled back and the staging
  database is not installed

### Requirement: Staging database validation

The system MUST run SQLite integrity and foreign-key validation before a
completed staging database can replace the live index.

#### Scenario: Validation passes

- **WHEN** SQLite reports a valid database and no foreign-key violations
- **THEN** the rebuild result can be handed to the atomic installer

#### Scenario: Validation fails

- **WHEN** either integrity or foreign-key validation reports a problem
- **THEN** the rebuild fails and the live database remains unchanged

### Requirement: Rebuild performance is measurable

The system SHALL expose rebuild timing measurements and a benchmark mode that
uses isolated temporary databases.

#### Scenario: Read-only benchmark

- **WHEN** a developer benchmarks eager and deferred query-index construction
- **THEN** the report contains per-run rebuild, SQLite write, query-index
  build, validation, file-count, shape-count, missing, and failure metrics
