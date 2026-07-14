"""
Export / Split Manager — copy files to output directories by issue type.

Phase 3 feature:
- Groups validation issues by rule name.
- Copies affected JSON files + their image files into per-rule subdirectories.
- Non-destructive: always copies, never moves or deletes originals.

Directory structure::

    output_dir/
      ├── label_in_allowlist/
      │   ├── file001.json
      │   ├── file001.jpg
      │   └── ...
      ├── group_id_uniqueness/
      └── ...
"""

import logging
import os
import os.path as osp
import shutil
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Set, Tuple

from .validation_engine import ValidationReport, Issue

logger = logging.getLogger(__name__)

# Common image file extensions to try when looking for associated images.
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".webp"}


@dataclass
class ExportResult:
    """Summary of an export / split operation."""

    total_files: int = 0
    total_issues: int = 0
    copied_files: int = 0  # unique JSON files copied
    copied_images: int = 0  # associated image files copied
    errors: List[Tuple[str, str]] = field(
        default_factory=list
    )  # (path, error)
    rules_exported: List[str] = field(default_factory=list)


class ExportManager:
    """Handles copying files into per-rule directories.

    Usage::

        mgr = ExportManager()
        result = mgr.export(
            report=validation_report,
            output_dir="/tmp/split_output",
            progress_callback=lambda cur, total, name: print(f"{cur}/{total}"),
        )
        print(f"Copied {result.copied_files} files into {len(result.rules_exported)} dirs")
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def export(
        self,
        report: ValidationReport,
        output_dir: str,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
    ) -> ExportResult:
        """Split files by rule type and copy them to ``output_dir``.

        Args:
            report: The ValidationReport from a completed scan.
            output_dir: Root directory where per-rule subfolders are created.
            progress_callback: Optional callable(current, total, filename).

        Returns:
            ExportResult with counts and any errors.
        """
        result = ExportResult(
            total_files=report.total_files,
            total_issues=report.issue_count,
        )

        if not report.issues:
            logger.info("No issues to export")
            return result

        # ── group unique file paths by rule ──────────────────────
        # {rule_name: {file_path, file_path, ...}}
        rule_files: Dict[str, Set[str]] = {}
        for issue in report.issues:
            if issue.file_path:
                rule_files.setdefault(issue.rule_name, set()).add(
                    issue.file_path
                )

        result.rules_exported = sorted(rule_files.keys())

        if progress_callback:
            progress_callback(0, len(result.rules_exported), "")

        # ── copy files per rule ──────────────────────────────────
        for ri, (rule_name, file_paths) in enumerate(
            sorted(rule_files.items()), 1
        ):
            rule_dir = osp.join(output_dir, rule_name)
            os.makedirs(rule_dir, exist_ok=True)

            for fp in file_paths:
                try:
                    self._copy_file_and_image(fp, rule_dir, result)
                except OSError as exc:
                    msg = str(exc)
                    result.errors.append((fp, msg))
                    logger.warning("Export copy failed for %s: %s", fp, msg)

            if progress_callback:
                progress_callback(ri, len(result.rules_exported), rule_name)

        logger.info(
            "Export finished: %d files + %d images copied, %d errors",
            result.copied_files,
            result.copied_images,
            len(result.errors),
        )
        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _copy_file_and_image(
        json_path: str, dest_dir: str, result: ExportResult
    ) -> None:
        """Copy a JSON file and its associated image to *dest_dir*."""
        if not osp.isfile(json_path):
            raise FileNotFoundError(f"Source not found: {json_path}")

        # Copy JSON
        json_name = osp.basename(json_path)
        shutil.copy2(json_path, osp.join(dest_dir, json_name))
        result.copied_files += 1

        # Try to find and copy the associated image
        image_path = _find_image_for_json(json_path)
        if image_path and osp.isfile(image_path):
            img_name = osp.basename(image_path)
            target = osp.join(dest_dir, img_name)
            if not osp.exists(target):
                shutil.copy2(image_path, target)
                result.copied_images += 1


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------


def _find_image_for_json(json_path: str) -> Optional[str]:
    """Find the image file associated with a JSON annotation file.

    Strategy (in order):
      1. Read ``imagePath`` from the JSON itself.
      2. Use the JSON's base name with common image extensions (same dir).
    """
    # 1. Try imagePath from JSON
    try:
        import json as _json

        with open(json_path, "r", encoding="utf-8") as fh:
            data = _json.load(fh)
        image_path = data.get("imagePath", "")
        if image_path:
            # imagePath might be relative — resolve against JSON dir
            candidate = osp.join(osp.dirname(json_path), image_path)
            if osp.isfile(candidate):
                return candidate
    except Exception:
        pass

    # 2. Same base name with common image extensions
    base, _ = osp.splitext(json_path)
    for ext in _IMAGE_EXTS:
        candidate = base + ext
        if osp.isfile(candidate):
            return candidate

    return None
