## Purpose

为选中矩形提供准确且平稳的边调整操作，使贴边和近边界的小框能够编辑，同时保留内部整体移动空间，极短边通过明确的中点把手与角点区分，所有修改保持可撤销。

## ADDED Requirements

### Requirement: Nearest edge and central moving area
The system SHALL compare geometric edge distances before applying inward eligibility, SHALL NOT substitute a farther edge when the nearest is ineligible, and SHALL preserve a central moving area by limiting inward bands to at most one quarter of the perpendicular span.

#### Scenario: Pointer nearer the other edge
- **WHEN** a small rectangle spans x=0..15 and the pointer is at x=9 halfway down its long side
- **THEN** the left edge SHALL NOT capture the pointer

#### Scenario: Central press
- **WHEN** the pointer is inside the middle half of a narrow rectangle along both axes
- **THEN** edge editing SHALL leave the press available for moving the rectangle

### Requirement: Symmetric screen-space boundary access
The system SHALL expand inward access continuously as available outward space at any image boundary becomes smaller than the normal hit tolerance, using screen distances consistently across zoom levels.

#### Scenario: Near but not exactly flush
- **WHEN** a small edge is one screen pixel from the image boundary
- **THEN** a nearby inward press within the reduced band SHALL be able to capture that edge

### Requirement: Small edge midpoint handles
The system SHALL show midpoint handles on small selected rectangles while edge editing is enabled. Handle hit areas SHALL be limited by both edge length and perpendicular span so that exact vertices and the centre remain separately operable.

#### Scenario: Short edge covered by corner tolerance
- **WHEN** the user presses the visible midpoint of a short edge
- **THEN** that edge SHALL be captured even if normal corner tolerance covers the midpoint

#### Scenario: Vertex and disabled feature
- **WHEN** the user presses an exact vertex or disables edge editing
- **THEN** handles SHALL NOT intercept native vertex editing or remain displayed when disabled

### Requirement: Offset-preserving drag
The system SHALL move a captured edge by the image-space displacement from its original press, preserve the opposite edge, enforce image bounds and minimum size, and commit one undo operation.

#### Scenario: Press beside the edge
- **WHEN** left=0, the user presses at x=5 then moves to x=6
- **THEN** the left edge SHALL become 1 rather than 6

#### Scenario: Return after clamping
- **WHEN** a drag reaches a boundary then returns to its starting pointer position
- **THEN** its geometry SHALL return to the starting geometry without accumulated drift
