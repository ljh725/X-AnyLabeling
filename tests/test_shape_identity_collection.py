"""Pure-Python tests for file-level Shape identity invariants."""

import uuid

from anylabeling.views.labeling.shape_identity import (
    MISSING_SHAPE_ID,
    new_shape_id,
    normalize_shape_identities,
    validate_shape_identities,
)


def test_generated_identity_is_uuid4_hex():
    """Generated identities use the documented UUID4 hex representation."""
    identity = new_shape_id()

    parsed = uuid.UUID(hex=identity)
    assert len(identity) == 32
    assert parsed.version == 4


def test_normalization_preserves_historical_non_uuid_identity():
    """Any non-empty historical string remains a valid identity."""
    result = normalize_shape_identities(["legacy-shape-name"])

    assert result.identities == ("legacy-shape-name",)
    assert result.diagnostics == ()


def test_normalization_classifies_missing_invalid_and_duplicate_values():
    """Each repair reason remains visible in structured diagnostics."""
    replacements = iter(("new-a", "new-b", "new-c"))
    result = normalize_shape_identities(
        [MISSING_SHAPE_ID, None, "kept", "kept"],
        id_factory=lambda: next(replacements),
    )

    assert result.identities == ("new-a", "new-b", "kept", "new-c")
    assert [item.reason for item in result.diagnostics] == [
        "missing",
        "invalid",
        "duplicate",
    ]
    assert result.diagnostics[-1].first_index == 2


def test_normalization_retries_factory_collisions():
    """Replacement allocation retries reserved and newly claimed values."""
    candidates = iter(("reserved", "kept", "fresh"))
    result = normalize_shape_identities(
        [MISSING_SHAPE_ID, "kept"],
        reserved_ids=("reserved",),
        id_factory=lambda: next(candidates),
    )

    assert result.identities == ("fresh", "kept")


def test_validation_is_read_only_and_reports_positions():
    """Validation reports every invariant violation without replacements."""
    diagnostics = validate_shape_identities(
        ["first", MISSING_SHAPE_ID, "", 7, "first"]
    )

    assert [item.reason for item in diagnostics] == [
        "missing",
        "invalid",
        "invalid",
        "duplicate",
    ]
    assert diagnostics[-1].index == 4
    assert diagnostics[-1].first_index == 0
    assert all(item.assigned_id is None for item in diagnostics)


def test_large_unique_collection_preserves_order_without_repairs():
    """A representative large collection completes as one ordered scan."""
    identities = [f"shape-{index}" for index in range(10000)]

    result = normalize_shape_identities(identities)

    assert result.identities == tuple(identities)
    assert result.repaired_count == 0
