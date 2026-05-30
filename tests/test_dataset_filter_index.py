import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
MODULE_PATH = (
    ROOT_DIR / "anylabeling/views/labeling/dataset_filter_index.py"
)

MODULE_SPEC = importlib.util.spec_from_file_location(
    "dataset_filter_index_module", MODULE_PATH
)
MODULE = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(MODULE)

DatasetFilterIndex = MODULE.DatasetFilterIndex


class TestDatasetFilterIndex(unittest.TestCase):

    @staticmethod
    def _touch(path: Path) -> None:
        path.write_bytes(b"")

    @staticmethod
    def _write_label(path: Path, label: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "shapes": [
                        {"label": label, "shape_type": "rectangle"}
                    ]
                },
                f,
            )

    def test_refresh_file_updates_existing_row_when_output_dir_changes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            image_dir = root / "images"
            old_output_dir = root / "labels_old"
            new_output_dir = root / "labels_new"
            image_dir.mkdir()
            old_output_dir.mkdir()
            new_output_dir.mkdir()

            image_path = image_dir / "sample.jpg"
            old_json_path = old_output_dir / "sample.json"
            new_json_path = new_output_dir / "sample.json"
            self._touch(image_path)
            self._write_label(old_json_path, "old")
            self._write_label(new_json_path, "new")

            index = DatasetFilterIndex(":memory:")
            self.assertTrue(index.open())
            index.rebuild([str(image_path)], output_dir=str(old_output_dir))

            index.refresh_file(str(image_path), output_dir=str(new_output_dir))

            rows = index._conn.execute(
                "SELECT image_path, json_path, shape_count FROM files"
            ).fetchall()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0][0], str(image_path))
            self.assertEqual(rows[0][1], str(new_json_path))
            self.assertEqual(rows[0][2], 1)

            shape_rows = index._conn.execute(
                "SELECT label FROM shapes"
            ).fetchall()
            self.assertEqual(shape_rows, [("new",)])
            index.close()

    def test_refresh_file_does_not_raise_unique_error_after_output_dir_change(
        self,
    ):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            image_dir = root / "images"
            old_output_dir = root / "labels_old"
            new_output_dir = root / "labels_new"
            image_dir.mkdir()
            old_output_dir.mkdir()
            new_output_dir.mkdir()

            image_path = image_dir / "sample.jpg"
            old_json_path = old_output_dir / "sample.json"
            new_json_path = new_output_dir / "sample.json"
            self._touch(image_path)
            self._write_label(old_json_path, "old")
            self._write_label(new_json_path, "new")

            index = DatasetFilterIndex(":memory:")
            self.assertTrue(index.open())
            index.rebuild([str(image_path)], output_dir=str(old_output_dir))

            try:
                index.refresh_file(
                    str(image_path), output_dir=str(new_output_dir)
                )
            except sqlite3.IntegrityError as exc:  # pragma: no cover
                self.fail(f"refresh_file raised IntegrityError: {exc}")
            finally:
                index.close()

    def test_open_configures_busy_timeout_and_wal(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "dataset_index.db"

            index = DatasetFilterIndex(str(db_path))
            self.assertTrue(index.open())

            busy_timeout = index._conn.execute(
                "PRAGMA busy_timeout"
            ).fetchone()[0]
            journal_mode = index._conn.execute(
                "PRAGMA journal_mode"
            ).fetchone()[0]

            self.assertEqual(busy_timeout, 30000)
            self.assertEqual(journal_mode.lower(), "wal")
            index.close()


if __name__ == "__main__":
    unittest.main()
