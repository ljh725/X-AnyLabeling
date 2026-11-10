"""Local conftest for the correction-metrics unit tests.

The SQLite-backed tests need a writable scratch directory per case.  This
sandbox denies writes to the system temp directory *and* to the pre-seeded
``PYTEST_DEBUG_TEMPROOT`` directory, and ``tempfile.mkdtemp()``'s ``0o700``
directory becomes unopenable under the sandbox ACL, so pytest's own ``tmp_path``
raises ``PermissionError: WinError 5`` here.  The fixture below therefore keeps
pytest's behaviour wherever it works and falls back to
``synthetic.workdir()`` (a package-local scratch tree, removed at exit) when it
does not.
"""

from __future__ import annotations

import pytest

from . import synthetic

collect_ignore_glob = ["_work", "_work/*"]


@pytest.fixture
def tmp_path(tmp_path_factory):
    """Writable per-test scratch directory, with a sandbox-safe fallback."""
    try:
        return tmp_path_factory.mktemp("case")
    except OSError:
        return synthetic.workdir()
