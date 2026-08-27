"""Tests for the non-blocking project Shape identity worker."""

import json

from anylabeling.views.labeling.shape_identity_worker import (
    ProjectShapeIdentityWorker,
)


def test_worker_runs_project_assignment_off_the_ui_thread(qapp, tmp_path):
    """The worker emits progress and completion without blocking the UI loop."""
    annotation = tmp_path / "annotation.json"
    annotation.write_text(
        json.dumps({"shapes": [{"label": "person"}]}),
        encoding="utf-8",
    )
    worker = ProjectShapeIdentityWorker([str(tmp_path)])
    results = []
    progress = []
    worker.completed.connect(results.append)
    worker.progress.connect(
        lambda current, total: progress.append((current, total))
    )

    worker.start()
    while worker.isRunning():
        qapp.processEvents()
        worker.wait(10)
    qapp.processEvents()

    assert results[0].files_changed == 1
    assert results[0].shapes_assigned == 1
    assert progress[-1] == (1, 1)
    worker.deleteLater()
