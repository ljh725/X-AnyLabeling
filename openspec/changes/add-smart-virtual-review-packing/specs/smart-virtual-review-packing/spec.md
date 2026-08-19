## Purpose

Packs current-image virtual-review task units into deterministic editable pages that reduce navigation while preserving sufficient on-screen target size and separation for accurate annotation work.

## ADDED Requirements

### Requirement: Atomic review tasks remain indivisible
The system SHALL treat each first-stage virtual task as an atomic unit when producing review pages. All members of one grouped task SHALL appear on the same page, and every input task SHALL appear in exactly one output page.

#### Scenario: Grouped task is packed
- **WHEN** a task contains an anchor and multiple same-group members
- **THEN** the system places the complete task on one page and does not split its members across pages

#### Scenario: All tasks are covered
- **WHEN** smart packing completes successfully
- **THEN** every input task appears once and only once in the generated page list

### Requirement: Packing protects projected editing precision
The system SHALL combine tasks only when every page anchor remains at or above the configured minimum projected on-screen short-side size after fitting the page union bounding box into the current viewport.

#### Scenario: Candidate remains editable
- **WHEN** adding a task keeps every page anchor at or above the configured projected-size threshold
- **THEN** the candidate remains eligible for that page

#### Scenario: Candidate would become too small
- **WHEN** adding a task would make any page anchor smaller than the configured projected-size threshold
- **THEN** the system rejects that candidate from the page

#### Scenario: Viewport is invalid
- **WHEN** the viewport dimensions or required task geometry are unavailable or non-positive
- **THEN** the affected tasks are emitted as singleton pages instead of being discarded

### Requirement: Packing protects target separation
The system SHALL combine tasks only when the projected screen-space gap between every pair of atomic task bounding boxes on the page meets the configured minimum gap. Overlapping or excessively close task boxes SHALL not be combined.

#### Scenario: Candidate has sufficient separation
- **WHEN** a candidate meets the projected-size threshold and all projected pairwise gaps meet the configured minimum
- **THEN** the candidate remains eligible for that page

#### Scenario: Candidate overlaps another task
- **WHEN** a candidate task bounding box overlaps a task already assigned to the page
- **THEN** the system rejects the candidate from that page

### Requirement: Packing is deterministic and bounded
The system SHALL generate the same page membership and order for unchanged tasks, viewport dimensions, and packing options. A page SHALL NOT contain more atomic tasks than the configured maximum.

#### Scenario: Same input is rebuilt
- **WHEN** unchanged tasks are packed repeatedly with the same viewport and options
- **THEN** the system returns the same ordered pages and task membership

#### Scenario: Multiple candidates pass the hard gates
- **WHEN** more than one candidate can join the current page
- **THEN** the system selects candidates using a stable geometry score and original task order as the final tie-breaker

#### Scenario: Page reaches its task limit
- **WHEN** the current page contains the configured maximum number of task units
- **THEN** the system closes that page and continues with the remaining unassigned tasks

### Requirement: Users can choose packing density
The system SHALL provide single-task, balanced, and high-density modes. Single-task mode SHALL emit one atomic task per page; balanced mode SHALL default to at most two tasks per page; high-density mode SHALL default to at most three tasks per page. The effective maximum, minimum projected size, and minimum projected gap SHALL be visible and configurable before generation.

#### Scenario: Single-task mode is selected
- **WHEN** the user generates pages in single-task mode
- **THEN** the result is behaviorally equivalent to first-stage one-task-at-a-time review

#### Scenario: A density preset is selected
- **WHEN** the user selects balanced or high-density mode
- **THEN** the corresponding conservative option values populate the packing controls before generation

#### Scenario: Packing options are invalid
- **WHEN** the maximum task count is outside the supported range or a screen-space threshold is non-finite or negative
- **THEN** generation is rejected with a validation message and the current session remains unchanged

### Requirement: Review navigation operates on generated pages
The system SHALL navigate generated pages with the existing next and previous virtual-review actions. Every member of every task on the current page SHALL be normally visible and editable, while base-visible non-page shapes SHALL remain dim and non-interactive.

#### Scenario: A multi-task page is opened
- **WHEN** the current page contains two or more atomic tasks
- **THEN** all member shapes from those tasks are included in the Canvas virtual-focus predicate and the viewport fits their union bounding box

#### Scenario: User navigates to the next page
- **WHEN** the user invokes the existing F2 next action during an active session
- **THEN** the next generated page opens directly without a full-image intermediate state

#### Scenario: User navigates to the previous page
- **WHEN** the user invokes the existing Shift+F2 previous action during an active session
- **THEN** the previous generated page opens directly

### Requirement: Packing results remain stable during editing
The system SHALL freeze page membership and order until explicit regeneration or a successful image load. Edits to labels, group ids, or geometry SHALL not silently repack the active current-image session.

#### Scenario: A task member is edited
- **WHEN** an edit changes a criterion field or task geometry during an active page session
- **THEN** the generated page membership and order remain unchanged

#### Scenario: User explicitly regenerates
- **WHEN** the user requests regeneration after editing or changing packing options
- **THEN** the system rebuilds atomic tasks and pages using the current image, viewport, criteria, and options

### Requirement: Packing reports its result and falls back safely
The system SHALL display total atomic tasks, total pages, current page position, and current-page task count. Any task that cannot be safely combined SHALL remain available as a singleton page.

#### Scenario: Packing reduces page count
- **WHEN** compatible tasks are combined
- **THEN** the Inspector reports both the original task count and the smaller generated page count

#### Scenario: No candidate can be combined
- **WHEN** all remaining candidates fail the projected-size or separation gates
- **THEN** the seed task is emitted as a singleton page and packing continues

### Requirement: Smart packing remains transient and current-image scoped
The system SHALL NOT write page identifiers, packing options, or page membership into annotation JSON and SHALL NOT create physical split files or cross-file task queues.

#### Scenario: User edits and saves from a smart page
- **WHEN** the user saves annotations after editing page members
- **THEN** only normal annotation data is persisted through the existing save flow

#### Scenario: User changes image
- **WHEN** an active smart-packing session successfully loads another image
- **THEN** atomic tasks and pages are rebuilt for that image without carrying task membership across files
