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
import json
import os
import os.path as osp
import shutil
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Set, Tuple

from .validation_engine import ValidationReport

logger = logging.getLogger(__name__)

# Common image file extensions to try when looking for associated images.
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".webp"}


@dataclass
class ExportResult:
    """Summary of an export / split operation."""

    total_files: int = 0
    total_issues: int = 0
    total_copy_tasks: int = 0
    copied_files: int = 0  # JSON copy operations completed
    copied_images: int = 0  # associated image files copied
    errors: List[Tuple[str, str]] = field(
        default_factory=list
    )  # (path, error)
    warnings: List[Tuple[str, str]] = field(
        default_factory=list
    )  # (path, warning)
    rules_exported: List[str] = field(default_factory=list)
    cancelled: bool = False


@dataclass(frozen=True)
class ImageLookupResult:
    """Result of resolving an annotation JSON to an associated image."""

    path: Optional[str] = None
    warning: str = ""


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
        cancel_callback: Optional[Callable[[], bool]] = None,
    ) -> ExportResult:
        """Split files by rule type and copy them to ``output_dir``.

        Args:
            report: The ValidationReport from a completed scan.
            output_dir: Root directory where per-rule subfolders are created.
            progress_callback: Optional callable(current, total, filename).
            cancel_callback: Optional callable returning True to stop before
                the next file copy.

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
        result.total_copy_tasks = sum(
            len(paths) for paths in rule_files.values()
        )

        if progress_callback:
            progress_callback(0, max(result.total_copy_tasks, 1), "")

        # ── copy files per rule ──────────────────────────────────
        current = 0
        for rule_name, file_paths in sorted(rule_files.items()):
            if _cancel_requested(cancel_callback):
                result.cancelled = True
                break

            rule_dir = osp.join(output_dir, rule_name)
            try:
                os.makedirs(rule_dir, exist_ok=True)
            except OSError as exc:
                current = self._record_directory_error(
                    file_paths,
                    rule_dir,
                    exc,
                    result,
                    progress_callback,
                    current,
                )
                continue

            for fp in sorted(file_paths):
                if _cancel_requested(cancel_callback):
                    result.cancelled = True
                    break
                try:
                    self._copy_file_and_image(fp, rule_dir, result)
                except OSError as exc:
                    msg = str(exc)
                    result.errors.append((fp, msg))
                    logger.warning("Export copy failed for %s: %s", fp, msg)

                current += 1
                if progress_callback:
                    progress_callback(
                        current,
                        max(result.total_copy_tasks, 1),
                        osp.basename(fp),
                    )

            if result.cancelled:
                break

        logger.info(
            "Export finished: %d files + %d images copied, %d errors, "
            "%d warnings, cancelled=%s",
            result.copied_files,
            result.copied_images,
            len(result.errors),
            len(result.warnings),
            result.cancelled,
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
        json_target = osp.join(dest_dir, json_name)
        try:
            shutil.copy2(json_path, json_target)
        except OSError as exc:
            raise OSError(
                f"JSON copy failed: {json_path} -> {json_target}: {exc}"
            ) from exc
        result.copied_files += 1

        # Try to find and copy the associated image
        lookup = _find_image_for_json(json_path)
        if lookup.warning:
            result.warnings.append((json_path, lookup.warning))
            logger.warning(
                "Export image lookup warning for %s: %s",
                json_path,
                lookup.warning,
            )
        image_path = lookup.path
        if image_path and osp.isfile(image_path):
            img_name = osp.basename(image_path)
            target = osp.join(dest_dir, img_name)
            if not osp.exists(target):
                try:
                    shutil.copy2(image_path, target)
                except OSError as exc:
                    raise OSError(
                        f"Image copy failed: {image_path} -> {target}: {exc}"
                    ) from exc
                result.copied_images += 1

    @staticmethod
    def _record_directory_error(
        file_paths: Set[str],
        rule_dir: str,
        exc: OSError,
        result: ExportResult,
        progress_callback: Optional[Callable[[int, int, str], None]],
        current: int,
    ) -> int:
        """Record directory creation failures for every file in a rule."""
        msg = f"Cannot create export directory {rule_dir}: {exc}"
        for fp in sorted(file_paths):
            result.errors.append((fp, msg))
            logger.warning("Export directory creation failed: %s", msg)
            current += 1
            if progress_callback:
                progress_callback(
                    current,
                    max(result.total_copy_tasks, 1),
                    osp.basename(fp),
                )
        return current


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------


def _find_image_for_json(json_path: str) -> ImageLookupResult:
    """Find the image file associated with a JSON annotation file.

    Strategy (in order):
      1. Read ``imagePath`` from the JSON itself.
      2. Use the JSON's base name with common image extensions (same dir).
    """
    warnings: List[str] = []

    # 1. Try imagePath from JSON
    try:
        with open(json_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            warnings.append(
                f"Cannot read imagePath: JSON root is "
                f"{type(data).__name__}"
            )
            image_path = ""
        else:
            image_path = data.get("imagePath", "")
        if image_path and not isinstance(image_path, str):
            warnings.append(
                f"imagePath is not a string: {type(image_path).__name__}"
            )
            image_path = ""
        if image_path:
            candidate = _resolve_image_path(json_path, image_path)
            if osp.isfile(candidate):
                return ImageLookupResult(path=candidate)
            warnings.append(f"imagePath not found: {candidate}")
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        warnings.append(f"Cannot read imagePath: invalid JSON ({exc})")
    except OSError as exc:
        warnings.append(f"Cannot read imagePath: {exc}")

    # 2. Same base name with common image extensions
    base, _ = osp.splitext(json_path)
    for ext in _IMAGE_EXTS:
        candidate = base + ext
        if osp.isfile(candidate):
            return ImageLookupResult(
                path=candidate,
                warning="; ".join(warnings),
            )

    warnings.append("Associated image not found by imagePath or base name")
    return ImageLookupResult(warning="; ".join(warnings))


def _resolve_image_path(json_path: str, image_path: str) -> str:
    """Resolve a JSON ``imagePath`` value against the JSON directory."""
    if osp.isabs(image_path):
        return image_path
    return osp.normpath(osp.join(osp.dirname(json_path), image_path))


def _cancel_requested(
    cancel_callback: Optional[Callable[[], bool]],
) -> bool:
    """Return whether an export caller requested cancellation."""
    return bool(cancel_callback and cancel_callback())
