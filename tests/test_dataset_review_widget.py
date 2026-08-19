"""Offscreen tests for the dataset review queue widget.

Covers queue controls, scan progress, draft exclusion confirmation,
task selection, outcome enablement, filters, summaries, warnings,
recovery choices, and read-only state.  Self-contained file.
"""

import pytest

from anylabeling.views.labeling import virtual_review as vr
from anylabeling.views.labeling.widgets.inspector import (
    dataset_review_widget as drw_module,
)


@pytest.fixture()
def widget(qapp):
    """Create a widget with scripted path providers."""

    providers = {
        "sidecar_save": lambda: "Q:/queues/new.xreview.sqlite3",
        "sidecar_open": lambda: "Q:/queues/open.xreview.sqlite3",
        "backup": lambda: "Q:/queues/backup.xreview.sqlite3",
        "root": lambda: "Q:/moved-ds",
        "save_as": lambda: "Q:/queues/copy.xreview.sqlite3",
    }
    w = drw_module.DatasetReviewWidget(path_providers=providers)
    yield w
    w.deleteLater()


def _capture(signal):
    """Return a list that captures signal emissions."""

    captured = []
    signal.connect(lambda *args: captured.append(args))
    return captured


def test_initial_state_gates_lifecycle_buttons(widget):
    assert widget.create_button.isEnabled()
    assert widget.open_button.isEnabled()
    assert not widget.close_button.isEnabled()
    assert not widget.rebuild_button.isEnabled()
    assert not widget.cancel_scan_button.isEnabled()
    assert not widget.progress_bar.isVisibleTo(widget)


def test_building_state_shows_progress_and_cancel(widget):
    widget.set_state("building")
    assert widget.cancel_scan_button.isEnabled()
    assert widget.progress_bar.isVisibleTo(widget)
    assert widget.progress_label.isVisibleTo(widget)
    widget.set_scan_progress(2, 5, "a.json")
    assert "2/5" in widget.progress_label.text()


def test_active_state_enables_outcomes(widget):
    widget.set_state("active")
    assert widget.close_button.isEnabled()
    assert widget.rebuild_button.isEnabled()
    assert widget.reconcile_button.isEnabled()
    assert widget.rebind_root_button.isEnabled()
    assert widget.backup_button.isEnabled()
    assert widget.complete_button.isEnabled()
    assert not widget.create_button.isEnabled()


def test_transitioning_blocks_outcome_buttons(widget):
    widget.set_state("transitioning")
    assert not widget.complete_button.isEnabled()
    assert not widget.complete_next_button.isEnabled()
    assert widget.close_button.isEnabled()


def test_persistence_blocked_shows_recovery_buttons(widget):
    widget.set_state("persistence_blocked")
    assert widget.retry_button.isVisibleTo(widget)
    assert widget.save_as_button.isVisibleTo(widget)
    widget.set_warning("写入失败")
    assert widget.warning_label.isVisibleTo(widget)


def test_readonly_disables_mutation_controls(widget):
    widget.set_state("active")
    widget.set_readonly(True)
    assert not widget.complete_button.isEnabled()
    assert not widget.bind_button.isEnabled()
    assert widget.readonly
    widget.set_readonly(False)
    assert widget.complete_button.isEnabled()


def test_create_and_open_emit_paths(widget):
    created = _capture(widget.create_requested)
    opened = _capture(widget.open_requested)
    widget.create_button.click()
    widget.open_button.click()
    assert created and created[0][0] == ("Q:/queues/new.xreview.sqlite3")
    assert opened and opened[0][0] == ("Q:/queues/open.xreview.sqlite3")


def test_empty_path_providers_suppress_requests(widget):
    widget._provider_sidecar_save = lambda: ""
    created = _capture(widget.create_requested)
    widget.create_button.click()
    assert created == []


def test_draft_confirmation_round_trip(widget):
    confirm_calls = []
    cancel_calls = []
    widget.set_draft_handlers(
        lambda: confirm_calls.append(None),
        lambda: cancel_calls.append(None),
    )
    draft = vr.QueueDraft(
        request=None,
        staging_path="staging",
        stats=vr.BuildStats(
            files_total=3,
            files_matched=2,
            files_excluded=1,
            tasks=4,
            pages=3,
        ),
        exclusions=(vr.FileExclusion("a.jpg", "a.json", "parse"),),
    )
    widget.show_draft(draft)
    assert widget.draft_label.isVisibleTo(widget)
    assert "排除" in widget.draft_label.text()
    widget.draft_confirm_button.click()
    assert confirm_calls == [None]
    assert not widget.draft_label.isVisibleTo(widget)
    widget.show_draft(draft)
    widget.draft_cancel_button.click()
    assert cancel_calls == [None]


