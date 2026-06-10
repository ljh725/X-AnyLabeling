# inspector-export-reliability Specification

## Purpose
TBD - created by archiving change inspect-inspector-bugs. Update Purpose after archive.
## Requirements
### Requirement: Export manager handles missing files gracefully
The `ExportManager.export()` method SHALL not crash when source files or associated images are missing.

#### Scenario: Missing source JSON file
- **WHEN** an issue references a JSON file that no longer exists
- **THEN** the export SHALL skip that file, record an error in ExportResult.errors, and continue processing other rules

#### Scenario: Missing associated image
- **WHEN** a JSON file exists but its associated image cannot be found
- **THEN** the export SHALL copy the JSON file only, increment copied_files count, and not increment copied_images count

### Requirement: Image path resolution is robust
The `_find_image_for_json()` helper SHALL support multiple image extensions and handle basename-only matching.

#### Scenario: Multiple image extensions
- **WHEN** a JSON file has a matching image with extension .jpg, .jpeg, .png, .bmp, .tiff, .tif, or .webp
- **THEN** the function SHALL find and return the correct image path

#### Scenario: Basename matching
- **WHEN** JSON and images are in different directories but share the same basename
- **THEN** the function SHALL correctly match them using basename comparison

### Requirement: Export preserves directory structure option
The export function SHALL support an optional flag to preserve original directory structure in output.

#### Scenario: Flat export (default)
- **WHEN** exporting with default settings
- **THEN** all files SHALL be copied directly into per-rule subdirectories without nested structure

