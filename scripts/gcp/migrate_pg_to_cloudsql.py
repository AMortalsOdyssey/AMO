#!/usr/bin/env python3
from __future__ import annotations

import io
import os
import sys
from pathlib import Path

import psycopg2
from sqlalchemy import create_engine


ROOT = Path(__file__).resolve().parents[2]
SERVER_DIR = ROOT / "server"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from app.models.tables import Base  # noqa: E402


DEFAULT_SCHEMA = os.environ.get("AMO_PG_SCHEMA", "amo")


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"missing required environment variable: {name}")
    return value


def _sync_dsn(dsn: str) -> str:
    return dsn.replace("+asyncpg", "")


def _quoted_columns(table) -> str:
    return ", ".join(f'"{column.name}"' for column in table.columns)


def ensure_schema_and_tables(dest_dsn: str, schema: str) -> None:
    engine = create_engine(dest_dsn)
    with engine.begin() as conn:
        conn.exec_driver_sql(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
        conn.exec_driver_sql(f'SET search_path TO "{schema}"')
        Base.metadata.create_all(bind=conn)


def truncate_destination(dst_cur, schema: str) -> None:
    tables = list(reversed(Base.metadata.sorted_tables))
    table_list = ", ".join(f'"{schema}"."{table.name}"' for table in tables)
    if table_list:
        dst_cur.execute(f"TRUNCATE TABLE {table_list} RESTART IDENTITY CASCADE")


def copy_table(src_cur, dst_cur, schema: str, table) -> int:
    buffer = io.StringIO()
    columns = _quoted_columns(table)
    src_cur.copy_expert(
        f'COPY (SELECT {columns} FROM "{schema}"."{table.name}") TO STDOUT WITH CSV',
        buffer,
    )
    row_count = max(buffer.getvalue().count("\n"), 0)
    buffer.seek(0)
    if buffer.getvalue():
        dst_cur.copy_expert(
            f'COPY "{schema}"."{table.name}" ({columns}) FROM STDIN WITH CSV',
            buffer,
        )
    return row_count


def sync_sequences(dst_cur, schema: str) -> None:
    for table in Base.metadata.sorted_tables:
        id_col = next((col for col in table.columns if col.name == "id"), None)
        if id_col is None:
            continue
        dst_cur.execute("SELECT pg_get_serial_sequence(%s, %s)", (f"{schema}.{table.name}", id_col.name))
        seq_name = dst_cur.fetchone()[0]
        if not seq_name:
            continue
        dst_cur.execute(f'SELECT COALESCE(MAX("{id_col.name}"), 1) FROM "{schema}"."{table.name}"')
        max_id = dst_cur.fetchone()[0]
        dst_cur.execute("SELECT setval(%s, %s, true)", (seq_name, max_id))


def main() -> None:
    source_dsn = _sync_dsn(_require_env("SOURCE_PG_DSN"))
    dest_dsn = _sync_dsn(_require_env("DEST_PG_DSN"))
    schema = os.environ.get("PG_SCHEMA", DEFAULT_SCHEMA)
    truncate_first = os.environ.get("TRUNCATE_FIRST", "1") != "0"

    print(f"preparing destination schema '{schema}'")
    ensure_schema_and_tables(dest_dsn, schema)

    src_conn = psycopg2.connect(source_dsn, options=f"-c search_path={schema}")
    dst_conn = psycopg2.connect(dest_dsn, options=f"-c search_path={schema}")
    src_conn.autocommit = False
    dst_conn.autocommit = False

    try:
        with src_conn.cursor() as src_cur, dst_conn.cursor() as dst_cur:
            if truncate_first:
                print("truncating destination tables")
                truncate_destination(dst_cur, schema)
                dst_conn.commit()

            for table in Base.metadata.sorted_tables:
                print(f"copying {table.name} ...", flush=True)
                rows = copy_table(src_cur, dst_cur, schema, table)
                dst_conn.commit()
                print(f"copied {rows} row(s) into {table.name}", flush=True)

            print("syncing sequences", flush=True)
            sync_sequences(dst_cur, schema)
            dst_conn.commit()
            print("migration complete", flush=True)
    finally:
        src_conn.close()
        dst_conn.close()


if __name__ == "__main__":
    main()
