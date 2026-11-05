"""Shared Qt application and user-configuration isolation.

Every test runs with a private configuration target, a private working
directory and a private ``QSettings`` INI file so that no verification run can
read, rewrite or create the real user configuration or registry keys.
Temporary directories are created with ``os.makedirs`` (not
``tempfile.mkdtemp``) so that the directory stays traversable on Windows
sandboxes that add a restrictive discretionary ACL to ``mkdtemp`` output.

``QSettings(organization, application)`` writes to the Windows registry even
when ``setDefaultFormat(IniFormat)`` is set and a user-scope INI path is
configured, so the fixture also substitutes a factory that binds every
construction to one INI file inside the isolated root.  Without that the
isolation only looked correct while the application still wrote to
``HKEY_CURRENT_USER``.

The fixture restores everything it changed - including values that were
``None`` before the test - and installs a write guard that fails the test if
any configuration save targets a path outside the isolated area.
"""

import os
import shutil
import uuid

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6 import QtCore, QtWidgets

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
#: Every configuration a test may touch has to live below this directory.
#: Tests that build their own workspace use it too, so the guard rejects only
#: real escapes (the user profile or another project) instead of duplicated
#: harness roots.
_ISOLATION_ROOT = os.path.join(_REPO_ROOT, ".tmp")


class _IsolatedQSettings:
    """Stand-in for ``QtCore.QSettings`` bound to one INI file.

    Attribute access (``QSettings.Format``, ``QSettings.Scope``) falls through
    to the real class, so call sites keep working unchanged.
    """

    def __init__(self, ini_path: str):
        self._ini_path = ini_path
        self._real = QtCore.QSettings

    def __call__(self, *_args, **_kwargs):
        return self._real(self._ini_path, self._real.Format.IniFormat)

    def __getattr__(self, name):
        return getattr(self._real, name)


def _is_inside(path: str, root: str) -> bool:
    try:
        candidate = os.path.normcase(os.path.abspath(path))
        normalized_root = os.path.normcase(os.path.abspath(root))
        return os.path.commonpath([candidate, normalized_root]) == (
            normalized_root
        )
    except ValueError:  # different drives on Windows
        return False


@pytest.fixture(scope="session", autouse=True)
def qt_application():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    app.setQuitOnLastWindowClosed(False)
    yield app


@pytest.fixture(autouse=True)
def isolated_user_configuration(monkeypatch):
    """Give every test a private config file and ``QSettings`` location."""

    from anylabeling import config as app_config
    from anylabeling import user_config

    root = os.path.join(_REPO_ROOT, ".tmp", "pytest-config", uuid.uuid4().hex)
    os.makedirs(root, exist_ok=True)
    config_path = os.path.join(root, ".xanylabelingrc")
    settings_path = os.path.join(root, "settings.ini")

    previous_target = os.environ.get(user_config.CONFIG_PATH_ENV)
    previous_session = user_config.current_session()
    previous_work_directory = app_config._work_directory
    previous_config_file = app_config.current_config_file

    os.environ[user_config.CONFIG_PATH_ENV] = config_path
    app_config._work_directory = root
    app_config.current_config_file = None
    user_config.end_session()

    monkeypatch.setattr(QtCore, "QSettings", _IsolatedQSettings(settings_path))
    # The factory passes an explicit INI file/format, so no process-wide
    # format or setPath mutation (and no inferred path restoration) is needed.

    real_save = user_config.ConfigSession.save

    def guarded_save(self, patch, **kwargs):
        target = self.target_path
        if target and not _is_inside(target, _ISOLATION_ROOT):
            raise AssertionError(
                "test tried to write a user configuration outside the "
                f"isolated area: {target!r} (root: {_ISOLATION_ROOT!r})"
            )
        return real_save(self, patch, **kwargs)

    monkeypatch.setattr(user_config.ConfigSession, "save", guarded_save)
    real_write = user_config._atomic_write_bytes

    def guarded_write(path, payload):
        if not _is_inside(path, _ISOLATION_ROOT):
            raise AssertionError(
                f"configuration write outside isolated area: {path!r}"
            )
        return real_write(path, payload)

    # Initialization, backup recovery and kept-aside copies also write files;
    # protecting only save() leaves these entry points outside the guard.
    monkeypatch.setattr(user_config, "_atomic_write_bytes", guarded_write)
    try:
        yield root
    finally:
        user_config.end_session()
        user_config.install_session(previous_session)
        app_config._work_directory = previous_work_directory
        app_config.current_config_file = previous_config_file
        if previous_target is None:
            os.environ.pop(user_config.CONFIG_PATH_ENV, None)
        else:
            os.environ[user_config.CONFIG_PATH_ENV] = previous_target
        shutil.rmtree(root, ignore_errors=True)
