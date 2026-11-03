"""Boundary probe for the history verification fix."""
import importlib.util
from pathlib import Path

from PyQt6 import QtCore
from anylabeling.services.inspection.manifest import build_manifest
from anylabeling.services.inspection.runner import InspectionRunner
from anylabeling.services.inspection.models import VerificationState

_source = Path(__file__).with_name('test_review_probes.py')
_spec = importlib.util.spec_from_file_location('review_four_helpers', _source)
_helpers = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_helpers)
window = _helpers.window


def test_restore_must_respect_unsaved_canvas_changes(window, tmp_path):
    host, dialog = _helpers._run(window, tmp_path)
    manifest = build_manifest(str(tmp_path))
    report = InspectionRunner(dialog.catalog).run(manifest, dialog._active_profile)
    dialog.storage.reports.save(report, manifest)
    dialog._load_report(report.run_id)
    assert dialog.report.issues[0].verification is VerificationState.CURRENT
    host.canvas.shapes[0].move_by(QtCore.QPointF(20, 20))
    host.set_dirty()
    host.canvas.shape_moved.emit()
    assert dialog.report.issues[0].verification is VerificationState.PENDING_RECHECK
    dialog._load_report(report.run_id)
    assert dialog.report.issues[0].verification in (VerificationState.STALE, VerificationState.PENDING_RECHECK, VerificationState.UNVERIFIABLE)
