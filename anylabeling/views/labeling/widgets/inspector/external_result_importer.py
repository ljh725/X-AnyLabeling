"""Import external validation results into Inspector reports."""

import csv
import json
import os.path as osp
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .validation_engine import Issue, ValidationReport

_ALLOWED_SEVERITIES = {"error", "warning", "info"}
_FILE_FIELD_NAMES = ("file_path", "json_path", "path", "file", "filename")


@dataclass
class ImportResult:
    """Result of importing external issue data."""

    report: ValidationReport
    errors: List[str] = field(default_factory=list)


class ExternalResultImporter:
    """Parse external checker output into a ValidationReport.

    Supported formats:
        TSV/TXT with a header row:
            file_path, shape_index, rule_name, severity, message, label,
            group_id

        JSON as either a list of issue objects or an object with an ``issues``
        list. Field names follow the TSV header. ``shape_index=-1`` represents
        a file-level issue.
    """

    def __init__(self, known_json_paths: Iterable[str]):
        """Initialize the importer with files currently known to Inspector."""
        self._known_json_paths = list(known_json_paths)
        self._by_basename = {
            osp.basename(path).lower(): path for path in self._known_json_paths
        }
        self._shape_cache: Dict[str, List[Any]] = {}

    def import_file(self, result_path: str) -> ImportResult:
        """Read *result_path* and return an Inspector validation report."""
        suffix = osp.splitext(result_path)[1].lower()
        if suffix == ".json":
            rows = self._read_json(result_path)
        else:
            rows = self._read_text_table(result_path)
        return self._rows_to_result(rows)

    @staticmethod
    def _read_json(result_path: str) -> List[Dict[str, Any]]:
        """Read a JSON result file."""
        with open(result_path, "r", encoding="utf-8-sig") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            data = data.get("issues", [])
        if not isinstance(data, list):
            raise ValueError("JSON result must be a list or contain issues[]")
        return [row for row in data if isinstance(row, dict)]

    @staticmethod
    def _read_text_table(result_path: str) -> List[Dict[str, Any]]:
        """Read a TSV/TXT result file with a header row."""
        with open(result_path, "r", encoding="utf-8-sig", newline="") as fh:
            sample = fh.read(4096)
            fh.seek(0)
            delimiter = "\t" if "\t" in sample else ","
            reader = csv.DictReader(fh, delimiter=delimiter)
            if not reader.fieldnames:
                raise ValueError("Result text file must include a header row")
            return [dict(row) for row in reader]

    def _rows_to_result(self, rows: List[Dict[str, Any]]) -> ImportResult:
        """Convert parsed rows into an ImportResult."""
        issues: List[Issue] = []
        errors: List[str] = []

        for line_no, row in enumerate(rows, 2):
            issue, error = self._row_to_issue(row)
            if error:
                errors.append(f"line {line_no}: {error}")
                continue
            if issue is not None:
                issues.append(issue)

        report = ValidationReport(
            total_files=len({issue.file_path for issue in issues}),
            total_records=0,
            issues=issues,
        )
        return ImportResult(report=report, errors=errors)

    def _row_to_issue(
        self, row: Dict[str, Any]
    ) -> Tuple[Optional[Issue], Optional[str]]:
        """Convert one external result row into an Issue."""
        raw_path = self._first_present(row, _FILE_FIELD_NAMES)
        if not raw_path:
            return None, "missing file_path"

        file_path = self._resolve_file_path(str(raw_path).strip())
        if not file_path:
            return None, f"unknown file_path: {raw_path}"

        shape_index, index_error = self._read_int(
            row.get("shape_index", -1), default=-1
        )
        if index_error:
            return None, f"invalid shape_index: {row.get('shape_index')}"

        group_id, group_error = self._read_int(
            row.get("group_id"), default=None
        )
        if group_error:
            group_id = None

        severity = str(row.get("severity") or "warning").strip().lower()
        if severity not in _ALLOWED_SEVERITIES:
            severity = "warning"

        rule_name = str(row.get("rule_name") or "external_result").strip()
        message = str(row.get("message") or "").strip()
        label = str(row.get("label") or "").strip()
        json_label, json_group_id = self._shape_metadata(
            file_path, shape_index
        )
        if not label:
            label = json_label
        if group_id is None:
            group_id = json_group_id
        if not message:
            message = f"[外部检测] {rule_name}"
        label, group_id = self._fallback_metadata_from_message(
            message, label, group_id
        )
        display_message = self._build_display_message(
            shape_index, label, group_id, message
        )

        return (
            Issue(
                rule_name=rule_name,
                severity=severity,
                message=display_message,
                file_path=file_path,
                shape_index=shape_index,
                label=label,
                group_id=group_id,
                extra={"source": "external", "raw_message": message},
            ),
            None,
        )

    @staticmethod
    def _first_present(row: Dict[str, Any], names: Iterable[str]) -> Any:
        """Return the first non-empty value matching any supported field name."""
        normalized = {str(key).lower(): value for key, value in row.items()}
        for name in names:
            value = normalized.get(name)
            if value not in (None, ""):
                return value
        return None

    def _resolve_file_path(self, raw_path: str) -> Optional[str]:
        """Resolve absolute, relative, or basename-only JSON references."""
        if osp.isfile(raw_path):
            return osp.normpath(raw_path)

        basename = osp.basename(raw_path).lower()
        if basename in self._by_basename:
            return self._by_basename[basename]

        if not basename.endswith(".json"):
            json_name = osp.splitext(basename)[0] + ".json"
            return self._by_basename.get(json_name)

        return None

    def _shape_metadata(
        self, file_path: str, shape_index: int
    ) -> Tuple[str, Optional[int]]:
        """Read label and group_id from the source JSON when possible."""
        if shape_index < 0 or not osp.isfile(file_path):
            return "", None

        if file_path not in self._shape_cache:
            try:
                with open(file_path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                shapes = data.get("shapes", [])
                if not isinstance(shapes, list):
                    shapes = []
            except Exception:
                shapes = []
            self._shape_cache[file_path] = shapes

        shapes = self._shape_cache[file_path]
        if shape_index >= len(shapes):
            return "", None

        shape = shapes[shape_index]
        if not isinstance(shape, dict):
            return "", None
        label = str(shape.get("label") or "")
        group_id = shape.get("group_id")
        if isinstance(group_id, bool) or not isinstance(group_id, int):
            group_id = None
        return label, group_id

    @staticmethod
    def _fallback_metadata_from_message(
        message: str, label: str, group_id: Optional[int]
    ) -> Tuple[str, Optional[int]]:
        """Extract lightweight metadata from common external messages."""
        if group_id is None:
            gid_match = re.search(r"group_id=(\d+)", message)
            if gid_match:
                group_id = int(gid_match.group(1))
        if not label:
            label_match = re.search(r"'([^']+)'", message)
            if label_match:
                label = label_match.group(1)
        return label, group_id

    @staticmethod
    def _build_display_message(
        shape_index: int,
        label: str,
        group_id: Optional[int],
        message: str,
    ) -> str:
        """Build a native-looking issue title for Inspector display."""
        parts = []
        if shape_index >= 0:
            parts.append(f"shape #{shape_index}")
        if label:
            parts.append(label)
        if group_id is not None:
            parts.append(f"gid={group_id}")
        if not parts:
            return message
        return " | ".join(parts) + f" | {message}"

    @staticmethod
    def _read_int(value: Any, default: Optional[int]) -> Tuple[Any, bool]:
        """Read an integer field and return (value, has_error)."""
        if value in (None, ""):
            return default, False
        try:
            return int(value), False
        except (TypeError, ValueError):
            return default, True
