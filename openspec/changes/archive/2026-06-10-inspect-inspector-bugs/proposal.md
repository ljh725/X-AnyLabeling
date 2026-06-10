## Why

The inspector module (`anylabeling/views/labeling/widgets/inspector/`) is a critical component for data quality validation in X-AnyLabeling. It contains 8 core files managing validation rules, UI components, and export functionality. Before implementing new features or releasing, we need a systematic review to identify potential bugs, edge cases, and logic flaws that could cause crashes, false positives/negatives in validation, or data corruption.

## What Changes

- **Code Review**: Systematic audit of all 8 inspector module files for logic errors, edge cases, and anti-patterns
- **Test Coverage Analysis**: Identify untested boundary conditions (empty labels, invalid group_id, missing files, etc.)
- **Bug Documentation**: Catalog found issues with severity ratings and reproduction steps
- **Fix Implementation**: Apply fixes for confirmed bugs with TDD approach
- **Regression Prevention**: Add unit tests for discovered edge cases

## Capabilities

### New Capabilities
- `inspector-validation-rules`: Enhanced validation rule logic with improved edge case handling
- `inspector-export-reliability`: Robust file export with better error handling and path resolution

### Modified Capabilities
- *(none - this is a review/fix cycle, not a feature addition)*

## Impact

- **Files Affected**: All files in `anylabeling/views/labeling/widgets/inspector/`
- **Risk**: Low - fixes only, no API changes
- **Testing**: Requires unit tests for validation engine rules
- **User Impact**: More reliable data validation, fewer false positives/negatives
