#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

import psycopg2
from neo4j import GraphDatabase

CURRENT_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = CURRENT_DIR.parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from graph_cleanup.lib import AliasLink, CharacterRecord, CleanupRules, build_cleanup_plan, dump_json


ROOT = Path(__file__).resolve().parents[2]
RULES_PATH = Path(__file__).with_name("rules.json")
OUTPUT_DIR = Path(__file__).with_name("output")
DEFAULT_REPORT_PATH = OUTPUT_DIR / f"graph_cleanup_report_{time.strftime('%Y%m%d_%H%M%S')}.json"

PG_CONFIG = {
    "host": os.environ.get("AMO_PG_HOST", "localhost"),
    "port": int(os.environ.get("AMO_PG_PORT", "5432")),
    "user": os.environ.get("AMO_PG_USER", "postgres"),
    "password": os.environ.get("AMO_PG_PASSWORD", "postgres"),
    "dbname": os.environ.get("AMO_PG_DB", "amo_canon"),
    "options": os.environ.get("AMO_PG_OPTIONS", "-csearch_path=amo"),
}

NEO4J_URI = os.environ.get("AMO_NEO4J_URI", os.environ.get("NEO4J_URI", "bolt://localhost:17687"))
NEO4J_USER = os.environ.get("AMO_NEO4J_USER", os.environ.get("NEO4J_USER", "neo4j"))
NEO4J_PASSWORD = os.environ.get("AMO_NEO4J_PASSWORD", os.environ.get("NEO4J_PASSWORD", "neo4j"))

WORLDLINE = "canon"
LOGGER = logging.getLogger("graph_cleanup")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Clean AMO character graph data and rebuild Neo4j projection.")
    parser.add_argument("--apply", action="store_true", help="Apply cleanup changes to PostgreSQL.")
    parser.add_argument("--skip-neo4j", action="store_true", help="Skip Neo4j rebuild.")
    parser.add_argument("--neo4j-uri", default=NEO4J_URI, help="Neo4j bolt URI for rebuild.")
    parser.add_argument("--report-file", default=str(DEFAULT_REPORT_PATH), help="Where to save the JSON report.")
    parser.add_argument("--sample-limit", type=int, default=20, help="How many sample rows to keep per section in the report.")
    return parser.parse_args()


def get_connection():
    conn = psycopg2.connect(**PG_CONFIG)
    conn.autocommit = False
    return conn


def fetch_metrics(cur) -> dict[str, int]:
    metrics: dict[str, int] = {}
    cur.execute(
        """
        SELECT count(*) FROM characters
        WHERE worldline_id = %s AND is_deleted = false
        """,
        (WORLDLINE,),
    )
    metrics["active_characters"] = cur.fetchone()[0]

    cur.execute(
        """
        SELECT count(*) FROM character_relations
        WHERE worldline_id = %s AND is_deleted = false
        """,
        (WORLDLINE,),
    )
    metrics["active_character_relations"] = cur.fetchone()[0]

    cur.execute(
        """
        WITH rel_counts AS (
          SELECT from_character_id AS char_id, count(*) AS cnt
          FROM character_relations
          WHERE worldline_id = %s AND is_deleted = false
          GROUP BY 1
          UNION ALL
          SELECT to_character_id AS char_id, count(*) AS cnt
          FROM character_relations
          WHERE worldline_id = %s AND is_deleted = false
          GROUP BY 1
        ),
        rel_sum AS (
          SELECT char_id, sum(cnt) AS rel_cnt
          FROM rel_counts
          GROUP BY 1
        )
        SELECT c.id, c.name, c.is_major, c.first_chapter, COALESCE(rs.rel_cnt, 0) AS relation_count
        FROM characters c
        LEFT JOIN rel_sum rs ON rs.char_id = c.id
        WHERE c.worldline_id = %s AND c.is_deleted = false
        """,
        (WORLDLINE, WORLDLINE, WORLDLINE),
    )
    characters = [
        CharacterRecord(
            id=row[0],
            name=row[1],
            is_major=row[2],
            first_chapter=row[3],
            relation_count=row[4],
        )
        for row in cur.fetchall()
    ]

    cur.execute(
        """
        SELECT alias_char.id, alias_char.name, canon_char.id, canon_char.name,
               count(DISTINCT cr.id) AS relation_count
        FROM characters alias_char
        JOIN character_aliases ca
          ON ca.alias = alias_char.name AND ca.worldline_id = %s
        JOIN characters canon_char
          ON canon_char.id = ca.character_id AND canon_char.worldline_id = %s
        LEFT JOIN character_relations cr
          ON (cr.from_character_id = alias_char.id OR cr.to_character_id = alias_char.id)
         AND cr.worldline_id = %s
         AND cr.is_deleted = false
        WHERE alias_char.worldline_id = %s
          AND alias_char.is_deleted = false
          AND canon_char.is_deleted = false
          AND alias_char.id <> canon_char.id
        GROUP BY alias_char.id, alias_char.name, canon_char.id, canon_char.name
        ORDER BY relation_count DESC, alias_char.name
        """,
        (WORLDLINE, WORLDLINE, WORLDLINE, WORLDLINE),
    )
    alias_links = [AliasLink(*row) for row in cur.fetchall()]

    metrics["alias_duplicate_characters"] = len({link.alias_id for link in alias_links})
    return metrics, characters, alias_links


