import json
import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
ENGINE_PATH = (
    ROOT_DIR / "anylabeling/views/labeling/filter_navigation_engine.py"
)
STATE_PATH = ROOT_DIR / "anylabeling/views/labeling/filter_state.py"

ENGINE_SPEC = importlib.util.spec_from_file_location(
    "filter_navigation_engine_module", ENGINE_PATH
)
ENGINE_MODULE = importlib.util.module_from_spec(ENGINE_SPEC)
ENGINE_SPEC.loader.exec_module(ENGINE_MODULE)

STATE_SPEC = importlib.util.spec_from_file_location(
    "filter_state_module", STATE_PATH
)
STATE_MODULE = importlib.util.module_from_spec(STATE_SPEC)
STATE_SPEC.loader.exec_module(STATE_MODULE)

FilterNavigationEngine = ENGINE_MODULE.FilterNavigationEngine
FilterState = STATE_MODULE.FilterState


class TestFilterNavigationEngine(unittest.TestCase):

    @staticmethod
    def _write_label(path, shapes):
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"shapes": shapes}, f)

    # ------------------------------------------------------------------
    # collect_matched_files
    # ------------------------------------------------------------------

    def test_label_filters_use_or_within_label_set(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            image_a = str(Path(temp_dir) / "a.jpg")
            image_b = str(Path(temp_dir) / "b.jpg")
            image_c = str(Path(temp_dir) / "c.jpg")
            self._write_label(
                Path(temp_dir) / "a.json",
                [{"label": "person", "shape_type": "rectangle"}],
            )
            self._write_label(
                Path(temp_dir) / "b.json",
                [{"label": "car", "shape_type": "polygon"}],
            )
            self._write_label(
                Path(temp_dir) / "c.json",
                [{"label": "dog", "shape_type": "rectangle"}],
            )

            engine = FilterNavigationEngine()
            state = FilterState(labels={"person", "car"})

            self.assertEqual(
                engine.collect_matched_files(
                    [image_a, image_b, image_c], state
                ),
                [image_a, image_b],
            )

    def test_label_gid_and_type_conditions_are_anded(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            image_a = str(Path(temp_dir) / "a.jpg")
            image_b = str(Path(temp_dir) / "b.jpg")
            image_c = str(Path(temp_dir) / "c.jpg")
            self._write_label(
                Path(temp_dir) / "a.json",
                [{"label": "person", "group_id": 1, "shape_type": "rectangle"}],
            )
            self._write_label(
                Path(temp_dir) / "b.json",
                [{"label": "person", "group_id": 2, "shape_type": "rectangle"}],
            )
            self._write_label(
                Path(temp_dir) / "c.json",
                [{"label": "car", "group_id": 1, "shape_type": "polygon"}],
            )

            engine = FilterNavigationEngine()
            state = FilterState(
                labels={"person", "car"}, gid="1", shape_type="rectangle"
            )

            self.assertEqual(
                engine.collect_matched_files(
                    [image_a, image_b, image_c], state
                ),
                [image_a],
            )

    def test_any_shape_match_makes_file_match(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            image = str(Path(temp_dir) / "a.jpg")
            self._write_label(
                Path(temp_dir) / "a.json",
                [
                    {"label": "dog", "shape_type": "rectangle"},
                    {"label": "person", "shape_type": "polygon"},
                ],
            )

            engine = FilterNavigationEngine()
            state = FilterState(labels={"person"})

            self.assertTrue(engine.file_matches_filter(image, state))

    def test_missing_or_invalid_json_does_not_match(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            missing_image = str(Path(temp_dir) / "missing.jpg")
            invalid_image = str(Path(temp_dir) / "invalid.jpg")
            with open(
                Path(temp_dir) / "invalid.json", "w", encoding="utf-8"
            ) as f:
                f.write("{")

            engine = FilterNavigationEngine()
            state = FilterState(labels={"person"})

            self.assertEqual(
                engine.collect_matched_files(
                    [missing_image, invalid_image], state
                ),
                [],
            )

    def test_output_dir_is_used_for_label_files(self):
        with tempfile.TemporaryDirectory() as image_dir:
            with tempfile.TemporaryDirectory() as output_dir:
                image = str(Path(image_dir) / "a.jpg")
                self._write_label(
                    Path(output_dir) / "a.json",
                    [{"label": "person", "shape_type": "rectangle"}],
                )

                engine = FilterNavigationEngine()
                state = FilterState(labels={"person"})

                self.assertEqual(
                    engine.collect_matched_files(
                        [image], state, output_dir=output_dir
                    ),
                    [image],
                )

    # ------------------------------------------------------------------
    # shapes_match_filter
    # ------------------------------------------------------------------

    def test_shapes_match_filter_with_dict_shapes(self):
        engine = FilterNavigationEngine()
        state = FilterState(labels={"person"})
        shapes = [
            {"label": "dog", "shape_type": "rectangle"},
            {"label": "person", "shape_type": "polygon"},
        ]
        self.assertTrue(engine.shapes_match_filter(shapes, state))

    def test_shapes_match_filter_returns_false_when_no_match(self):
        engine = FilterNavigationEngine()
        state = FilterState(labels={"person", "car"}, gid="1")
        shapes = [
            {"label": "dog", "group_id": 1},
            {"label": "cat", "group_id": 1},
        ]
        self.assertFalse(engine.shapes_match_filter(shapes, state))


if __name__ == "__main__":
    unittest.main()
