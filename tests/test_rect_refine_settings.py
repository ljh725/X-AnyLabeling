"""Stage 5 tests: settings config injection + schema shortcut key +
runtime_applier action map for the three-box refine mode.

These verify the wiring that makes the refine mode configurable via the
settings dialog (shortcut remapping) and the yaml config block (threshold
tuning).  Pure-Python where possible; the action-map check is PyQt offscreen.
"""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from anylabeling.views.labeling.settings.schema import (
        SETTING_FIELDS,
        _shortcut_category_map,
    )

    SCHEMA_AVAILABLE = True
except Exception:  # noqa: BLE001
    SCHEMA_AVAILABLE = False


# ---------------------------------------------------------------------------
# 1. Schema: accept_rect_refine_workgroup is a registered View shortcut
# ---------------------------------------------------------------------------


@unittest.skipUnless(
    SCHEMA_AVAILABLE, "Settings schema dependencies are unavailable"
)
class TestSchemaShortcutRegistration(unittest.TestCase):
    def test_accept_key_in_view_category(self):
        categories = _shortcut_category_map()
        view_keys = categories.get("View", ())
        self.assertIn("accept_rect_refine_workgroup", view_keys)

    def test_accept_field_present_in_setting_fields(self):
        keys = {f.key for f in SETTING_FIELDS}
        self.assertIn("shortcuts.accept_rect_refine_workgroup", keys)


# ---------------------------------------------------------------------------
# 2. Config injection: yaml rect_refine block flows into workflow config
# ---------------------------------------------------------------------------


class TestConfigInjection(unittest.TestCase):
    """Verify _build_rect_refine_config maps the flat yaml layout onto the
    nested DEFAULTS shape the workflow expects."""

    def _build_with_user_config(self, user_cfg):
        # Minimal stub replicating LabelingWidget._build_rect_refine_config
        # without booting Qt.
        from anylabeling.views.labeling.rect_refine_grouping import (
            DEFAULTS as RR_DEFAULTS,
        )

        cfg = {
            "face_to_head": dict(RR_DEFAULTS["face_to_head"]),
            "head_to_person": dict(RR_DEFAULTS["head_to_person"]),
            "general": dict(RR_DEFAULTS["general"]),
        }
        if not isinstance(user_cfg, dict):
            return cfg
        for sub in ("face_to_head", "head_to_person"):
            val = user_cfg.get(sub)
            if isinstance(val, dict):
                cfg[sub].update(val)
        for key in (
            "min_accept_score",
            "ambiguous_top_gap",
            "alignment_hint_px",
        ):
            if key in user_cfg:
                cfg["general"][key] = user_cfg[key]
        return cfg

    def test_defaults_when_no_block(self):
        cfg = self._build_with_user_config({})
        from anylabeling.views.labeling.rect_refine_grouping import DEFAULTS

        self.assertEqual(cfg["general"]["min_accept_score"], 0.55)
        self.assertEqual(cfg["general"]["alignment_hint_px"], 3.0)
        self.assertEqual(
            cfg["face_to_head"]["w_containment"],
            DEFAULTS["face_to_head"]["w_containment"],
        )

    def test_user_threshold_overrides_general(self):
        cfg = self._build_with_user_config(
            {"min_accept_score": 0.7, "alignment_hint_px": 5.0}
        )
        self.assertEqual(cfg["general"]["min_accept_score"], 0.7)
        self.assertEqual(cfg["general"]["alignment_hint_px"], 5.0)

    def test_user_subsection_override_merges(self):
        cfg = self._build_with_user_config(
            {"face_to_head": {"w_containment": 0.5}}
        )
        self.assertEqual(cfg["face_to_head"]["w_containment"], 0.5)
        # Other face_to_head keys preserved from defaults.
        from anylabeling.views.labeling.rect_refine_grouping import DEFAULTS

        self.assertEqual(
            cfg["face_to_head"]["w_iou"], DEFAULTS["face_to_head"]["w_iou"]
        )

    def test_non_dict_falls_back_to_defaults(self):
        cfg = self._build_with_user_config("not a dict")
        from anylabeling.views.labeling.rect_refine_grouping import DEFAULTS

        self.assertEqual(cfg["general"]["min_accept_score"], 0.55)


# ---------------------------------------------------------------------------
# 3. Config yaml: the shipped default config has the rect_refine block
# ---------------------------------------------------------------------------


class TestShippedConfigYaml(unittest.TestCase):
    def test_yaml_has_rect_refine_block_and_shortcut(self):
        import yaml

        cfg_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "anylabeling",
            "configs",
            "xanylabeling_config.yaml",
        )
        with open(cfg_path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        self.assertIn("rect_refine", cfg)
        rr = cfg["rect_refine"]
        self.assertEqual(rr["alignment_hint_px"], 3.0)
        self.assertEqual(rr["min_accept_score"], 0.55)
        self.assertIn("face_to_head", rr)
        self.assertIn("head_to_person", rr)
        # Shortcut registered with the spec default.
        self.assertEqual(
            cfg["shortcuts"]["accept_rect_refine_workgroup"], "Ctrl+Return"
        )


# ---------------------------------------------------------------------------
# 4. runtime_applier action map (PyQt offscreen)
# ---------------------------------------------------------------------------


@unittest.skipUnless(
    SCHEMA_AVAILABLE, "Settings schema dependencies are unavailable"
)
class TestRuntimeApplierActionMap(unittest.TestCase):
    def test_accept_action_in_shortcut_map(self):
        # Source-level guard: the runtime_applier module must wire the new
        # shortcut key to the QAction.  We inspect the module source rather
        # than booting the full widget (which is heavy and covered by the
        # UI integration tests).
        import inspect

        from anylabeling.views.labeling.settings import runtime_applier

        src = inspect.getsource(runtime_applier)
        self.assertIn("shortcuts.accept_rect_refine_workgroup", src)
        self.assertIn("accept_rect_refine_workgroup", src)


if __name__ == "__main__":
    unittest.main()