def mark_character_deleted(cur, character_id: int) -> None:
    cur.execute(
        """
        UPDATE characters
        SET is_deleted = true, updated_at = now()
        WHERE id = %s
        """,
        (character_id,),
    )
    cur.execute(
        """
        UPDATE character_relations
        SET is_deleted = true, updated_at = now()
        WHERE worldline_id = %s
          AND is_deleted = false
          AND (from_character_id = %s OR to_character_id = %s)
        """,
        (WORLDLINE, character_id, character_id),
    )
    cur.execute(
        """
        UPDATE faction_memberships
        SET is_deleted = true, updated_at = now()
        WHERE worldline_id = %s
          AND is_deleted = false
          AND character_id = %s
        """,
        (WORLDLINE, character_id),
    )


def prune_relation_types(cur, rules: CleanupRules) -> dict[str, int]:
    pruned: dict[str, int] = {}
    for relation_type in sorted(rules.relation_prune_types):
        cur.execute(
            """
            UPDATE character_relations
            SET is_deleted = true, updated_at = now()
            WHERE worldline_id = %s
              AND is_deleted = false
              AND relation_type = %s
            """,
            (WORLDLINE, relation_type),
        )
        if cur.rowcount:
            pruned[relation_type] = cur.rowcount
    return pruned


def transfer_aliases(cur, alias_id: int, alias_name: str, canonical_id: int) -> None:
    cur.execute(
        """
        SELECT alias, alias_type, COALESCE(first_chapter, 0), last_chapter
        FROM character_aliases
        WHERE character_id = %s AND worldline_id = %s
        """,
        (alias_id, WORLDLINE),
    )
    rows = cur.fetchall()
    for alias, alias_type, first_chapter, last_chapter in rows:
        cur.execute(
            """
            INSERT INTO character_aliases (character_id, alias, alias_type, first_chapter, last_chapter, worldline_id)
            VALUES (%s, %s, %s, NULLIF(%s, 0), %s, %s)
            ON CONFLICT (character_id, alias, worldline_id) DO UPDATE SET
              first_chapter = LEAST(COALESCE(character_aliases.first_chapter, EXCLUDED.first_chapter), COALESCE(EXCLUDED.first_chapter, character_aliases.first_chapter)),
              last_chapter = COALESCE(EXCLUDED.last_chapter, character_aliases.last_chapter)
            """,
            (canonical_id, alias, alias_type, first_chapter, last_chapter, WORLDLINE),
        )
    cur.execute("DELETE FROM character_aliases WHERE character_id = %s AND worldline_id = %s", (alias_id, WORLDLINE))
    cur.execute(
        """
        INSERT INTO character_aliases (character_id, alias, alias_type, first_chapter, worldline_id)
        VALUES (%s, %s, 'merged_name', NULL, %s)
        ON CONFLICT (character_id, alias, worldline_id) DO NOTHING
        """,
        (canonical_id, alias_name, WORLDLINE),
    )


