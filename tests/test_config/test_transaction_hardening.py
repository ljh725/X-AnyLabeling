"""Storage failure injection, baseline protection and recovery tests.

Covers the gaps recorded in ``openspec/changes/fix-user-settings-persistence``
tasks 3.2-3.5: the draft baseline must survive an unrelated save, an external
write between the locked re-read and the replacement must be refused, every
storage failure must surface as one displayable error, and a restored backup
must rebuild the effective configuration instead of overlaying the old one.
"""

import copy
import os
import shutil
import uuid

import pytest
import yaml

from anylabeling import user_config

REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

TEMPLATE = {
    "canvas": {"epsilon": 8.0, "label_font_size": 8},
    "shortcuts": {"open": "Ctrl+O", "save": "Ctrl+S"},
    "digit_shortcuts": {},
}


def _workspace():
    path = os.path.join(
        REPO_ROOT, ".tmp", "transaction-hardening", uuid.uuid4().hex
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


def _start(workspace, disk=None):
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
        normalizer=normalize_user_config,
    )


# -- baselines and effective synchronization ------------------------------


def test_unrelated_save_syncs_external_change_into_effective(workspace):
    first = _start(
        workspace, {"canvas": {"epsilon": 8.0, "label_font_size": 8}}
    )
    second = _start(
        workspace, {"canvas": {"epsilon": 8.0, "label_font_size": 8}}
    )

    second.save({"canvas.label_font_size": 14})
    assert first.effective["canvas"]["label_font_size"] == 8

    first.save({"canvas.epsilon": 9.0})

    assert first.effective["canvas"]["label_font_size"] == 14
    assert _read(os.path.join(workspace, ".xanylabelingrc"))["canvas"][
        "epsilon"
    ] == 9.0


def test_old_draft_field_conflicts_after_an_unrelated_save(workspace):
    first = _start(
        workspace, {"canvas": {"epsilon": 8.0, "label_font_size": 8}}
    )
    second = _start(
        workspace, {"canvas": {"epsilon": 8.0, "label_font_size": 8}}
    )

    # Another entry writes X...
    second.save({"canvas.label_font_size": 14})
    # ...this process commits an unrelated Y and must not absorb X.
    first.save({"canvas.epsilon": 9.0})

    stale = user_config.ConfigPatch(
        {"canvas.label_font_size": 20},
        baselines={"canvas.label_font_size": 8},
    )
    with pytest.raises(user_config.ConfigConflict) as excinfo:
        first.save(stale)

    assert excinfo.value.conflicts == ["canvas.label_font_size"]
    assert excinfo.value.conflict_keys == ["canvas.label_font_size"]
    data = _read(os.path.join(workspace, ".xanylabelingrc"))
    assert data["canvas"]["label_font_size"] == 14


def test_reload_adopts_the_newer_document(workspace):
    first = _start(workspace, {"canvas": {"epsilon": 8.0}})
    second = _start(workspace, {"canvas": {"epsilon": 8.0}})
    second.save({"canvas.epsilon": 9.5})

    assert first.reload() is True
    assert first.effective["canvas"]["epsilon"] == 9.5
    assert first.reload() is False


def test_deleted_field_can_be_submitted_as_absent_baseline(workspace):
    session = _start(
        workspace, {"shortcuts": {"open": "Ctrl+O", "save": "Ctrl+S"}}
    )
    patch = user_config.ConfigPatch(
        {"shortcuts.zoom_in": ["Ctrl+="]},
        baselines={"shortcuts.zoom_in": user_config.DELETE},
    )
    session.save(patch)
    data = _read(session.target_path)
    assert data["shortcuts"]["zoom_in"] == ["Ctrl+="]
    assert data["shortcuts"]["save"] == "Ctrl+S"


# -- external change and failure injection --------------------------------


def test_external_change_between_read_and_replace_is_refused(
    workspace, monkeypatch
):
    session = _start(workspace, {"canvas": {"epsilon": 8.0}})
    target = session.target_path
    real_verify = user_config._verify_document

    def verify_then_edit(data, payload):
        real_verify(data, payload)
        _write(
            target,
            {"canvas": {"epsilon": 8.0, "label_font_size": 12}},
        )

    monkeypatch.setattr(user_config, "_verify_document", verify_then_edit)
    with pytest.raises(user_config.ConfigExternalChange) as excinfo:
        session.save({"canvas.epsilon": 9.0})
    monkeypatch.setattr(user_config, "_verify_document", real_verify)

    assert excinfo.value.retryable is True
    data = _read(target)
    assert data["canvas"]["epsilon"] == 8.0
    assert data["canvas"]["label_font_size"] == 12
    assert session.effective["canvas"]["epsilon"] == 8.0


