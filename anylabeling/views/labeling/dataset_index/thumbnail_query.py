"""Pure SQL-backed thumbnail filtering, stable sorting and review metadata."""

from __future__ import annotations

import hashlib
import json
import math
import os.path as osp
import sqlite3
from dataclasses import dataclass, fields
from typing import Any

from .types import DatasetThumbnailPage, DatasetThumbnailRef

REVIEW_STATES = ("unreviewed", "confirmed", "needs_edit", "skipped")
SORT_MODES = ("original", "small_pixels", "small_relative", "aspect_outliers")


def finite_number(value: Any) -> float | None:
    """Return a finite numeric annotation value, excluding booleans."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value) if math.isfinite(value) else None
    return None


def review_metadata(shape: dict, dimensions: dict) -> tuple:
    """Extract searchable attributes and an exact semantic shape revision."""
    width = finite_number(dimensions.get("imageWidth"))
    height = finite_number(dimensions.get("imageHeight"))
    signature = hashlib.sha256(
        json.dumps(
            shape, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    return (
        finite_number(shape.get("score", shape.get("scoring"))),
        str(shape.get("description") or ""),
        int(bool(shape.get("difficult", False))),
        width if width and width > 0 else None,
        height if height and height > 0 else None,
        signature,
    )


@dataclass(frozen=True)
class ThumbnailQuery:
    """Optional filters; empty fields preserve the existing original order."""

    filename: str = ""
    sort: str = "original"
    area_unit: str = "pixels"
    area_min: float | None = None
    area_max: float | None = None
    ratio_min: float | None = None
    ratio_max: float | None = None
    score_min: float | None = None
    score_max: float | None = None
    group_id: str = ""
    description: str = ""
    difficult: str = ""
    shape_type: str = ""
    review: str = ""

    def validate(self) -> None:
        """Reject unsupported choices and inverted or nonfinite ranges."""
        if self.sort not in SORT_MODES or self.area_unit not in (
            "pixels",
            "percent",
        ):
            raise ValueError("Invalid sort or area unit")
        if self.review not in ("", *REVIEW_STATES) or self.difficult not in (
            "",
            "yes",
            "no",
        ):
            raise ValueError("Invalid status filter")
        for name in ("filename", "group_id", "description", "shape_type"):
            if not isinstance(getattr(self, name), str):
                raise ValueError("Invalid text filter")
        for name in ("area", "ratio", "score"):
            low, high = getattr(self, name + "_min"), getattr(
                self, name + "_max"
            )
            for value in (low, high):
                if value is not None and (
                    finite_number(value) is None
                    or (name != "score" and value < 0)
                ):
                    raise ValueError(
                        "Ranges must contain finite valid numbers"
                    )
            if low is not None and high is not None and low > high:
                raise ValueError("Minimum must not exceed maximum")

    @classmethod
    def from_dict(cls, value: object) -> ThumbnailQuery:
        """Load saved settings without trusting malformed values."""
        if not isinstance(value, dict):
            return cls()
        try:
            result = cls(
                **{
                    f.name: value[f.name]
                    for f in fields(cls)
                    if f.name in value
                }
            )
            result.validate()
            return result
        except (ValueError, TypeError):
            return cls()


_WIDTH = "(s.bbox_x_max-s.bbox_x_min)"
_HEIGHT = "(s.bbox_y_max-s.bbox_y_min)"
_VALID = f"{_WIDTH}>0 AND {_HEIGHT}>0"
_AREA = f"CASE WHEN {_VALID} THEN {_WIDTH}*{_HEIGHT} END"
_RATIO = f"CASE WHEN {_VALID} THEN 1.0*{_WIDTH}/{_HEIGHT} END"
_PERCENT = f"CASE WHEN s.image_width>0 AND s.image_height>0 THEN 100.0*({_AREA})/s.image_width/s.image_height END"
_UNIQUE = "(SELECT COUNT(*) FROM shapes si WHERE si.file_id=s.file_id AND si.shape_id=s.shape_id)=1 AND s.shape_id<>''"


def _log(value: float | None) -> float | None:
    """Return a safe logarithm for SQLite's ratio ordering."""
    return math.log(value) if value and value > 0 else None


def _path(value: str) -> str:
    """Match persisted paths using the host filesystem's case rules."""
    return osp.normcase(osp.abspath(value))


