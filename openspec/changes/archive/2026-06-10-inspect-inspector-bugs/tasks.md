## 1. Setup and Initial Review

- [x] 1.1 Create branch for inspector bug review
- [x] 1.2 Run existing tests to establish baseline
- [x] 1.3 Review all 8 inspector files to identify potential issues

## 2. Validation Engine Rules Audit

- [x] 2.1 Test `LabelInAllowlist` with empty labels, None labels
- [x] 2.2 Test `GroupIdValid` with boolean group_id (True/False)
- [x] 2.3 Test `PersonRectRequiresGroupId` with negative, None, string group_id
- [x] 2.4 Test `GroupLabelUniqueness` cross-file behavior (should be per-file only)
- [x] 2.5 Test `GroupIdUniqueness` with empty UNIQUE_TYPES set
- [x] 2.6 Test `HeadFaceGroupIdUniqueness` with invalid group_id values
- [x] 2.7 Test `LabelShapeTypeBinding` with labels not in either set
- [x] 2.8 Test `GroupIdKeypointIntegrity` with missing person rectangle
- [x] 2.9 Test `RequiredFieldNotEmpty` with empty points list
- [x] 2.10 Test `AttributeConsistency` edge cases (if enabled)

## 3. FlatIndex Edge Cases

- [x] 3.1 Test `scan_files` with empty JSON file list
- [x] 3.2 Test `scan_files` with malformed JSON files
- [x] 3.3 Test `scan_files` with missing imagePath references
- [x] 3.4 Verify incremental refresh behavior on single-file update
- [x] 3.5 Test query methods with non-existent labels/group_ids

## 4. Export Manager Robustness

- [x] 4.1 Test `export` with missing source JSON files
- [x] 4.2 Test `_find_image_for_json` with multiple image extensions
- [x] 4.3 Test `_find_image_for_json` with JSON and images in different directories
- [x] 4.4 Test `export` with empty issue list
- [x] 4.5 Verify ExportResult error tracking works correctly

## 5. UI Components Check

- [x] 5.1 Test `InspectorScanThread` cancellation behavior
- [x] 5.2 Test `EditableTableWidget` rapid edit scenarios
- [x] 5.3 Test `IssueListWidget` with empty report
- [x] 5.4 Test `RuleConfigWidget` parameter serialization/deserialization
- [x] 5.5 Verify signal connections in `InspectorPanel` (issue_navigate_requested, shape_edit_requested)

## 6. Bug Fixes and Testing

- [x] 6.1 Write unit tests for each confirmed bug (TDD approach)
- [x] 6.2 Fix validation rule edge cases identified in tasks 2.x
- [x] 6.3 Fix export manager error handling gaps
- [x] 6.4 Fix any UI signal/slot connection issues
- [x] 6.5 Run full test suite to verify no regressions

## 7. Documentation and Cleanup

- [x] 7.1 Document all found bugs in BUGS.md with severity and reproduction steps
- [x] 7.2 Update code comments for fixed edge cases
- [x] 7.3 Verify all tests pass
- [x] 7.4 Archive change with `openspec archive`
