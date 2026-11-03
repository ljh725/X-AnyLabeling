"""Scope guard for the shared editing commands imported into 4.2.1."""

import unittest

from anylabeling.views.labeling import editing_commands

EXPECTED_COMMANDS = ("apply_field_changes", "store_undo_step")
EXCLUDED_COMMANDS = (
    "delete_shapes",
    "group_shapes",
    "ungroup_shapes",
    "edit_fields",
    "edit_label",
    "duplicate_shapes",
    "union_shapes",
    "ensure_edit_baseline",
    "refresh_shape_metadata",
)


class TestEditingCommandScope(unittest.TestCase):
    """Keep the ported surface limited to what retained features need."""

    def test_field_patch_commands_are_available(self):
        for name in EXPECTED_COMMANDS:
            with self.subTest(name=name):
                self.assertTrue(
                    callable(getattr(editing_commands, name, None))
                )

    def test_excluded_commands_are_not_imported(self):
        for name in EXCLUDED_COMMANDS:
            with self.subTest(name=name):
                self.assertFalse(
                    hasattr(editing_commands, name),
                    f"{name} belongs to an excluded feature set",
                )

    def test_field_contract_matches_the_label_dialog(self):
        self.assertEqual(
            editing_commands.BATCH_FIELDS,
            (
                "label",
                "flags",
                "group_id",
                "description",
                "difficult",
                "kie_linking",
            ),
        )
        self.assertEqual(
            editing_commands.REVIEW_STATUS_FIELD, "review_status"
        )


if __name__ == "__main__":
    unittest.main()
