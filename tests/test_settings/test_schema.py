"""Validate settings coverage and optional rectangle workflow fields."""

import unittest

try:
    from anylabeling.views.labeling.settings.schema import (
        EXCLUDED_KEYS,
        SETTING_FIELDS,
        SETTINGS_KEYS,
        SETTINGS_GENERAL_KEYS,
        SETTINGS_SHAPE_KEYS,
        SETTINGS_PRIMARY_ORDER,
        SETTINGS_SHORTCUT_KEYS_CORE,
        defaults_map,
        fields_for_primary,
    )

    SCHEMA_AVAILABLE = True
except Exception:
    SCHEMA_AVAILABLE = False


@unittest.skipUnless(
    SCHEMA_AVAILABLE, "Settings schema dependencies are unavailable"
)
class TestSettingsSchema(unittest.TestCase):
    """Check settings schema invariants without brittle historical counts."""

    def test_field_count(self) -> None:
        """Every exposed field has a unique settings key."""
        keys = [field.key for field in SETTING_FIELDS]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(set(keys), set(SETTINGS_KEYS))

    def test_shortcut_and_non_shortcut_count(self) -> None:
        """Rectangle commands belong to the shortcut settings section."""
        shortcut_fields = [
            field for field in SETTING_FIELDS if field.primary == "Shortcuts"
        ]
        self.assertTrue(shortcut_fields)
        self.assertTrue(
            all(
                field.key.startswith("shortcuts.") for field in shortcut_fields
            )
        )
        self.assertIn(
            "shortcuts.rectangle_extreme", {f.key for f in shortcut_fields}
        )
        self.assertIn(
            "shortcuts.rectangle_next", {f.key for f in shortcut_fields}
        )

    def test_defaults_cover_all_keys(self) -> None:
        """Every exposed key has a template default."""
        defaults = defaults_map()
        self.assertEqual(set(defaults.keys()), set(SETTINGS_KEYS))

    def test_included_and_excluded_keys(self) -> None:
        """Required public settings exclude internal-only options."""
        expected_keys = {
            "display_label_popup",
            "auto_switch_to_edit_mode",
            "system_clipboard",
            "shape.line_color",
            "canvas.mask.opacity",
            "canvas.crosshair.show",
            "canvas.crosshair.width",
            "canvas.crosshair.color",
            "canvas.crosshair.opacity",
            "canvas.brush.point_distance",
            "auto_person_instance",
            "digit_shortcut_mode",
            "canvas_precision_mode",
            "canvas_precision_max_factor",
            "canvas_precision_factor",
            "model_hub",
            "logger_level",
            "shortcuts.open",
            "shortcuts.zoom_in",
            "shortcuts.add_point_to_edge",
            "shortcuts.quit",
            "shortcuts.open_settings",
            "shortcuts.auto_labeling_add_point",
            "shortcuts.auto_labeling_finish_object",
            "shortcuts.toggle_precision_mode_lock",
        }
        for key in expected_keys:
            self.assertIn(key, SETTINGS_KEYS)

        for key in EXCLUDED_KEYS:
            self.assertNotIn(key, SETTINGS_KEYS)

    def test_primary_and_key_sets(self) -> None:
        """Display groups and core keys remain available."""
        self.assertEqual(
            SETTINGS_PRIMARY_ORDER,
            ("Shortcuts", "General", "Shape", "Appearance", "Canvas"),
        )
        self.assertTrue(SETTINGS_GENERAL_KEYS)
        self.assertTrue(SETTINGS_SHAPE_KEYS)
        self.assertTrue(SETTINGS_SHORTCUT_KEYS_CORE)
        for key in SETTINGS_GENERAL_KEYS:
            self.assertIn(key, SETTINGS_KEYS)
        for key in SETTINGS_SHAPE_KEYS:
            self.assertIn(key, SETTINGS_KEYS)
        for key in SETTINGS_SHORTCUT_KEYS_CORE:
            self.assertIn(key, SETTINGS_KEYS)

    def test_fields_for_primary(self) -> None:
        """Fields are routed to the intended settings groups."""
        general_fields = fields_for_primary("General")
        shape_fields = fields_for_primary("Shape")
        shortcut_fields = fields_for_primary("Shortcuts")
        canvas_fields = fields_for_primary("Canvas")
        self.assertEqual(
            [field.key for field in general_fields],
            list(SETTINGS_GENERAL_KEYS),
        )
        self.assertEqual(
            [field.key for field in shape_fields], list(SETTINGS_SHAPE_KEYS)
        )
        shape_keys = {field.key for field in shape_fields}
        self.assertIn("shape.line_color", shape_keys)
        self.assertIn("shape.point_size", shape_keys)
        self.assertIn("shape.line_width", shape_keys)
        self.assertIn(
            "shortcuts.rectangle_refine",
            {field.key for field in shortcut_fields},
        )
        for key in SETTINGS_SHORTCUT_KEYS_CORE:
            self.assertIn(key, [field.key for field in shortcut_fields])
        self.assertIn(
            "rectangle_workflow.enabled", {f.key for f in canvas_fields}
        )
        canvas_keys = {field.key for field in canvas_fields}
        self.assertIn("canvas.crosshair.show", canvas_keys)
        self.assertIn("canvas.crosshair.width", canvas_keys)
        self.assertIn("canvas.crosshair.color", canvas_keys)
        self.assertIn("canvas.crosshair.opacity", canvas_keys)
        self.assertIn("canvas.brush.point_distance", canvas_keys)
        self.assertIn("canvas_precision_max_factor", canvas_keys)
        self.assertIn("canvas_precision_factor", canvas_keys)

    def test_visible_fields_have_labels_and_workflow_help(self) -> None:
        """New workflow settings provide readable labels and help."""
        fields = (
            fields_for_primary("General")
            + fields_for_primary("Shape")
            + fields_for_primary("Canvas")
        )
        self.assertTrue(all(field.label for field in fields))
        workflow = [
            f for f in fields if f.key.startswith("rectangle_workflow.")
        ]
        self.assertTrue(workflow)
        self.assertTrue(all(field.description for field in workflow))
