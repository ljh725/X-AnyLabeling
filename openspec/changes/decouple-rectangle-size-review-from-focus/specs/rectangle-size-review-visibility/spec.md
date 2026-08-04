## Purpose

Define stable rectangle-size review behavior that remains independent from
temporary editing focus while continuing to respect persistent visibility
controls on the current canvas.

## ADDED Requirements

### Requirement: Review eligibility is independent from editing focus

The system SHALL evaluate every base-visible rectangle that matches an enabled
rectangle-size rule, regardless of whether an editing-focus mode currently
allows interaction with that rectangle.

#### Scenario: Focus excludes a violating rectangle from interaction

- **WHEN** a base-visible violating rectangle is outside the active three-box
  focus group
- **THEN** its rectangle-size issue remains in the current review result

#### Scenario: Focus anchor changes

- **WHEN** the user changes the three-box focus anchor without changing shapes
  or rectangle-size rules
- **THEN** the rectangle-size issue set remains unchanged

#### Scenario: Rules change while focus is active

- **WHEN** rules are applied while three-box focus excludes some matching
  rectangles from interaction
- **THEN** all base-visible rectangles are evaluated against the complete new
  rule set

### Requirement: Base-hidden rectangles are excluded from review

The system SHALL exclude rectangles hidden by canvas visibility, per-shape
visibility, or dataset filtering from rectangle-size review.

#### Scenario: Rectangle is hidden through a base visibility control

- **WHEN** a rectangle becomes hidden through any base visibility mechanism
- **THEN** its rectangle-size issue is removed from the current review result

#### Scenario: Base visibility is restored

- **WHEN** a previously base-hidden violating rectangle becomes base-visible
- **THEN** its rectangle-size issue is restored after review refresh

### Requirement: Review results and painted warnings use one policy

The system SHALL construct rectangle-size warning overlays from the same base
visibility policy used to produce the current review result.

#### Scenario: Non-focused rectangle retains its warning

- **WHEN** a base-visible violating rectangle is excluded only by editing focus
- **THEN** its warning overlay remains available for painting

#### Scenario: Base-hidden rectangle has no warning

- **WHEN** a violating rectangle is base-hidden
- **THEN** neither a current issue nor a warning overlay is exposed for it

### Requirement: Editing focus behavior remains unchanged

The system SHALL continue to use the focus-aware interaction policy for hover,
selection, and geometry editing.

#### Scenario: Non-member remains non-interactive

- **WHEN** three-box focus is active and a shape is outside its member set
- **THEN** the shape remains unavailable for normal hover, selection, and edit
  operations even though rectangle-size review may report it
