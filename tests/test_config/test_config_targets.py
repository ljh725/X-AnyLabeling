"""Startup configuration target and transient-overlay tests."""

import copy
import os
import shutil
import uuid

import pytest
import yaml

from anylabeling import config as app_config
from anylabeling import user_config

REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)


def _workspace():
    path = os.path.join(REPO_ROOT, ".tmp", "config-targets", uuid.uuid4().hex)
    os.makedirs(path, exist_ok=True)
    return path


@pytest.fixture
def workspace():
    path = _workspace()
    previous = app_config.get_work_directory()
    try:
        yield path
    finally:
        user_config.end_session()
        app_config.set_work_directory(previous)
        shutil.rmtree(path, ignore_errors=True)


def _read(path):
    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def test_default_startup_uses_work_directory_and_is_stable(workspace):
    app_config.set_work_directory(workspace)
    target = os.path.join(workspace, ".xanylabelingrc")
    config = app_config.get_config(target, None)
    assert user_config.current_session().target_path == os.path.normpath(target)
    assert os.path.isfile(target)
    assert config["canvas"]["epsilon"] == _read(target)["canvas"]["epsilon"]

    previous_cwd = os.getcwd()
    os.chdir(REPO_ROOT)
    try:
        user_config.save_values({"model_hub": "modelscope"})
    finally:
        os.chdir(previous_cwd)
    assert _read(target)["model_hub"] == "modelscope"


def test_work_directory_parameter_selects_its_own_file(workspace):
    app_config.set_work_directory(workspace)
    target = os.path.join(workspace, ".xanylabelingrc")
    app_config.get_config(target, None)
    user_config.save_values({"canvas.epsilon": 9.5})
    assert _read(target)["canvas"]["epsilon"] == 9.5


def test_file_config_wins_over_work_directory(workspace):
    other_dir = os.path.join(workspace, "profile")
    os.makedirs(other_dir, exist_ok=True)
    app_config.set_work_directory(other_dir)
    chosen = os.path.join(workspace, "custom", "settings.yaml")
    os.makedirs(os.path.dirname(chosen), exist_ok=True)

    app_config.get_config(chosen, None)
    assert user_config.current_session().target_path == os.path.normpath(chosen)
    user_config.save_values({"canvas.epsilon": 9.5})

    assert _read(chosen)["canvas"]["epsilon"] == 9.5
    assert not os.path.exists(
        os.path.join(other_dir, ".xanylabelingrc")
    ), "the working-directory file must not be created or rewritten"


def test_inline_config_overrides_are_not_persisted(workspace):
    app_config.set_work_directory(workspace)
    default_target = os.path.join(workspace, ".xanylabelingrc")
    inline = yaml.safe_dump({"canvas": {"epsilon": 9.9}})

    config = app_config.get_config(inline, None)
    session = user_config.current_session()
    assert session.target_path == os.path.normpath(default_target)
    assert config["canvas"]["epsilon"] == 9.9

    user_config.save_values({"model_hub": "modelscope"})
    stored = _read(default_target)
    assert stored["canvas"]["epsilon"] != 9.9
    assert stored["model_hub"] == "modelscope"


def test_command_line_overrides_are_not_persisted(workspace):
    app_config.set_work_directory(workspace)
    target = os.path.join(workspace, ".xanylabelingrc")
    config = app_config.get_config(
        target, {"canvas": {"epsilon": 9.9}, "labels": ["car"]}
    )
    assert config["canvas"]["epsilon"] == 9.9

    user_config.save_values({"model_hub": "modelscope"})
    stored = _read(target)
    assert stored["canvas"]["epsilon"] != 9.9
    assert stored["model_hub"] == "modelscope"
    assert not stored["labels"]


def test_existing_file_value_wins_over_template_and_cli(workspace):
    app_config.set_work_directory(workspace)
    target = os.path.join(workspace, ".xanylabelingrc")
    with open(target, "w", encoding="utf-8") as handle:
        yaml.safe_dump(
            {"canvas": {"epsilon": 7.5}, "theme": "dark"}, handle
        )

    config = app_config.get_config(
        target, {"canvas": {"epsilon": 9.9}}
    )
    assert config["canvas"]["epsilon"] == 9.9
    assert config["theme"] == "dark"

    user_config.save_values({"model_hub": "modelscope"})
    stored = _read(target)
    assert stored["canvas"]["epsilon"] == 7.5
    assert stored["theme"] == "dark"


def test_legacy_read_path_does_not_create_files(workspace, monkeypatch):
    app_config.set_work_directory(workspace)
    monkeypatch.setattr(
        app_config, "current_config_file", os.path.join(workspace, "missing.yaml")
    )
    config = app_config.get_config()
    template = app_config.get_default_config()
    assert config["canvas"]["epsilon"] == template["canvas"]["epsilon"]
    assert not os.path.exists(os.path.join(workspace, ".xanylabelingrc"))
    assert not os.path.exists(os.path.join(workspace, "missing.yaml"))


def test_first_start_uses_a_migrated_legacy_file(workspace):
    """Task 2.2: the migration result must reach the first effective view."""

    app_config.set_work_directory(workspace)
    target = os.path.join(workspace, ".xanylabelingrc")
    legacy = os.path.join(workspace, ".anylabelingrc")
    digit_entry = {"mode": "rectangle", "label": "car"}
    with open(legacy, "w", encoding="utf-8") as handle:
        yaml.safe_dump(
            {
                "shortcuts": {"open": "Ctrl+Shift+O"},
                "digit_shortcuts": {1: digit_entry},
                "theme": "dark",
            },
            handle,
        )

    config = app_config.get_config(target, None)

    assert user_config.current_session().disk_exists
    assert config["shortcuts"]["open"] == "Ctrl+Shift+O"
    assert config["digit_shortcuts"][1] == digit_entry
    assert config["theme"] == "dark"
    assert _read(target)["shortcuts"]["open"] == "Ctrl+Shift+O"

    # The second start reads the migrated file and sees the same values.
    user_config.end_session()
    again = app_config.get_config(target, None)
    assert again["shortcuts"]["open"] == "Ctrl+Shift+O"
    assert again["digit_shortcuts"][1] == digit_entry


def test_existing_target_is_not_overwritten_by_legacy_migration(workspace):
    app_config.set_work_directory(workspace)
    target = os.path.join(workspace, ".xanylabelingrc")
    legacy = os.path.join(workspace, ".anylabelingrc")
    with open(legacy, "w", encoding="utf-8") as handle:
        yaml.safe_dump({"shortcuts": {"open": "Ctrl+L"}}, handle)
    with open(target, "w", encoding="utf-8") as handle:
        yaml.safe_dump({"shortcuts": {"open": "Ctrl+T"}}, handle)

    config = app_config.get_config(target, None)

    assert config["shortcuts"]["open"] == "Ctrl+T"
    assert _read(target)["shortcuts"]["open"] == "Ctrl+T"


def test_transient_overrides_survive_an_unrelated_save(workspace):
    """A CLI/inline value stays transient instead of being reset or stored."""

    app_config.set_work_directory(workspace)
    target = os.path.join(workspace, ".xanylabelingrc")
    config = app_config.get_config(target, {"canvas": {"epsilon": 9.9}})

    user_config.save_values({"model_hub": "modelscope"})

    assert config["canvas"]["epsilon"] == 9.9
    assert _read(target)["canvas"]["epsilon"] != 9.9
    assert _read(target)["model_hub"] == "modelscope"
