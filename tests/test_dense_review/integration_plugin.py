"""Opt-in real startup for legacy GUI integration fixtures.

Some tests construct MainWindow from a template instead of get_config(),
skipping the configuration session that real application startup creates.
Run those together with -p tests.test_dense_review.integration_plugin and
--basetemp below .tmp. This uses the real store, keeps the shared write guard,
and does not suppress persistence errors or mock preference writes.
"""

from pathlib import Path

import pytest

from anylabeling import config as app_config
from anylabeling import user_config


@pytest.fixture(autouse=True)
def real_isolated_startup(isolated_user_configuration):
    target = Path(isolated_user_configuration) / ".xanylabelingrc"
    app_config.get_config(str(target), None)
    assert user_config.current_session() is not None
