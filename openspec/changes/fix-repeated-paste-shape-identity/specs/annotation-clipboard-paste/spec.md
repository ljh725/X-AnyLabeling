## Purpose

Ensure annotation clipboard paste remains repeatable across rapid actions and image navigation while every pasted annotation has independent live and persistent identity.

## ADDED Requirements

### Requirement: Every paste creates independent annotations
The system SHALL create one fresh live annotation object with a fresh persistent shape identity for every copied annotation on every paste invocation, regardless of whether invocations occur rapidly on the same image or use the system or in-memory clipboard mode.

#### Scenario: Rapid repeated paste on one image
- **WHEN** a user copies one annotation and invokes paste twice in rapid succession on the same image
- **THEN** the image contains two newly pasted annotations
- **AND** the two annotations are different live objects with different persistent shape identities
- **AND** editing either pasted annotation does not mutate the other

#### Scenario: Repeated paste of multiple selected annotations
- **WHEN** a user copies multiple selected annotations and invokes paste twice on the same image
- **THEN** each invocation adds the full copied annotation count
- **AND** no live annotation object or persistent shape identity is shared between the two pasted batches

### Requirement: Clipboard templates remain reusable across images
The system SHALL retain copied annotation data across image navigation and SHALL materialize a fresh pasted batch for each target image without turning clipboard templates into Canvas-owned live objects.

#### Scenario: Paste after image navigation
- **WHEN** a user copies annotations, pastes them on one image, navigates to another image, and pastes again
- **THEN** both images receive independent pasted annotation objects
- **AND** the clipboard remains available after navigation
- **AND** each pasted annotation preserves the copied user-visible fields and grouping metadata while receiving a fresh persistent shape identity

### Requirement: Append operations preserve live-object uniqueness atomically
The system MUST reject an append request whose incoming annotations contain duplicate live object references or whose objects are already owned by the current Canvas, and it MUST do so before mutating the Canvas, label list, selection, backup, dirty state, or behavior-event count.

#### Scenario: Incoming batch repeats one live object
- **WHEN** an append request contains the same live annotation object more than once
- **THEN** the request fails before any annotation UI state changes
- **AND** no requested annotation is silently deduplicated

#### Scenario: Incoming object is already on the Canvas
- **WHEN** an append request contains a live annotation object already owned by the current Canvas
- **THEN** the request fails before any annotation UI state changes
- **AND** the existing Canvas snapshot remains unchanged

#### Scenario: Valid repeated paste reaches observers
- **WHEN** repeated paste requests contain fresh annotation objects
- **THEN** full-shape observers receive snapshots with unique live object references
- **AND** rectangle-size monitoring does not raise a duplicate-object exception

### Requirement: Existing copy semantics remain compatible
The system SHALL preserve existing annotation field-copy behavior, cross-image clipboard availability, label-list and Canvas reference alignment for each newly pasted annotation, and system-clipboard interoperability.

#### Scenario: Pasted annotation remains synchronized across views
- **WHEN** a valid paste adds an annotation
- **THEN** the label-list entry and Canvas entry refer to the same newly created live object
- **AND** changes made through either view remain visible through the other