def merge_character_relations(cur, alias_id: int, canonical_id: int) -> int:
    cur.execute(
        """
        SELECT id, from_character_id, to_character_id, relation_type, valid_from_chapter, valid_until_chapter,
               attributes, confidence
        FROM character_relations
        WHERE worldline_id = %s
          AND is_deleted = false
          AND (from_character_id = %s OR to_character_id = %s)
        ORDER BY id
        """,
        (WORLDLINE, alias_id, alias_id),
    )
    migrated = 0
    for row in cur.fetchall():
        rel_id, from_id, to_id, relation_type, from_ch, until_ch, attributes, confidence = row
        new_from = canonical_id if from_id == alias_id else from_id
        new_to = canonical_id if to_id == alias_id else to_id
        if new_from == new_to:
            cur.execute(
                """
                UPDATE character_relations
                SET is_deleted = true, updated_at = now()
                WHERE id = %s
                """,
                (rel_id,),
            )
            migrated += 1
            continue
        cur.execute(
            """
            INSERT INTO character_relations (
              from_character_id, to_character_id, relation_type, valid_from_chapter, valid_until_chapter,
              attributes, confidence, worldline_id, extraction_version
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 1)
            ON CONFLICT (from_character_id, to_character_id, relation_type, worldline_id)
            DO UPDATE SET
              valid_from_chapter = LEAST(character_relations.valid_from_chapter, EXCLUDED.valid_from_chapter),
              valid_until_chapter = COALESCE(EXCLUDED.valid_until_chapter, character_relations.valid_until_chapter),
              attributes = character_relations.attributes || EXCLUDED.attributes,
              confidence = CASE
                  WHEN character_relations.confidence = 'high' OR EXCLUDED.confidence IS NULL THEN character_relations.confidence
                  ELSE EXCLUDED.confidence
              END,
              updated_at = now()
            RETURNING id
            """,
            (new_from, new_to, relation_type, from_ch, until_ch, json.dumps(attributes or {}, ensure_ascii=False), confidence, WORLDLINE),
        )
        new_rel_id = cur.fetchone()[0]
        cur.execute(
            """
            UPDATE character_relations
            SET is_deleted = true, superseded_by = %s, updated_at = now()
            WHERE id = %s
            """,
            (new_rel_id, rel_id),
        )
        migrated += 1
    return migrated


def merge_faction_memberships(cur, alias_id: int, canonical_id: int) -> int:
    cur.execute(
        """
        SELECT id, faction_id, role, valid_from_chapter, valid_until_chapter, confidence
        FROM faction_memberships
        WHERE worldline_id = %s AND is_deleted = false AND character_id = %s
        ORDER BY id
        """,
        (WORLDLINE, alias_id),
    )
    migrated = 0
    for row in cur.fetchall():
        membership_id, faction_id, role, from_ch, until_ch, confidence = row
        cur.execute(
            """
            INSERT INTO faction_memberships (
              character_id, faction_id, role, valid_from_chapter, valid_until_chapter,
              confidence, worldline_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (character_id, faction_id, role, worldline_id)
            DO UPDATE SET
              valid_from_chapter = LEAST(faction_memberships.valid_from_chapter, EXCLUDED.valid_from_chapter),
              valid_until_chapter = COALESCE(EXCLUDED.valid_until_chapter, faction_memberships.valid_until_chapter),
              confidence = CASE
                  WHEN faction_memberships.confidence = 'high' OR EXCLUDED.confidence IS NULL THEN faction_memberships.confidence
                  ELSE EXCLUDED.confidence
              END,
              updated_at = now()
            """,
            (canonical_id, faction_id, role, from_ch, until_ch, confidence, WORLDLINE),
        )
        cur.execute(
            """
            UPDATE faction_memberships
            SET is_deleted = true, updated_at = now()
            WHERE id = %s
            """,
            (membership_id,),
        )
        migrated += 1
    return migrated


