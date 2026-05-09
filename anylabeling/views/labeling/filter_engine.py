"""Shape filter execution engine.

Separates the *computation* of filter matches and
*application* of visibility from widget / UI code.
"""

from PyQt6 import QtCore

from .logger import logger


class ShapeFilterEngine:
    """Computes which items match a FilterState and syncs visibility.

    Accepts external references via callables to avoid coupling
    to the widget internals.
    """

    def __init__(
        self,
        label_list,              # LabelListWidget
        canvas,                  # Canvas
        get_label_info,          # callable -> dict
        update_select_toggle_tooltip=None,  # optional callable
    ):
        self._label_list = label_list
        self._canvas = canvas
        self._get_label_info = get_label_info
        self._update_select_toggle_tooltip = update_select_toggle_tooltip

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def compute_matches(self, filter_state, filter_index):
        """Return set of LabelListWidgetItems that match *filter_state*.

        Parameters
        ----------
        filter_state : FilterState
        filter_index : dict  (built by _rebuild_filter_index)

        Returns
        -------
        set of LabelListWidgetItem
        """
        if filter_index is None:
            return set()

        selected_labels = filter_state.labels
        current_gid = filter_state.gid
        current_type = filter_state.shape_type
        idx = filter_index

        # --- narrow by most-restrictive criterion ---
        candidates = None
        if selected_labels:
            candidate_list = []
            for lbl in selected_labels:
                if lbl in idx["label"]:
                    candidate_list.extend(idx["label"][lbl])
            candidates = set(candidate_list)
        elif current_type:
            if current_type in idx["shape_type"]:
                candidates = set(idx["shape_type"][current_type])
        elif current_gid != "-1":
            if current_gid in idx["gid"]:
                candidates = set(idx["gid"][current_gid])

        if candidates is None:
            candidates = set(idx["all"])

        # --- second pass: apply remaining conditions + label_info ---
        label_info = self._get_label_info()
        matched = set()
        for item in candidates:
            try:
                shape = item.shape()
            except RuntimeError:
                continue
            if current_gid != "-1" and str(shape.group_id) != str(current_gid):
                continue
            if current_type and shape.shape_type != current_type:
                continue
            if selected_labels and shape.label not in selected_labels:
                continue
            # Respect per-label visibility toggle
            if not label_info.get(shape.label, {}).get("visible", True):
                continue
            matched.add(item)
        return matched

    def sync_label_list_visibility(self, get_visible):
        """Walk *label_list*, calling *get_visible(item)→bool*, and set
        item.checkState / shape.visible / canvas.visible accordingly.

        Returns
        -------
        (visible_count: int, changed: bool)
        """
        model = self._label_list.model()
        blocker = QtCore.QSignalBlocker(model)
        self._label_list.setUpdatesEnabled(False)
        visible_count = 0
        changed = False
        try:
            logger.info(
                "[DIAG] sync_label_list_visibility ENTER | item_count=%d",
                model.rowCount(),
            )
            for idx, item in enumerate(self._label_list):
                prev_check = item.checkState()
                shape = item.shape()
                prev_visible = shape.visible if shape else None

                is_visible = bool(get_visible(item))
                if is_visible:
                    visible_count += 1

                check_state = (
                    QtCore.Qt.CheckState.Checked
                    if is_visible
                    else QtCore.Qt.CheckState.Unchecked
                )
                logger.info(
                    "[DIAG] sync_label_list_visibility ITEM[%d] | label=%s | prev_check=%s | is_vis=%s | target_check=%s | prev_shape_vis=%s",
                    idx,
                    shape.label if shape else "N/A",
                    "Checked" if prev_check == QtCore.Qt.CheckState.Checked else "Unchecked",
                    is_visible,
                    "Checked" if check_state == QtCore.Qt.CheckState.Checked else "Unchecked",
                    prev_visible,
                )
                if item.checkState() != check_state:
                    logger.warning(
                        "[DIAG] sync_label_list_visibility CHANGED CHECK | ITEM[%d] %s: %s -> %s",
                        idx,
                        shape.label if shape else "N/A",
                        "Checked" if prev_check == QtCore.Qt.CheckState.Checked else "Unchecked",
                        "Checked" if check_state == QtCore.Qt.CheckState.Checked else "Unchecked",
                    )
                    item.setCheckState(check_state)
                    changed = True
                if shape.visible != is_visible:
                    logger.warning(
                        "[DIAG] sync_label_list_visibility CHANGED VISIBLE | ITEM[%d] %s: %s -> %s",
                        idx,
                        shape.label if shape else "N/A",
                        prev_visible,
                        is_visible,
                    )
                    changed = True
                shape.visible = is_visible
                self._canvas.visible[shape] = is_visible
        finally:
            self._label_list.setUpdatesEnabled(True)
            del blocker

        logger.info(
            "[DIAG] sync_label_list_visibility EXIT | visible_count=%d | changed=%s",
            visible_count,
            changed,
        )
        if self._update_select_toggle_tooltip:
            self._update_select_toggle_tooltip()
        return visible_count, changed

    def apply_label_visibility(self):
        """Apply per-label-type visibility from label_info."""
        _, changed = self.sync_label_list_visibility(
            lambda item: self._get_label_info()
            .get(item.shape().label, {})
            .get("visible", True)
        )
        return changed
