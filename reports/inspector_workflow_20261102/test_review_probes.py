"""Independent review probes; assertions describe required behavior."""
import importlib.util
import json
from dataclasses import replace
from pathlib import Path

from PyQt6 import QtWidgets
from anylabeling.services.inspection.models import Decision, VerificationState, RunScope
from anylabeling.services.inspection.profiles import default_profiles
from anylabeling.services.inspection.runner import InspectionRunner
from anylabeling.services.inspection.manifest import build_manifest

_source = Path(__file__).resolve().parents[2] / 'tests/test_inspection/test_inspector_dialog.py'
_spec = importlib.util.spec_from_file_location('inspection_review_helpers', _source)
_helpers = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_helpers)
window = _helpers.window


def _run(window, tmp_path):
    host = window.labeling_widget.view
    assert host.load_file(_helpers._prepare_image(tmp_path))
    host.open_inspector()
    dialog = host.inspector_dialog
    dialog.profile_combo.setCurrentIndex(dialog.profile_combo.findData('generic'))
    dialog._start_run()
    assert _helpers._wait_until(QtWidgets.QApplication.instance(), lambda: dialog.report is not None)
    dialog.issue_table.selectRow(0)
    return host, dialog


def test_history_must_be_stale_after_external_annotation_edit(window, tmp_path):
    host, dialog = _run(window, tmp_path)
    dialog._set_decision(Decision.FALSE_POSITIVE)
    run_id = dialog.report.run_id
    path = tmp_path / 'image.json'
    data = json.loads(path.read_text(encoding='utf-8'))
    data['shapes'][0]['points'] = [[35, 35], [60, 60]]
    path.write_text(json.dumps(data), encoding='utf-8')
    dialog._load_report(run_id)
    assert dialog.report.issues[0].verification in (VerificationState.STALE, VerificationState.UNVERIFIABLE)


def test_selected_profile_must_not_be_replaced_by_last_binding(window, tmp_path):
    host, dialog = _run(window, tmp_path)
    issue = dialog.report.issues[0]
    old_run_id = dialog.report.run_id
    profile = replace(dialog._active_profile, profile_id='review_without_duplicate', name='No duplicate rule', rules=tuple(r for r in dialog._active_profile.rules if r.rule_id not in issue.rule_ids))
    dialog._profiles[profile.profile_id] = profile
    dialog._refresh_profile_combo(profile.profile_id)
    dialog._start_run()
    assert _helpers._wait_until(QtWidgets.QApplication.instance(), lambda: dialog.report.run_id != old_run_id)
    assert dialog._active_profile.profile_id == profile.profile_id


def test_delete_selected_canvas_box_preserves_other_duplicate(window, tmp_path, monkeypatch):
    host, dialog = _run(window, tmp_path)
    host.canvas.select_shapes([host.canvas.shapes[0]])
    monkeypatch.setattr(QtWidgets.QMessageBox, 'question', lambda *args, **kwargs: QtWidgets.QMessageBox.StandardButton.Yes)
    dialog._delete_selected()
    assert len(host.canvas.shapes) == 1


def test_manifest_read_error_cannot_produce_completed_run(tmp_path):
    _helpers._prepare_image(tmp_path)
    from PIL import Image
    Image.new('RGB', (64, 64)).save(tmp_path / 'bad.png')
    (tmp_path / 'bad.json').write_text(json.dumps({'imageWidth': 'invalid', 'imageHeight':64, 'shapes': []}), encoding='utf-8')
    manifest = build_manifest(str(tmp_path))
    # Parsing failures may remain in files as error snapshots after the fix.
    assert manifest.errors or any(f.annotation_state == 'error' for f in manifest.files)
    profile = next(p for p in default_profiles() if p.profile_id == 'generic')
    report = InspectionRunner().run(manifest, profile)
    assert report.state.value != 'completed'
    assert report.requested_files == 2
    assert report.failed_files == 1