def merge_item_ownerships(cur, alias_id: int, canonical_id: int) -> int:
    cur.execute(
        """
        SELECT id, item_id, item_type, valid_from_chapter, valid_until_chapter,
               valid_from_year, valid_until_year, ownership_type, confidence
        FROM item_ownerships
        WHERE worldline_id = %s AND character_id = %s
        ORDER BY id
        """,
        (WORLDLINE, alias_id),
    )
    migrated = 0
    for row in cur.fetchall():
        ownership_id, item_id, item_type, from_ch, until_ch, from_year, until_year, ownership_type, confidence = row
        cur.execute(
            """
            INSERT INTO item_ownerships (
              character_id, item_id, item_type, valid_from_chapter, valid_until_chapter,
              valid_from_year, valid_until_year, ownership_type, confidence, worldline_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (character_id, item_id, item_type, worldline_id)
            DO UPDATE SET
              valid_from_chapter = LEAST(item_ownerships.valid_from_chapter, EXCLUDED.valid_from_chapter),
              valid_until_chapter = COALESCE(EXCLUDED.valid_until_chapter, item_ownerships.valid_until_chapter),
              valid_from_year = COALESCE(item_ownerships.valid_from_year, EXCLUDED.valid_from_year),
              valid_until_year = COALESCE(EXCLUDED.valid_until_year, item_ownerships.valid_until_year),
              ownership_type = COALESCE(item_ownerships.ownership_type, EXCLUDED.ownership_type),
              confidence = CASE
                  WHEN item_ownerships.confidence = 'high' OR EXCLUDED.confidence IS NULL THEN item_ownerships.confidence
                  ELSE EXCLUDED.confidence
              END,
              updated_at = now()
            """,
            (canonical_id, item_id, item_type, from_ch, until_ch, from_year, until_year, ownership_type, confidence, WORLDLINE),
        )
        cur.execute("DELETE FROM item_ownerships WHERE id = %s", (ownership_id,))
        migrated += 1
    return migrated


def merge_character_techniques(cur, alias_id: int, canonical_id: int) -> int:
    cur.execute(
        """
        SELECT id, technique_id, relation_type, first_chapter, last_chapter, proficiency, extraction_version
        FROM character_techniques
        WHERE worldline_id = %s AND character_id = %s
        ORDER BY id
        """,
        (WORLDLINE, alias_id),
    )
    migrated = 0
    for row in cur.fetchall():
        record_id, technique_id, relation_type, first_chapter, last_chapter, proficiency, extraction_version = row
        cur.execute(
            """
            INSERT INTO character_techniques (
              character_id, technique_id, relation_type, first_chapter, last_chapter, proficiency,
              worldline_id, extraction_version
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (character_id, technique_id, worldline_id)
            DO UPDATE SET
              first_chapter = LEAST(character_techniques.first_chapter, EXCLUDED.first_chapter),
              last_chapter = COALESCE(EXCLUDED.last_chapter, character_techniques.last_chapter),
              proficiency = COALESCE(character_techniques.proficiency, EXCLUDED.proficiency),
              updated_at = now()
            """,
            (canonical_id, technique_id, relation_type, first_chapter, last_chapter, proficiency, WORLDLINE, extraction_version),
        )
        cur.execute("DELETE FROM character_techniques WHERE id = %s", (record_id,))
        migrated += 1
    return migrated


def _merge_list_values(existing: list[Any] | None, incoming: list[Any] | None) -> list[Any]:
    merged: list[Any] = []
    seen = set()
    for seq in (existing or [], incoming or []):
        marker = json.dumps(seq, ensure_ascii=False, sort_keys=True)
        if marker in seen:
            continue
        seen.add(marker)
        merged.append(seq)
    return merged


