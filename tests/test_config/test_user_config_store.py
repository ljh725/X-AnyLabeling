"""Transactional user-configuration storage tests."""

import copy
import json
import os
import shutil
import subprocess
import sys
import time
import uuid

import pytest
import yaml

from anylabeling import user_config

REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
WORKER = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "_user_config_worker.py"
)

TEMPLATE = {
    "canvas": {"epsilon": 8.0, "label_font_size": 8},
    "shortcuts": {"open": "Ctrl+O"},
    "digit_shortcuts": {},
}


def _workspace():
    path = os.path.join(
        REPO_ROOT, ".tmp", "config-store-tests", uuid.uuid4().hex
    )
    os.makedirs(path, exist_ok=True)
    return path


@pytest.fixture
def workspace():
    path = _workspace()
    try:
        yield path
    finally:
        user_config.end_session()
        shutil.rmtree(path, ignore_errors=True)


def _write(path, data):
    with open(path, "w", encoding="utf-8") as handle:
        yaml.safe_dump(data, handle, allow_unicode=True)


def _read(path):
    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _start(workspace, disk=None, ensure_created=False):
    from anylabeling.config import normalize_user_config

    target = os.path.join(workspace, ".xanylabelingrc")
    if disk is not None:
        _write(target, disk)
    effective = copy.deepcopy(TEMPLATE)
    if disk:
        effective.update(copy.deepcopy(disk))
    return user_config.begin_session(
        target_path=target,
        origin="file",
        template=copy.deepcopy(TEMPLATE),
        effective=effective,
        disk_data=copy.deepcopy(disk),
        ensure_created=ensure_created,
        normalizer=normalize_user_config,
    )


def test_patch_merges_independent_fields(workspace):
    session = _start(workspace, {"canvas": {"epsilon": 8.0}})
    target = session.target_path
    session.save({"shortcuts.open": "Ctrl+Shift+O"})

    second = _start(
        workspace,
        {
            "canvas": {"epsilon": 8.0},
            "shortcuts": {"open": "Ctrl+Shift+O"},
        },
    )
    second.save({"canvas.epsilon": 9.5})

    data = _read(target)
    assert data["canvas"]["epsilon"] == 9.5
    assert data["shortcuts"]["open"] == "Ctrl+Shift+O"
    assert second.effective["canvas"]["epsilon"] == 9.5


def test_same_field_conflict_keeps_first_writer(workspace):
    _start(workspace, {"canvas": {"epsilon": 8.0}})
    first = _start(workspace, {"canvas": {"epsilon": 8.0}})
    second = _start(workspace, {"canvas": {"epsilon": 8.0}})

    first.save({"canvas.epsilon": 9.0})
    with pytest.raises(user_config.ConfigConflict) as excinfo:
        second.save({"canvas.epsilon": 10.0})
    assert excinfo.value.conflicts == ["canvas.epsilon"]

    data = _read(os.path.join(workspace, ".xanylabelingrc"))
    assert data["canvas"]["epsilon"] == 9.0


def test_equal_value_submission_is_idempotent(workspace):
    session = _start(workspace, {"canvas": {"epsilon": 8.0}})
    session.save({"canvas.epsilon": 9.0})
    target = session.target_path
    before = os.path.getmtime(target)
    backup = os.path.join(workspace, ".xanylabelingrc.bak")
    backup_before = os.path.getmtime(backup)

    result = session.save({"canvas.epsilon": 9.0})
    assert result.changed is False
    assert os.path.getmtime(target) == before
    assert os.path.getmtime(backup) == backup_before


def test_delete_removes_field_and_preserves_unknown_keys(workspace):
    session = _start(
        workspace,
        {
            "canvas": {"epsilon": 8.0},
            "shortcuts": {"open": "Ctrl+O", "save": "Ctrl+S"},
            "x-extension": {"keep": True},
        },
    )
    session.save(user_config.ConfigPatch(deletes=["shortcuts.open"]))
    data = _read(os.path.join(workspace, ".xanylabelingrc"))
    assert "open" not in data["shortcuts"]
    assert data["shortcuts"]["save"] == "Ctrl+S"
    assert data["x-extension"] == {"keep": True}
    assert data["canvas"]["epsilon"] == 8.0


