"""Isolated user-configuration context for development scripts.

Screenshots, benchmarks and other tooling must never read or rewrite the real
user configuration (``~/.xanylabelingrc``) or the registry-backed ``QSettings``
store.  The scripts used to hand a template mapping straight to ``MainWindow``,
which bypassed :func:`anylabeling.config.get_config` and therefore never
installed a session: saving silently failed instead of writing to a temporary
location, so the isolation was never actually exercised.

``QSettings(organization, application)`` keeps using the Windows registry even
after ``setDefaultFormat(IniFormat)``, so the context also substitutes a small
factory binding every construction to one INI file inside the throw-away
directory.

:class:`IsolatedConfig` installs a *real* configuration session through the
same startup entry the application uses, so a script that saves a preference
exercises the true persistence path - and any bug in it shows up during
development instead of on a user machine.

Usage::

    with IsolatedConfig(root) as isolated:
        window = MainWindow(app, config=isolated.config)
        ...
    # everything (work directory, env override, QSettings, session) is
    # restored here, including values that were ``None`` before.
"""

from __future__ import annotations

import os

from PyQt6 import QtCore

from anylabeling import config as app_config
from anylabeling import user_config

DEFAULT_CONFIG_FILENAME = ".xanylabelingrc"


class _IsolatedQSettings:
    """Stand-in for ``QtCore.QSettings`` bound to one INI file."""

    def __init__(self, ini_path: str):
        self._ini_path = ini_path
        self._real = QtCore.QSettings

    def __call__(self, *_args, **_kwargs):
        return self._real(self._ini_path, self._real.Format.IniFormat)

    def __getattr__(self, name):
        return getattr(self._real, name)


class IsolatedConfig:
    """A temporary configuration target plus its QSettings location."""

    def __init__(
        self,
        root: str,
        *,
        filename: str = DEFAULT_CONFIG_FILENAME,
        create: bool = True,
    ):
        self.root = os.path.abspath(root)
        self.target_path = os.path.join(self.root, filename)
        self.settings_path = os.path.join(self.root, "settings.ini")
        self._create = create
        self._previous: dict | None = None
        self.config: dict | None = None

    def __enter__(self) -> "IsolatedConfig":
        os.makedirs(self.root, exist_ok=True)
        self._previous = {
            "session": user_config.current_session(),
            "work_directory": app_config._work_directory,
            "config_file": app_config.current_config_file,
            "env": os.environ.get(user_config.CONFIG_PATH_ENV),
            "qsettings": QtCore.QSettings,
        }
        app_config.set_work_directory(self.root)
        app_config.current_config_file = self.target_path
        os.environ[user_config.CONFIG_PATH_ENV] = self.target_path
        QtCore.QSettings = _IsolatedQSettings(self.settings_path)
        user_config.end_session()
        if self._create and not os.path.isfile(self.target_path):
            user_config.initialize_target(
                self.target_path,
                app_config.get_default_config(),
                force=True,
            )
        # ``get_config`` is the real startup entry: it resolves the target,
        # creates or migrates it under the cross-process lock and installs the
        # process session every settings entry shares.
        self.config = app_config.get_config(self.target_path, None)
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        previous = self._previous or {}
        user_config.end_session()
        user_config.install_session(previous.get("session"))
        app_config._work_directory = previous.get("work_directory")
        app_config.current_config_file = previous.get("config_file")
        env_value = previous.get("env")
        if env_value is None:
            os.environ.pop(user_config.CONFIG_PATH_ENV, None)
        else:
            os.environ[user_config.CONFIG_PATH_ENV] = env_value
        restored = previous.get("qsettings")
        if restored is not None:
            QtCore.QSettings = restored
        self._previous = None
        return False