def merge_character_snapshots(cur, alias_id: int, canonical_id: int) -> int:
    cur.execute(
        """
        SELECT id, realm_stage, chapter_start, chapter_end, year_start, year_end, knowledge_cutoff,
               knowledge_cutoff_year, equipment, techniques, spirit_beasts, faction_id, location_id,
               persona_prompt, personality_traits, extraction_version
        FROM character_snapshots
        WHERE character_id = %s AND worldline_id = %s
        ORDER BY id
        """,
        (alias_id, WORLDLINE),
    )
    migrated = 0
    for row in cur.fetchall():
        (
            snapshot_id,
            realm_stage,
            chapter_start,
            chapter_end,
            year_start,
            year_end,
            knowledge_cutoff,
            knowledge_cutoff_year,
            equipment,
            techniques,
            spirit_beasts,
            faction_id,
            location_id,
            persona_prompt,
            personality_traits,
            extraction_version,
        ) = row
        cur.execute(
            """
            SELECT id, chapter_start, chapter_end, year_start, year_end, knowledge_cutoff,
                   knowledge_cutoff_year, equipment, techniques, spirit_beasts, faction_id,
                   location_id, persona_prompt, personality_traits
            FROM character_snapshots
            WHERE character_id = %s AND realm_stage = %s AND worldline_id = %s
            """,
            (canonical_id, realm_stage, WORLDLINE),
        )
        existing = cur.fetchone()
        if existing:
            (
                target_id,
                ex_ch_start,
                ex_ch_end,
                ex_year_start,
                ex_year_end,
                ex_cutoff,
                ex_cutoff_year,
                ex_equipment,
                ex_techniques,
                ex_spirit_beasts,
                ex_faction_id,
                ex_location_id,
                ex_persona_prompt,
                ex_traits,
            ) = existing
            merged_equipment = dict(ex_equipment or {})
            merged_equipment.update(equipment or {})
            merged_techniques = _merge_list_values(ex_techniques, techniques)
            merged_spirit_beasts = _merge_list_values(ex_spirit_beasts, spirit_beasts)
            merged_traits = _merge_list_values(ex_traits, personality_traits)
            cur.execute(
                """
                UPDATE character_snapshots
                SET chapter_start = LEAST(chapter_start, %s),
                    chapter_end = CASE
                        WHEN chapter_end IS NULL THEN %s
                        WHEN %s IS NULL THEN chapter_end
                        ELSE GREATEST(chapter_end, %s)
                    END,
                    year_start = COALESCE(year_start, %s),
                    year_end = COALESCE(%s, year_end),
                    knowledge_cutoff = LEAST(knowledge_cutoff, %s),
                    knowledge_cutoff_year = COALESCE(knowledge_cutoff_year, %s),
                    equipment = %s,
                    techniques = %s,
                    spirit_beasts = %s,
                    faction_id = COALESCE(faction_id, %s),
                    location_id = COALESCE(location_id, %s),
                    persona_prompt = COALESCE(persona_prompt, %s),
                    personality_traits = %s,
                    updated_at = now()
                WHERE id = %s
                """,
                (
                    chapter_start,
                    chapter_end,
                    chapter_end,
                    chapter_end,
                    year_start,
                    year_end,
                    knowledge_cutoff,
                    knowledge_cutoff_year,
                    json.dumps(merged_equipment, ensure_ascii=False),
                    json.dumps(merged_techniques, ensure_ascii=False),
                    json.dumps(merged_spirit_beasts, ensure_ascii=False),
                    ex_faction_id or faction_id,
                    ex_location_id or location_id,
                    ex_persona_prompt or persona_prompt,
                    json.dumps(merged_traits, ensure_ascii=False),
                    target_id,
                ),
            )
            cur.execute("DELETE FROM character_snapshots WHERE id = %s", (snapshot_id,))
        else:
            cur.execute(
                """
                UPDATE character_snapshots
                SET character_id = %s, updated_at = now()
                WHERE id = %s
                """,
                (canonical_id, snapshot_id),
            )
        migrated += 1
    return migrated


def merge_character_realm_timeline(cur, alias_id: int, canonical_id: int) -> int:
    cur.execute(
        """
        SELECT id, realm_stage, start_chapter, start_year, end_chapter, end_year, confidence
        FROM character_realm_timeline
        WHERE character_id = %s AND worldline_id = %s
        ORDER BY id
        """,
        (alias_id, WORLDLINE),
    )
    migrated = 0
    for row in cur.fetchall():
        timeline_id, realm_stage, start_chapter, start_year, end_chapter, end_year, confidence = row
        cur.execute(
            """
            SELECT id, start_chapter, start_year, end_chapter, end_year, confidence
            FROM character_realm_timeline
            WHERE character_id = %s AND realm_stage = %s AND worldline_id = %s
            """,
            (canonical_id, realm_stage, WORLDLINE),
        )
        existing = cur.fetchone()
        if existing:
            target_id, ex_start_ch, ex_start_year, ex_end_ch, ex_end_year, ex_confidence = existing
            merged_confidence = "high" if "high" in {confidence, ex_confidence} else (ex_confidence or confidence)
            cur.execute(
                """
                UPDATE character_realm_timeline
                SET start_chapter = LEAST(start_chapter, %s),
                    start_year = COALESCE(start_year, %s),
                    end_chapter = CASE
                        WHEN end_chapter IS NULL THEN %s
                        WHEN %s IS NULL THEN end_chapter
                        ELSE GREATEST(end_chapter, %s)
                    END,
                    end_year = COALESCE(%s, end_year),
                    confidence = %s
                WHERE id = %s
                """,
                (
                    start_chapter,
                    start_year,
                    end_chapter,
                    end_chapter,
                    end_chapter,
                    end_year,
                    merged_confidence,
                    target_id,
                ),
            )
            cur.execute("DELETE FROM character_realm_timeline WHERE id = %s", (timeline_id,))
        else:
            cur.execute(
                """
                UPDATE character_realm_timeline
                SET character_id = %s
                WHERE id = %s
                """,
                (canonical_id, timeline_id),
            )
        migrated += 1
    return migrated


