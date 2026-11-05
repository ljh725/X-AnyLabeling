"""Run isolated negative controls without overwriting workspace source.

Run from the repository root with the test environment's Python:
  python openspec/changes/fix-rectangle-preview-overlap/evidence/verify_preview_controls.py dirty-signal
  python openspec/changes/fix-rectangle-preview-overlap/evidence/verify_preview_controls.py pre-p2
Each control must produce assertion failures (pytest exit 1), not errors.
"""

import ast
import contextlib
import io
import os
from pathlib import Path
import subprocess
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path.cwd()))

import pytest
from anylabeling.views.labeling.widgets import point_fit
from anylabeling.views.labeling.widgets.canvas import Canvas

mode = sys.argv[1]
original = Canvas._build_point_fit_preview
if mode == "dirty-signal":
    def unwanted_signal(self):
        preview = original(self)
        if preview is not None:
            self.shape_moved.emit()
        return preview

    Canvas._build_point_fit_preview = unwanted_signal
    selection = (
        "preview_cancel_preserves_host_dirty or "
        "nudge_preview_preserves_host_dirty or fit_commit_marks_host_dirty_once"
    )
elif mode == "pre-p2":
    # Load only the unmodified historical method, not an entire old module
    # or checkout. Everything else, including the tests, is current code.
    source = subprocess.check_output([
        "git", "show",
        "9673d3b9:anylabeling/views/labeling/widgets/point_fit.py",
    ], encoding="utf-8")
    tree = ast.parse(source)
    owner = next(n for n in tree.body
                 if isinstance(n, ast.ClassDef) and n.name == "PointFitMixin")
    method = next(n for n in owner.body
                  if isinstance(n, ast.FunctionDef)
                  and n.name == "_build_point_fit_preview")
    namespace = dict(vars(point_fit))
    exec(compile(ast.Module(body=[method], type_ignores=[]),
                 "historical-9673d3b9-point_fit.py", "exec"), namespace)
    Canvas._build_point_fit_preview = namespace[method.name]
    selection = "test_keyboard_nudge_invalidates_hover_candidate"
else:
    raise SystemExit("Choose dirty-signal or pre-p2")

capture = io.StringIO()
try:
    with contextlib.redirect_stdout(capture), contextlib.redirect_stderr(capture):
        result = pytest.main([
            "tests/test_canvas/test_rectangle_preview_overlap.py",
            "-k", selection, "-q", "--tb=short", "--color=no",
            "-p", "no:cacheprovider",
        ])
finally:
    Canvas._build_point_fit_preview = original
output = capture.getvalue()
Path(__file__).with_name(f"{mode}.txt").write_text(output, encoding="utf-8")
print(output)
print(f"Control {mode}: pytest exit {int(result)} (expected 1)")
raise SystemExit(0 if int(result) == 1 and " ERROR " not in output else 1)
