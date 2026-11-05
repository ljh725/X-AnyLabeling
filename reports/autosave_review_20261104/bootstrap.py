"""Start the production config session missing from legacy GUI fixtures."""
import copy
import os
import pytest


@pytest.fixture(autouse=True)
def configuration_session(isolated_user_configuration):
    from anylabeling import user_config
    from anylabeling.config import normalize_user_config
    from anylabeling.views.labeling.settings.schema import load_template_config

    config = copy.deepcopy(load_template_config())
    user_config.begin_session(
        target_path=os.path.join(isolated_user_configuration, ".xanylabelingrc"),
        origin="file", template=copy.deepcopy(config), effective=config,
        disk_data=None, ensure_created=True, normalizer=normalize_user_config,
    )
    yield