def test_backup_failure_keeps_the_target_untouched(workspace, monkeypatch):
    session = _start(workspace, {"canvas": {"epsilon": 8.0}})
    target = session.target_path
    before = _read(target)
    real_write = user_config._atomic_write_bytes

    def fail_on_backup(path, payload):
        if path.endswith(user_config.BACKUP_SUFFIX):
            raise user_config.ConfigWriteError("simulated backup failure")
        return real_write(path, payload)

    monkeypatch.setattr(user_config, "_atomic_write_bytes", fail_on_backup)
    with pytest.raises(user_config.ConfigWriteError):
        session.save({"canvas.epsilon": 9.0})
    monkeypatch.setattr(user_config, "_atomic_write_bytes", real_write)

    assert _read(target) == before
    assert session.effective["canvas"]["epsilon"] == 8.0
    assert not os.path.exists(target + user_config.BACKUP_SUFFIX)


def test_target_replace_failure_keeps_original_and_backup(
    workspace, monkeypatch
):
    session = _start(workspace, {"canvas": {"epsilon": 8.0}})
    target = session.target_path
    before = _read(target)
    real_write = user_config._atomic_write_bytes

    def fail_on_target(path, payload):
        if not path.endswith(user_config.BACKUP_SUFFIX):
            raise user_config.ConfigWriteError("simulated replace failure")
        return real_write(path, payload)

    monkeypatch.setattr(user_config, "_atomic_write_bytes", fail_on_target)
    with pytest.raises(user_config.ConfigWriteError):
        session.save({"canvas.epsilon": 9.0})
    monkeypatch.setattr(user_config, "_atomic_write_bytes", real_write)

    assert _read(target) == before
    assert _read(target + user_config.BACKUP_SUFFIX) == before
    assert session.effective["canvas"]["epsilon"] == 8.0
    assert not [
        name for name in os.listdir(workspace) if name.endswith(".tmp")
    ]


def test_temporary_file_creation_failure_is_a_storage_error(
    workspace, monkeypatch
):
    session = _start(workspace, {"canvas": {"epsilon": 8.0}})
    target = session.target_path
    before = _read(target)

    def failing_mkstemp(**_kwargs):
        raise OSError("simulated mkstemp failure")

    monkeypatch.setattr(user_config.tempfile, "mkstemp", failing_mkstemp)
    with pytest.raises(user_config.ConfigWriteError):
        session.save({"canvas.epsilon": 9.0})
    monkeypatch.undo()

    assert _read(target) == before
    session.save({"canvas.epsilon": 9.0})
    assert _read(target)["canvas"]["epsilon"] == 9.0


def test_repaired_document_can_be_saved_again(workspace):
    target = os.path.join(workspace, ".xanylabelingrc")
    with open(target, "w", encoding="utf-8") as handle:
        handle.write("canvas: [unclosed\n")
    session = user_config.begin_session(
        target_path=target,
        origin="file",
        template=copy.deepcopy(TEMPLATE),
        effective=copy.deepcopy(TEMPLATE),
        disk_data=None,
        disk_error=user_config.ConfigInvalid("damaged", path=target),
        normalizer=lambda value: value,
    )
    with pytest.raises(user_config.ConfigInvalid):
        session.save({"canvas.epsilon": 9.0})

    _write(target, {"canvas": {"epsilon": 8.0}})
    session.save({"canvas.epsilon": 9.0})

    assert _read(target)["canvas"]["epsilon"] == 9.0


# -- recovery --------------------------------------------------------------


def test_restore_rebuilds_effective_instead_of_overlaying(workspace):
    session = _start(
        workspace,
        {"canvas": {"epsilon": 8.0}, "shortcuts": {"open": "Ctrl+O"}},
    )
    session.save({"canvas.epsilon": 9.0})
    session.save(
        {("digit_shortcuts", 1): {"mode": "rectangle", "label": "car"}}
    )
    # The next save rotates the backup to the document that already contains
    # the digit mapping; ``model_hub`` is only written afterwards, so it must
    # not survive the restore.
    session.save({"model_hub": "modelscope"})
    with open(session.target_path, "w", encoding="utf-8") as handle:
        handle.write("not: [valid")

    user_config.restore_backup()

    assert session.effective["canvas"]["epsilon"] == 9.0
    assert session.effective["digit_shortcuts"][1] == {
        "mode": "rectangle",
        "label": "car",
    }
    assert session.effective.get("model_hub") != "modelscope"
    saved = _read(session.target_path)
    assert saved["canvas"]["epsilon"] == 9.0
    assert 1 in saved["digit_shortcuts"]


