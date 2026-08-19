"""Regression tests for the settings page registry."""

from anylabeling.views.labeling.settings.schema import (
    SETTINGS_PRIMARY_ORDER,
    fields_for_primary,
)


def test_appearance_settings_page_is_registered() -> None:
    """Expose annotation appearance fields in the settings navigation."""
    assert "Appearance" in SETTINGS_PRIMARY_ORDER

    fields = fields_for_primary("Appearance")

    assert fields
    assert all(field.primary == "Appearance" for field in fields)
    assert {field.key for field in fields} >= {
        "annotation_appearance.color_mode",
        "annotation_appearance.show_labels",
        "annotation_appearance.show_gid",
    }