def remap_simple_character_fk(cur, table: str, column: str, alias_id: int, canonical_id: int) -> int:
    cur.execute(f"UPDATE {table} SET {column} = %s WHERE {column} = %s", (canonical_id, alias_id))
    return cur.rowcount


def apply_merge(cur, merge) -> dict[str, int]:
    LOGGER.info(
        "start merge alias_id=%s alias_name=%s canonical_id=%s canonical_name=%s reason=%s",
        merge.alias_id,
        merge.alias_name,
        merge.canonical_id,
        merge.canonical_name,
        merge.reason,
    )
    transfer_aliases(cur, merge.alias_id, merge.alias_name, merge.canonical_id)
    operations = [
        ("character_relations", lambda: merge_character_relations(cur, merge.alias_id, merge.canonical_id)),
        ("faction_memberships", lambda: merge_faction_memberships(cur, merge.alias_id, merge.canonical_id)),
        ("item_ownerships", lambda: merge_item_ownerships(cur, merge.alias_id, merge.canonical_id)),
        ("character_techniques", lambda: merge_character_techniques(cur, merge.alias_id, merge.canonical_id)),
        ("character_snapshots", lambda: merge_character_snapshots(cur, merge.alias_id, merge.canonical_id)),
        ("character_realm_timeline", lambda: merge_character_realm_timeline(cur, merge.alias_id, merge.canonical_id)),
        ("events", lambda: remap_simple_character_fk(cur, "events", "primary_character_id", merge.alias_id, merge.canonical_id)),
        ("master_timeline", lambda: remap_simple_character_fk(cur, "master_timeline", "primary_character_id", merge.alias_id, merge.canonical_id)),
    ]
    stats: dict[str, int] = {}
    for label, handler in operations:
        started_at = time.time()
        LOGGER.info(
            "merge step start alias_id=%s alias_name=%s step=%s",
            merge.alias_id,
            merge.alias_name,
            label,
        )
        stats[label] = handler()
        LOGGER.info(
            "merge step done alias_id=%s alias_name=%s step=%s affected=%s elapsed=%.2fs",
            merge.alias_id,
            merge.alias_name,
            label,
            stats[label],
            time.time() - started_at,
        )
    mark_character_deleted(cur, merge.alias_id)
    LOGGER.info(
        "finish merge alias_id=%s alias_name=%s canonical_id=%s canonical_name=%s stats=%s",
        merge.alias_id,
        merge.alias_name,
        merge.canonical_id,
        merge.canonical_name,
        stats,
    )
    return stats


def upsert_node(session, label: str, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    session.run(
        f"""
        UNWIND $rows AS row
        MERGE (n:{label} {{id: row.id}})
        SET n += row.props
        """,
        rows=rows,
    )


def _neo4j_property_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, list):
        if all(item is None or isinstance(item, (bool, int, float, str)) for item in value):
            return value
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _neo4j_props(props: dict[str, Any]) -> dict[str, Any]:
    return {key: _neo4j_property_value(value) for key, value in props.items() if value is not None}


