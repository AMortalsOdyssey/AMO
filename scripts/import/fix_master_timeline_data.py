#!/usr/bin/env python3
"""
修复 master_timeline 历史脏数据。

处理规则：
1. 以 chapter_year_mapping 作为 chapter_start 对应年份的真值来源。
2. 对同章同事件(event_name)的多条记录，只保留一条。
3. 若同章同事件已存在正确 world_year 的记录，删除其余旧版本。
4. 若只有错误年份版本，则保留最新一条并将年份修正到映射值。
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass

import os

import psycopg2
import psycopg2.extras

PG_CONFIG = {
    "host": os.environ.get("AMO_PG_HOST", "localhost"),
    "port": int(os.environ.get("AMO_PG_PORT", "5432")),
    "user": os.environ.get("AMO_PG_USER", "postgres"),
    "password": os.environ.get("AMO_PG_PASSWORD", "postgres"),
    "dbname": os.environ.get("AMO_PG_DB", "amo_canon"),
    "options": os.environ.get("AMO_PG_OPTIONS", "-csearch_path=amo"),
}


@dataclass
class TimelineRow:
    id: int
    chapter_start: int
    event_name: str
    world_year: int
    mapped_world_year: int


def load_rows(cur) -> list[TimelineRow]:
    cur.execute("""
        SELECT
            mt.id,
            mt.chapter_start,
            mt.event_name,
            mt.world_year,
            cym.world_year AS mapped_world_year
        FROM amo.master_timeline mt
        JOIN amo.chapter_year_mapping cym
          ON cym.chapter_num = mt.chapter_start
        ORDER BY mt.chapter_start, mt.event_name, mt.id
    """)
    return [TimelineRow(**row) for row in cur.fetchall()]


def summarize_actions(rows: list[TimelineRow]):
    groups = defaultdict(list)
    for row in rows:
        groups[(row.chapter_start, row.event_name)].append(row)

    delete_ids: list[int] = []
    updates: list[tuple[int, int]] = []
    samples: list[str] = []

    for (chapter_start, event_name), group in sorted(groups.items()):
        desired_year = group[0].mapped_world_year
        matching = [row for row in group if row.world_year == desired_year]

        if matching:
            keep = max(matching, key=lambda row: row.id)
        else:
            keep = max(group, key=lambda row: row.id)

        for row in group:
            if row.id == keep.id:
                continue
            delete_ids.append(row.id)
            if len(samples) < 12:
                samples.append(
                    f"DELETE id={row.id} ch={row.chapter_start} year={row.world_year} name={row.event_name}"
                )

        if keep.world_year != desired_year:
            updates.append((keep.id, desired_year))
            if len(samples) < 12:
                samples.append(
                    f"UPDATE id={keep.id} ch={keep.chapter_start} {keep.world_year}->{desired_year} name={keep.event_name}"
                )

    return delete_ids, updates, samples


def verify(cur):
    cur.execute("""
        SELECT count(*)
        FROM amo.master_timeline mt
        JOIN amo.chapter_year_mapping cym
          ON cym.chapter_num = mt.chapter_start
        WHERE mt.world_year IS DISTINCT FROM cym.world_year
    """)
    mismatched_rows = cur.fetchone()["count"]

    cur.execute("""
        SELECT count(*)
        FROM (
            SELECT 1
            FROM amo.master_timeline
            GROUP BY chapter_start, event_name
            HAVING count(*) > 1
        ) t
    """)
    duplicate_groups = cur.fetchone()["count"]
    return mismatched_rows, duplicate_groups


def apply_changes(cur, delete_ids: list[int], updates: list[tuple[int, int]]):
    if delete_ids:
        cur.execute("DELETE FROM amo.master_timeline WHERE id = ANY(%s)", (delete_ids,))

    for row_id, world_year in updates:
        cur.execute("""
            UPDATE amo.master_timeline
            SET world_year = %s
            WHERE id = %s
        """, (world_year, row_id))


def main():
    parser = argparse.ArgumentParser(description="修复 master_timeline 脏数据")
    parser.add_argument("--apply", action="store_true", help="真正写入数据库")
    args = parser.parse_args()

    conn = psycopg2.connect(**PG_CONFIG)
    conn.autocommit = False

    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            rows = load_rows(cur)
            delete_ids, updates, samples = summarize_actions(rows)

            print(f"rows_scanned={len(rows)}")
            print(f"delete_rows={len(delete_ids)}")
            print(f"update_rows={len(updates)}")
            print("samples:")
            for sample in samples:
                print(sample)

            apply_changes(cur, delete_ids, updates)
            mismatched_rows, duplicate_groups = verify(cur)
            print(f"post_check.mismatched_rows={mismatched_rows}")
            print(f"post_check.duplicate_groups={duplicate_groups}")

            if args.apply:
                conn.commit()
                print("database_changes=committed")
            else:
                conn.rollback()
                print("database_changes=rolled_back")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
