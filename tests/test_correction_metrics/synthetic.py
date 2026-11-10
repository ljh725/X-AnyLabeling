"""Deterministic synthetic annotation scenes for correction-metrics tests.

Implements the eight fixed acceptance samples of tasks.md **1.3**, following
``.local/stage/team/samples-design.md``: literal object IDs, integer geometry,
no RNG, no clock, no Qt and no PIL.  Every builder returns a plain list of
X-AnyLabeling label-format shape dicts -- exactly what ``core.snapshot()``
consumes -- so the tests are pure logic and run without a GUI.

Object-ID prefixes (samples-design.md §1.4)::

    p-  dense 30 portraits      s-  stress grid        o-  occluded small
    l-  partially locked        r-  mixed rectangles   g-  polygons
    t-  rotation                k-  point              n-  newly created
    u-  legacy unknown origin   m-  manual boxes       a-  AI boxes

Expected nets for every sample are documented in the builder docstrings and
asserted with literal numbers in the test modules (never recomputed from the
implementation under test).
"""

from __future__ import annotations

import atexit
import copy
import itertools
import shutil
from pathlib import Path

from anylabeling.services.correction_metrics.core import (
    SHAPE_ID,
    CorrectionRound,
    initialise_state,
    snapshot,
)

DENSE_LABELS = ("cat", "dog", "person", "car", "tree", "sign")
STRESS_LABELS = ("cat", "dog", "person")
LEGACY_LABELS = ("cat", "dog", "person", "car", "tree")


# ---------------------------------------------------------------------------
# shape builders
# ---------------------------------------------------------------------------
def rect(shape_id, label, box, **kw):
    """Return a rectangle shape dict from ``(left, top, right, bottom)``."""
    left, top, right, bottom = box
    shape = {
        SHAPE_ID: shape_id,
        "label": label,
        "points": [[left, top], [right, top], [right, bottom], [left, bottom]],
        "group_id": None,
        "description": "",
        "difficult": False,
        "shape_type": "rectangle",
        "flags": {},
        "attributes": {},
        "kie_linking": [],
        "score": None,
        "locked": False,
    }
    shape.update(kw)
    return shape


def polygon(shape_id, label, points, **kw):
    """Return a polygon shape dict (``shape_type='polygon'``)."""
    shape = rect(shape_id, label, (0, 0, 0, 0), shape_type="polygon", **kw)
    shape["points"] = [list(point) for point in points]
    return shape


def rotation(shape_id, label, points, **kw):
    """Return a rotated-box shape dict (``shape_type='rotation'``)."""
    shape = polygon(shape_id, label, points, **kw)
    shape["shape_type"] = "rotation"
    return shape


def point_mark(shape_id, label, xy, **kw):
    """Return a point shape dict (``shape_type='point'``)."""
    shape = polygon(shape_id, label, [xy], **kw)
    shape["shape_type"] = "point"
    return shape


def bbox_of(shape):
    """Return the axis-aligned ``(left, top, right, bottom)`` of a shape."""
    xs = [point[0] for point in shape["points"]]
    ys = [point[1] for point in shape["points"]]
    return (min(xs), min(ys), max(xs), max(ys))


def by_id(shapes):
    """Index a shape list by ``xanylabeling_shape_id``."""
    return {shape[SHAPE_ID]: shape for shape in shapes}


def moved(shape, dx, dy):
    """Copy of ``shape`` translated by ``(dx, dy)`` (identity preserved)."""
    left, top, right, bottom = bbox_of(shape)
    return rect(shape[SHAPE_ID], shape["label"],
                (left + dx, top + dy, right + dx, bottom + dy))


def relabelled(shape, label):
    """Copy of ``shape`` with a new class label (geometry preserved)."""
    clone = copy.deepcopy(shape)
    clone["label"] = label
    return clone


def resized(shape, box):
    """Copy of ``shape`` as a rectangle with a new ``(l, t, r, b)`` box."""
    return rect(shape[SHAPE_ID], shape["label"], box)


# ---------------------------------------------------------------------------
# the eight fixed samples
# ---------------------------------------------------------------------------
def empty_scene():
    """样本 1 ``empty_blank``: zero objects.

    Expected net for the ``freeze`` variant: baseline/final 0, every count 0,
    ``modified_rate``/``unchanged_rate`` N/A, ``ai_count`` 0.
    """
    return []


