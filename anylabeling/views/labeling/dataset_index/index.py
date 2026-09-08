"""DatasetFilterIndex — 基于 SQLite 的派生索引缓存，用于快速筛选查询。

JSON 标注文件是唯一真实数据源。
SQLite 仅作为可丢弃、可重建的索引缓存，不保存不可从 JSON 恢复的信息。
"""

import hashlib
import logging
import math
import os
import os.path as osp
import sqlite3
import time
import uuid
from concurrent.futures import (
    FIRST_COMPLETED,
    Future,
    ThreadPoolExecutor,
    wait,
)
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Set, Tuple

from .json_stream import JsonStreamError, read_top_level_array
from .thumbnail_query import ThumbnailQuery, query_review_page, review_metadata
from .types import (
    DatasetThumbnailLocation,
    DatasetThumbnailPage,
    DatasetThumbnailRef,
)

logger = logging.getLogger(__name__)


def _points_bbox(points: object) -> tuple[Optional[float], ...]:
    """Return an axis-aligned bbox for numeric two-dimensional points."""
    values: list[tuple[float, float]] = []
    if isinstance(points, (list, tuple)):
        for point in points:
            if not isinstance(point, (list, tuple)) or len(point) < 2:
                continue
            x, y = point[0], point[1]
            if isinstance(x, bool) or isinstance(y, bool):
                continue
            if not isinstance(x, (int, float)) or not isinstance(
                y, (int, float)
            ):
                continue
            x_value, y_value = float(x), float(y)
            if math.isfinite(x_value) and math.isfinite(y_value):
                values.append((x_value, y_value))
    if not values:
        return (None, None, None, None)
    xs, ys = zip(*values)
    return (min(xs), min(ys), max(xs), max(ys))


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

SCHEMA_VERSION = "4"
CACHE_DIR = osp.expanduser("~/.cache/xanylabeling/dataset_index")
INDEX_STATUS_OK = "ok"
INDEX_STATUS_MISSING = "missing"
INDEX_STATUS_ERROR = "error"
SQLITE_BUSY_TIMEOUT_MS = 30000
INDEX_READ_WORKERS = 4
INDEX_READ_PREFETCH_LIMIT = 64
# Compatibility alias for extensions that imported the pre-pipeline name.
INDEX_READ_BATCH_SIZE = INDEX_READ_PREFETCH_LIMIT
QUERY_INDEX_DEFINITIONS = (
    (
        "idx_shapes_label",
        "CREATE INDEX IF NOT EXISTS idx_shapes_label ON shapes(label)",
    ),
    (
        "idx_shapes_group_id",
        "CREATE INDEX IF NOT EXISTS idx_shapes_group_id ON shapes(group_id)",
    ),
    (
        "idx_shapes_shape_type",
        "CREATE INDEX IF NOT EXISTS idx_shapes_shape_type "
        "ON shapes(shape_type)",
    ),
    (
        "idx_shapes_file_id",
        "CREATE INDEX IF NOT EXISTS idx_shapes_file_id ON shapes(file_id)",
    ),
    (
        "idx_shapes_file_shape",
        "CREATE INDEX IF NOT EXISTS idx_shapes_file_shape "
        "ON shapes(file_id, shape_index)",
    ),
    (
        "idx_shapes_file_shape_id",
        "CREATE INDEX IF NOT EXISTS idx_shapes_file_shape_id "
        "ON shapes(file_id, shape_id)",
    ),
    (
        "idx_files_sort_order",
        "CREATE INDEX IF NOT EXISTS idx_files_sort_order "
        "ON files(sort_order)",
    ),
)

DATASET_INDEX_MISSING = "missing"
DATASET_INDEX_CACHED = "cached_unverified"
DATASET_INDEX_SYNCING = "syncing"
DATASET_INDEX_READY = "ready"
DATASET_INDEX_STALE = "stale"
DATASET_INDEX_FAILED = "failed"

META_BUILD_STATE = "build_state"
META_DATASET_ROOT = "dataset_root"
META_OUTPUT_DIR = "output_dir"
META_COMPLETED_AT = "completed_at"
META_FILE_COUNT = "file_count"
META_SHAPE_COUNT = "shape_count"

ProgressCallback = Callable[[int, int, str], None]
CancelCheck = Callable[[], bool]


@dataclass
class DatasetIndexPerformance:
    """Non-persisted performance measurements for one index operation."""

    planning_seconds: float = 0.0
    pipeline_wall_seconds: float = 0.0
    read_work_seconds: float = 0.0
    sqlite_write_seconds: float = 0.0
    commit_seconds: float = 0.0
    index_build_seconds: float = 0.0
    finalize_seconds: float = 0.0
    integrity_check_seconds: float = 0.0
    foreign_key_check_seconds: float = 0.0
    json_bytes: int = 0
    max_in_flight: int = 0


@dataclass
class DatasetIndexResult:
    """索引构建/刷新结果。

    该对象用于 Phase 3 后台线程向 UI 汇报最终状态。
    """

    total: int = 0
    inserted: int = 0
    updated: int = 0
    removed: int = 0
    failed: int = 0
    missing: int = 0
    shape_count: int = 0
    cancelled: bool = False
    fatal_error: bool = False
    elapsed_seconds: float = 0.0
    target_db_path: Optional[str] = None
    staged_db_path: Optional[str] = None
    error_messages: List[str] = field(default_factory=list)
    performance: DatasetIndexPerformance = field(
        default_factory=DatasetIndexPerformance
    )

    @property
    def changed(self) -> int:
        """返回本次实际变更的文件数量。"""
        return self.inserted + self.updated + self.removed


@dataclass
class PreparedIndexFile:
    """Filesystem and lightweight JSON data prepared for SQLite insertion."""

    image_path: str
    json_path: str
    sort_order: int
    json_mtime: float = 0.0
    json_mtime_ns: int = 0
    json_size: int = 0
    shapes: List[tuple] = field(default_factory=list)
    status: str = INDEX_STATUS_MISSING
    error_message: str = ""
    read_seconds: float = 0.0


# ---------------------------------------------------------------------------
# 公共 API
# ---------------------------------------------------------------------------


