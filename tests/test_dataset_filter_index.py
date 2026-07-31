import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from anylabeling.views.labeling.dataset_index import (
    DATASET_INDEX_READY,
    INDEX_STATUS_OK,
    DatasetFilterIndex,
    install_staged_database,
)


class TestDatasetFilterIndex(unittest.TestCase):

    @staticmethod
    def _touch(path: Path) -> None:
        path.write_bytes(b"")

    @staticmethod
    def _write_label(path: Path, label: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(
                {"shapes": [{"label": label, "shape_type": "rectangle"}]},
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

    def test_refresh_persists_identity_statuses_and_summary(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            image_path = root / "sample.jpg"
            json_path = root / "sample.json"
            db_path = root / "dataset.db"
            self._touch(image_path)
            self._write_label(json_path, "person")

            index = DatasetFilterIndex(str(db_path))
            result = index.refresh([str(image_path)], dataset_root=str(root))

            self.assertEqual(result.inserted, 1)
            self.assertEqual(result.shape_count, 1)
            self.assertEqual(result.missing, 0)
            self.assertEqual(index.snapshot_state(), DATASET_INDEX_READY)
            self.assertTrue(index.is_compatible(str(root)))
            self.assertEqual(
                index.file_statuses([str(image_path)])[str(image_path)],
                (INDEX_STATUS_OK, str(json_path)),
            )
            index.close()

    def test_refresh_uses_nanosecond_mtime_for_change_detection(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            image_path = root / "sample.jpg"
            json_path = root / "sample.json"
            db_path = root / "dataset.db"
            self._touch(image_path)
            self._write_label(json_path, "person")

            index = DatasetFilterIndex(str(db_path))
            try:
                index.rebuild([str(image_path)], dataset_root=str(root))
                stat_result = json_path.stat()
                index._conn.execute(
                    "UPDATE files SET json_mtime = ?, json_mtime_ns = ?",
                    (stat_result.st_mtime, stat_result.st_mtime_ns + 1),
                )
                index._conn.commit()

                result = index.refresh(
                    [str(image_path)], dataset_root=str(root)
                )

                self.assertEqual(result.updated, 1)
                stored_mtime_ns = index._conn.execute(
                    "SELECT json_mtime_ns FROM files"
                ).fetchone()[0]
                self.assertEqual(stored_mtime_ns, stat_result.st_mtime_ns)
            finally:
                index.close()

    def test_open_adds_nanosecond_mtime_column_to_existing_schema(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "dataset.db"
            index = DatasetFilterIndex(str(db_path))
            self.assertTrue(index.open())
            index.close()

            connection = sqlite3.connect(str(db_path))
            connection.execute("ALTER TABLE files DROP COLUMN json_mtime_ns")
            connection.commit()
            connection.close()

            migrated = DatasetFilterIndex(str(db_path))
            self.assertTrue(migrated.open())
            columns = {
                row[1]
                for row in migrated._conn.execute("PRAGMA table_info(files)")
            }
            self.assertIn("json_mtime_ns", columns)
            migrated.close()

    def test_cancelled_refresh_rolls_back_all_changes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            image_path = root / "sample.jpg"
            json_path = root / "sample.json"
            db_path = root / "dataset.db"
            self._touch(image_path)
            self._write_label(json_path, "before")

            index = DatasetFilterIndex(str(db_path))
            try:
                index.rebuild([str(image_path)], dataset_root=str(root))
                self._write_label(json_path, "after")

                result = index.refresh(
                    [str(image_path)],
                    cancel_check=lambda: True,
                    dataset_root=str(root),
                )

                self.assertTrue(result.cancelled)
                labels = index._conn.execute(
                    "SELECT label FROM shapes"
                ).fetchall()
                self.assertEqual(labels, [("before",)])
            finally:
                index.close()

    def test_install_staged_database_replaces_complete_snapshot(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target_path = root / "target.db"
            staged_path = root / "staged.db"

            target = DatasetFilterIndex(
                str(target_path), journal_mode="delete"
            )
            target.open()
            target._conn.execute(
                "INSERT INTO dataset_meta (key, value) VALUES (?, ?)",
                ("marker", "old"),
            )
            target._conn.commit()
            target.close()

            staged = DatasetFilterIndex(
                str(staged_path), journal_mode="delete"
            )
            staged.open()
            staged._conn.execute(
                "INSERT INTO dataset_meta (key, value) VALUES (?, ?)",
                ("marker", "new"),
            )
            staged._conn.commit()
            staged.close()

            install_staged_database(str(staged_path), str(target_path))

            installed = DatasetFilterIndex(str(target_path))
            self.assertTrue(installed.open())
            self.assertEqual(installed.metadata()["marker"], "new")
            self.assertFalse(staged_path.exists())
            installed.close()

    def test_install_staged_database_preserves_target_when_stage_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target_path = root / "target.db"
            target_path.write_bytes(b"original")

            with self.assertRaises(FileNotFoundError):
                install_staged_database(
                    str(root / "missing.db"), str(target_path)
                )

            self.assertEqual(target_path.read_bytes(), b"original")


if __name__ == "__main__":
    unittest.main()