def dense_30():
    """样本 2 ``dense_30_six_classes``: 30 rectangles, six classes, five each.

    Grid 6x5, ``x=20+col*100``, ``y=20+row*110``, ``w=70``, ``h=90``; labels
    ``cat/dog/person/car/tree/sign`` in five-object groups.  With the
    ``scripted_corrections`` variant of samples-design.md §3.2 (see
    :func:`apply_dense_script`) the expected net is::

        baseline 30, final 30, added 2, deleted 2, geometry_changed 5,
        class_changed 4, modified_original 10, unchanged 20,
        modified_rate 1/3, unchanged_rate 2/3, transactions 11,
        touches 13, unique_objects 12, ai_count 30.
    """
    shapes = []
    for index in range(30):
        col, row = index % 6, index // 6
        shapes.append(rect(
            "p-%03d" % (index + 1),
            DENSE_LABELS[index // 5],
            (20 + col * 100, 20 + row * 110,
             20 + col * 100 + 70, 20 + row * 110 + 90),
        ))
    return shapes


def stress_300():
    """样本 3 ``stress_300_grid``: 300 rectangles, three classes x100.

    Grid 20x15, ``x=col*32``, ``y=row*42``, ``w=28``, ``h=38``; labels cycle
    ``cat/dog/person``.  Expected net for ``batch_relabel_10`` (one
    transaction relabelling s-001..s-010 to ``sign``): class_changed 10,
    modified_original 10, unchanged 290, transactions 1, touches 10,
    unique_objects 10, ai_count 300.
    """
    shapes = []
    for index in range(300):
        col, row = index % 20, index // 20
        shapes.append(rect(
            "s-%03d" % (index + 1),
            STRESS_LABELS[index % 3],
            (col * 32, row * 42, col * 32 + 28, row * 42 + 38),
        ))
    return shapes


def occluded_small():
    """样本 4 ``occluded_small``: six 8x8 and six 60x80 rectangles.

    ``o-001..o-006`` are 8x8 targets, ``o-007..o-012`` are 60x80 targets; the
    labels alternate ``cat/dog``.  samples-design.md §3.4 expects::

        freeze             -> unchanged 12, transactions 0
        equivalent_rewrite -> geometry_changed 0, unchanged 12, transactions 0
        one_pixel_edge     -> geometry_changed 1, unchanged 11, transactions 1
        subpixel_noise     -> geometry_changed 1 (o-005 +0.4px must be seen)
        move_occluded_pair -> geometry_changed 2, touches 2, transactions 1
    """
    shapes = []
    for index in range(6):
        shapes.append(rect(
            "o-%03d" % (index + 1),
            "cat" if index % 2 == 0 else "dog",
            (20 + index * 40, 20, 28 + index * 40, 28),
        ))
    for index in range(6):
        shapes.append(rect(
            "o-%03d" % (index + 7),
            "dog" if index % 2 == 0 else "cat",
            (20 + index * 100, 200, 80 + index * 100, 280),
        ))
    return shapes


def locked_partial():
    """样本 5 ``partial_locked``: ten rectangles, four of them locked.

    ``l-002``, ``l-005``, ``l-008`` and ``l-010`` carry ``locked=True``.
    ``locked`` is not snapshot content, so ``lock_toggle_only`` yields
    geometry_changed 0 / unchanged 10 / transactions 0.
    """
    shapes = []
    locked = {1, 4, 7, 9}
    for index in range(10):
        col, row = index % 5, index // 5
        shapes.append(rect(
            "l-%03d" % (index + 1),
            "cat" if index % 2 == 0 else "dog",
            (30 + col * 110, 30 + row * 120,
             30 + col * 110 + 80, 30 + row * 120 + 90),
            locked=index in locked,
        ))
    return shapes


def mixed_shapes():
    """样本 6 ``mixed_shapes``: eight rectangles plus four non-rectangles.

    ``r-001..r-008`` rectangles, ``g-001``/``g-002`` polygons, ``t-001``
    rotation, ``k-001`` point.  ``freeze`` expects baseline 8 / final 8 /
    unsupported_count 4 / ``partial-scope``.  Converting ``r-004`` to a
    polygon (same ID) expects scope_changes 1, added 0, deleted 0,
    final_count 7, unsupported_count 5, ``type-conversion``.
    """
    shapes = []
    for index in range(8):
        col, row = index % 4, index // 4
        shapes.append(rect(
            "r-%03d" % (index + 1),
            "cat" if index % 2 == 0 else "dog",
            (20 + col * 140, 20 + row * 140,
             20 + col * 140 + 60, 20 + row * 140 + 60),
        ))
    shapes.append(polygon("g-001", "cat", [(400, 400), (460, 400), (430, 460)]))
    shapes.append(polygon("g-002", "dog", [(500, 20), (560, 20), (560, 80), (500, 80)]))
    shapes.append(rotation("t-001", "cat", [(500, 200), (560, 200), (560, 260), (500, 260)]))
    shapes.append(point_mark("k-001", "dog", (600, 500)))
    return shapes


def unknown_origin():
    """样本 7 ``legacy_unknown``: 25 legacy rectangles, unknown origin.

    Grid 5x5, classes ``cat/dog/person/car/tree`` five each.  ``freeze``
    expects ``ai_count`` None, ``unknown-origin`` in issues,
    ``modified_rate`` 0.0, ``unchanged_rate`` 1.0, unchanged 25.
    """
    shapes = []
    for index in range(25):
        col, row = index % 5, index // 5
        shapes.append(rect(
            "u-%03d" % (index + 1),
            LEGACY_LABELS[index // 5],
            (30 + col * 120, 30 + row * 120,
             30 + col * 120 + 90, 30 + row * 120 + 90),
        ))
    return shapes


def manual5_ai3():
    """样本 8 ``additive_5_plus_3``: five manual plus three AI rectangles.

    ``m-001..m-005`` are the pre-existing manual boxes, ``a-001..a-003`` are
    the three objects of this AI run.  ``ai_count`` must be 3 and never 8.
    ``fix_after_append`` (relabel ``a-001`` dog->cat, move ``m-002``, delete
    ``a-003``) expects added 0, deleted 1, geometry_changed 1, class_changed 1,
    modified_original 3, unchanged 5, final 7, transactions 3, touches 3,
    unique_objects 3, ai_count 3.
    """
    shapes = []
    for index in range(5):
        shapes.append(rect(
            "m-%03d" % (index + 1),
            "cat" if index % 2 == 0 else "dog",
            (20 + index * 110, 20, 20 + index * 110 + 80, 20 + 90),
        ))
    ai = (("a-001", "dog", (40, 400, 120, 490)),
          ("a-002", "car", (180, 400, 260, 490)),
          ("a-003", "car", (320, 400, 400, 490)))
    for shape_id, label, box in ai:
        shapes.append(rect(shape_id, label, box))
    return shapes


# ---------------------------------------------------------------------------
# scripted correction transactions (samples-design.md §3.2)
# ---------------------------------------------------------------------------
def apply_dense_script(round_obj):
    """Replay the eleven scripted transactions on :func:`dense_30`.

    T1-T5 move ``p-003/p-007/p-012/p-019/p-014`` by (+6, +4); T6-T8 relabel
    ``p-002 cat->dog``, ``p-011 person->car``, ``p-025 tree->sign``; T9
    relabels the already-moved ``p-014 person->dog``; T10 deletes
    ``p-021/p-028``; T11 creates ``n-101/n-102``.  Every step uses a stable
    ``transaction_id`` so idempotency is reproducible.
    """
    baseline = by_id(dense_30())
    current = {}
    for transaction_id, shape_id in (
        ("T1", "p-003"), ("T2", "p-007"), ("T3", "p-012"),
        ("T4", "p-019"), ("T5", "p-014"),
    ):
        updated = moved(baseline[shape_id], 6, 4)
        current[shape_id] = updated
        assert round_obj.patch(shapes=[updated],
                               transaction_id=transaction_id) is True
    for transaction_id, shape_id, label in (
        ("T6", "p-002", "dog"), ("T7", "p-011", "car"),
        ("T8", "p-025", "sign"), ("T9", "p-014", "dog"),
    ):
        updated = relabelled(current.get(shape_id, baseline[shape_id]), label)
        current[shape_id] = updated
        assert round_obj.patch(shapes=[updated],
                               transaction_id=transaction_id) is True
    assert round_obj.patch(removed_ids=("p-021", "p-028"),
                           transaction_id="T10") is True
    assert round_obj.patch(
        shapes=[rect("n-101", "cat", (40, 560, 110, 620)),
                rect("n-102", "car", (180, 560, 250, 620))],
        transaction_id="T11",
    ) is True


# ---------------------------------------------------------------------------
# round fixtures
# ---------------------------------------------------------------------------
class MemoryStore:
    """Minimal in-memory stand-in for ``MetricsStore`` (pure-logic tests only).

    Implements exactly the surface ``CorrectionRound`` uses: ``session_id``,
    ``_enqueue``, ``gaps``, ``flush`` and ``error``.  Persisted writes are
    recorded for assertions; ``failing=True`` simulates a closed/full store.
    The real ``MetricsStore`` is exercised separately in ``test_storage.py``.
    """

    def __init__(self, dataset_id="synthetic-dataset",
                 session_id="synthetic-session", failing=False):
        self.dataset_id = dataset_id
        self.session_id = session_id
        self.error = None
        self.failing = failing
        self.writes = []
        self._gaps = {}
        self._target_gaps = {}

    def gaps_for(self, image_path, label_path):
        """Image/label-scoped gaps (see ``MetricsStore.gaps_for``)."""
        return set(self._target_gaps.get((image_path, label_path), ()))

    def _enqueue(self, state, operations):
        if self.failing:
            return False
        self.writes.append((copy.deepcopy(state), operations))
        return True

    def gaps(self, round_id):
        return set(self._gaps.get(round_id, ()))

    def inject_gap(self, round_id, reason="storage-gap"):
        self._gaps.setdefault(round_id, set()).add(reason)

    def flush(self, timeout=2):
        return not self.failing

    def close(self, timeout=2):
        self.failing = True


def make_round(shapes, *, origin="replacement", predicted=(), provenance=None,
               saved=True, image_path="scene.png", label_path="scene.json",
               image_digest="image-digest-1", phase="correction", store=None):
    """Build a ``CorrectionRound`` over a fresh in-memory store."""
    store = store or MemoryStore()
    state = initialise_state(
        store.dataset_id, image_path, label_path, image_digest,
        snapshot(shapes), origin, provenance or {}, predicted, saved, phase,
    )
    return CorrectionRound(store, state)


def draft_snapshot(round_obj):
    """Return the round's current draft snapshot (a ``core`` dict)."""
    return round_obj._state["draft"]


# ---------------------------------------------------------------------------
# scratch directories for the SQLite-backed tests
# ---------------------------------------------------------------------------
_WORK_PARENT = Path(__file__).resolve().parents[2] / ".tmp" / "correction_metrics_work"
_WORK_DIRS = []
_WORK_COUNTER = itertools.count()


def workdir():
    """Create a writable throw-away directory for SQLite-backed tests.

    ``pytest``'s ``tmp_path`` is unusable in this sandbox: writes to the system
    temp directory and to ``PYTEST_DEBUG_TEMPROOT`` are denied, and
    ``tempfile.mkdtemp()`` creates its directory with mode ``0o700``, which the
    sandbox turns into an ACL that the same process can no longer open
    (``PermissionError: WinError 5`` / ``sqlite3.OperationalError: unable to
    open database file``).  Directories are therefore created here with the
    default mode inside ``.tmp/correction_metrics_work`` (git-ignored), and removed at
    interpreter exit.  ``conftest.py`` maps ``tmp_path`` onto this helper.
    """
    _WORK_PARENT.mkdir(parents=True, exist_ok=True)
    while True:
        candidate = _WORK_PARENT / ("case-%06d" % next(_WORK_COUNTER))
        try:
            candidate.mkdir()
        except FileExistsError:
            continue
        _WORK_DIRS.append(candidate)
        return candidate


def cleanup_workdirs():
    """Remove every scratch directory created by :func:`workdir`."""
    for path in _WORK_DIRS:
        shutil.rmtree(path, ignore_errors=True)
    _WORK_DIRS.clear()


atexit.register(cleanup_workdirs)