def test_backup_holds_previous_valid_document(workspace):
    session = _start(workspace, {"canvas": {"epsilon": 8.0}})
    target = session.target_path
    session.save({"canvas.epsilon": 9.0})
    first_document = _read(target)

    session.save({"canvas.epsilon": 9.5})
    backup = _read(os.path.join(workspace, ".xanylabelingrc.bak"))
    assert backup == first_document
    assert _read(target)["canvas"]["epsilon"] == 9.5


def test_corrupt_document_is_never_overwritten(workspace):
    target = os.path.join(workspace, ".xanylabelingrc")
    with open(target, "w", encoding="utf-8") as handle:
        handle.write("canvas: [unclosed\n")
    with pytest.raises(user_config.ConfigInvalid):
        user_config.read_config_document(target)

    session = user_config.begin_session(
        target_path=target,
        origin="file",
        template=copy.deepcopy(TEMPLATE),
        effective=copy.deepcopy(TEMPLATE),
        disk_data=None,
        disk_error=user_config.ConfigInvalid(
            "damaged", path=target
        ),
        normalizer=lambda value: value,
    )
    with pytest.raises(user_config.ConfigInvalid):
        session.save({"canvas.epsilon": 10.0})
    with open(target, encoding="utf-8") as handle:
        assert handle.read() == "canvas: [unclosed\n"


def test_restore_backup_keeps_damaged_content(workspace):
    session = _start(workspace, {"canvas": {"epsilon": 8.0}})
    target = session.target_path
    session.save({"canvas.epsilon": 9.0})
    good_document = _read(target)
    session.save({"canvas.epsilon": 9.5})
    with open(target, "w", encoding="utf-8") as handle:
        handle.write("not: [valid")

    result = user_config.restore_backup()
    assert result.backup_path == target + ".bak"
    assert _read(target) == good_document
    corrupt = [
        name
        for name in os.listdir(workspace)
        if ".corrupt-" in name
    ]
    assert corrupt, "damaged content should be preserved"
    assert session.effective["canvas"]["epsilon"] == good_document[
        "canvas"
    ]["epsilon"]


def test_missing_backup_is_reported(workspace):
    _start(workspace, {"canvas": {"epsilon": 8.0}})
    with pytest.raises(user_config.ConfigError):
        user_config.restore_backup()


def test_lock_busy_is_retryable_and_writes_nothing(workspace):
    from PyQt6 import QtCore

    session = _start(workspace, {"canvas": {"epsilon": 8.0}})
    target = session.target_path
    blocker = QtCore.QLockFile(target + user_config.LOCK_SUFFIX)
    assert blocker.tryLock(1000)
    try:
        with pytest.raises(user_config.ConfigLockBusy) as excinfo:
            session.save({"canvas.epsilon": 9.0}, wait_ms=0)
        assert excinfo.value.retryable is True
    finally:
        blocker.unlock()
    assert _read(target)["canvas"]["epsilon"] == 8.0
    session.save({"canvas.epsilon": 9.0})
    assert _read(target)["canvas"]["epsilon"] == 9.0


def test_creation_writes_template_and_reports_created(workspace):
    session = _start(workspace, ensure_created=True)
    target = session.target_path
    assert os.path.isfile(target)
    assert _read(target) == TEMPLATE

    result = session.save({"canvas.epsilon": 9.0})
    assert result.created is False
    assert _read(target)["canvas"]["epsilon"] == 9.0


def test_legacy_file_is_migrated_without_deleting_it(workspace):
    legacy = os.path.join(workspace, ".anylabelingrc")
    _write(legacy, {"canvas": {"epsilon": 7.0}})
    target = os.path.join(workspace, ".xanylabelingrc")
    session = user_config.begin_session(
        target_path=target,
        origin="default",
        template=copy.deepcopy(TEMPLATE),
        effective=copy.deepcopy(TEMPLATE),
        allow_legacy_migration=True,
        normalizer=lambda value: value,
    )
    assert os.path.isfile(legacy)
    assert _read(target)["canvas"]["epsilon"] == 7.0
    assert session.disk_exists


