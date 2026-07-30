"""Configuration cleanup tests for lightweight three-box focus."""

from __future__ import annotations

import copy
import inspect
import os
import unittest

import yaml

from anylabeling.config import update_dict, validate_config_item
from anylabeling.views.labeling.rect_refine_types import (
    DEFAULT_RECT_REFINE_LABEL_ROLES,
    parse_rect_refine_label_roles,
)

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
    def _load_config(self) -> dict:
        """Load a new copy of the shipped YAML configuration."""
        cfg_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "anylabeling",
            "configs",
            "xanylabeling_config.yaml",
        )
        with open(cfg_path, encoding="utf-8") as stream:
            return yaml.safe_load(stream)

    def test_yaml_has_only_label_role_focus_config(self):
        config = self._load_config()
        rect_refine = config["rect_refine"]

        self.assertEqual(
            rect_refine,
            {
                "label_roles": {
                    "body": ["person", "halfperson"],
                    "head": ["head"],
                    "face": ["face"],
                }
            },
        )
        self.assertNotIn(
            "accept_rect_refine_workgroup",
            config["shortcuts"],
        )

    def test_partial_user_override_keeps_other_default_roles(self):
        config = self._load_config()
        user_config = {
            "rect_refine": {
                "label_roles": {
                    "body": ["person", "upper_body"],
                }
            }
        }

        update_dict(
            config,
            copy.deepcopy(user_config),
            validate_item=validate_config_item,
        )
        roles = parse_rect_refine_label_roles(config["rect_refine"])

        self.assertEqual(roles.body, frozenset(("person", "upper_body")))
        self.assertEqual(roles.head, frozenset(("head",)))
        self.assertEqual(roles.face, frozenset(("face",)))


class TestLabelRoleParsing(unittest.TestCase):
    def test_missing_config_uses_shipped_roles(self):
        roles = parse_rect_refine_label_roles(None)

        self.assertEqual(roles, DEFAULT_RECT_REFINE_LABEL_ROLES)
        self.assertIn("halfperson", roles.body)

    def test_invalid_role_uses_its_default(self):
        roles = parse_rect_refine_label_roles(
            {
                "label_roles": {
                    "body": "person",
                    "head": ["custom_head"],
                }
            }
        )

        self.assertEqual(
            roles.body,
            DEFAULT_RECT_REFINE_LABEL_ROLES.body,
        )
        self.assertEqual(roles.head, frozenset(("custom_head",)))

    def test_overlapping_roles_use_all_defaults(self):
        roles = parse_rect_refine_label_roles(
            {
                "label_roles": {
                    "body": ["person"],
                    "head": ["person"],
                    "face": ["face"],
                }
            }
        )

        self.assertEqual(roles, DEFAULT_RECT_REFINE_LABEL_ROLES)


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