def _query_base(
    conn: sqlite3.Connection, label: str, review_db: str | None
) -> tuple[str, list]:
    """Build trusted SQL expressions; user values remain bound parameters."""
    join = ""
    conn.create_function("thumb_path", 1, _path)
    status = "'unreviewed'"
    if review_db:
        if any(
            row[1] == "thumb_review"
            for row in conn.execute("PRAGMA database_list")
        ):
            conn.execute("DETACH DATABASE thumb_review")
        conn.execute("ATTACH DATABASE ? AS thumb_review", (review_db,))
        join = "LEFT JOIN thumb_review.marks r ON r.image_path=thumb_path(f.image_path) AND r.shape_id=s.shape_id"
        status = f"CASE WHEN ({_UNIQUE}) AND r.signature=s.signature THEN r.state ELSE 'unreviewed' END"
    sql = f"""SELECT f.image_path, f.json_path, f.sort_order, s.shape_index,
        s.shape_id, s.label, s.bbox_x_min, s.bbox_y_min, s.bbox_x_max, s.bbox_y_max,
        s.score, s.description, s.difficult, s.group_id, s.shape_type,
        s.image_width, s.image_height, s.signature,
        {status} AS review_status, ({_UNIQUE}) AS unique_identity,
        {_AREA} AS area, {_PERCENT} AS percent, {_RATIO} AS ratio
        FROM shapes s JOIN files f ON f.id=s.file_id {join} WHERE s.label=?"""
    return sql, [label]


def _conditions(options: ThumbnailQuery) -> tuple[str, list]:
    """Translate filters into parameters without accepting SQL fragments."""
    conditions, values = [], []
    for column, value in (
        ("image_path", options.filename),
        ("description", options.description),
    ):
        if value:
            conditions.append(f"instr(lower({column}),lower(?))>0")
            values.append(value)
    for column, value in (
        ("group_id", options.group_id),
        ("shape_type", options.shape_type),
        ("review_status", options.review),
    ):
        if value:
            conditions.append(f"{column}=?")
            values.append(value)
    if options.difficult:
        conditions.append("difficult=?")
        values.append(int(options.difficult == "yes"))
    for name, column in (
        ("area", "percent" if options.area_unit == "percent" else "area"),
        ("ratio", "ratio"),
        ("score", "score"),
    ):
        for suffix, operator in (("min", ">="), ("max", "<=")):
            value = getattr(options, f"{name}_{suffix}")
            if value is not None:
                conditions.append(f"{column}{operator}?")
                values.append(value)
    return " AND ".join(conditions) or "1", values


def query_review_page(
    conn: sqlite3.Connection,
    label: str,
    limit: int = 100,
    offset: int = 0,
    options: ThumbnailQuery | None = None,
    review_db: str | None = None,
    anchor: tuple[str, str] | None = None,
) -> DatasetThumbnailPage:
    """Filter and rank the whole label before limiting the returned cards."""
    options = options or ThumbnailQuery()
    options.validate()
    limit, offset = max(1, min(100, limit)), max(0, offset)
    base, params = _query_base(conn, label, review_db)
    where, extra = _conditions(options)
    order = "sort_order,image_path,shape_index"
    if options.sort in ("small_pixels", "small_relative"):
        column = "area" if options.sort == "small_pixels" else "percent"
        order = f"{column} IS NULL,{column}," + order
    elif options.sort == "aspect_outliers":
        conn.create_function("thumb_log", 1, _log)
        # Median over the entire label, independent of optional filters.
        count = conn.execute(
            f"SELECT COUNT(*) FROM shapes s WHERE s.label=? AND {_VALID}",
            (label,),
        ).fetchone()[0]
        row = conn.execute(
            f"SELECT {_RATIO} FROM shapes s WHERE s.label=? AND {_VALID} ORDER BY {_RATIO} LIMIT 1 OFFSET ?",
            (label, count // 2),
        ).fetchone()
        median = float(row[0]) if row else 1.0
        order = (
            f"ratio IS NULL,abs(thumb_log(ratio)-thumb_log({median!r})) DESC,"
            + order
        )
    cte = f"WITH objects AS ({base}), filtered AS (SELECT * FROM objects WHERE {where})"
    params += extra
    total = conn.execute(
        cte + " SELECT COUNT(*) FROM filtered", params
    ).fetchone()[0]
    if anchor:
        ranked = (
            cte
            + f", ranked AS (SELECT *,row_number() OVER (ORDER BY {order})-1 AS pos FROM filtered) SELECT pos FROM ranked WHERE thumb_path(image_path)=thumb_path(?) AND shape_id=?"
        )
        matches = conn.execute(ranked, [*params, *anchor]).fetchall()
        if len(matches) == 1:
            offset = int(matches[0][0]) // limit * limit
    rows = conn.execute(
        cte + f" SELECT * FROM filtered ORDER BY {order} LIMIT ? OFFSET ?",
        [*params, limit, offset],
    ).fetchall()
    items = tuple(
        DatasetThumbnailRef(
            str(r[0]),
            str(r[1] or ""),
            int(r[2]),
            int(r[3]),
            str(r[4] or ""),
            str(r[5]),
            tuple(r[6:10]) if all(v is not None for v in r[6:10]) else None,
            r[10],
            str(r[11] or ""),
            bool(r[12]),
            str(r[13]),
            str(r[14]),
            r[15],
            r[16],
            str(r[17] or ""),
            str(r[18]),
            bool(r[19]),
        )
        for r in rows
    )
    return DatasetThumbnailPage(label, int(total), limit, offset, items)
