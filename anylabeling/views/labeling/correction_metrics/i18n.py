"""Feature strings in the application's standard Qt translation catalog."""

from functools import lru_cache
from pathlib import Path

from PyQt6.QtCore import QCoreApplication, QT_TRANSLATE_NOOP, QTranslator


MESSAGES = {
    "title": QT_TRANSLATE_NOOP("CorrectionCost", "Correction Cost Statistics"),
    "need_image": QT_TRANSLATE_NOOP("CorrectionCost", "Open an image first."),
    "save_before_complete": QT_TRANSLATE_NOOP("CorrectionCost", "Save the current version before marking it complete."),
    "incomplete": QT_TRANSLATE_NOOP("CorrectionCost", "Correction cost records are incomplete."),
    "scope": QT_TRANSLATE_NOOP("CorrectionCost", "Scope"),
    "start": QT_TRANSLATE_NOOP("CorrectionCost", "Start recording"),
    "first": QT_TRANSLATE_NOOP("CorrectionCost", "First image"),
    "last": QT_TRANSLATE_NOOP("CorrectionCost", "Last image"),
    "all": QT_TRANSLATE_NOOP("CorrectionCost", "All"),
    "this": QT_TRANSLATE_NOOP("CorrectionCost", "Current image"),
    "image_total": QT_TRANSLATE_NOOP("CorrectionCost", "{count} images"),
    "scope_range": QT_TRANSLATE_NOOP("CorrectionCost", "{count} image(s): {first} … {last}"),
    "cancel": QT_TRANSLATE_NOOP("CorrectionCost", "Cancel"),
    "close": QT_TRANSLATE_NOOP("CorrectionCost", "Close"),
    "details": QT_TRANSLATE_NOOP("CorrectionCost", "Show details"),
    "hide_details": QT_TRANSLATE_NOOP("CorrectionCost", "Hide details"),
    "pause": QT_TRANSLATE_NOOP("CorrectionCost", "Pause timer"),
    "resume": QT_TRANSLATE_NOOP("CorrectionCost", "Resume timer"),
    "stop": QT_TRANSLATE_NOOP("CorrectionCost", "Stop recording"),
    "complete": QT_TRANSLATE_NOOP("CorrectionCost", "Finish round"),
    "continue": QT_TRANSLATE_NOOP("CorrectionCost", "Continue correction"),
    "review": QT_TRANSLATE_NOOP("CorrectionCost", "Start review"),
    "report": QT_TRANSLATE_NOOP("CorrectionCost", "Report"),
    "idle_keep": QT_TRANSLATE_NOOP("CorrectionCost", "Keep as review time"),
    "idle_exclude": QT_TRANSLATE_NOOP("CorrectionCost", "Exclude idle time"),
    "current_image": QT_TRANSLATE_NOOP("CorrectionCost", "Image"),
    "round": QT_TRANSLATE_NOOP("CorrectionCost", "Round"),
    "baseline": QT_TRANSLATE_NOOP("CorrectionCost", "Starting boxes"),
    "saved": QT_TRANSLATE_NOOP("CorrectionCost", "Saved result"),
    "draft": QT_TRANSLATE_NOOP("CorrectionCost", "Current draft"),
    "quality": QT_TRANSLATE_NOOP("CorrectionCost", "Quality assessment"),
    "processing": QT_TRANSLATE_NOOP("CorrectionCost", "Processing status"),
    "time": QT_TRANSLATE_NOOP("CorrectionCost", "In-app processing"),
    "seconds": QT_TRANSLATE_NOOP("CorrectionCost", "{seconds} s"),
    "timing": QT_TRANSLATE_NOOP("CorrectionCost", "Timer"),
    "operations": QT_TRANSLATE_NOOP("CorrectionCost", "Operations / touches / unique objects"),
    "integrity": QT_TRANSLATE_NOOP("CorrectionCost", "Record integrity"),
    "clean": QT_TRANSLATE_NOOP("CorrectionCost", "No recorded gaps"),
    "net": QT_TRANSLATE_NOOP("CorrectionCost", "Added {added} · Deleted {deleted} · Geometry {geometry_changed} · Class {class_changed}"),
    "unfinished": QT_TRANSLATE_NOOP("CorrectionCost", "In progress"),
    "processing-complete": QT_TRANSLATE_NOOP("CorrectionCost", "Completed"),
    "not-assessed": QT_TRANSLATE_NOOP("CorrectionCost", "Not assessed"),
    "unknown-existing": QT_TRANSLATE_NOOP("CorrectionCost", "Existing annotations, unknown source"),
    "replacement": QT_TRANSLATE_NOOP("CorrectionCost", "Replacement prediction"),
    "additive": QT_TRANSLATE_NOOP("CorrectionCost", "Appended prediction"),
    "correction": QT_TRANSLATE_NOOP("CorrectionCost", "Correction"),
    "working": QT_TRANSLATE_NOOP("CorrectionCost", "Processing"),
    "inactive": QT_TRANSLATE_NOOP("CorrectionCost", "Inactive"),
    "blocking_wait": QT_TRANSLATE_NOOP("CorrectionCost", "Waiting"),
    "not_ready": QT_TRANSLATE_NOOP("CorrectionCost", "Loading"),
    "paused": QT_TRANSLATE_NOOP("CorrectionCost", "Paused"),
    "closed": QT_TRANSLATE_NOOP("CorrectionCost", "Stopped"),
    "idle_note": QT_TRANSLATE_NOOP("CorrectionCost", "Pending idle: {seconds} s (included until confirmed)"),
    "report_title": QT_TRANSLATE_NOOP("CorrectionCost", "Correction Cost Report"),
    "refresh": QT_TRANSLATE_NOOP("CorrectionCost", "Refresh snapshot"),
    "snapshot": QT_TRANSLATE_NOOP("CorrectionCost", "Snapshot {stamp}"),
    "images": QT_TRANSLATE_NOOP("CorrectionCost", "Image rounds"),
    "classes": QT_TRANSLATE_NOOP("CorrectionCost", "Class changes"),
    "groups": QT_TRANSLATE_NOOP("CorrectionCost", "By density and model"),
    "current_only": QT_TRANSLATE_NOOP("CorrectionCost", "Current results only"),
    "search": QT_TRANSLATE_NOOP("CorrectionCost", "Search image, class or model"),
    "phase": QT_TRANSLATE_NOOP("CorrectionCost", "Stage"),
    "versions": QT_TRANSLATE_NOOP("CorrectionCost", "Model version"),
    "rounds": QT_TRANSLATE_NOOP("CorrectionCost", "Rounds"),
    "images_count": QT_TRANSLATE_NOOP("CorrectionCost", "Distinct images"),
    "counts": QT_TRANSLATE_NOOP("CorrectionCost", "{images} completed image(s) · {eligible}/{rounds} comparable rounds"),
    "excluded": QT_TRANSLATE_NOOP("CorrectionCost", "Excluded reasons"),
    "group_note": QT_TRANSLATE_NOOP("CorrectionCost", "Comparable saved rounds only. Density uses final rectangles. Sequential runs on the same image are dependent."),
    "prev": QT_TRANSLATE_NOOP("CorrectionCost", "Previous page"),
    "next": QT_TRANSLATE_NOOP("CorrectionCost", "Next page"),
    "page": QT_TRANSLATE_NOOP("CorrectionCost", "Page {page}/{pages} · {count} rows"),
    "selected_finish": QT_TRANSLATE_NOOP("CorrectionCost", "Finish selected rounds…"),
    "selected_confirm": QT_TRANSLATE_NOOP("CorrectionCost", "Mark only the following {count} saved round(s) complete?"),
    "snapshot_changed": QT_TRANSLATE_NOOP("CorrectionCost", "Revalidate revisions before applying. Changed or ineligible rows will be skipped."),
    "select_rows": QT_TRANSLATE_NOOP("CorrectionCost", "Select current saved rows on the Images tab."),
    "no_data": QT_TRANSLATE_NOOP("CorrectionCost", "No recorded image"),
    "export": QT_TRANSLATE_NOOP("CorrectionCost", "Export CSV…"),
    "dictionary": QT_TRANSLATE_NOOP("CorrectionCost", "Metric dictionary"),
    "loading": QT_TRANSLATE_NOOP("CorrectionCost", "Loading report…"),
    "exporting": QT_TRANSLATE_NOOP("CorrectionCost", "Writing CSV…"),
    "exported": QT_TRANSLATE_NOOP("CorrectionCost", "Exported {file}"),
    "error": QT_TRANSLATE_NOOP("CorrectionCost", "Operation failed"),
    "yes": QT_TRANSLATE_NOOP("CorrectionCost", "Yes"),
    "no": QT_TRANSLATE_NOOP("CorrectionCost", "No"),
    "current": QT_TRANSLATE_NOOP("CorrectionCost", "Current"),
    "completed": QT_TRANSLATE_NOOP("CorrectionCost", "Completed"),
    "baseline_count": QT_TRANSLATE_NOOP("CorrectionCost", "Initial boxes"),
    "ai_count": QT_TRANSLATE_NOOP("CorrectionCost", "AI boxes"),
    "final_count": QT_TRANSLATE_NOOP("CorrectionCost", "Saved boxes"),
    "added": QT_TRANSLATE_NOOP("CorrectionCost", "Added"),
    "deleted": QT_TRANSLATE_NOOP("CorrectionCost", "Deleted"),
    "geometry_changed": QT_TRANSLATE_NOOP("CorrectionCost", "Geometry edits"),
    "class_changed": QT_TRANSLATE_NOOP("CorrectionCost", "Class edits"),
    "transactions": QT_TRANSLATE_NOOP("CorrectionCost", "Operations"),
    "working_seconds": QT_TRANSLATE_NOOP("CorrectionCost", "Processing (s)"),
    "median_seconds": QT_TRANSLATE_NOOP("CorrectionCost", "Median seconds/round"),
    "seconds_per_100": QT_TRANSLATE_NOOP("CorrectionCost", "Seconds / 100 boxes"),
    "issues": QT_TRANSLATE_NOOP("CorrectionCost", "Limitations"),
    "image_path": QT_TRANSLATE_NOOP("CorrectionCost", "Image"),
    "model": QT_TRANSLATE_NOOP("CorrectionCost", "Model"),
    "model_version": QT_TRANSLATE_NOOP("CorrectionCost", "Model version"),
    "category_version": QT_TRANSLATE_NOOP("CorrectionCost", "Class vocabulary version"),
    "kind": QT_TRANSLATE_NOOP("CorrectionCost", "Metric"),
    "initial_class": QT_TRANSLATE_NOOP("CorrectionCost", "Initial class"),
    "final_class": QT_TRANSLATE_NOOP("CorrectionCost", "Final class"),
    "count": QT_TRANSLATE_NOOP("CorrectionCost", "Objects"),
    "denominator": QT_TRANSLATE_NOOP("CorrectionCost", "Denominator"),
    "origin": QT_TRANSLATE_NOOP("CorrectionCost", "Baseline source"),
    "modified_original": QT_TRANSLATE_NOOP("CorrectionCost", "Changed original boxes"),
    "modified_rate": QT_TRANSLATE_NOOP("CorrectionCost", "Changed / initial"),
    "density": QT_TRANSLATE_NOOP("CorrectionCost", "Final boxes per image"),
    "initial": QT_TRANSLATE_NOOP("CorrectionCost", "Initial"),
    "final": QT_TRANSLATE_NOOP("CorrectionCost", "Final"),
    "geometry": QT_TRANSLATE_NOOP("CorrectionCost", "Geometry"),
    "unsaved": QT_TRANSLATE_NOOP("CorrectionCost", "Unsaved"),
    "partial_scope": QT_TRANSLATE_NOOP("CorrectionCost", "Partial rectangle scope"),
    "unknown_source": QT_TRANSLATE_NOOP("CorrectionCost", "Unknown source"),
    "interrupted": QT_TRANSLATE_NOOP("CorrectionCost", "Interrupted timing"),
    "history": QT_TRANSLATE_NOOP("CorrectionCost", "Historical"),
    "idle_threshold": QT_TRANSLATE_NOOP("CorrectionCost", "Idle prompt after (s)"),
}


@lru_cache(maxsize=4)
def _catalog(locale):
    translator = QTranslator()
    resource = f":/languages/translations/{locale}.qm"
    if not translator.load(resource):
        path = Path(__file__).resolve().parents[3] / "resources" / "translations"
        translator.load(str(path / (locale + ".qm")))
    return translator


def tr(key, language=None, **values):
    source = MESSAGES.get(key, key)
    if language in ("zh_CN", "ja_JP", "ko_KR", "en_US"):
        translated = _catalog(language).translate("CorrectionCost", source)
    else:
        translated = QCoreApplication.translate("CorrectionCost", source)
    message = translated or source
    return message.format(**values) if values else message