def rebuild_neo4j(cur, neo4j_uri: str) -> dict[str, int]:
    driver = GraphDatabase.driver(neo4j_uri, auth=(NEO4J_USER, NEO4J_PASSWORD))
    try:
        with driver.session() as session:
            session.run("MATCH (c:Character) DETACH DELETE c")

            node_specs = [
                ("Character", "SELECT id, name, gender, first_chapter, is_major FROM characters WHERE worldline_id = %s AND is_deleted = false", WORLDLINE),
                ("Faction", "SELECT id, name, faction_type, first_chapter FROM factions WHERE worldline_id = %s AND is_deleted = false", WORLDLINE),
                ("Artifact", "SELECT id, name, item_type, first_chapter FROM items_artifacts WHERE worldline_id = %s AND is_deleted = false", WORLDLINE),
                ("Technique", "SELECT id, name, technique_type, first_chapter FROM techniques WHERE worldline_id = %s AND is_deleted = false", WORLDLINE),
                ("SpiritBeast", "SELECT id, name, species, first_chapter FROM spirit_beasts WHERE worldline_id = %s AND is_deleted = false", WORLDLINE),
                ("Location", "SELECT id, name, location_type, first_chapter FROM locations WHERE worldline_id = %s AND is_deleted = false", WORLDLINE),
            ]
            node_counts: dict[str, int] = {}
            for label, sql, worldline in node_specs:
                cur.execute(sql, (worldline,))
                rows = []
                for row in cur.fetchall():
                    props = {"name": row[1], "worldline": WORLDLINE}
                    if label == "Character":
                        props.update({"gender": row[2], "first_chapter": row[3], "is_major": row[4]})
                    else:
                        props.update({"kind": row[2], "first_chapter": row[3]})
                    rows.append({"id": row[0], "props": _neo4j_props(props)})
                upsert_node(session, label, rows)
                node_counts[label] = len(rows)

            rel_counts: dict[str, int] = {}

            cur.execute(
                """
                SELECT from_character_id, to_character_id, relation_type, valid_from_chapter, valid_until_chapter, attributes
                FROM character_relations
                WHERE worldline_id = %s AND is_deleted = false
                """,
                (WORLDLINE,),
            )
            rows = [
                {
                    "from_id": row[0],
                    "to_id": row[1],
                    "props": _neo4j_props({
                        "worldline": WORLDLINE,
                        "type": row[2],
                        "valid_from_chapter": row[3],
                        "valid_until_chapter": row[4],
                        "attributes": row[5] or {},
                    }),
                }
                for row in cur.fetchall()
            ]
            session.run(
                """
                UNWIND $rows AS row
                MATCH (a:Character {id: row.from_id})
                MATCH (b:Character {id: row.to_id})
                MERGE (a)-[r:RELATION]->(b)
                SET r += row.props
                """,
                rows=rows,
            )
            rel_counts["RELATION"] = len(rows)

            cur.execute(
                """
                SELECT character_id, faction_id, role, valid_from_chapter, valid_until_chapter
                FROM faction_memberships
                WHERE worldline_id = %s AND is_deleted = false
                """,
                (WORLDLINE,),
            )
            rows = [
                {
                    "from_id": row[0],
                    "to_id": row[1],
                    "props": _neo4j_props({
                        "worldline": WORLDLINE,
                        "type": row[2],
                        "valid_from_chapter": row[3],
                        "valid_until_chapter": row[4],
                    }),
                }
                for row in cur.fetchall()
            ]
            session.run(
                """
                UNWIND $rows AS row
                MATCH (a:Character {id: row.from_id})
                MATCH (b:Faction {id: row.to_id})
                MERGE (a)-[r:BELONGS_TO]->(b)
                SET r += row.props
                """,
                rows=rows,
            )
            rel_counts["BELONGS_TO"] = len(rows)

            cur.execute(
                """
                SELECT character_id, item_id, item_type, ownership_type, valid_from_chapter, valid_until_chapter
                FROM item_ownerships
                WHERE worldline_id = %s
                """,
                (WORLDLINE,),
            )
            ownership_rows = cur.fetchall()
            artifact_rows = []
            spirit_rows = []
            for row in ownership_rows:
                payload = {
                    "from_id": row[0],
                    "to_id": row[1],
                    "props": _neo4j_props({
                        "worldline": WORLDLINE,
                        "type": row[3] or ("bonded" if row[2] == "spirit_beast" else "own"),
                        "valid_from_chapter": row[4],
                        "valid_until_chapter": row[5],
                    }),
                }
                if row[2] == "spirit_beast":
                    spirit_rows.append(payload)
                else:
                    artifact_rows.append(payload)
            if artifact_rows:
                session.run(
                    """
                    UNWIND $rows AS row
                    MATCH (a:Character {id: row.from_id})
                    MATCH (b:Artifact {id: row.to_id})
                    MERGE (a)-[r:OWNS]->(b)
                    SET r += row.props
                    """,
                    rows=artifact_rows,
                )
            if spirit_rows:
                session.run(
                    """
                    UNWIND $rows AS row
                    MATCH (a:Character {id: row.from_id})
                    MATCH (b:SpiritBeast {id: row.to_id})
                    MERGE (a)-[r:BONDED_TO]->(b)
                    SET r += row.props
                    """,
                    rows=spirit_rows,
                )
            rel_counts["OWNS"] = len(artifact_rows)
            rel_counts["BONDED_TO"] = len(spirit_rows)

            cur.execute(
                """
                SELECT character_id, technique_id, relation_type, first_chapter, last_chapter, proficiency
                FROM character_techniques
                WHERE worldline_id = %s
                """,
                (WORLDLINE,),
            )
            rows = [
                {
                    "from_id": row[0],
                    "to_id": row[1],
                    "props": _neo4j_props({
                        "worldline": WORLDLINE,
                        "type": row[2] or "mastered",
                        "valid_from_chapter": row[3],
                        "valid_until_chapter": row[4],
                        "proficiency": row[5],
                    }),
                }
                for row in cur.fetchall()
            ]
            if rows:
                session.run(
                    """
                    UNWIND $rows AS row
                    MATCH (a:Character {id: row.from_id})
                    MATCH (b:Technique {id: row.to_id})
                    MERGE (a)-[r:MASTERS]->(b)
                    SET r += row.props
                    """,
                    rows=rows,
                )
            rel_counts["MASTERS"] = len(rows)

            return {"nodes": node_counts, "relationships": rel_counts}
    finally:
        driver.close()


