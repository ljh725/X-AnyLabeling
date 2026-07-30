"""Configuration cleanup tests for lightweight three-box focus."""

from __future__ import annotations

import inspect
import os
import unittest

import yaml

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from anylabeling.views.labeling.settings.schema import (
        SETTING_FIELDS,
        _shortcut_category_map,
    )

    SCHEMA_AVAILABLE = True
except Exception:  # noqa: BLE001
    SCHEMA_AVAILABLE = False


@unittest.skipUnless(
    SCHEMA_AVAILABLE, "Settings schema dependencies are unavailable"
)
class TestSchemaShortcutRegistration(unittest.TestCase):
    def test_accept_key_not_in_view_category(self):
        categories = _shortcut_category_map()
        self.assertNotIn(
            "accept_rect_refine_workgroup",
            categories.get("View", ()),
        )

    def test_accept_field_not_in_setting_fields(self):
        keys = {field.key for field in SETTING_FIELDS}
        self.assertNotIn("shortcuts.accept_rect_refine_workgroup", keys)


class TestShippedConfigYaml(unittest.TestCase):
    def test_yaml_has_no_scoring_or_accept_config(self):
        cfg_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "anylabeling",
            "configs",
            "xanylabeling_config.yaml",
        )
        with open(cfg_path, encoding="utf-8") as stream:
            config = yaml.safe_load(stream)

        self.assertNotIn("rect_refine", config)
        self.assertNotIn(
            "accept_rect_refine_workgroup",
            config["shortcuts"],
        )


@unittest.skipUnless(
    SCHEMA_AVAILABLE, "Settings schema dependencies are unavailable"
)
class TestRuntimeApplierActionMap(unittest.TestCase):
    def test_accept_action_not_in_shortcut_map(self):
        from anylabeling.views.labeling.settings import runtime_applier

        source = inspect.getsource(runtime_applier)
        self.assertNotIn("shortcuts.accept_rect_refine_workgroup", source)
        self.assertNotIn("accept_rect_refine_workgroup", source)


if __name__ == "__main__":
    unittest.main()