def _task(task_id, outcome, freshness, binding, label="person"):
    return vr.AtomicTaskRecord(
        task_id=task_id,
        file_id="f1",
        source_order=0,
        locator={
            "kind": "single",
            "gid": None,
            "members": [{"label": label}],
        },
        outcome=outcome,
        freshness=freshness,
        binding_state=binding,
    )


def test_task_rows_and_selection_drive_outcomes(widget):
    widget.set_state("active")
    tasks = [
        _task(
            "t1",
            vr.TaskOutcome.COMPLETED,
            vr.TaskFreshness.STALE,
            vr.BindingState.CHANGED_RESOLVED,
        ),
        _task(
            "t2",
            vr.TaskOutcome.PENDING,
            vr.TaskFreshness.FRESH,
            vr.BindingState.AMBIGUOUS,
        ),
    ]
    widget.set_current_page("a.json", 2, 7, tasks, {})
    assert widget.info_label.text().startswith("来源：a.json")
    assert "3/7" in widget.info_label.text()
    assert widget.task_list.count() == 2
    assert "已完成 · 已过期" in widget.task_list.item(0).text()
    assert "歧义" in widget.task_list.item(1).text()

    outcomes = _capture(widget.outcome_requested)
    widget.task_list.item(0).setSelected(True)
    widget.complete_button.click()
    assert outcomes[-1] == ("completed", ("t1",))

    widget.task_list.clearSelection()
    widget.skip_button.click()
    assert outcomes[-1] == ("skipped", None)


def test_manual_bind_requires_selection(widget):
    widget.set_state("active")
    binds = _capture(widget.manual_bind_requested)
    widget.bind_button.click()
    assert binds == []
    assert "选择" in widget.warning_label.text()
    widget.set_current_page(
        "a.json",
        0,
        1,
        [
            _task(
                "t9",
                vr.TaskOutcome.PENDING,
                vr.TaskFreshness.FRESH,
                vr.BindingState.AMBIGUOUS,
            )
        ],
        {},
    )
    widget.task_list.item(0).setSelected(True)
    widget.bind_button.click()
    assert binds and binds[0][0] == "t9"


def test_filter_box_emits_selected_filter(widget):
    filters = _capture(widget.filter_changed)
    index = widget.filter_box.findData("stale")
    widget.filter_box.setCurrentIndex(index)
    assert filters and filters[-1] == ("stale",)


def test_summary_counters_and_no_actionable_feedback(widget):
    widget.set_state("active")
    summary = vr.QueueSummary(
        total_files=3,
        total_pages=3,
        total_tasks=3,
        tasks_by_outcome={"pending": 2, "completed": 1},
        actionable_tasks=2,
        actionable_pages=2,
        unresolved_tasks=1,
        stale_tasks=0,
    )
    widget.set_summary(summary, "actionable")
    text = widget.summary_label.text()
    assert "任务 3" in text and "可操作 2" in text
    done_all = vr.QueueSummary(
        total_tasks=4,
        tasks_by_outcome={"completed": 4},
        actionable_tasks=0,
    )
    widget.set_summary(done_all, "actionable")
    assert "没有剩余可处理工作" in widget.summary_label.text()
    widget.set_summary(None, "all")
    assert widget.summary_label.text() == ""


def test_takeover_prompt_and_confirmation(widget):
    confirmed = _capture(widget.takeover_confirmed)
    widget.show_takeover_prompt(
        {"instance_id": "ghost", "pid": 4242}, "Q:/queues/q.sqlite3"
    )
    assert "ghost" in widget.warning_label.text()
    assert widget.takeover_button.isVisibleTo(widget)
    widget.takeover_button.click()
    assert confirmed == [("Q:/queues/q.sqlite3",)]


def test_backup_save_as_and_root_reconcile_emit_paths(widget):
    widget.set_state("active")
    backups = _capture(widget.backup_requested)
    reconciles = _capture(widget.reconcile_requested)
    widget.backup_button.click()
    widget.rebind_root_button.click()
    assert backups == [("Q:/queues/backup.xreview.sqlite3",)]
    assert reconciles == [("Q:/moved-ds",)]
    widget.set_state("persistence_blocked")
    save_as = _capture(widget.save_as_requested)
    retries = _capture(widget.retry_persistence_requested)
    widget.save_as_button.click()
    widget.retry_button.click()
    assert save_as == [("Q:/queues/copy.xreview.sqlite3",)]
    assert retries == [()]


def test_draft_row_visible_only_in_confirmation(widget):
    widget.set_state("active")
    assert not widget.draft_row_widget.isVisibleTo(widget)
    widget.set_state("draft_confirmation")
    assert widget.draft_row_widget.isVisibleTo(widget)
