"""Read annotation metadata without retaining shapes or touching Qt objects."""

import json
import os
import queue
import threading
from collections import deque
from dataclasses import dataclass

import natsort

from .file_search import matches_filename, matches_label_attribute, parse_search_pattern


@dataclass(frozen=True)
class AnnotationMetadata:
    presence: str
    review: str
    error: str = ""


def read_annotation_metadata(path):
    """Return independent presence and review states for one annotation.

    Only the top-level ``checked`` field is authoritative.  A complete JSON
    parse also ensures a truncated document cannot be reported as reviewed.
    The parsed shapes are discarded before this function returns.
    """
    try:
        with open(path, "r", encoding="utf-8") as stream:
            data = json.load(stream)
        if not isinstance(data, dict):
            raise ValueError("annotation root must be an object")
        checked = data.get("checked", False)
        if checked is True:
            review = "passed"
        elif checked == "failed":
            review = "failed"
        else:
            review = "unchecked"
        return AnnotationMetadata("present", review)
    except FileNotFoundError:
        return AnnotationMetadata("missing", "unchecked")
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        return AnnotationMetadata("error", "error", str(exc))


def annotation_path(image_path, output_dir):
    name = os.path.splitext(image_path)[0] + ".json"
    return os.path.join(output_dir, os.path.basename(name)) if output_dir else name


class MetadataWorker:
    """One cancellable producer with bounded delivery to the GUI consumer.

    A record includes the caller's context and revision snapshot so that a
    consumer can reject results superseded by a save or directory change.
    The consumer owns all Qt work and must retain this object until it exits.
    """

    def __init__(self, paths, output_dir, generation, revisions, batch_size=128):
        self.paths = tuple(paths)
        self.output_dir = output_dir
        self.generation = generation
        self.revisions = dict(revisions)
        self.batch_size = max(1, batch_size)
        self.results = queue.Queue(maxsize=4)
        self.cancelled = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self._lock = threading.Lock()
        self._pending = set(self.paths)
        self._priority = deque()

    def start(self):
        self.thread.start()

    def cancel(self):
        self.cancelled.set()

    def prioritize(self, path):
        """Move a pending navigation candidate ahead of ordinary scanning."""
        with self._lock:
            if path in self._pending and path not in self._priority:
                self._priority.append(path)

    def _publish(self, batch):
        while not self.cancelled.is_set():
            try:
                self.results.put(batch, timeout=0.05)
                return True
            except queue.Full:
                continue
        return False

    def _run(self):
        batch = []
        paths = iter(self.paths)
        while True:
            if self.cancelled.is_set():
                return
            with self._lock:
                prioritized = bool(self._priority)
                if self._priority:
                    path = self._priority.popleft()
                else:
                    path = next(paths, None)
                    while path is not None and path not in self._pending:
                        path = next(paths, None)
                if path is None:
                    break
                self._pending.discard(path)
            metadata = read_annotation_metadata(annotation_path(path, self.output_dir))
            batch.append((self.generation, path, self.revisions.get(path, 0), metadata))
            if prioritized or len(batch) >= self.batch_size:
                if not self._publish(batch):
                    return
                batch = []
        if batch and not self._publish(batch):
            return
        self._publish(None)


class MetadataController:
    """Coalesce requests while an older worker is cancelling.

    The caller invokes ``poll`` from its event loop.  There is at most one
    live worker and one pending request, even during rapid directory changes.
    """

    def __init__(self):
        self.worker = None
        self.pending = None
        self.retry_pending = None
        self.generation = 0

    def request(self, paths, output_dir, revisions):
        self.generation += 1
        self.retry_pending = None
        self.pending = (tuple(paths), output_dir, self.generation, dict(revisions))
        if self.worker is not None:
            self.worker.cancel()
        self._start_pending()
        return self.generation

    def cancel(self):
        self.generation += 1
        self.pending = None
        self.retry_pending = None
        if self.worker is not None:
            self.worker.cancel()

    def _start_pending(self):
        if self.worker is not None:
            if self.worker.thread.is_alive():
                return
            if self.worker.generation == self.generation and not self.worker.results.empty():
                return
        self.worker = None
        if self.pending is not None:
            self.worker = MetadataWorker(*self.pending)
            self.pending = None
            self.worker.start()
        elif self.retry_pending is not None:
            path, output_dir, revision = self.retry_pending
            self.retry_pending = None
            self.worker = MetadataWorker([path], output_dir, self.generation, {path: revision})
            self.worker.start()

    def poll(self):
        """Drain bounded batches without waiting; return only current records."""
        records = []
        if self.worker is not None:
            for _ in range(4):
                try:
                    batch = self.worker.results.get_nowait()
                except queue.Empty:
                    break
                if batch is not None:
                    records.extend(r for r in batch if r[0] == self.generation)
        self._start_pending()
        return records

    def prioritize(self, path):
        if self.worker is not None and self.pending is None:
            self.worker.prioritize(path)

    def retry(self, path, output_dir, revision):
        self.retry_pending = (path, output_dir, revision)

    def is_running(self):
        return self.pending is not None or self.retry_pending is not None or (
            self.worker is not None and (
                self.worker.thread.is_alive()
                or (self.worker.generation == self.generation and not self.worker.results.empty())
            )
        )


