from anylabeling.views.labeling.widgets.appearance import (
    IsolationState,
    derive_isolation_state,
)


class _Shape:
    def __init__(self, token, group_id=None):
        self.shape_token = token
        self.group_id = group_id


def test_single_group_isolates_all_group_members():
    state = derive_isolation_state("image-a", [_Shape("a", 7)])
    assert state == IsolationState(
        image_token="image-a", enabled=True, focused_group_id=7
    )
    assert state.allows(_Shape("other", 7))
    assert not state.allows(_Shape("other", 8))


def test_mixed_and_ungrouped_selection_uses_exact_tokens():
    selected = [_Shape("a", 7), _Shape("b", 8), _Shape("c")]
    state = derive_isolation_state("image-a", selected)
    assert state.focused_group_id is None
    assert state.selected_shape_tokens == ("a", "b", "c")
    assert state.allows(_Shape("a", 99))
    assert not state.allows(_Shape("other", 7))


def test_disabled_or_empty_selection_is_noop():
    assert not derive_isolation_state("image-a", [], enabled=True).enabled
    assert not derive_isolation_state(
        "image-a", [_Shape("a", 1)], enabled=False
    ).enabled
