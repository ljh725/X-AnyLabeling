"""Filter state management with normalization for label/gid/shape_type filtering."""


class FilterState:
    """Immutable-like state for shape filter criteria.

    All setters normalize inputs so that empty/None gid becomes "-1",
    and empty labels become set().
    """

    DEFAULT_GID = "-1"
    DEFAULT_TYPE = ""

    def __init__(self, labels=None, gid=None, shape_type=None):
        self.labels: set = labels if labels is not None else set()
        self.gid: str = self._normalize_gid(gid)
        self.shape_type: str = shape_type or self.DEFAULT_TYPE

    # ------------------------------------------------------------------
    # Normalization helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _normalize_gid(gid):
        if gid is None or gid == "":
            return FilterState.DEFAULT_GID
        return str(gid)

    # ------------------------------------------------------------------
    # Setters (always normalize)
    # ------------------------------------------------------------------
    def set_labels(self, labels):
        self.labels = set(labels) if labels else set()

    def set_gid(self, gid):
        self.gid = self._normalize_gid(gid)

    def set_shape_type(self, shape_type):
        self.shape_type = shape_type or self.DEFAULT_TYPE

    def reset(self):
        """Reset to default (no active filter)."""
        self.labels = set()
        self.gid = self.DEFAULT_GID
        self.shape_type = self.DEFAULT_TYPE

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------
    def has_active_filter(self) -> bool:
        return (
            bool(self.labels)
            or self.gid != self.DEFAULT_GID
            or self.shape_type != self.DEFAULT_TYPE
        )

    # ------------------------------------------------------------------
    # Serialization helpers (used by pending restore)
    # ------------------------------------------------------------------
    def copy(self) -> "FilterState":
        """Return a deep clone."""
        return FilterState(
            labels=set(self.labels),
            gid=self.gid,
            shape_type=self.shape_type,
        )

    def to_dict(self) -> dict:
        return {
            "labels": set(self.labels),
            "gid": self.gid,
            "shape_type": self.shape_type,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "FilterState":
        return cls(
            labels=d.get("labels", set()),
            gid=d.get("gid", cls.DEFAULT_GID),
            shape_type=d.get("shape_type", cls.DEFAULT_TYPE),
        )

    def __repr__(self):
        return (
            f"FilterState(labels={self.labels!r}, "
            f"gid={self.gid!r}, shape_type={self.shape_type!r})"
        )
