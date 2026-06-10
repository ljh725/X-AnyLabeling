# inspector-validation-rules Specification

## Purpose
TBD - created by archiving change inspect-inspector-bugs. Update Purpose after archive.
## Requirements
### Requirement: Validation rules handle edge cases correctly
All validation rules in `validation_engine.py` SHALL correctly handle boundary conditions including empty labels, missing group_id, negative group_id, boolean group_id, and None values.

#### Scenario: Empty label detection
- **WHEN** a shape has an empty string label
- **THEN** the `LabelInAllowlist` rule SHALL report an error with message containing "空标签"

#### Scenario: Invalid group_id rejection
- **WHEN** a person rectangle has group_id set to -1, True, or None
- **THEN** the `PersonRectRequiresGroupId` rule SHALL report an error

#### Scenario: Boolean group_id handling
- **WHEN** any shape has group_id=True or group_id=False
- **THEN** the `GroupIdValid` rule SHALL treat these as invalid (boolean is not integer)

### Requirement: Group-level uniqueness checks work correctly
Group-level uniqueness rules (`GroupLabelUniqueness`, `GroupIdUniqueness`, `HeadFaceGroupIdUniqueness`) SHALL correctly identify duplicates within the same file and group_id.

#### Scenario: Duplicate labels in same group
- **WHEN** two shapes in the same group_id have identical labels
- **THEN** `GroupLabelUniqueness` SHALL report an error for both shapes

#### Scenario: Cross-file isolation
- **WHEN** duplicate labels exist in different files with the same group_id
- **THEN** `GroupLabelUniqueness` SHALL NOT report an error (checks are per-file)

### Requirement: Shape-type binding validation is accurate
The `LabelShapeTypeBinding` rule SHALL correctly validate that rectangle labels use rectangle type and point labels use point type.

#### Scenario: Rectangle label with wrong type
- **WHEN** a shape labeled "person" has shape_type "point"
- **THEN** the rule SHALL report a binding error

#### Scenario: Unbound label detection
- **WHEN** a shape label is not in either rectangle_labels or point_lists
- **THEN** the rule SHALL report an "unbound" error