def test_restore_normalizes_legacy_backup_keys(workspace):
    from anylabeling.config import normalize_user_config

    target = os.path.join(workspace, ".xanylabelingrc")
    _write(target, {"canvas": {"epsilon": 8.0}})
    _write(target + user_config.BACKUP_SUFFIX, {"epsilon": 7.0})
    session = user_config.begin_session(
        target_path=target,
        origin="file",
        template=copy.deepcopy(TEMPLATE),
        effective=copy.deepcopy(TEMPLATE),
        disk_data={"canvas": {"epsilon": 8.0}},
        normalizer=normalize_user_config,
    )

    user_config.restore_backup()

    assert session.effective["canvas"]["epsilon"] == 7.0
    assert "epsilon" not in session.effective


def test_restore_keeps_a_second_copy_of_the_damaged_file(workspace):
    session = _start(workspace, {"canvas": {"epsilon": 8.0}})
    session.save({"canvas.epsilon": 9.0})

    for _attempt in range(2):
        with open(session.target_path, "w", encoding="utf-8") as handle:
            handle.write("not: [valid")
        user_config.restore_backup()

    copies = [name for name in os.listdir(workspace) if ".corrupt-" in name]
    assert len(copies) == 2, copies
    # The second restore uses the same (still valid) backup.
    assert _read(session.target_path)["canvas"]["epsilon"] == 8.0


# -- merged validation and unsafe full snapshots ---------------------------


def test_merged_shortcut_conflict_is_refused(workspace):
    from anylabeling.config import validate_merged_config

    session = _start(
        workspace,
        {"shortcuts": {"open": "Ctrl+O", "save": "Ctrl+S"}},
    )
    session.validator = validate_merged_config

    with pytest.raises(user_config.ConfigConflict) as excinfo:
        session.save({"shortcuts.save": "Ctrl+O"})

    assert "shortcuts.save" in excinfo.value.conflict_keys
    assert _read(session.target_path)["shortcuts"]["save"] == "Ctrl+S"


def test_whitelisted_duplicate_shortcut_is_allowed(workspace):
    from anylabeling.config import validate_merged_config

    session = _start(workspace, {"shortcuts": {"undo": "Ctrl+Z"}})
    session.validator = validate_merged_config

    session.save({"shortcuts.undo_last_point": "Ctrl+Z"})
    assert (
        _read(session.target_path)["shortcuts"]["undo_last_point"] == "Ctrl+Z"
    )


def test_save_config_refuses_an_unsafe_whole_snapshot(workspace):
    from anylabeling import config as app_config

    session = _start(workspace, {"canvas": {"epsilon": 8.0}})
    snapshot = copy.deepcopy(session.effective)
    snapshot["canvas"]["epsilon"] = 9.0

    assert app_config.save_config(snapshot) is False
    assert _read(session.target_path)["canvas"]["epsilon"] == 8.0


def test_save_config_accepts_explicit_fields_and_baselines(workspace):
    from anylabeling import config as app_config

    session = _start(workspace, {"canvas": {"epsilon": 8.0}})
    snapshot = copy.deepcopy(session.effective)
    snapshot["canvas"]["epsilon"] = 9.0

    assert app_config.save_config(snapshot, fields={"canvas.epsilon": 9.0})
    assert _read(session.target_path)["canvas"]["epsilon"] == 9.0

    # A baseline from before another entry's change is a conflict.
    stale = copy.deepcopy(snapshot)
    stale["canvas"]["epsilon"] = 9.5
    session2 = _start(workspace, {"canvas": {"epsilon": 8.0}})
    session2.save({"canvas.epsilon": 9.9})
    assert (
        app_config.save_config(
            stale, baselines={"canvas": {"epsilon": 9.0}}
        )
        is False
    )
    assert _read(session2.target_path)["canvas"]["epsilon"] == 9.9


def test_digit_paths_keep_integer_segments(workspace):
    from anylabeling import config as app_config

    session = _start(workspace, {"digit_shortcuts": {}})
    snapshot = copy.deepcopy(session.effective)
    snapshot["digit_shortcuts"][2] = {"mode": "polygon", "label": "road"}

    assert app_config.save_config(snapshot, baselines=session.effective)

    data = _read(session.target_path)
    assert data["digit_shortcuts"][2] == {
        "mode": "polygon",
        "label": "road",
    }
    assert all(
        isinstance(key, int) for key in data["digit_shortcuts"].keys()
    )
