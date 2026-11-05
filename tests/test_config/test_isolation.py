"""The verification harness must not touch the real user configuration.

Task 6.1 of ``fix-user-settings-persistence``: every test has to run against a
private target and a private ``QSettings`` file, the global state has to be
restored afterwards, and a save that targets anything outside the isolated
area has to fail loudly instead of silently writing the developer's profile.
"""

import os

import pytest

from PyQt6 import QtCore

from anylabeling import config as app_config
from anylabeling import user_config

REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
ISOLATION_ROOT = os.path.join(REPO_ROOT, ".tmp")


def _path_state(path):
    try:
        stat = os.stat(path)
    except OSError:
        return (False, None, None)
    return (True, stat.st_size, stat.st_mtime_ns)


def _real_user_config_paths():
    home = os.path.expanduser("~")
    return (
        os.path.join(home, user_config.DEFAULT_CONFIG_FILENAME),
        os.path.join(home, user_config.LEGACY_CONFIG_FILENAME),
    )


def test_isolated_target_and_settings_location(isolated_user_configuration):
    config_path = os.environ[user_config.CONFIG_PATH_ENV]
    assert os.path.abspath(config_path).startswith(
        os.path.abspath(isolated_user_configuration)
    )
    assert os.path.abspath(app_config.get_work_directory()).startswith(
        os.path.abspath(isolated_user_configuration)
    )

    settings = QtCore.QSettings("anylabeling", "anylabeling")
    settings.setValue("isolation-probe", "1")
    settings.sync()
    settings_path = os.path.abspath(settings.fileName())
    assert settings_path.startswith(
        os.path.abspath(isolated_user_configuration)
    )
    settings.remove("isolation-probe")
    settings.sync()


def test_saving_a_preference_never_touches_the_user_profile():
    real_paths = _real_user_config_paths()
    before = [_path_state(path) for path in real_paths]

    target = os.path.join(ISOLATION_ROOT, "isolation-probe", "profile")
    os.makedirs(target, exist_ok=True)
    config_file = os.path.join(target, ".xanylabelingrc")
    app_config.set_work_directory(target)
    config = app_config.get_config(config_file, None)
    user_config.save_values({"model_hub": "modelscope"})
    assert config["model_hub"] == "modelscope"

    after = [_path_state(path) for path in real_paths]
    assert before == after, "the real user configuration was modified"


def test_save_outside_the_isolated_area_is_refused():
    outside = os.path.join(REPO_ROOT, "not-isolated-profile")
    os.makedirs(outside, exist_ok=True)
    target = os.path.join(outside, ".xanylabelingrc")

    session = user_config.begin_session(
        target_path=target,
        origin="file",
        template={"theme": "light"},
        effective={"theme": "light"},
        disk_data=None,
        ensure_created=False,
        normalizer=lambda value: value,
    )
    try:
        with pytest.raises(AssertionError):
            session.save({"theme": "dark"})
        assert not os.path.exists(target)
    finally:
        import shutil

        shutil.rmtree(outside, ignore_errors=True)


def test_previous_global_state_is_restored_after_a_test():
    """The fixture saves and restores even values that were ``None``."""

    from anylabeling import user_config as module

    previous = module.current_session()
    marker = object()

    module.install_session(marker)
    try:
        assert module.current_session() is marker
    finally:
        module.install_session(previous)

    assert module.current_session() is previous


@pytest.mark.parametrize("exceptional", [False, True])
@pytest.mark.parametrize("empty_state", [False, True])
def test_fixture_lifecycle_restores_settings_path_and_global_state(
    exceptional, empty_state
):
    """Exercise teardown, nested use and an interrupted test."""
    import importlib.util
    import uuid

    specification = importlib.util.spec_from_file_location(
        "isolation_lifecycle_fixture",
        os.path.join(REPO_ROOT, "tests", "conftest.py"),
    )
    fixture_module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(fixture_module)
    isolated_user_configuration = fixture_module.isolated_user_configuration

    real_settings = QtCore.QSettings
    while hasattr(real_settings, "_real"):
        real_settings = real_settings._real

    # A unique, nonexistent organization avoids reading any real settings.
    organization = "settings-fixture-probe-" + uuid.uuid4().hex

    def ini_location():
        return real_settings(
            real_settings.Format.IniFormat,
            real_settings.Scope.UserScope,
            organization,
            "state",
        ).fileName()

    with pytest.MonkeyPatch.context() as original:
        if empty_state:
            original.setattr(app_config, "_work_directory", None)
            original.setattr(app_config, "current_config_file", None)
            original.delenv(user_config.CONFIG_PATH_ENV, raising=False)
        before = (
            ini_location(),
            real_settings.defaultFormat(),
            QtCore.QSettings,
            app_config._work_directory,
            app_config.current_config_file,
            os.environ.get(user_config.CONFIG_PATH_ENV),
            user_config.current_session(),
        )
        with pytest.MonkeyPatch.context() as patch:
            lifecycle = isolated_user_configuration.__wrapped__(patch)
            next(lifecycle)
            if exceptional:
                with pytest.raises(RuntimeError, match="interrupted"):
                    lifecycle.throw(RuntimeError("interrupted"))
            else:
                lifecycle.close()
        after = (
            ini_location(),
            real_settings.defaultFormat(),
            QtCore.QSettings,
            app_config._work_directory,
            app_config.current_config_file,
            os.environ.get(user_config.CONFIG_PATH_ENV),
            user_config.current_session(),
        )
        assert after == before