def run_cleanup(args: argparse.Namespace) -> dict[str, Any]:
    rules = CleanupRules.load(RULES_PATH)

    with get_connection() as conn:
        cur = conn.cursor()
        before_metrics, characters, alias_links = fetch_metrics(cur)
        plan = build_cleanup_plan(characters, alias_links, rules)

        report: dict[str, Any] = {
            "mode": "apply" if args.apply else "dry_run",
            "before": before_metrics,
            "plan": {
                "merge_count": len(plan.merges),
                "prune_count": len(plan.prunes),
                "sample_merges": [candidate.__dict__ for candidate in plan.merges[: args.sample_limit]],
                "sample_prunes": [candidate.__dict__ for candidate in plan.prunes[: args.sample_limit]],
                "sample_skipped_aliases": plan.skipped_aliases[: args.sample_limit],
            },
        }

        if not args.apply:
            conn.rollback()
            return report

        applied = {
            "merged_characters": 0,
            "pruned_characters": 0,
            "pruned_relation_types": {},
            "migrated_rows": {
                "character_relations": 0,
                "faction_memberships": 0,
                "item_ownerships": 0,
                "character_techniques": 0,
                "character_snapshots": 0,
                "character_realm_timeline": 0,
                "events": 0,
                "master_timeline": 0,
            },
        }

        total_merges = len(plan.merges)
        for index, merge in enumerate(plan.merges, start=1):
            merge_started_at = time.time()
            LOGGER.info(
                "apply merge %s/%s alias_id=%s alias_name=%s canonical_id=%s canonical_name=%s",
                index,
                total_merges,
                merge.alias_id,
                merge.alias_name,
                merge.canonical_id,
                merge.canonical_name,
            )
            try:
                stats = apply_merge(cur, merge)
            except Exception:
                LOGGER.exception(
                    "merge failed index=%s alias_id=%s alias_name=%s canonical_id=%s canonical_name=%s",
                    index,
                    merge.alias_id,
                    merge.alias_name,
                    merge.canonical_id,
                    merge.canonical_name,
                )
                raise
            applied["merged_characters"] += 1
            for key, value in stats.items():
                applied["migrated_rows"][key] += value
            LOGGER.info(
                "applied merge %s/%s alias_id=%s alias_name=%s elapsed=%.2fs cumulative=%s",
                index,
                total_merges,
                merge.alias_id,
                merge.alias_name,
                time.time() - merge_started_at,
                applied["migrated_rows"],
            )

        total_prunes = len(plan.prunes)
        for index, prune in enumerate(plan.prunes, start=1):
            mark_character_deleted(cur, prune.character_id)
            applied["pruned_characters"] += 1
            if index == 1 or index % 50 == 0 or index == total_prunes:
                LOGGER.info(
                    "applied prune %s/%s character_id=%s name=%s",
                    index,
                    total_prunes,
                    prune.character_id,
                    prune.character_name,
                )

        applied["pruned_relation_types"] = prune_relation_types(cur, rules)

        conn.commit()

        after_metrics, _, _ = fetch_metrics(cur)
        report["applied"] = applied
        report["after"] = after_metrics

        if not args.skip_neo4j:
            report["neo4j_rebuild"] = rebuild_neo4j(cur, args.neo4j_uri)

        return report


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = parse_args()
    report = run_cleanup(args)
    dump_json(args.report_file, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
