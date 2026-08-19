## Purpose

Provides a reversible, in-application review queue that turns many annotation objects in one image into focused, navigable task groups while preserving the original annotation file as the single source of truth.

## ADDED Requirements

### Requirement: Review criteria create deterministic virtual tasks

The system SHALL allow a user to generate a virtual task list for the current image using label, shape type, group-id mode/value, and inclusive pixel width/height ranges. The same criteria and unchanged annotation order SHALL produce the same task order.

#### Scenario: Criteria match an anchor
- **WHEN** a visible shape satisfies all configured criteria
- **THEN** the shape SHALL be eligible as a virtual-task anchor

#### Scenario: A size boundary is included
- **WHEN** a shape width or height equals a configured minimum or maximum
- **THEN** the shape SHALL remain eligible for that criterion

#### Scenario: No shape matches
- **WHEN** task generation completes with no eligible anchors
- **THEN** the system SHALL keep normal annotation behavior and report that no virtual tasks were generated

### Requirement: Grouped shapes form one editable task

The system SHALL create at most one task for each valid group id in the current image and SHALL include all same-group shapes in that task, even when those member shapes do not satisfy the anchor criteria. A shape without a valid group id SHALL form a single-shape task.

#### Scenario: Multiple matching shapes share one group
- **WHEN** two or more eligible anchors have the same valid group id
- **THEN** the system SHALL create one task containing that group’s shapes

#### Scenario: A member does not match anchor criteria
- **WHEN** a same-group head, face, or keypoint does not satisfy the configured anchor label or size criteria
- **THEN** the member SHALL still be included in the grouped task

#### Scenario: Ungrouped anchor
- **WHEN** an eligible anchor has no valid group id
- **THEN** the system SHALL create a task containing that anchor only

### Requirement: Focused task display separates viewing from interaction

While a virtual task is active, the current task members SHALL be rendered normally and SHALL remain editable. Other base-visible shapes SHALL be visually deemphasized and SHALL not be selectable or editable through normal canvas interaction. Existing base visibility and filter state SHALL remain unchanged.

#### Scenario: Current task is active
- **WHEN** a virtual task is selected
- **THEN** all task members SHALL be visible and interactive

#### Scenario: Unrelated shape is visible
- **WHEN** a shape is base-visible but is not in the current task
- **THEN** it SHALL remain available as visual context but SHALL reject normal mouse selection and editing

#### Scenario: Existing hidden shape
- **WHEN** a shape is already hidden by a user visibility control or dataset filter
- **THEN** virtual review SHALL not make it visible

### Requirement: Keyboard navigation changes tasks directly

The system SHALL provide previous and next virtual-task navigation without requiring the user to return to a full-image view. The default next shortcut SHALL be F2, the default previous shortcut SHALL be Shift+F2, and the existing F1 digit-shortcut pagination SHALL remain unchanged.

#### Scenario: Next task
- **WHEN** the user presses F2 while a virtual review session is active and no drawing/drag transaction is in progress
- **THEN** the system SHALL commit the current in-memory edit state, focus the next task, and update the task progress indicator

#### Scenario: Previous task
- **WHEN** the user presses Shift+F2 under the same conditions
- **THEN** the system SHALL focus the previous task without opening a full-image intermediate view

#### Scenario: Boundary navigation
- **WHEN** the user navigates before the first task or after the last task in an image
- **THEN** the system SHALL keep the current boundary task and show a status hint without changing images

#### Scenario: F1 compatibility
- **WHEN** the user presses F1
- **THEN** the existing digit-shortcut page action SHALL run and virtual review navigation SHALL not run

### Requirement: Task focus controls the viewport without persisting transient state

The system SHALL center and zoom the canvas on the current task group when entering or navigating to a task, and SHALL restore the pre-session viewport when virtual review ends. Temporary task navigation SHALL not overwrite the persisted per-image viewport state.

#### Scenario: Navigate to a task
- **WHEN** the current virtual task changes
- **THEN** the canvas SHALL center the task group using a padded union bounding box

#### Scenario: Exit review
- **WHEN** the user exits virtual review
- **THEN** normal visibility, interaction, and the pre-session viewport SHALL be restored

### Requirement: Annotation persistence remains unchanged

The system SHALL edit the existing in-memory Shapes and SHALL NOT write virtual-task identifiers, split files, or merge manifests into the annotation dataset. Normal undo, autosave, manual save, and image-change save protection SHALL remain effective.

#### Scenario: Edit within one image
- **WHEN** the user edits a task member and navigates to another task in the same image
- **THEN** the edit SHALL remain available through the existing undo/save flow

#### Scenario: Change image with unsaved edits
- **WHEN** the user leaves the image with unsaved changes
- **THEN** the existing save/discard/cancel protection SHALL decide whether the image change proceeds

### Requirement: Task sessions are stable until explicitly rebuilt

After task generation, the system SHALL keep the task membership and order stable until the user regenerates the list or loads another image. Removed members SHALL be skipped safely, and removed anchors SHALL be reported and skipped.

#### Scenario: Edit changes a criterion field
- **WHEN** the user changes a label, group id, width, or height during an active session
- **THEN** the current task list SHALL not silently reorder or remove tasks

#### Scenario: Anchor is deleted
- **WHEN** a task anchor is deleted before that task is opened
- **THEN** the system SHALL skip the invalid task and report the reason
