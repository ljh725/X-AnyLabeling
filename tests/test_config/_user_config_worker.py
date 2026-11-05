"""Subprocess worker used by the cross-process configuration tests.

Usage: python _user_config_worker.py '<json payload>'

Payload keys:

* ``target`` - configuration file the worker reads.
* ``barrier`` - file the worker waits for before running its steps.
* ``ready`` - file the worker creates once its session is installed.
* ``steps`` - list of field saves.  Each step is ``{"key", "value"}`` plus
  optional ``baseline`` (the value the caller started from), ``absent``
  (the field did not exist at baseline) and ``wait_for`` (a file that must
  exist before the step runs) and ``done`` (a file created after the step).
* ``key``/``value`` - legacy single-step form.

Exit codes: 0 all steps saved, 3 conflict, 4 other error.
"""

import json
import os
import sys
import time

sys.path.insert(0, os.getcwd())


def _wait_for(path, timeout=30):
    deadline = time.time() + timeout
    while not os.path.exists(path):
        if time.time() > deadline:
            return False
        time.sleep(0.02)
    return True


def _touch(path):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("done")


def main():
    payload = json.loads(sys.argv[1])
    from anylabeling import user_config
    from anylabeling.config import get_default_config, normalize_user_config

    target = payload["target"]
    data, _ = user_config.read_config_document(target)
    template = get_default_config()
    effective = template
    if data:
        effective = normalize_user_config(data)
    user_config.begin_session(
        target_path=target,
        origin="file",
        template=template,
        effective=effective,
        disk_data=data,
        normalizer=normalize_user_config,
    )
    _touch(payload["ready"])
    if not _wait_for(payload["barrier"]):
        print("barrier timeout", file=sys.stderr)
        return 2

    steps = payload.get("steps")
    if not steps:
        steps = [{"key": payload["key"], "value": payload["value"]}]

    for step in steps:
        wait_for = step.get("wait_for")
        if wait_for and not _wait_for(wait_for):
            print(f"step timeout waiting for {wait_for}", file=sys.stderr)
            return 2
        patch = user_config.ConfigPatch({step["key"]: step["value"]})
        if step.get("baseline") is not None:
            patch.set_baseline(step["key"], step["baseline"])
        elif step.get("absent"):
            patch.set_baseline(step["key"], user_config.DELETE)
        try:
            user_config.save_patch(patch)
        except user_config.ConfigConflict as error:
            print(f"conflict: {error}", file=sys.stderr)
            return 3
        except user_config.ConfigError as error:
            print(f"error: {error}", file=sys.stderr)
            return 4
        done = step.get("done")
        if done:
            _touch(done)
    return 0


if __name__ == "__main__":
    sys.exit(main())
