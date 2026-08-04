## 1. Regression Coverage

- [x] 1.1 Add a multi-rule end-to-end regression covering focus activation,
  anchor changes, and rule replacement without issue loss.
- [x] 1.2 Update Canvas notification expectations so focus-only visibility
  changes preserve base-visible rectangle-size issues.
- [x] 1.3 Add overlay assertions proving focus-excluded warnings remain
  paintable while base-hidden warnings remain suppressed.

## 2. Review Visibility Decoupling

- [x] 2.1 Rename the monitor visibility callback contract to review eligibility
  and update all repository callers without changing the candidate data field.
- [x] 2.2 Inject Canvas base visibility from the rectangle-size controller and
  update its adapter validation and test doubles.
- [x] 2.3 Change Canvas violation-overlay filtering to use base visibility while
  preserving focus-aware shape interaction.

## 3. Verification

- [x] 3.1 Run the targeted rectangle-size, Canvas notification, and three-box
  focus tests and resolve regressions.
- [x] 3.2 Run formatting, scoped lint/compile checks, and strict OpenSpec
  validation for the affected files and change artifacts.
- [x] 3.3 Review the final diff against the pre-existing dirty Canvas and
  LabelingWidget changes to confirm no user work was overwritten.