def test_legacy_key_is_replaced_by_nested_target(workspace):
    from anylabeling.config import normalize_user_config

    session = _start(workspace, {"epsilon": 7.0})
    session.save({"canvas.epsilon": 10.0})
    data = _read(os.path.join(workspace, ".xanylabelingrc"))
    assert "epsilon" not in data
    assert data["canvas"]["epsilon"] == 10.0
    assert normalize_user_config(data)["canvas"]["epsilon"] == 10.0


def test_digit_entries_use_integer_keys(workspace):
    session = _start(workspace, {"digit_shortcuts": {"2": {"mode": "polygon"}}})
    session.save(
        {("digit_shortcuts", 1): {"mode": "rectangle", "label": "car"}}
    )
    data = _read(os.path.join(workspace, ".xanylabelingrc"))
    assert data["digit_shortcuts"][1] == {
        "mode": "rectangle",
        "label": "car",
    }
    assert 2 in data["digit_shortcuts"]

    session.save(user_config.ConfigPatch(deletes=[("digit_shortcuts", 2)]))
    data = _read(os.path.join(workspace, ".xanylabelingrc"))
    assert 2 not in data["digit_shortcuts"]
    assert 1 in data["digit_shortcuts"]


def test_unserializable_value_is_rejected_without_damage(workspace):
    session = _start(workspace, {"canvas": {"epsilon": 8.0}})
    target = session.target_path
    before = _read(target)

    with pytest.raises(user_config.ConfigWriteError):
        session.save({"canvas.epsilon": object()})

    assert _read(target) == before
    assert session.effective["canvas"]["epsilon"] == 8.0


def test_failed_replace_keeps_the_previous_file(workspace, monkeypatch):
    session = _start(workspace, {"canvas": {"epsilon": 8.0}})
    target = session.target_path
    before = _read(target)

    real_replace = os.replace

    def failing_replace(source, destination):
        raise OSError("simulated replacement failure")

    monkeypatch.setattr(os, "replace", failing_replace)
    try:
        with pytest.raises(user_config.ConfigWriteError):
            session.save({"canvas.epsilon": 9.0})
    finally:
        monkeypatch.setattr(os, "replace", real_replace)

    assert _read(target) == before
    assert not [
        name for name in os.listdir(workspace) if name.endswith(".tmp")
    ]


def _wait_for(path, timeout=20.0):
    deadline = time.time() + timeout
    while not os.path.exists(path):
        if time.time() > deadline:
            raise AssertionError(f"timed out waiting for {path}")
        time.sleep(0.02)


def _spawn_worker(workspace, name, key, value, barrier):
    ready = os.path.join(workspace, f"{name}.ready")
    stdout_path = os.path.join(workspace, f"{name}.out")
    stderr_path = os.path.join(workspace, f"{name}.err")
    payload = {
        "target": os.path.join(workspace, ".xanylabelingrc"),
        "barrier": barrier,
        "ready": ready,
        "key": key,
        "value": value,
    }
    return _spawn_payload(workspace, name, payload, ready)


def _spawn_steps_worker(workspace, name, steps, barrier):
    ready = os.path.join(workspace, f"{name}.ready")
    payload = {
        "target": os.path.join(workspace, ".xanylabelingrc"),
        "barrier": barrier,
        "ready": ready,
        "steps": steps,
    }
    return _spawn_payload(workspace, name, payload, ready)


def _spawn_payload(workspace, name, payload, ready):
    stdout_path = os.path.join(workspace, f"{name}.out")
    stderr_path = os.path.join(workspace, f"{name}.err")
    stdout_file = open(stdout_path, "w", encoding="utf-8")
    stderr_file = open(stderr_path, "w", encoding="utf-8")
    process = subprocess.Popen(
        [sys.executable, WORKER, json.dumps(payload)],
        cwd=REPO_ROOT,
        stdout=stdout_file,
        stderr=stderr_file,
        text=True,
    )
    process._test_files = (stdout_file, stderr_file)
    _wait_for(ready)
    return process


def _finish_worker(process):
    code = process.wait(30)
    for handle in process._test_files:
        handle.close()
    return code


