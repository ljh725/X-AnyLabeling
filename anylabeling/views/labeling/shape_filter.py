"""Pure rules combining label/group filters with manual visibility.

Native 4.2.1 applies either the label filter or the group filter, whichever
wins in ``_refresh_shape_filters``. These helpers combine both criteria,
support inverting the combined result, and keep a shape the user hid by hand
hidden no matter what the filter says.
"""

NO_GROUP_FILTER = "-1"


def has_active_filter(label="", gid=NO_GROUP_FILTER):
    """Return whether a label or group filter is currently set."""
    return bool(label) or str(gid) not in ("", NO_GROUP_FILTER)


def matches_filter(shape, label="", gid=NO_GROUP_FILTER):
    """Return whether one shape satisfies every active filter criterion."""
    if label and getattr(shape, "label", "") != label:
        return False
    if str(gid) not in ("", NO_GROUP_FILTER):
        group_id = getattr(shape, "group_id", None)
        if group_id is None or str(group_id) != str(gid):
            return False
    return True


def desired_visibility(
    shape,
    label="",
    gid=NO_GROUP_FILTER,
    label_visible=True,
    invert=False,
    manually_hidden=False,
):
    """Resolve the visible state for one shape.

    Manual hides win over every filter; per-label visibility wins over the
    filter result; the invert flag only applies while a filter is active.
    """
    if manually_hidden or not label_visible:
        return False
    if not has_active_filter(label, gid):
        return True
    matched = matches_filter(shape, label, gid)
    return not matched if invert else matched
