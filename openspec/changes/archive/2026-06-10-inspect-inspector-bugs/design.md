## Context

The inspector module in X-AnyLabeling provides data quality validation through a PyQt6-based UI. It consists of 8 core files:

- `flat_index.py` — In-memory index of shapes across JSON annotation files
- `validation_engine.py` — 11 validation rules for checking annotation quality
- `rule_config_widget.py` — UI for configuring validation rules and label sets
- `issue_list_widget.py` — Display of validation issues grouped by rule
- `editable_table_widget.py` — Editable table for modifying shape properties
- `inspector_panel.py` — Main coordinator panel with scan/validate/export workflow
- `export_manager.py` — File export by issue type with image copying
- `external_result_importer.py` — Import of external validation results

Current concerns:
- Some validation rules may have edge case gaps (e.g., group_id handling with None/negative/boolean values)
- Export manager relies on image path resolution that may fail with non-standard directory structures
- Limited test coverage for boundary conditions
- UI signals may not properly handle rapid edits or cancellation

## Goals / Non-Goals

**Goals:**
- Systematically review all inspector files for logic bugs
- Identify and fix edge cases in validation rules
- Improve error handling in file operations (export, import)
- Add unit tests for discovered boundary conditions
- Document all findings and fixes

**Non-Goals:**
- No new features or UI redesign
- No changes to the core annotation format
- No performance optimization (unless critical bugs found)
- No migration of existing data

## Decisions

### Decision 1: Use TDD for bug fixes
**Rationale**: Test-driven development ensures fixes are correct and prevents regression. For each bug found, write a failing test first, then fix the code.

### Decision 2: Review order: validation_engine → flat_index → export_manager → UI components
**Rationale**: Start with core logic (validation rules), then data layer (index), then I/O (export), then UI. This follows dependency order and catches foundational issues first.

### Decision 3: Severity classification for findings
**Rationale**: Not all issues need immediate fixing. Use severity levels:
- **Critical**: Crash or data corruption risk
- **High**: Incorrect validation results (false positive/negative)
- **Medium**: Poor error handling or edge case gap
- **Low**: Code smell or minor improvement

### Decision 4: Fix in place, do not refactor architecture
**Rationale**: Keep changes minimal to reduce risk. Only fix the specific bug, do not refactor surrounding code unless necessary.

## Risks / Trade-offs

- **[Risk] Fixing one bug may introduce another** → Mitigation: Always add regression test before fix
- **[Risk] Edge case fixes may affect performance** → Mitigation: Benchmark with 1000+ files if changes affect scan loop
- **[Trade-off] Time vs thoroughness** → We will time-box each file review to 30 minutes, documenting skipped items for future review

## Migration Plan

No migration needed — all changes are bug fixes with no data format changes.

## Open Questions

1. Should we add integration tests for the full scan → validate → export workflow?
2. How should we handle backward compatibility if validation rules become stricter?
