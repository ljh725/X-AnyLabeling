"""Pure-Python helpers for persistent Shape identity invariants."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Literal, Optional

SHAPE_ID_FIELD = "xanylabeling_shape_id"
MISSING_SHAPE_ID = object()
ShapeIdentityIssueReason = Literal["missing", "invalid", "duplicate"]


@dataclass(frozen=True)
class ShapeIdentityDiagnostic:
    """Describe one missing, invalid, or duplicate Shape identity."""

    reason: ShapeIdentityIssueReason
    index: int
    original_id: Any
    assigned_id: Optional[str] = None
    first_index: Optional[int] = None


@dataclass(frozen=True)
class ShapeIdentityNormalizationResult:
    """Return normalized identities and the repairs that produced them."""

    identities: tuple[str, ...]
    diagnostics: tuple[ShapeIdentityDiagnostic, ...]

    @property
    def repaired_count(self) -> int:
        """Return the number of identities replaced during normalization."""
        return len(self.diagnostics)


def new_shape_id() -> str:
    """Return a random UUID4 identity in lowercase hexadecimal form."""
    return uuid.uuid4().hex


def normalize_shape_identities(
    identities: Iterable[Any],
    *,
    reserved_ids: Iterable[str] = (),
    id_factory: Callable[[], str] = new_shape_id,
) -> ShapeIdentityNormalizationResult:
    """Normalize identities while preserving the first valid occurrence.

    Args:
        identities: Serialized or runtime identity values in Shape order.
        reserved_ids: Valid identities already owned by another collection.
        id_factory: Callable used to allocate replacement identities.

    Returns:
        Ordered normalized identities plus structured repair diagnostics.
    """
    values = tuple(identities)
    claimed: dict[str, Optional[int]] = {
        value: None
        for value in reserved_ids
        if isinstance(value, str) and value
    }
    unavailable = set(claimed)
    unavailable.update(
        value for value in values if isinstance(value, str) and value
    )
    normalized = []
    diagnostics = []

    for index, value in enumerate(values):
        reason: Optional[ShapeIdentityIssueReason] = None
        first_index: Optional[int] = None
        if value is MISSING_SHAPE_ID:
            reason = "missing"
        elif not isinstance(value, str) or not value:
            reason = "invalid"
        elif value in claimed:
            reason = "duplicate"
            first_index = claimed[value]

        if reason is None:
            assigned_id = value
        else:
            assigned_id = _generate_unique_shape_id(unavailable, id_factory)
            diagnostics.append(
                ShapeIdentityDiagnostic(
                    reason=reason,
                    index=index,
                    original_id=value,
                    assigned_id=assigned_id,
                    first_index=first_index,
                )
            )

        normalized.append(assigned_id)
        claimed[assigned_id] = index
        unavailable.add(assigned_id)

    return ShapeIdentityNormalizationResult(
        identities=tuple(normalized),
        diagnostics=tuple(diagnostics),
    )


def validate_shape_identities(
    identities: Iterable[Any],
) -> tuple[ShapeIdentityDiagnostic, ...]:
    """Return identity invariant violations without modifying any value."""
    claimed: dict[str, int] = {}
    diagnostics = []
    for index, value in enumerate(identities):
        if value is MISSING_SHAPE_ID:
            diagnostics.append(
                ShapeIdentityDiagnostic("missing", index, value)
            )
            continue
        if not isinstance(value, str) or not value:
            diagnostics.append(
                ShapeIdentityDiagnostic("invalid", index, value)
            )
            continue
        if value in claimed:
            diagnostics.append(
                ShapeIdentityDiagnostic(
                    "duplicate",
                    index,
                    value,
                    first_index=claimed[value],
                )
            )
            continue
        claimed[value] = index
    return tuple(diagnostics)


def describe_shape_identity_diagnostics(
    diagnostics: Iterable[ShapeIdentityDiagnostic],
) -> str:
    """Render identity diagnostics as a concise operator-facing message."""
    parts = []
    for diagnostic in diagnostics:
        if diagnostic.reason == "duplicate":
            detail = (
                f"shape[{diagnostic.index}] duplicate id "
                f"{diagnostic.original_id!r} first used by "
                f"shape[{diagnostic.first_index}]"
            )
        elif diagnostic.reason == "missing":
            detail = f"shape[{diagnostic.index}] missing id"
        else:
            detail = (
                f"shape[{diagnostic.index}] invalid id "
                f"{diagnostic.original_id!r}"
            )
        if diagnostic.assigned_id is not None:
            detail += f" -> {diagnostic.assigned_id}"
        parts.append(detail)
    return "; ".join(parts)


def _generate_unique_shape_id(
    unavailable: set[str],
    id_factory: Callable[[], str],
) -> str:
    """Generate a valid identity not present in the claimed collection."""
    for _attempt in range(1024):
        candidate = id_factory()
        if (
            isinstance(candidate, str)
            and candidate
            and candidate not in unavailable
        ):
            return candidate
    raise RuntimeError("Unable to generate a unique Shape identity")