class DatasetFilterIndex:
    """基于 SQLite 的 JSON 标注派生索引，用于快速筛选和导航。

    所有标注数据仍从 JSON 文件读取，本模块永远不会写入 JSON。
    SQLite 数据库是一个可随时删除并重建的临时缓存。
    """

    def __init__(
        self,
        db_path: Optional[str] = None,
        journal_mode: str = "wal",
        defer_query_indexes: bool = False,
    ):
        """初始化索引实例。

        Args:
            db_path: SQLite 数据库文件路径。若为 None，则后续所有操作跳过。
            journal_mode: SQLite 日志模式。正式缓存使用 ``wal``，临时重建
                数据库使用 ``delete``，确保所有数据都落入单个主文件后再替换。
            defer_query_indexes: 是否在 ``rebuild`` 数据写入完成后再创建查询
                索引。仅应对可丢弃的 staging 数据库启用。
        """
        self.db_path = db_path
        self.journal_mode = journal_mode.lower()
        self.defer_query_indexes = defer_query_indexes
        self._conn: Optional[sqlite3.Connection] = None

    # ------------------------------------------------------------------
    # 生命周期管理
    # ------------------------------------------------------------------

    def open(self) -> bool:
        """打开或创建 SQLite 缓存数据库。

        如果数据库不存在，会自动创建并初始化表结构。
        如果 db_path 为 None，直接返回 False。

        Returns:
            成功打开返回 True，失败返回 False。
        """
        if self._conn is not None:
            return True
        if self.db_path is None:
            return False
        try:
            self._conn = sqlite3.connect(
                self.db_path, timeout=SQLITE_BUSY_TIMEOUT_MS / 1000, uri=True
            )
            self._conn.execute(
                f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}"
            )
            if self.db_path != ":memory:":
                if self.journal_mode not in {"wal", "delete"}:
                    raise ValueError(
                        f"Unsupported journal mode: {self.journal_mode}"
                    )
                self._conn.execute(
                    f"PRAGMA journal_mode = {self.journal_mode.upper()}"
                )
                self._conn.execute("PRAGMA synchronous = NORMAL")
            self._conn.execute("PRAGMA foreign_keys = ON")
            self._ensure_schema()
            return True
        except sqlite3.Error as exc:
            logger.warning(
                f"Failed to open SQLite cache {self.db_path}: {exc}"
            )
            self._conn = None
            return False

    def close(self) -> None:
        """关闭底层 SQLite 连接。

        安全关闭连接并释放资源。即使关闭失败也不会抛出异常。
        """
        if self._conn is not None:
            try:
                self._conn.close()
            except sqlite3.Error:
                pass
            self._conn = None

    def is_ready(self) -> bool:
        """检查缓存是否已打开且可用。

        Returns:
            连接已建立返回 True，否则返回 False。
        """
        return self._conn is not None

    def metadata(self) -> Dict[str, str]:
        """Return all persisted dataset index metadata."""
        if self._conn is None:
            return {}
        try:
            cursor = self._conn.execute("SELECT key, value FROM dataset_meta")
            return {str(key): str(value) for key, value in cursor.fetchall()}
        except sqlite3.Error:
            return {}

    def snapshot_state(self) -> str:
        """Return the persisted snapshot state, including legacy caches."""
        metadata = self.metadata()
        state = metadata.get(META_BUILD_STATE)
        if state:
            return state
        if self._conn is None:
            return DATASET_INDEX_MISSING
        try:
            row = self._conn.execute("SELECT COUNT(*) FROM files").fetchone()
            return (
                DATASET_INDEX_READY
                if row and row[0]
                else DATASET_INDEX_MISSING
            )
        except sqlite3.Error:
            return DATASET_INDEX_FAILED

    def is_compatible(
        self,
        dataset_root: str,
        output_dir: Optional[str] = None,
    ) -> bool:
        """Check whether persisted metadata belongs to the requested dataset.

        Caches created before identity metadata was introduced are accepted as
        legacy caches because their filename is already derived from the dataset
        root. They are reported to the UI as unverified until Refresh completes.
        """
        metadata = self.metadata()
        stored_root = metadata.get(META_DATASET_ROOT)
        if stored_root and stored_root != _normalize_path(dataset_root):
            return False
        stored_output_dir = metadata.get(META_OUTPUT_DIR)
        if stored_output_dir is not None:
            requested = _normalize_optional_path(output_dir)
            if stored_output_dir != requested:
                return False
        return True

    def file_statuses(
        self, image_paths: Optional[List[str]] = None
    ) -> Dict[str, Tuple[str, str]]:
        """Return cached ``image_path -> (status, json_path)`` records."""
        if self._conn is None:
            return {}
        requested = set(image_paths) if image_paths is not None else None
        try:
            cursor = self._conn.execute(
                "SELECT image_path, index_status, json_path FROM files"
            )
            results: Dict[str, Tuple[str, str]] = {}
            for image_path, status, json_path in cursor.fetchall():
                if requested is None or image_path in requested:
                    results[image_path] = (status, json_path or "")
            return results
        except sqlite3.Error as exc:
            logger.warning(f"Failed to list dataset index statuses: {exc}")
            return {}

    def integrity_check(self) -> bool:
        """Return whether SQLite reports the current cache as valid."""
        if self._conn is None:
            return False
        try:
            row = self._conn.execute("PRAGMA integrity_check").fetchone()
            return bool(row and str(row[0]).lower() == "ok")
        except sqlite3.Error:
            return False

    def foreign_key_check(self) -> bool:
        """Return whether SQLite reports no foreign-key violations."""
        if self._conn is None:
            return False
        try:
            row = self._conn.execute("PRAGMA foreign_key_check").fetchone()
            return row is None
        except sqlite3.Error:
            return False

    # ------------------------------------------------------------------
    # 高层操作（供外部调用）
    # ------------------------------------------------------------------

    def load_or_build(
        self,
        image_files: List[str],
        output_dir: Optional[str] = None,
        progress_callback: Optional[ProgressCallback] = None,
        cancel_check: Optional[CancelCheck] = None,
        dataset_root: Optional[str] = None,
    ) -> DatasetIndexResult:
        """确保缓存与当前图片列表保持同步（增量更新）。

        工作流程：
        1. 扫描现有缓存中的所有文件记录。
        2. 对比磁盘上 JSON 文件的 mtime 和 size，识别新增/删除/修改的文件。
        3. 对变化的文件进行增量更新。
        4. 插入新文件，移除已删除的文件。

        Args:
            image_files: 当前数据集中的所有图片路径列表。
            output_dir: JSON 标注文件存放目录。若为 None，则在与图片相同目录查找 JSON。
            progress_callback: 进度回调，格式为 (current, total, filename)。
            cancel_check: 取消检查回调，返回 True 表示请求取消。

        Returns:
            本次增量刷新结果。
        """
        started_at = time.perf_counter()
        if not self.open():
            logger.info("DatasetFilterIndex: skipping (no db_path)")
            return DatasetIndexResult(total=len(image_files))
        result = self._incremental_update(
            image_files, output_dir, progress_callback, cancel_check
        )
        if not result.cancelled and not result.fatal_error:
            finalize_started = time.perf_counter()
            self._write_snapshot_metadata(
                image_files, output_dir, dataset_root, DATASET_INDEX_READY
            )
            self._populate_result_summary(result)
            self._conn.commit()
            result.performance.finalize_seconds = (
                time.perf_counter() - finalize_started
            )
        result.elapsed_seconds = time.perf_counter() - started_at
        result.target_db_path = self.db_path
        return result

    def refresh(
        self,
        image_files: List[str],
        output_dir: Optional[str] = None,
        progress_callback: Optional[ProgressCallback] = None,
        cancel_check: Optional[CancelCheck] = None,
        dataset_root: Optional[str] = None,
    ) -> DatasetIndexResult:
        """刷新索引（与 load_or_build 等价，语义上表示显式刷新）。

        Args:
            image_files: 当前数据集中的所有图片路径列表。
            output_dir: JSON 标注文件存放目录。
            progress_callback: 进度回调，格式为 (current, total, filename)。
            cancel_check: 取消检查回调，返回 True 表示请求取消。

        Returns:
            本次刷新结果。
        """
        return self.load_or_build(
            image_files,
            output_dir,
            progress_callback,
            cancel_check,
            dataset_root,
        )

    def rebuild(
        self,
        image_files: List[str],
        output_dir: Optional[str] = None,
        progress_callback: Optional[ProgressCallback] = None,
        cancel_check: Optional[CancelCheck] = None,
        dataset_root: Optional[str] = None,
    ) -> DatasetIndexResult:
        """清空现有缓存并从头重建。

        适用场景：
        - 缓存文件损坏或 schema 版本不匹配。
        - 用户手动触发 "Rebuild Dataset Index"。
        - 需要确保索引与磁盘完全一致。

        Args:
            image_files: 当前数据集中的所有图片路径列表。
            output_dir: JSON 标注文件存放目录。
            progress_callback: 进度回调，格式为 (current, total, filename)。
            cancel_check: 取消检查回调，返回 True 表示请求取消。

        Returns:
            本次重建结果。
        """
        started_at = time.perf_counter()
        if not self.open():
            return DatasetIndexResult(total=len(image_files))
        self._clear_all()
        result = self._insert_files(
            image_files, output_dir, progress_callback, cancel_check
        )
        if not result.cancelled and not result.fatal_error:
            if self.defer_query_indexes:
                index_started = time.perf_counter()
                self._conn.execute("BEGIN")
                try:
                    indexes_created = self._create_query_indexes(cancel_check)
                    if not indexes_created:
                        self._conn.rollback()
                        result.cancelled = True
                    else:
                        result.performance.index_build_seconds = (
                            time.perf_counter() - index_started
                        )
                except Exception:
                    self._conn.rollback()
                    raise
        if not result.cancelled and not result.fatal_error:
            finalize_started = time.perf_counter()
            self._write_snapshot_metadata(
                image_files, output_dir, dataset_root, DATASET_INDEX_READY
            )
            self._populate_result_summary(result)
            self._conn.commit()
            result.performance.finalize_seconds = (
                time.perf_counter() - finalize_started
            )
        result.elapsed_seconds = time.perf_counter() - started_at
        result.target_db_path = self.db_path
        performance = result.performance
        logger.info(
            "Dataset index rebuild metrics: files=%d shapes=%d total=%.3fs "
            "planning=%.3fs pipeline=%.3fs read_work=%.3fs "
            "sqlite_write=%.3fs commit=%.3fs indexes=%.3fs "
            "finalize=%.3fs json_bytes=%d max_in_flight=%d",
            len(image_files),
            result.shape_count,
            result.elapsed_seconds,
            performance.planning_seconds,
            performance.pipeline_wall_seconds,
            performance.read_work_seconds,
            performance.sqlite_write_seconds,
            performance.commit_seconds,
            performance.index_build_seconds,
            performance.finalize_seconds,
            performance.json_bytes,
            performance.max_in_flight,
        )
        return result

    def refresh_file(
        self,
        image_path: str,
        output_dir: Optional[str] = None,
    ) -> None:
        """重建单个文件的派生索引。

        适用场景：用户在当前图片上修改标注并保存后，只更新该文件的索引，
        避免全量重建。

        Args:
            image_path: 图片文件路径。
            output_dir: JSON 标注文件存放目录。
        """
        if self._conn is None:
            return
        json_path = self._json_path_for_image(image_path, output_dir)
        file_id = self._file_id_for_json(json_path)
        if file_id is None:
            file_id = self._file_id_for_image(image_path)
        if file_id is not None:
            self._remove_file_shapes(file_id)
            self._update_file(file_id, json_path)
        else:
            self._insert_single(image_path, json_path)
        self._conn.commit()

    def _write_snapshot_metadata(
        self,
        image_files: List[str],
        output_dir: Optional[str],
        dataset_root: Optional[str],
        state: str,
    ) -> None:
        """Persist identity and completion metadata for a cache snapshot."""
        assert self._conn is not None
        values = {
            META_BUILD_STATE: state,
            META_OUTPUT_DIR: _normalize_optional_path(output_dir),
            META_COMPLETED_AT: str(time.time()),
            META_FILE_COUNT: str(len(image_files)),
        }
        if dataset_root:
            values[META_DATASET_ROOT] = _normalize_path(dataset_root)
        self._conn.executemany(
            "INSERT OR REPLACE INTO dataset_meta (key, value) VALUES (?, ?)",
            values.items(),
        )

    def _populate_result_summary(self, result: DatasetIndexResult) -> None:
        """Populate result counters from the completed cache snapshot."""
        assert self._conn is not None
        result.shape_count = self._conn.execute(
            "SELECT COUNT(*) FROM shapes"
        ).fetchone()[0]
        result.missing = self._conn.execute(
            "SELECT COUNT(*) FROM files WHERE index_status = ?",
            (INDEX_STATUS_MISSING,),
        ).fetchone()[0]
        self._conn.execute(
            "INSERT OR REPLACE INTO dataset_meta (key, value) VALUES (?, ?)",
            (META_SHAPE_COUNT, str(result.shape_count)),
        )

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def query(self, filter_state) -> List[str]:
        """查询符合条件的图片路径列表。

        查询语义（与 FilterState 保持一致）：
        - label 集合内部为 OR（任一 label 命中即可）。
        - label / gid / shape_type 之间为 AND（需同时满足）。
        - 一个文件只要包含至少一个匹配的 shape，该文件即命中。

        Args:
            filter_state: 筛选条件对象，需包含 labels、gid、shape_type 属性。

        Returns:
            命中的图片路径列表，按原始 image_files 顺序排序。
        """
        if self._conn is None:
            return []

        labels = getattr(filter_state, "labels", set())
        gid = getattr(filter_state, "gid", "")
        shape_type = getattr(filter_state, "shape_type", "")

        # FilterState 默认 gid 是 "-1"，也代表“未筛选 gid”。
        if not labels and (not gid or gid == "-1") and not shape_type:
            return self._all_image_paths()

        conditions = []
        params: List[str] = []

        if labels:
            placeholders = ",".join("?" for _ in labels)
            conditions.append(f"label IN ({placeholders})")
            params.extend(labels)

        if gid and gid != "-1":
            conditions.append("group_id = ?")
            params.append(gid)

        if shape_type:
            conditions.append("shape_type = ?")
            params.append(shape_type)

        where_clause = " AND ".join(conditions)

        sql = f"""
            SELECT DISTINCT f.image_path
            FROM shapes s
            JOIN files f ON s.file_id = f.id
            WHERE {where_clause}
            ORDER BY f.sort_order, f.image_path
        """

        try:
            cursor = self._conn.execute(sql, params)
            return [row[0] for row in cursor.fetchall()]
        except sqlite3.Error as exc:
            logger.warning(f"DatasetFilterIndex query failed: {exc}")
            return []

    def query_shapes(self, filter_state) -> Dict[str, List[int]]:
        """查询每张命中图片中的具体 shape_index。

        该接口属于 Phase 3 的更细粒度 shape 级缓存能力。它不只返回
        “哪些图片命中”，还返回“每张图片里哪些 shape 命中”。

        Args:
            filter_state: 筛选条件对象，需包含 labels、gid、shape_type 属性。

        Returns:
            字典，key 为 image_path，value 为命中的 shape_index 列表。
        """
        if self._conn is None:
            return {}

        labels = getattr(filter_state, "labels", set())
        gid = getattr(filter_state, "gid", "")
        shape_type = getattr(filter_state, "shape_type", "")
        conditions = []
        params: List[str] = []

        if labels:
            placeholders = ",".join("?" for _ in labels)
            conditions.append(f"s.label IN ({placeholders})")
            params.extend(labels)

        if gid and gid != "-1":
            conditions.append("s.group_id = ?")
            params.append(gid)

        if shape_type:
            conditions.append("s.shape_type = ?")
            params.append(shape_type)

        where_clause = " AND ".join(conditions) or "1 = 1"
        sql = f"""
            SELECT f.image_path, s.shape_index
            FROM shapes s
            JOIN files f ON s.file_id = f.id
            WHERE {where_clause}
            ORDER BY f.sort_order, f.image_path, s.shape_index
        """

        try:
            results: Dict[str, List[int]] = {}
            cursor = self._conn.execute(sql, params)
            for image_path, shape_index in cursor.fetchall():
                results.setdefault(image_path, []).append(shape_index)
            return results
        except sqlite3.Error as exc:
            logger.warning(f"DatasetFilterIndex shape query failed: {exc}")
            return {}

    def query_label_files(self, labels: Set[str]) -> List[str]:
        """Return indexed image paths containing any requested label.

        The result is only a candidate optimization. Callers must still read
        and validate each JSON file before applying a destructive migration.
        An empty result means the index is unavailable or no label matched.
        """
        if self._conn is None or not labels:
            return []
        placeholders = ",".join("?" for _ in labels)
        try:
            cursor = self._conn.execute(
                f"""
                SELECT DISTINCT f.image_path
                FROM shapes s
                JOIN files f ON s.file_id = f.id
                WHERE s.label IN ({placeholders})
                ORDER BY f.sort_order, f.image_path
                """,
                tuple(labels),
            )
            return [row[0] for row in cursor.fetchall()]
        except sqlite3.Error as exc:
            logger.warning("DatasetFilterIndex label query failed: %s", exc)
            return []

    def query_label_counts(self) -> List[tuple[str, int]]:
        """Return non-empty indexed labels and their Shape counts."""
        if self._conn is None:
            return []
        try:
            rows = self._conn.execute("""
                SELECT label, COUNT(*)
                FROM shapes
                WHERE label IS NOT NULL AND label <> ''
                GROUP BY label
                ORDER BY label COLLATE NOCASE, label
                """).fetchall()
            return [(str(label), int(count)) for label, count in rows]
        except sqlite3.Error as exc:
            logger.warning(
                "DatasetFilterIndex label-count query failed: %s", exc
            )
            return []

    def query_thumbnail_objects(
        self, label: str, limit: int = 100, offset: int = 0
    ) -> DatasetThumbnailPage:
        """Return a stable, bounded page of objects for one exact label.

        Args:
            label: Exact Shape label to query.
            limit: Requested page size, clamped to the range 1..100.
            offset: Zero-based row offset.

        Returns:
            A page containing only lightweight index references.
        """
        normalized_label = label if isinstance(label, str) else ""
        page_limit = max(1, min(int(limit), 100))
        page_offset = max(0, int(offset))
        if self._conn is None or not normalized_label:
            return DatasetThumbnailPage(
                normalized_label, 0, page_limit, page_offset, ()
            )

        try:
            total_row = self._conn.execute(
                "SELECT COUNT(*) FROM shapes WHERE label = ?",
                (normalized_label,),
            ).fetchone()
            total = int(total_row[0]) if total_row else 0
            rows = self._conn.execute(
                """
                SELECT f.image_path, f.json_path, f.sort_order,
                       s.shape_index, s.shape_id, s.label,
                       s.bbox_x_min, s.bbox_y_min,
                       s.bbox_x_max, s.bbox_y_max
                FROM shapes s
                JOIN files f ON s.file_id = f.id
                WHERE s.label = ?
                ORDER BY f.sort_order, f.image_path, s.shape_index
                LIMIT ? OFFSET ?
                """,
                (normalized_label, page_limit, page_offset),
            ).fetchall()
            items = []
            for row in rows:
                image_path, json_path, sort_order, shape_index, shape_id = row[
                    :5
                ]
                row_label = row[5] or ""
                bbox_values = row[6:10]
                bbox = (
                    tuple(float(value) for value in bbox_values)
                    if all(value is not None for value in bbox_values)
                    else None
                )
                items.append(
                    DatasetThumbnailRef(
                        image_path=str(image_path or ""),
                        json_path=str(json_path or ""),
                        sort_order=int(sort_order or 0),
                        shape_index=int(shape_index),
                        shape_id=str(shape_id or ""),
                        label=str(row_label),
                        bbox=bbox,
                    )
                )
            return DatasetThumbnailPage(
                normalized_label,
                total,
                page_limit,
                page_offset,
                tuple(items),
            )
        except (sqlite3.Error, TypeError, ValueError) as exc:
            logger.warning(
                "DatasetFilterIndex thumbnail query failed: %s", exc
            )
            return DatasetThumbnailPage(
                normalized_label, 0, page_limit, page_offset, ()
            )

    def query_thumbnail_review(
        self,
        label: str,
        limit: int = 100,
        offset: int = 0,
        options: Optional[ThumbnailQuery] = None,
        review_db: Optional[str] = None,
        anchor: Optional[tuple[str, str]] = None,
    ) -> DatasetThumbnailPage:
        """Query all matching objects before applying the bounded page."""
        if self._conn is None:
            return DatasetThumbnailPage(label, 0, min(100, limit), offset, ())
        return query_review_page(
            self._conn, label, limit, offset, options, review_db, anchor
        )

    def query_thumbnail_location(
        self, image_path: str, shape_id: str
    ) -> Optional[DatasetThumbnailLocation]:
        """Return the label-relative offset of one unique permanent object."""
        if self._conn is None or not image_path or not shape_id:
            return None
        normalized_path = osp.abspath(osp.normpath(str(image_path)))
        try:
            rows = self._conn.execute(
                """
                SELECT f.image_path, f.json_path, f.sort_order,
                       s.shape_index, s.shape_id, s.label
                FROM shapes s
                JOIN files f ON s.file_id = f.id
                WHERE f.image_path = ? AND s.shape_id = ?
                ORDER BY s.shape_index
                LIMIT 2
                """,
                (normalized_path, str(shape_id)),
            ).fetchall()
            if len(rows) != 1:
                return None
            row = rows[0]
            label = str(row[5] or "")
            if not label:
                return None
            before = self._conn.execute(
                """
                SELECT COUNT(*)
                FROM shapes s
                JOIN files f ON s.file_id = f.id
                WHERE s.label = ? AND (
                    f.sort_order < ? OR
                    (f.sort_order = ? AND f.image_path < ?) OR
                    (f.sort_order = ? AND f.image_path = ?
                     AND s.shape_index < ?)
                )
                """,
                (
                    label,
                    int(row[2]),
                    int(row[2]),
                    str(row[0]),
                    int(row[2]),
                    str(row[0]),
                    int(row[3]),
                ),
            ).fetchone()
            return DatasetThumbnailLocation(
                image_path=str(row[0]),
                json_path=str(row[1] or ""),
                sort_order=int(row[2]),
                shape_index=int(row[3]),
                shape_id=str(row[4]),
                label=label,
                offset=int(before[0]) if before else 0,
            )
        except (sqlite3.Error, TypeError, ValueError) as exc:
            logger.warning(
                "DatasetFilterIndex thumbnail-location query failed: %s", exc
            )
            return None

    # ------------------------------------------------------------------
    # Schema 管理（内部）
    # ------------------------------------------------------------------

    def _ensure_schema(self) -> None:
        """初始化数据库表结构（如果不存在则创建）。

        创建三张表：
        - dataset_meta: 存储元数据（如 schema_version）。
        - files: 存储文件级元数据（路径、mtime、size、shape 数量等）。
        - shapes: 存储 shape 级轻量索引字段（label、group_id、shape_type）。

        默认同时创建查询索引；staging rebuild 可以延迟到数据写入完成后创建。
        """
        assert self._conn is not None
        existing_version = self._read_schema_version()
        has_legacy_tables = existing_version is None and self._table_exists(
            "files"
        )
        if has_legacy_tables or (
            existing_version and existing_version != SCHEMA_VERSION
        ):
            logger.warning(
                "DatasetFilterIndex schema mismatch: "
                f"existing={existing_version}, expected={SCHEMA_VERSION}; "
                "recreating cache tables"
            )
            self._drop_schema()

        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS dataset_meta (
                key TEXT PRIMARY KEY,
                value TEXT
            );

            CREATE TABLE IF NOT EXISTS files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                image_path TEXT NOT NULL UNIQUE,
                json_path TEXT,
                sort_order INTEGER DEFAULT 0,
                json_mtime REAL,
                json_mtime_ns INTEGER DEFAULT 0,
                json_size INTEGER,
                shape_count INTEGER DEFAULT 0,
                indexed_at REAL DEFAULT 0,
                index_status TEXT DEFAULT 'ok',
                error_message TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS shapes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_id INTEGER NOT NULL,
                shape_index INTEGER NOT NULL,
                shape_id TEXT,
                label TEXT,
                group_id TEXT,
                shape_type TEXT,
                bbox_x_min REAL,
                bbox_y_min REAL,
                bbox_x_max REAL,
                bbox_y_max REAL,
                score REAL,
                description TEXT,
                difficult INTEGER,
                image_width REAL,
                image_height REAL,
                signature TEXT,
                FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE
            );
            """)
        if not self.defer_query_indexes:
            self._create_query_indexes()
        file_columns = {
            row[1] for row in self._conn.execute("PRAGMA table_info(files)")
        }
        if "json_mtime_ns" not in file_columns:
            self._conn.execute(
                "ALTER TABLE files ADD COLUMN "
                "json_mtime_ns INTEGER DEFAULT 0"
            )
        self._conn.execute(
            "INSERT OR REPLACE INTO dataset_meta (key, value) VALUES (?, ?)",
            ("schema_version", SCHEMA_VERSION),
        )
        self._conn.commit()

    def _create_query_indexes(
        self,
        cancel_check: Optional[CancelCheck] = None,
    ) -> bool:
        """Create all query indexes, optionally stopping between indexes.

        Args:
            cancel_check: Optional callback checked between index builds.

        Returns:
            ``True`` when every index exists, or ``False`` when cancelled.
        """
        assert self._conn is not None
        for _name, statement in QUERY_INDEX_DEFINITIONS:
            if cancel_check and cancel_check():
                return False
            self._conn.execute(statement)
        return not (cancel_check and cancel_check())

    def _read_schema_version(self) -> Optional[str]:
        """读取当前缓存数据库的 schema 版本。

        Returns:
            已存在的 schema_version；如果缓存是空库或读取失败，返回 None。
        """
        assert self._conn is not None
        try:
            cursor = self._conn.execute("""
                SELECT name FROM sqlite_master
                WHERE type = 'table' AND name = 'dataset_meta'
                """)
            if cursor.fetchone() is None:
                return None
            cursor = self._conn.execute(
                "SELECT value FROM dataset_meta WHERE key = ?",
                ("schema_version",),
            )
            row = cursor.fetchone()
            return row[0] if row else None
        except sqlite3.Error:
            return None

    def _table_exists(self, table_name: str) -> bool:
        """检查指定表是否存在。

        Args:
            table_name: SQLite 表名。

        Returns:
            表存在返回 True，否则返回 False。
        """
        assert self._conn is not None
        try:
            cursor = self._conn.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type = 'table' AND name = ?
                """,
                (table_name,),
            )
            return cursor.fetchone() is not None
        except sqlite3.Error:
            return False

    def _drop_schema(self) -> None:
        """删除旧 schema 表。

        当 schema_version 不匹配时调用。SQLite 缓存是派生数据，删除后
        可以从 JSON 重新构建，不会影响真实标注。
        """
        assert self._conn is not None
        self._conn.executescript("""
            DROP TABLE IF EXISTS shapes;
            DROP TABLE IF EXISTS files;
            DROP TABLE IF EXISTS dataset_meta;
            """)
        self._conn.commit()

    # ------------------------------------------------------------------
    # 增量更新（内部）
    # ------------------------------------------------------------------

    def _incremental_update(  # noqa: C901
        self,
        image_files: List[str],
        output_dir: Optional[str] = None,
        progress_callback: Optional[ProgressCallback] = None,
        cancel_check: Optional[CancelCheck] = None,
    ) -> DatasetIndexResult:
        """对比磁盘文件与缓存记录，执行增量更新。

        工作流程：
        1. 构建当前图片 -> JSON 路径映射。
        2. 加载缓存中的所有文件记录。
        3. 对比 mtime 和 size，识别新增/删除/修改的文件。
        4. 分别执行插入、更新、删除操作。
        5. 提交事务并记录统计信息。

        Args:
            image_files: 当前数据集中的所有图片路径列表。
            output_dir: JSON 标注文件存放目录。
            progress_callback: 进度回调，格式为 (current, total, filename)。
            cancel_check: 取消检查回调，返回 True 表示请求取消。

        Returns:
            本次增量更新结果。
        """
        assert self._conn is not None
        result = DatasetIndexResult(total=len(image_files))

        # 构建当前图片到 JSON 路径的映射
        current: dict[str, str] = {}
        current_by_json: dict[str, tuple[str, int]] = {}
        for sort_order, img in enumerate(image_files):
            jpath = self._json_path_for_image(img, output_dir)
            current[img] = jpath
            current_by_json[jpath] = (img, sort_order)
        current_json_paths = set(current.values())

        # 加载缓存中的文件记录
        cached: dict[str, tuple[int, float, int, int]] = {}
        try:
            cursor = self._conn.execute(
                "SELECT id, json_path, json_mtime, json_mtime_ns, "
                "json_size FROM files"
            )
            for row in cursor:
                file_id, jpath, mtime, mtime_ns, size = row
                cached[jpath] = (
                    file_id,
                    mtime or 0.0,
                    mtime_ns or 0,
                    size or 0,
                )
        except sqlite3.Error as exc:
            logger.warning(f"Failed to read cached files: {exc}")
            result.failed += 1
            result.fatal_error = True
            result.error_messages.append(str(exc))
            return result

        # 确定需要执行的操作
        to_remove: Set[int] = set()
        to_update: List[str] = []
        to_insert: List[str] = []

        for jpath, (
            file_id,
            cached_mtime,
            cached_mtime_ns,
            cached_size,
        ) in cached.items():
            if jpath not in current_json_paths:
                to_remove.add(file_id)
                continue
            try:
                st = os.stat(jpath)
            except OSError:
                to_remove.add(file_id)
                continue
            mtime_changed = (
                st.st_mtime_ns != cached_mtime_ns
                if cached_mtime_ns
                else st.st_mtime != cached_mtime
            )
            if mtime_changed or st.st_size != cached_size:
                to_update.append(jpath)

        for img, jpath in current.items():
            if jpath not in cached:
                to_insert.append(img)

        # 执行操作
        for file_id in to_remove:
            self._remove_by_file_id(file_id)
            result.removed += 1

        total_ops = len(to_update) + len(to_insert)
        current_op = 0

        for jpath, (_img, sort_order) in current_by_json.items():
            if jpath in cached and jpath not in to_update:
                file_id = cached[jpath][0]
                if file_id not in to_remove:
                    self._update_sort_order(file_id, sort_order)

        for jpath in to_update:
            if cancel_check and cancel_check():
                result.cancelled = True
                self._conn.rollback()
                return result
            file_id = self._file_id_for_json(jpath)
            if file_id is not None:
                _img, sort_order = current_by_json[jpath]
                self._remove_file_shapes(file_id)
                status = self._update_file(
                    file_id, jpath, sort_order=sort_order
                )
                result.updated += 1
                if status == INDEX_STATUS_ERROR:
                    result.failed += 1
                    result.error_messages.append(jpath)
            current_op += 1
            if progress_callback:
                progress_callback(current_op, total_ops, osp.basename(jpath))

        for img in to_insert:
            if cancel_check and cancel_check():
                result.cancelled = True
                self._conn.rollback()
                return result
            jpath = current[img]
            _img, sort_order = current_by_json[jpath]
            status = self._insert_single(img, jpath, sort_order=sort_order)
            result.inserted += 1
            if status == INDEX_STATUS_ERROR:
                result.failed += 1
                result.error_messages.append(jpath)
            current_op += 1
            if progress_callback:
                progress_callback(current_op, total_ops, osp.basename(jpath))

        self._conn.commit()
        logger.info(
            f"DatasetFilterIndex incremental update: "
            f"removed={len(to_remove)}, updated={len(to_update)}, "
            f"inserted={len(to_insert)}"
        )
        return result

    # ------------------------------------------------------------------
    # 插入 / 更新 / 删除（内部）
    # ------------------------------------------------------------------

    def _insert_files(
        self,
        image_files: List[str],
        output_dir: Optional[str] = None,
        progress_callback: Optional[ProgressCallback] = None,
        cancel_check: Optional[CancelCheck] = None,
    ) -> DatasetIndexResult:
        """Stream prepared files into SQLite during a full rebuild.

        A bounded number of JSON reads run concurrently. The caller thread
        writes each completed result immediately, allowing reads and SQLite
        writes to overlap without sharing the connection across threads.

        Args:
            image_files: 所有图片路径列表。
            output_dir: JSON 标注文件存放目录。
            progress_callback: 进度回调，格式为 (current, total, filename)。
            cancel_check: 取消检查回调，返回 True 表示请求取消。

        Returns:
            本次批量插入结果。
        """
        result = DatasetIndexResult(total=len(image_files))
        total = len(image_files)
        planning_started = time.perf_counter()
        entries = [
            (img, self._json_path_for_image(img, output_dir), sort_order)
            for sort_order, img in enumerate(image_files)
        ]
        result.performance.planning_seconds = (
            time.perf_counter() - planning_started
        )
        worker_count = min(INDEX_READ_WORKERS, max(total, 1))
        prefetch_limit = min(INDEX_READ_PREFETCH_LIMIT, max(total, 1))
        entry_iterator = iter(entries)
        pending: Set[Future[PreparedIndexFile]] = set()
        completed = 0
        pipeline_started = time.perf_counter()

        if cancel_check and cancel_check():
            result.cancelled = True
            self._conn.rollback()
            result.performance.pipeline_wall_seconds = (
                time.perf_counter() - pipeline_started
            )
            return result

        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            while len(pending) < prefetch_limit:
                try:
                    entry = next(entry_iterator)
                except StopIteration:
                    break
                pending.add(executor.submit(self._prepare_index_file, *entry))
            result.performance.max_in_flight = len(pending)

            while pending:
                if cancel_check and cancel_check():
                    result.cancelled = True
                    for future in pending:
                        future.cancel()
                    self._conn.rollback()
                    result.performance.pipeline_wall_seconds = (
                        time.perf_counter() - pipeline_started
                    )
                    return result

                done, pending = wait(
                    pending,
                    return_when=FIRST_COMPLETED,
                )
                for future in done:
                    if cancel_check and cancel_check():
                        result.cancelled = True
                        for pending_future in pending:
                            pending_future.cancel()
                        self._conn.rollback()
                        result.performance.pipeline_wall_seconds = (
                            time.perf_counter() - pipeline_started
                        )
                        return result

                    prepared = future.result()
                    result.performance.read_work_seconds += (
                        prepared.read_seconds
                    )
                    result.performance.json_bytes += prepared.json_size

                    try:
                        entry = next(entry_iterator)
                    except StopIteration:
                        entry = None
                    if entry is not None:
                        pending.add(
                            executor.submit(self._prepare_index_file, *entry)
                        )
                        result.performance.max_in_flight = max(
                            result.performance.max_in_flight,
                            len(pending),
                        )

                    write_started = time.perf_counter()
                    status = self._insert_prepared_file(prepared)
                    result.performance.sqlite_write_seconds += (
                        time.perf_counter() - write_started
                    )
                    result.inserted += 1
                    if status == INDEX_STATUS_ERROR:
                        result.failed += 1
                        result.error_messages.append(prepared.json_path)
                    completed += 1
                    if progress_callback:
                        progress_callback(
                            completed,
                            total,
                            osp.basename(prepared.json_path),
                        )
        commit_started = time.perf_counter()
        self._conn.commit()
        result.performance.commit_seconds = (
            time.perf_counter() - commit_started
        )
        result.performance.pipeline_wall_seconds = (
            time.perf_counter() - pipeline_started
        )
        return result

    def _insert_single(
        self, image_path: str, json_path: str, sort_order: int = 0
    ) -> str:
        """插入单个文件及其 shapes。

        如果 JSON 文件不存在，仍会插入一条 files 记录（shape_count=0），
        以确保该图片在 "无筛选条件" 查询时能被返回。

        Args:
            image_path: 图片文件路径。
            json_path: 对应的 JSON 标注文件路径。
            sort_order: 图片在原始 image_files 中的位置，用于保持导航顺序。

        Returns:
            本文件索引状态。
        """
        prepared = self._prepare_index_file(image_path, json_path, sort_order)
        return self._insert_prepared_file(prepared)

    @classmethod
    def _prepare_index_file(
        cls, image_path: str, json_path: str, sort_order: int
    ) -> PreparedIndexFile:
        """Read one JSON file without touching the SQLite connection."""
        read_started = time.perf_counter()
        try:
            stat_result = os.stat(json_path)
        except OSError:
            return PreparedIndexFile(
                image_path=image_path,
                json_path=json_path,
                sort_order=sort_order,
                status=INDEX_STATUS_MISSING,
                error_message="JSON file does not exist",
                read_seconds=time.perf_counter() - read_started,
            )
        shapes, error_message = cls._read_shapes(
            json_path, include_geometry=True, include_metadata=True
        )
        status = INDEX_STATUS_ERROR if error_message else INDEX_STATUS_OK
        return PreparedIndexFile(
            image_path=image_path,
            json_path=json_path,
            sort_order=sort_order,
            json_mtime=stat_result.st_mtime,
            json_mtime_ns=stat_result.st_mtime_ns,
            json_size=stat_result.st_size,
            shapes=shapes,
            status=status,
            error_message=error_message,
            read_seconds=time.perf_counter() - read_started,
        )

    def _insert_prepared_file(self, prepared: PreparedIndexFile) -> str:
        """Insert one already-read file record and all of its shapes."""
        if prepared.status == INDEX_STATUS_MISSING:
            self._conn.execute(
                """
                INSERT INTO files
                (image_path, json_path, sort_order, json_mtime,
                 json_mtime_ns, json_size, shape_count, indexed_at,
                 index_status, error_message)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    prepared.image_path,
                    prepared.json_path,
                    prepared.sort_order,
                    0.0,
                    0,
                    0,
                    0,
                    time.time(),
                    INDEX_STATUS_MISSING,
                    prepared.error_message,
                ),
            )
            return INDEX_STATUS_MISSING

        cursor = self._conn.execute(
            """
            INSERT INTO files
            (image_path, json_path, sort_order, json_mtime,
             json_mtime_ns, json_size, shape_count, indexed_at,
             index_status, error_message)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                prepared.image_path,
                prepared.json_path,
                prepared.sort_order,
                prepared.json_mtime,
                prepared.json_mtime_ns,
                prepared.json_size,
                len(prepared.shapes),
                time.time(),
                prepared.status,
                prepared.error_message,
            ),
        )
        file_id = cursor.lastrowid

        self._conn.executemany(
            """
            INSERT INTO shapes
            (file_id, shape_index, shape_id, label, group_id, shape_type,
             bbox_x_min, bbox_y_min, bbox_x_max, bbox_y_max,
             score, description, difficult, image_width, image_height, signature)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                (
                    file_id,
                    idx,
                    shape_id,
                    label,
                    gid,
                    stype,
                    *bbox,
                )
                for idx, (label, gid, stype, shape_id, *bbox) in enumerate(
                    prepared.shapes
                )
            ),
        )
        return prepared.status

    def _update_file(
        self, file_id: int, json_path: str, sort_order: Optional[int] = None
    ) -> str:
        """更新单个文件的元数据并重新插入其 shapes。

        先更新 files 表的 mtime/size/shape_count，然后重新解析 JSON 并插入 shapes。
        如果 JSON 文件已不存在，将 shape_count 设为 0。

        Args:
            file_id: 数据库中的文件记录 ID。
            json_path: JSON 标注文件路径。
            sort_order: 图片在原始 image_files 中的位置。None 表示不更新顺序。

        Returns:
            本文件索引状态。
        """
        sort_order_sql = ""
        params_prefix: tuple = ()
        if sort_order is not None:
            sort_order_sql = "sort_order = ?,"
            params_prefix = (sort_order,)

        try:
            stat_result = os.stat(json_path)
        except OSError:
            self._conn.execute(
                f"""
                UPDATE files
                SET json_path = ?, {sort_order_sql} json_mtime = ?,
                    json_mtime_ns = ?, json_size = ?, shape_count = ?,
                    indexed_at = ?, index_status = ?, error_message = ?
                WHERE id = ?
                """,
                (json_path,)
                + params_prefix
                + (
                    0.0,
                    0,
                    0,
                    0,
                    time.time(),
                    INDEX_STATUS_MISSING,
                    "JSON file does not exist",
                    file_id,
                ),
            )
            return INDEX_STATUS_MISSING

        shapes, error_message = self._read_shapes(
            json_path, include_geometry=True, include_metadata=True
        )
        status = INDEX_STATUS_ERROR if error_message else INDEX_STATUS_OK

        self._conn.execute(
            f"""
            UPDATE files
            SET json_path = ?, {sort_order_sql} json_mtime = ?,
                json_mtime_ns = ?, json_size = ?, shape_count = ?, indexed_at = ?,
                index_status = ?, error_message = ?
            WHERE id = ?
            """,
            (json_path,)
            + params_prefix
            + (
                stat_result.st_mtime,
                stat_result.st_mtime_ns,
                stat_result.st_size,
                len(shapes),
                time.time(),
                status,
                error_message,
                file_id,
            ),
        )

        self._conn.executemany(
            """
            INSERT INTO shapes
            (file_id, shape_index, shape_id, label, group_id, shape_type,
             bbox_x_min, bbox_y_min, bbox_x_max, bbox_y_max,
             score, description, difficult, image_width, image_height, signature)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                (
                    file_id,
                    idx,
                    shape_id,
                    label,
                    gid,
                    stype,
                    *bbox,
                )
                for idx, (label, gid, stype, shape_id, *bbox) in enumerate(
                    shapes
                )
            ),
        )
        return status

    def _remove_by_file_id(self, file_id: int) -> None:
        """根据 file_id 删除文件记录及其关联的 shapes（级联删除）。

        Args:
            file_id: 数据库中的文件记录 ID。
        """
        self._conn.execute("DELETE FROM shapes WHERE file_id = ?", (file_id,))
        self._conn.execute("DELETE FROM files WHERE id = ?", (file_id,))

    def _update_sort_order(self, file_id: int, sort_order: int) -> None:
        """更新文件排序序号。

        即使 JSON 没有变化，目录重新加载后的 image_files 顺序也可能变化。
        这里单独更新 sort_order，保证查询结果和导航顺序始终跟随当前文件列表。

        Args:
            file_id: 数据库中的文件记录 ID。
            sort_order: 图片在当前 image_files 中的位置。
        """
        self._conn.execute(
            "UPDATE files SET sort_order = ? WHERE id = ?",
            (sort_order, file_id),
        )

    def _remove_by_json_path(self, json_path: str) -> None:
        """根据 JSON 路径删除文件记录。

        Args:
            json_path: JSON 标注文件路径。
        """
        file_id = self._file_id_for_json(json_path)
        if file_id is not None:
            self._remove_by_file_id(file_id)

    def _remove_file_shapes(self, file_id: int) -> None:
        """删除指定文件的所有 shape 记录。

        在更新文件前调用，清除旧 shapes 后再插入新 shapes。

        Args:
            file_id: 数据库中的文件记录 ID。
        """
        self._conn.execute("DELETE FROM shapes WHERE file_id = ?", (file_id,))

    def _clear_all(self) -> None:
        """清空所有表（ rebuild 时调用）。

        删除 shapes 和 files 表的所有数据，保留 schema 结构。
        同时重置 schema_version 记录。
        """
        self._conn.execute("DELETE FROM shapes")
        self._conn.execute("DELETE FROM files")
        self._conn.execute(
            "INSERT OR REPLACE INTO dataset_meta (key, value) VALUES (?, ?)",
            ("schema_version", SCHEMA_VERSION),
        )

    # ------------------------------------------------------------------
    # 辅助方法（内部）
    # ------------------------------------------------------------------

    def _file_id_for_json(self, json_path: str) -> Optional[int]:
        """根据 JSON 路径查询对应的 file_id。

        Args:
            json_path: JSON 标注文件路径。

        Returns:
            文件记录 ID，若不存在则返回 None。
        """
        try:
            cursor = self._conn.execute(
                "SELECT id FROM files WHERE json_path = ?", (json_path,)
            )
            row = cursor.fetchone()
            return row[0] if row else None
        except sqlite3.Error:
            return None

    def _file_id_for_image(self, image_path: str) -> Optional[int]:
        """根据图片路径查询对应的 file_id。

        Args:
            image_path: 图片文件路径。

        Returns:
            文件记录 ID，若不存在则返回 None。
        """
        try:
            cursor = self._conn.execute(
                "SELECT id FROM files WHERE image_path = ?", (image_path,)
            )
            row = cursor.fetchone()
            return row[0] if row else None
        except sqlite3.Error:
            return None

    def _all_image_paths(self) -> List[str]:
        """获取缓存中所有图片路径。

        Returns:
            所有已索引的图片路径列表，按原始 image_files 顺序排序。
        """
        try:
            cursor = self._conn.execute(
                "SELECT image_path FROM files ORDER BY sort_order, image_path"
            )
            return [row[0] for row in cursor.fetchall()]
        except sqlite3.Error as exc:
            logger.warning(f"Failed to list image paths: {exc}")
            return []

    @staticmethod
    def _json_path_for_image(
        image_file: str, output_dir: Optional[str] = None
    ) -> str:
        """根据图片路径推导对应的 JSON 标注路径。

        规则：
        1. 将图片扩展名替换为 .json。
        2. 如果指定了 output_dir，JSON 放在 output_dir 下（使用 basename）。
        3. 否则 JSON 与图片在同一目录。

        Args:
            image_file: 图片文件路径。
            output_dir: JSON 标注文件存放目录（可选）。

        Returns:
            推导出的 JSON 文件路径。
        """
        label_file = osp.splitext(image_file)[0] + ".json"
        if output_dir:
            label_file = osp.join(output_dir, osp.basename(label_file))
        return label_file

    @staticmethod
    def _read_shapes(
        json_path: str,
        include_geometry: bool = False,
        include_metadata: bool = False,
    ) -> Tuple[List[tuple], str]:
        """从 JSON 文件中读取轻量 shape 字段。

        只提取查询所需的字段：label、group_id、shape_type；缩略图索引
        构建时可额外提取永久 Shape ID 和 bbox，不保留完整 points。

        Args:
            json_path: JSON 标注文件路径。

        Returns:
            二元组 `(shapes, error_message)`。默认 shapes 中每个元素为
            `(label, group_id, shape_type)`；当 ``include_geometry`` 为真时，
            每个元素还包含 `shape_id` 和四个 bbox 值。如果解析失败，
            shapes 为空，error_message 保存失败原因。
        """
        try:
            dimensions = {}
            with open(json_path, "r", encoding="utf-8") as f:
                shape_values = read_top_level_array(
                    f, "shapes", metadata=dimensions
                )
            results = []
            for shape in shape_values:
                if not isinstance(shape, dict):
                    raise JsonStreamError("Shape entry is not an object")
                label = shape.get("label", "") or ""
                gid = shape.get("group_id")
                gid = str(gid) if gid is not None else "-1"
                stype = shape.get("shape_type", "") or ""
                if not include_geometry:
                    results.append((label, gid, stype))
                    continue
                shape_id_value = shape.get("xanylabeling_shape_id")
                shape_id = (
                    str(shape_id_value) if shape_id_value is not None else ""
                )
                bbox = _points_bbox(shape.get("points"))
                extra = (
                    review_metadata(shape, dimensions)
                    if include_metadata
                    else ()
                )
                results.append((label, gid, stype, shape_id, *bbox, *extra))
        except (JsonStreamError, OSError, AttributeError) as exc:
            logger.warning(
                f"Failed to read JSON index fields {json_path}: {exc}"
            )
            return [], str(exc)
        return results, ""