class ViewWorker:
    """Enumerate a directory or filter a snapshot without Qt access."""

    def __init__(self, generation, directory=None, extensions=(), paths=None,
                 output_dir=None, pattern=None, batch_size=128, extra_paths=()):
        self.generation = generation
        self.directory = directory
        self.extensions = tuple(extensions)
        self.paths = paths
        self.output_dir = output_dir
        self.pattern = pattern
        self.batch_size = batch_size
        self.extra_paths = tuple(extra_paths)
        self.results = queue.Queue(maxsize=4)
        self.cancelled = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self.thread.start()

    def cancel(self):
        self.cancelled.set()

    def _publish(self, kind, value):
        while not self.cancelled.is_set():
            try:
                self.results.put((self.generation, kind, value), timeout=0.05)
                return True
            except queue.Full:
                pass
        return False

    def _run(self):
        try:
            if self.paths is None:
                paths = []
                def onerror(error):
                    raise error
                directory = os.path.normpath(os.path.abspath(self.directory))
                if not os.path.isdir(directory):
                    raise FileNotFoundError(directory)
                for root, _, files in os.walk(directory, onerror=onerror):
                    if self.cancelled.is_set():
                        return
                    paths.extend(os.path.normpath(os.path.join(root, name))
                                 for name in files if name.lower().endswith(self.extensions))
                try:
                    paths = natsort.natsorted(paths)
                except (OSError, ValueError):
                    paths = sorted(paths)
                scanned = set(paths)
                paths.extend(path for path in self.extra_paths if path not in scanned)
                if not self._publish("paths", paths):
                    return
            else:
                paths = self.paths
            pattern = parse_search_pattern(self.pattern or "")
            batch = []
            errors = 0
            for index, path in enumerate(paths, 1):
                if self.cancelled.is_set():
                    return
                if pattern.mode == "index":
                    match = pattern.index == index
                else:
                    match = matches_filename(path, pattern)
                    if match and pattern.mode == "attribute":
                        label = annotation_path(path, self.output_dir)
                        try:
                            match = matches_label_attribute(path, label, pattern, strict=True)
                        except (OSError, ValueError, TypeError, KeyError, AttributeError):
                            errors += 1
                            match = False
                if match:
                    batch.append(path)
                    if len(batch) >= self.batch_size:
                        if not self._publish("matches", batch):
                            return
                        batch = []
            if batch and not self._publish("matches", batch):
                return
            self._publish("done", errors)
        except Exception as exc:
            self._publish("error", str(exc))


class ViewController:
    """Limit directory and search work to one worker and one latest request."""

    def __init__(self):
        self.generation = 0
        self.worker = None
        self.pending = None

    def request(self, **kwargs):
        self.generation += 1
        self.pending = (self.generation, kwargs)
        if self.worker is not None:
            self.worker.cancel()
        self._start_pending()
        return self.generation

    def cancel(self):
        self.generation += 1
        self.pending = None
        if self.worker is not None:
            self.worker.cancel()

    def _start_pending(self):
        if self.worker is not None:
            if self.worker.thread.is_alive():
                return
            if self.worker.generation == self.generation and not self.worker.results.empty():
                return
        self.worker = None
        if self.pending:
            generation, kwargs = self.pending
            self.pending = None
            self.worker = ViewWorker(generation, **kwargs)
            self.worker.start()

    def poll(self):
        results = []
        if self.worker is not None:
            for _ in range(4):
                try:
                    result = self.worker.results.get_nowait()
                except queue.Empty:
                    break
                if result[0] == self.generation:
                    results.append(result)
        self._start_pending()
        return results

    def is_running(self):
        return self.pending is not None or (
            self.worker is not None and (
                self.worker.thread.is_alive()
                or (self.worker.generation == self.generation and not self.worker.results.empty())
            )
        )
