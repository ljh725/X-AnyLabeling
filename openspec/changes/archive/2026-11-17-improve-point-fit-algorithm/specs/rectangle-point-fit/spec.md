## Purpose

为选中矩形提供稳定的单点拟合操作，使角点判断在缩放和越过框边时连续，并保证按下时确定的固定点与模式贯穿整次操作，预览能够准确反映裁剪后的提交结果。

## ADDED Requirements

### Requirement: Continuous size-aware corner inference
The system SHALL use screen-space ambiguity bands that vary continuously at rectangle boundaries and are limited independently by rectangle width and height.

#### Scenario: Cross the top edge
- **WHEN** the pointer moves from (151.5, 100) to (151.5, 99.9) for box (100, 100, 200, 200) at scale 1
- **THEN** both positions SHALL infer the top-right corner

#### Scenario: Narrow rectangle
- **WHEN** a rectangle occupies 1.5 screen pixels horizontally and the pointer is clearly in its left or right quarter
- **THEN** its entire interior SHALL NOT be rejected as ambiguous

### Requirement: Captured gesture keeps its anchor and mode
The system SHALL freeze the original geometry, selected corner and Alt mode at a valid Shift-left press until release or cancellation. Crossing the anchor SHALL normalize the resulting rectangle without choosing a new anchor.

#### Scenario: Cross the centre after pressing
- **WHEN** the user presses at (120, 120) then releases at (180, 120) in default mode for box (100, 100, 200, 200)
- **THEN** the anchor SHALL remain (200, 200) and the result SHALL be (180, 120, 200, 200)

#### Scenario: Release Alt first
- **WHEN** an inward fit begins with Alt held and Alt is released before the mouse
- **THEN** the inward mode SHALL still be used on release

### Requirement: Preview matches clipped geometry
The system SHALL display the actual image-clipped anchor and destination and commit the same geometry shown by the preview. Invalid fits SHALL fall back to native selection and moving; successful fits SHALL remain one undo operation.

#### Scenario: Pointer outside image
- **WHEN** a valid destination exceeds the image extent
- **THEN** the preview destination SHALL appear on the clipped boundary and the committed rectangle SHALL match the preview

#### Scenario: Cancel Shift
- **WHEN** Shift is released during a captured fit
- **THEN** no geometry or undo entry SHALL be committed
