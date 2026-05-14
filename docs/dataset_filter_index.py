"""DatasetFilterIndex — 基于 SQLite 的派生索引缓存，用于快速筛选查询。

JSON 标注文件是唯一真实数据源。
SQLite 仅作为可丢弃、可重建的索引缓存，不保存不可从 JSON 恢复的信息。
"""

import hashlib
import json
import logging
import os
import os.path as osp
import sqlite3
import time
from typing import List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

SCHEMA_VERSION = "2"
CACHE_DIR = osp.expanduser("~/.cache/xanylabeling/dataset_index")
INDEX_STATUS_OK = "ok"
INDEX_STATUS_MISSING = "missing"
INDEX_STATUS_ERROR = "error"

# ---------------------------------------------------------------------------
# 公共 API
# ---------------------------------------------------------------------------


class DatasetFilterIndex:
    """基于 SQLite 的 JSON 标注派生索引，用于快速筛选和导航。

    所有标注数据仍从 JSON 文件读取，本模块永远不会写入 JSON。
    SQLite 数据库是一个可随时删除并重建的临时缓存。
    """

    def __init__(self, db_path: Optional[str] = None):
        """初始化索引实例。

        Args:
            db_path: SQLite 数据库文件路径。若为 None，则后续所有操作跳过。
        """
        self.db_path = db_path
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
        if self.db_path is None:
            return False
        try:
            self._conn = sqlite3.connect(self.db_path)
            self._conn.execute("PRAGMA foreign_keys = ON")
            self._ensure_schema()
            return True
        except sqlite3.Error as exc:
            logger.warning(f"Failed to open SQLite cache {self.db_path}: {exc}")
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

    # ------------------------------------------------------------------
    # 高层操作（供外部调用）
    # ------------------------------------------------------------------

    def load_or_build(
        self,
        image_files: List[str],
        output_dir: Optional[str] = None,
    ) -> None:
        """确保缓存与当前图片列表保持同步（增量更新）。

        工作流程：
        1. 扫描现有缓存中的所有文件记录。
        2. 对比磁盘上 JSON 文件的 mtime 和 size，识别新增/删除/修改的文件。
        3. 对变化的文件进行增量更新。
        4. 插入新文件，移除已删除的文件。

        Args:
            image_files: 当前数据集中的所有图片路径列表。
            output_dir: JSON 标注文件存放目录。若为 None，则在与图片相同目录查找 JSON。
        """
        if not self.open():
            logger.info("DatasetFilterIndex: skipping (no db_path)")
            return
        self._incremental_update(image_files, output_dir)

    def refresh(
        self,
        image_files: List[str],
        output_dir: Optional[str] = None,
    ) -> None:
        """刷新索引（与 load_or_build 等价，语义上表示显式刷新）。

        Args:
            image_files: 当前数据集中的所有图片路径列表。
            output_dir: JSON 标注文件存放目录。
        """
        self.load_or_build(image_files, output_dir)

    def rebuild(
        self,
        image_files: List[str],
        output_dir: Optional[str] = None,
    ) -> None:
        """清空现有缓存并从头重建。

        适用场景：
        - 缓存文件损坏或 schema 版本不匹配。
        - 用户手动触发 "Rebuild Dataset Index"。
        - 需要确保索引与磁盘完全一致。

        Args:
            image_files: 当前数据集中的所有图片路径列表。
            output_dir: JSON 标注文件存放目录。
        """
        if not self.open():
            return
        self._clear_all()
        self._insert_files(image_files, output_dir)

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
        if file_id is not None:
            self._remove_file_shapes(file_id)
            self._update_file(file_id, json_path)
        else:
            self._insert_single(image_path, json_path)
        self._conn.commit()

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

    # ------------------------------------------------------------------
    # Schema 管理（内部）
    # ------------------------------------------------------------------

    def _ensure_schema(self) -> None:
        """初始化数据库表结构（如果不存在则创建）。

        创建三张表：
        - dataset_meta: 存储元数据（如 schema_version）。
        - files: 存储文件级元数据（路径、mtime、size、shape 数量等）。
        - shapes: 存储 shape 级轻量索引字段（label、group_id、shape_type）。

        同时创建 shapes 表上的索引，加速查询。
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

        self._conn.executescript(
            """
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
                label TEXT,
                group_id TEXT,
                shape_type TEXT,
                FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_shapes_label
                ON shapes(label);
            CREATE INDEX IF NOT EXISTS idx_shapes_group_id
                ON shapes(group_id);
            CREATE INDEX IF NOT EXISTS idx_shapes_shape_type
                ON shapes(shape_type);
            CREATE INDEX IF NOT EXISTS idx_shapes_file_id
                ON shapes(file_id);
            CREATE INDEX IF NOT EXISTS idx_shapes_file_shape
                ON shapes(file_id, shape_index);
            CREATE INDEX IF NOT EXISTS idx_files_sort_order
                ON files(sort_order);
            """
        )
        self._conn.execute(
            "INSERT OR REPLACE INTO dataset_meta (key, value) VALUES (?, ?)",
            ("schema_version", SCHEMA_VERSION),
        )
        self._conn.commit()

    def _read_schema_version(self) -> Optional[str]:
        """读取当前缓存数据库的 schema 版本。

        Returns:
            已存在的 schema_version；如果缓存是空库或读取失败，返回 None。
        """
        assert self._conn is not None
        try:
            cursor = self._conn.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type = 'table' AND name = 'dataset_meta'
                """
            )
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
        self._conn.executescript(
            """
            DROP TABLE IF EXISTS shapes;
            DROP TABLE IF EXISTS files;
            DROP TABLE IF EXISTS dataset_meta;
            """
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # 增量更新（内部）
    # ------------------------------------------------------------------

    def _incremental_update(
        self,
        image_files: List[str],
        output_dir: Optional[str] = None,
    ) -> None:
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
        """
        assert self._conn is not None

        # 构建当前图片到 JSON 路径的映射
        current: dict[str, str] = {}
        current_by_json: dict[str, tuple[str, int]] = {}
        for sort_order, img in enumerate(image_files):
            jpath = self._json_path_for_image(img, output_dir)
            current[img] = jpath
            current_by_json[jpath] = (img, sort_order)
        current_json_paths = set(current.values())

        # 加载缓存中的文件记录
        cached: dict[str, tuple[int, float, int]] = {}
        try:
            cursor = self._conn.execute(
                "SELECT id, json_path, json_mtime, json_size FROM files"
            )
            for row in cursor:
                file_id, jpath, mtime, size = row
                cached[jpath] = (file_id, mtime or 0.0, size or 0)
        except sqlite3.Error as exc:
            logger.warning(f"Failed to read cached files: {exc}")
            return

        # 确定需要执行的操作
        to_remove: Set[int] = set()
        to_update: List[str] = []
        to_insert: List[str] = []

        for jpath, (file_id, cached_mtime, cached_size) in cached.items():
            if jpath not in current_json_paths:
                to_remove.add(file_id)
                continue
            if not osp.exists(jpath):
                to_remove.add(file_id)
                continue
            st = os.stat(jpath)
            if st.st_mtime != cached_mtime or st.st_size != cached_size:
                to_update.append(jpath)

        for img, jpath in current.items():
            if jpath not in cached:
                to_insert.append(img)

        # 执行操作
        for file_id in to_remove:
            self._remove_by_file_id(file_id)

        for jpath, (_img, sort_order) in current_by_json.items():
            if jpath in cached and jpath not in to_update:
                file_id = cached[jpath][0]
                if file_id not in to_remove:
                    self._update_sort_order(file_id, sort_order)

        for jpath in to_update:
            file_id = self._file_id_for_json(jpath)
            if file_id is not None:
                _img, sort_order = current_by_json[jpath]
                self._remove_file_shapes(file_id)
                self._update_file(file_id, jpath, sort_order=sort_order)

        for img in to_insert:
            jpath = current[img]
            _img, sort_order = current_by_json[jpath]
            self._insert_single(img, jpath, sort_order=sort_order)

        self._conn.commit()
        logger.info(
            f"DatasetFilterIndex incremental update: "
            f"removed={len(to_remove)}, updated={len(to_update)}, "
            f"inserted={len(to_insert)}"
        )

    # ------------------------------------------------------------------
    # 插入 / 更新 / 删除（内部）
    # ------------------------------------------------------------------

    def _insert_files(
        self,
        image_files: List[str],
        output_dir: Optional[str] = None,
    ) -> None:
        """批量插入所有图片文件（ rebuild 时调用）。

        遍历所有图片，逐个插入文件记录和 shape 记录，最后统一提交事务。

        Args:
            image_files: 所有图片路径列表。
            output_dir: JSON 标注文件存放目录。
        """
        for sort_order, img in enumerate(image_files):
            jpath = self._json_path_for_image(img, output_dir)
            self._insert_single(img, jpath, sort_order=sort_order)
        self._conn.commit()

    def _insert_single(
        self, image_path: str, json_path: str, sort_order: int = 0
    ) -> None:
        """插入单个文件及其 shapes。

        如果 JSON 文件不存在，仍会插入一条 files 记录（shape_count=0），
        以确保该图片在 "无筛选条件" 查询时能被返回。

        Args:
            image_path: 图片文件路径。
            json_path: 对应的 JSON 标注文件路径。
            sort_order: 图片在原始 image_files 中的位置，用于保持导航顺序。
        """
        if not osp.exists(json_path):
            self._conn.execute(
                """
                INSERT INTO files
                (image_path, json_path, sort_order, json_mtime, json_size,
                 shape_count, indexed_at, index_status, error_message)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    image_path,
                    json_path,
                    sort_order,
                    0.0,
                    0,
                    0,
                    time.time(),
                    INDEX_STATUS_MISSING,
                    "JSON file does not exist",
                ),
            )
            return

        st = os.stat(json_path)
        shapes, error_message = self._read_shapes(json_path)
        status = INDEX_STATUS_ERROR if error_message else INDEX_STATUS_OK

        cursor = self._conn.execute(
            """
            INSERT INTO files
            (image_path, json_path, sort_order, json_mtime, json_size,
             shape_count, indexed_at, index_status, error_message)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                image_path,
                json_path,
                sort_order,
                st.st_mtime,
                st.st_size,
                len(shapes),
                time.time(),
                status,
                error_message,
            ),
        )
        file_id = cursor.lastrowid

        for idx, (label, gid, stype) in enumerate(shapes):
            self._conn.execute(
                """
                INSERT INTO shapes
                (file_id, shape_index, label, group_id, shape_type)
                VALUES (?, ?, ?, ?, ?)
                """,
                (file_id, idx, label, gid, stype),
            )

    def _update_file(
        self, file_id: int, json_path: str, sort_order: Optional[int] = None
    ) -> None:
        """更新单个文件的元数据并重新插入其 shapes。

        先更新 files 表的 mtime/size/shape_count，然后重新解析 JSON 并插入 shapes。
        如果 JSON 文件已不存在，将 shape_count 设为 0。

        Args:
            file_id: 数据库中的文件记录 ID。
            json_path: JSON 标注文件路径。
            sort_order: 图片在原始 image_files 中的位置。None 表示不更新顺序。
        """
        sort_order_sql = ""
        params_prefix: tuple = ()
        if sort_order is not None:
            sort_order_sql = "sort_order = ?,"
            params_prefix = (sort_order,)

        if not osp.exists(json_path):
            self._conn.execute(
                f"""
                UPDATE files
                SET {sort_order_sql} json_mtime = ?, json_size = ?,
                    shape_count = ?, indexed_at = ?, index_status = ?,
                    error_message = ?
                WHERE id = ?
                """,
                params_prefix
                + (
                    0.0,
                    0,
                    0,
                    time.time(),
                    INDEX_STATUS_MISSING,
                    "JSON file does not exist",
                    file_id,
                ),
            )
            return

        st = os.stat(json_path)
        shapes, error_message = self._read_shapes(json_path)
        status = INDEX_STATUS_ERROR if error_message else INDEX_STATUS_OK

        self._conn.execute(
            f"""
            UPDATE files
            SET {sort_order_sql} json_mtime = ?, json_size = ?,
                shape_count = ?, indexed_at = ?,
                index_status = ?, error_message = ?
            WHERE id = ?
            """,
            params_prefix
            + (
                st.st_mtime,
                st.st_size,
                len(shapes),
                time.time(),
                status,
                error_message,
                file_id,
            ),
        )

        for idx, (label, gid, stype) in enumerate(shapes):
            self._conn.execute(
                """
                INSERT INTO shapes
                (file_id, shape_index, label, group_id, shape_type)
                VALUES (?, ?, ?, ?, ?)
                """,
                (file_id, idx, label, gid, stype),
            )

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
        self._conn.execute(
            "DELETE FROM shapes WHERE file_id = ?", (file_id,)
        )

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
    def _read_shapes(json_path: str) -> Tuple[List[tuple], str]:
        """从 JSON 文件中读取轻量 shape 字段。

        只提取查询所需的字段：label、group_id、shape_type。
        不读取 points、imageData 等完整数据。

        Args:
            json_path: JSON 标注文件路径。

        Returns:
            二元组 `(shapes, error_message)`。shapes 中每个元素为
            `(label, group_id, shape_type)`。如果解析失败，shapes 为空，
            error_message 保存失败原因。
        """
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError, AttributeError) as exc:
            logger.warning(f"Failed to read JSON index fields {json_path}: {exc}")
            return [], str(exc)

        results = []
        for shape in data.get("shapes", []):
            label = shape.get("label", "") or ""
            gid = shape.get("group_id")
            gid = str(gid) if gid is not None else "-1"
            stype = shape.get("shape_type", "") or ""
            results.append((label, gid, stype))
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