# ---------------------------------------------------------------------------
# 工厂函数
# ---------------------------------------------------------------------------


def make_db_path(dataset_root: str) -> str:
    """根据数据集根目录生成稳定的缓存数据库路径。

    使用 SHA256 哈希确保不同数据集有独立的缓存文件，
    避免多个数据集共用同一缓存导致数据混乱。

    Args:
        dataset_root: 数据集根目录路径。

    Returns:
        缓存数据库文件的绝对路径。
    """
    dataset_root = osp.normcase(osp.abspath(osp.normpath(dataset_root)))
    digest = hashlib.sha256(dataset_root.encode("utf-8")).hexdigest()[:16]
    os.makedirs(CACHE_DIR, exist_ok=True)
    return osp.join(CACHE_DIR, f"{digest}.db")


def make_staging_db_path(db_path: str) -> str:
    """Return a unique same-directory path for an atomic cache rebuild."""
    return f"{db_path}.rebuild-{uuid.uuid4().hex}.tmp"


def remove_database_files(db_path: Optional[str]) -> None:
    """Remove a derived SQLite database and its transient sidecar files."""
    if not db_path:
        return
    for suffix in ("", "-wal", "-shm"):
        path = f"{db_path}{suffix}"
        try:
            if osp.exists(path):
                os.remove(path)
        except OSError as exc:
            logger.warning(f"Failed to remove temporary index {path}: {exc}")


def install_staged_database(staged_path: str, target_path: str) -> None:
    """Atomically replace a closed target cache with a completed staging DB."""
    if not osp.isfile(staged_path):
        raise FileNotFoundError(staged_path)
    for suffix in ("-wal", "-shm"):
        sidecar = f"{target_path}{suffix}"
        if osp.exists(sidecar):
            os.remove(sidecar)
    os.replace(staged_path, target_path)


def _normalize_path(path: str) -> str:
    """Return a stable absolute identity path."""
    return osp.normcase(osp.abspath(osp.normpath(path)))


def _normalize_optional_path(path: Optional[str]) -> str:
    """Normalize an optional path for metadata comparison."""
    return _normalize_path(path) if path else ""
