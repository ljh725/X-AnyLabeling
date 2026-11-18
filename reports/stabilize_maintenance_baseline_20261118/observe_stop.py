"""Observe the original Windows training-stop test in detached worktrees."""

import argparse
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import threading
import time
import traceback
from unittest.mock import patch


NODE = (
    "tests/test_auto_training/test_trainer.py::"
    "test_stop_training_terminates_silent_process_immediately"
)
REVISIONS = {
    "candidate": "0e4a223e2b8f74f9c8a9e093643b3fa581d8c293",
    "integration": "a7a9a1048f2eab1e3a0272cd57b5c400becca970",
}


def observe_pytest(args):
    """Trace stop, tree termination and the test's real thread join."""
    sys.path.insert(0, os.getcwd())
    import pytest
    from anylabeling.services.auto_training.ultralytics import trainer

    start = time.monotonic()
    worker = None
    training_process = None
    original_worker = trainer.TrainingManager._run_training
    original_stop = trainer.TrainingManager.stop_training
    original_terminate = trainer.terminate_process_tree
    original_run = subprocess.run
    original_join = threading.Thread.join

    def emit(event, **values):
        print("TRACE " + json.dumps({
            "seconds": round(time.monotonic() - start, 6),
            "event": event,
            "thread": threading.current_thread().name,
            **values,
        }), flush=True)

    def snapshot():
        frames = sys._current_frames()
        return {
            "child_pid": training_process.pid,
            "child_exit_code": training_process.poll(),
            "worker_alive": worker.is_alive(),
            "worker_stack": traceback.format_stack(frames[worker.ident])
            if worker.ident in frames else [],
            "terminator_stacks": {
                thread.name: traceback.format_stack(frames[thread.ident])
                for thread in threading.enumerate()
                if thread.name.endswith("(terminate)")
                and thread.ident in frames
            },
        }

    def run_worker(manager, payload_path):
        nonlocal worker
        worker = threading.current_thread()
        try:
            return original_worker(manager, payload_path)
        finally:
            emit(
                "worker_return",
                child_exit_code=training_process.poll()
                if training_process is not None else None,
                payload_exists=Path(payload_path).exists(),
            )

    def stop(manager, *positional, **keywords):
        nonlocal training_process
        training_process = manager.training_process
        emit("stop_call", **snapshot())
        result = original_stop(manager, *positional, **keywords)
        emit("stop_return", accepted=result, **snapshot())
        return result

    def terminate(process):
        emit("terminate_call", pid=process.pid, child_exit_code=process.poll())
        try:
            return original_terminate(process)
        finally:
            emit("terminate_return", child_exit_code=process.poll())

    def run(command, *positional, **keywords):
        if not isinstance(command, list) or command[0] != "taskkill":
            return original_run(command, *positional, **keywords)
        emit("taskkill_call", command=command)
        result = original_run(command, *positional, **keywords)
        emit("taskkill_return", returncode=result.returncode,
             forced="/F" in command, child_exit_code=training_process.poll())
        return result

    def join(thread, timeout=None):
        if thread is not worker:
            return original_join(thread, timeout)
        emit("join_call", timeout=timeout)
        result = original_join(thread, timeout)
        emit("join_return", **snapshot())
        return result

    emit("source", path=trainer.__file__)
    with (
        patch.object(trainer.TrainingManager, "_run_training", run_worker),
        patch.object(trainer.TrainingManager, "stop_training", stop),
        patch.object(trainer, "terminate_process_tree", terminate),
        patch.object(subprocess, "run", run),
        patch.object(threading.Thread, "join", join),
    ):
        result = pytest.main(args)
        if worker is not None and worker.is_alive():
            original_join(worker, timeout=10)
        if worker is not None and training_process is not None:
            emit("final", pytest_exit_code=int(result), **snapshot())
    return int(result)


def run_matrix(worktrees, output):
    """Run the original test once bare and three times observed per side."""
    script = Path(__file__).resolve()
    output.mkdir(parents=True, exist_ok=True)
    results = []
    env = {
        **os.environ,
        "QT_QPA_PLATFORM": "offscreen",
        "PYTHONIOENCODING": "utf-8",
    }
    env.pop("PYTHONPATH", None)
    for iteration in range(4):
        for label, expected in REVISIONS.items():
            tree = worktrees / label
            head = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=tree, text=True
            ).strip()
            assert head == expected
            assert not subprocess.check_output(
                ["git", "status", "--porcelain", "--untracked-files=no"],
                cwd=tree,
            )
            case = f"{label}-{iteration}"
            args = [
                NODE, "-vv", "-s", "--color=no", "-p", "no:cacheprovider",
                "-o", "faulthandler_timeout=12",
                "--basetemp", str(tree / ".tmp" / case),
            ]
            entry = [str(script), "--observe"] if iteration else ["-m", "pytest"]
            command = [sys.executable, *entry, *args]
            start = time.monotonic()
            with (output / f"{case}.txt").open("wb") as log:
                child = subprocess.Popen(
                    command, cwd=tree, env=env, stdout=log,
                    stderr=subprocess.STDOUT,
                )
                timed_out = False
                try:
                    code = child.wait(timeout=45)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(child.pid)],
                        stdout=log, stderr=subprocess.STDOUT, timeout=10,
                        check=True,
                    )
                    code = child.wait(timeout=5)
            record = {
                "case": case, "head": head, "cwd": str(tree),
                "command": command, "observed": bool(iteration),
                "exit_code": code, "timed_out": timed_out,
                "elapsed_seconds": round(time.monotonic() - start, 3),
            }
            results.append(record)
            (output / "runs.json").write_text(json.dumps({
                "python": sys.version, "platform": platform.platform(),
                "qt_platform": "offscreen", "hard_timeout_seconds": 45,
                "runs": results,
            }, indent=2) + "\n", encoding="utf-8")
            print(case, code, timed_out, flush=True)


if __name__ == "__main__":
    if sys.argv[1:2] == ["--observe"]:
        sys.exit(observe_pytest(sys.argv[2:]))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("worktrees", type=Path)
    parser.add_argument("output", type=Path)
    cli = parser.parse_args()
    run_matrix(cli.worktrees.resolve(), cli.output.resolve())