def test_two_processes_merge_different_fields(workspace):
    _start(workspace, {"canvas": {"epsilon": 8.0, "label_font_size": 8}})
    user_config.end_session()
    barrier = os.path.join(workspace, "barrier")

    first = _spawn_worker(workspace, "a", "canvas.epsilon", 9.0, barrier)
    second = _spawn_worker(
        workspace, "b", "canvas.label_font_size", 14, barrier
    )
    open(barrier, "w", encoding="utf-8").close()
    assert _finish_worker(first) == 0, _read_text(workspace, "a.err")
    assert _finish_worker(second) == 0, _read_text(workspace, "b.err")

    data = _read(os.path.join(workspace, ".xanylabelingrc"))
    assert data["canvas"]["epsilon"] == 9.0
    assert data["canvas"]["label_font_size"] == 14


def _read_text(workspace, name):
    path = os.path.join(workspace, name)
    if not os.path.exists(path):
        return ""
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def test_two_processes_conflict_on_same_field(workspace):
    _start(workspace, {"canvas": {"epsilon": 8.0}})
    user_config.end_session()
    barrier = os.path.join(workspace, "barrier")

    first = _spawn_worker(workspace, "c", "canvas.epsilon", 9.0, barrier)
    second = _spawn_worker(workspace, "d", "canvas.epsilon", 10.0, barrier)
    open(barrier, "w", encoding="utf-8").close()
    codes = sorted([_finish_worker(first), _finish_worker(second)])
    assert codes == [0, 3], (
        codes,
        _read_text(workspace, "c.err"),
        _read_text(workspace, "d.err"),
    )

    data = _read(os.path.join(workspace, ".xanylabelingrc"))
    assert data["canvas"]["epsilon"] in (9.0, 10.0)


def test_stale_process_cannot_replace_a_field_written_elsewhere(workspace):
    """The recorded P1 gap: an unrelated save must not absorb a foreign value.

    Process A saves a different field, which re-reads the document, and then
    submits a value it drafted before process B changed that field.  A keeps
    its original baseline, so the transaction must report a conflict instead
    of silently overwriting B.
    """

    _start(workspace, {"canvas": {"epsilon": 8.0, "label_font_size": 8}})
    user_config.end_session()
    barrier = os.path.join(workspace, "barrier")
    written_by_b = os.path.join(workspace, "b.done")

    stale = _spawn_steps_worker(
        workspace,
        "a",
        [
            {"key": "canvas.label_font_size", "value": 22},
            {
                "key": "canvas.epsilon",
                "value": 9.0,
                "baseline": 8.0,
                "wait_for": written_by_b,
            },
        ],
        barrier,
    )
    writer = _spawn_steps_worker(
        workspace,
        "b",
        [
            {
                "key": "canvas.epsilon",
                "value": 9.5,
                "done": written_by_b,
            }
        ],
        barrier,
    )
    open(barrier, "w", encoding="utf-8").close()

    assert _finish_worker(writer) == 0, _read_text(workspace, "b.err")
    assert _finish_worker(stale) == 3, (
        _read_text(workspace, "a.out"),
        _read_text(workspace, "a.err"),
    )

    data = _read(os.path.join(workspace, ".xanylabelingrc"))
    assert data["canvas"]["epsilon"] == 9.5
    assert data["canvas"]["label_font_size"] == 22


def test_fresh_process_reads_the_committed_document(workspace):
    from anylabeling.config import normalize_user_config

    session = user_config.begin_session(
        target_path=os.path.join(workspace, ".xanylabelingrc"),
        origin="file",
        template=copy.deepcopy(TEMPLATE),
        effective=copy.deepcopy(TEMPLATE),
        disk_data=None,
        ensure_created=True,
        normalizer=normalize_user_config,
    )
    session.save({"canvas.epsilon": 9.25, "model_hub": "modelscope"})
    target = session.target_path
    user_config.end_session()

    output = os.path.join(workspace, "reader.out")
    code = (
        "import os, sys\n"
        "sys.path.insert(0, os.getcwd())\n"
        "from anylabeling import config\n"
        "values = config.get_config(sys.argv[1], None)\n"
        "open(sys.argv[2], 'w', encoding='utf-8').write("
        "str(values['canvas']['epsilon']) + '|' + values['model_hub'])\n"
    )
    subprocess.run(
        [sys.executable, "-c", code, target, output],
        cwd=REPO_ROOT,
        check=True,
    )
    with open(output, encoding="utf-8") as handle:
        assert handle.read() == "9.25|modelscope"
