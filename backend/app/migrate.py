"""Additive schema reconciliation at startup.

`Base.metadata.create_all` creates missing *tables* but never touches a table
that already exists, so adding a column to a model breaks every existing
deployment with "no such column" until the database is wiped. Wiping is not an
option once real reports are in there.

This closes exactly that gap and nothing more: it adds columns that the models
declare and the database lacks. It deliberately does NOT drop, rename, retype or
reorder anything — those change or destroy existing data and need a real
migration with a human deciding what happens to each row. When you need one,
bring in Alembic; this module stays as the safety net for the additive case.
"""
import logging

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from .database import Base

logger = logging.getLogger("floodwatch.migrate")


def _column_ddl(column, dialect) -> str | None:
    """DDL for one ADD COLUMN, or None when it cannot be added safely.

    A NOT NULL column with no server default cannot be added to a table that
    already has rows — the existing rows would have nothing to put in it.
    """
    try:
        type_sql = column.type.compile(dialect=dialect)
    except SQLAlchemyError:
        return None

    parts = [f'"{column.name}"', type_sql]

    if column.server_default is not None:
        default = getattr(column.server_default, "arg", None)
        if default is not None:
            parts.append(f"DEFAULT {default}")
            if not column.nullable:
                parts.append("NOT NULL")
    elif not column.nullable:
        # Add it as nullable rather than refusing outright: the application
        # already treats a fresh column as empty, and refusing would leave the
        # app unable to start at all.
        logger.warning(
            "คอลัมน์ %s เป็น NOT NULL แต่ไม่มีค่าเริ่มต้น จะเพิ่มแบบยอมให้ว่างแทน",
            column.name,
        )

    return " ".join(parts)


def sync_schema(engine: Engine) -> list[str]:
    """Add any model columns missing from existing tables. Returns what changed."""
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    applied: list[str] = []

    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue  # create_all handles brand-new tables

        present = {col["name"] for col in inspector.get_columns(table.name)}
        missing = [col for col in table.columns if col.name not in present]
        if not missing:
            continue

        for column in missing:
            ddl = _column_ddl(column, engine.dialect)
            if ddl is None:
                logger.warning("ข้ามคอลัมน์ %s.%s — สร้าง DDL ไม่ได้", table.name, column.name)
                continue
            statement = f'ALTER TABLE "{table.name}" ADD COLUMN {ddl}'
            try:
                with engine.begin() as connection:
                    connection.execute(text(statement))
                applied.append(f"{table.name}.{column.name}")
                logger.info("เพิ่มคอลัมน์ %s.%s", table.name, column.name)
            except SQLAlchemyError as exc:
                # One failed column must not stop the rest, or the app never
                # reaches a usable state.
                logger.error("เพิ่มคอลัมน์ %s.%s ไม่สำเร็จ: %s", table.name, column.name, exc)

    return applied


def report_drift(engine: Engine) -> dict[str, list[str]]:
    """Differences this module will not fix, so an operator can see them.

    Columns that exist in the database but not in the models are left alone —
    they may belong to an older release that is still running, and dropping
    them would break it.
    """
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    drift: dict[str, list[str]] = {}

    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue
        present = {col["name"] for col in inspector.get_columns(table.name)}
        declared = {col.name for col in table.columns}
        extra = sorted(present - declared)
        if extra:
            drift[table.name] = extra
    return drift
