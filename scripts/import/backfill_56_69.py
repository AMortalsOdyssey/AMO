#!/usr/bin/env python3
"""
补齐 56-69 章的 Stage 5-7 聚合数据。

背景: run_abac4283 在处理 56-100 章时中断于第 72 章（Stage 2/3 并发阶段），
      56-69 章的逐章数据（实体/事件/关系/时间线）已写入 DB，
      但 Stage 6 聚合数据（chapter_year_mapping, master_timeline, character_snapshots, realm_timeline）缺失。
      随后 run_57e154cb 只跑了 70-100 章，所以 56-69 章的聚合数据被遗漏。

策略: 从 run_abac4283 的 stage1-4 JSON 输出读取，重建 EntityNormalizer + CrossChapterAggregator，
      然后只写 Stage 6-7 的聚合数据到 PG。
"""

import sys
import json
from pathlib import Path

# 复用 run_import.py 中的类和配置
sys.path.insert(0, str(Path(__file__).parent))
from run_import import (
    PG_CONFIG, NEO4J_CONFIG,
    ExtractedEntity, ExtractedEvent, ExtractedRelation, TimelineEntry,
    ChapterExtraction, CharacterSnapshot,
    EntityNormalizer, CrossChapterAggregator, PGWriter,
    read_chapter, CHAPTERS_DIR,
)

RUN_DIR = Path(__file__).parent / "output" / "run_abac4283"
BACKFILL_RUN_ID = "backfill_56_69"
START_CH = 56
END_CH = 69


def load_json(stage_dir: str, ch_num: int):
    path = RUN_DIR / stage_dir / f"chapter_{ch_num:04d}.json"
    if not path.exists():
        print(f"  WARNING: {path} not found")
        return None
    with open(path) as f:
        return json.load(f)


def dict_to_entity(d: dict) -> ExtractedEntity:
    return ExtractedEntity(
        entity_type=d["entity_type"],
        name=d["name"],
        aliases=d.get("aliases", []),
        attributes=d.get("attributes", {}),
        first_chapter=d.get("first_chapter", 0),
        source_quotes=d.get("source_quotes", []),
        confidence=d.get("confidence", "high"),
    )


def dict_to_event(d: dict) -> ExtractedEvent:
    return ExtractedEvent(
        event_name=d["event_name"],
        event_type=d["event_type"],
        chapter=d["chapter"],
        chapter_end=d.get("chapter_end"),
        event_detail=d.get("event_detail", ""),
        result=d.get("result", ""),
        primary_character=d.get("primary_character", ""),
        participants=d.get("participants", []),
        location=d.get("location", ""),
        time_hint=d.get("time_hint", ""),
        realm_changes=d.get("realm_changes", {}),
        source_quotes=d.get("source_quotes", []),
        confidence=d.get("confidence", "high"),
    )


def dict_to_timeline(d: dict) -> TimelineEntry:
    return TimelineEntry(
        chapter=d["chapter"],
        time_hint=d.get("time_hint", ""),
        estimated_year=d.get("estimated_year"),
        year_end=d.get("year_end"),
        confidence=d.get("confidence", "estimated"),
        realm_changes=d.get("realm_changes", {}),
        reasoning=d.get("reasoning", ""),
    )


def main():
    print(f"=== Backfill aggregation data for chapters {START_CH}-{END_CH} ===")
    print(f"Reading from: {RUN_DIR}")

    normalizer = EntityNormalizer()
    aggregator = CrossChapterAggregator()

    # 逐章重建
    for ch_num in range(START_CH, END_CH + 1):
        print(f"\n--- Chapter {ch_num} ---")

        # 读取章节标题
        try:
            title, _, _ = read_chapter(ch_num)
        except FileNotFoundError:
            title = f"第{ch_num}章"

        # Stage 1: entities
        entities_raw = load_json("stage1_entities", ch_num)
        entities = [dict_to_entity(e) for e in (entities_raw or [])]
        print(f"  Entities: {len(entities)}")

        # 更新归一化器
        for ent in entities:
            normalizer.add_entity(ent)

        # Stage 2: events
        events_raw = load_json("stage2_events", ch_num)
        events = [dict_to_event(e) for e in (events_raw or [])]
        print(f"  Events: {len(events)}")

        # Stage 4: timeline
        timeline_raw = load_json("stage4_timeline", ch_num)
        timeline = dict_to_timeline(timeline_raw) if timeline_raw else TimelineEntry(chapter=ch_num)
        print(f"  Year: {timeline.estimated_year}, Realm changes: {timeline.realm_changes}")

        # 组装 ChapterExtraction
        extraction = ChapterExtraction(
            chapter_num=ch_num,
            chapter_title=title,
            entities=entities,
            events=events,
            timeline=timeline,
        )
        aggregator.add_extraction(extraction)

    # Stage 6: 聚合
    print("\n=== Stage 6: Cross-chapter aggregation ===")
    snapshots = aggregator.generate_snapshots(normalizer)
    print(f"  Snapshots: {len(snapshots)}")
    print(f"  Chapter-year map: {len(aggregator.chapter_year_map)} entries")
    print(f"  Master timeline: {len(aggregator.master_events)} events")
    print(f"  Realm timeline: {len(aggregator.realm_timeline)} characters")

    for ch, yd in sorted(aggregator.chapter_year_map.items()):
        print(f"    Ch {ch}: year={yd['world_year']}")
    for mt in aggregator.master_events:
        print(f"    [{mt['event_type']}] Ch {mt['chapter_start']}: {mt['event_name']}")
    for snap in snapshots:
        print(f"    Snapshot: {snap.character_name} @ Ch {snap.chapter_start} ({snap.realm_stage})")

    # Stage 7: 写入 PG
    print("\n=== Stage 7: Writing aggregated data to PG ===")
    pg = PGWriter(PG_CONFIG, BACKFILL_RUN_ID)

    # 预热 entity_cache（从 DB 读取已有实体）
    with pg.conn.cursor() as cur:
        for table, etype in [
            ("characters", "Character"), ("factions", "Faction"),
            ("locations", "Location"), ("items_artifacts", "Artifact"),
            ("techniques", "Technique"), ("spirit_beasts", "SpiritBeast"),
        ]:
            cur.execute(f"SELECT id, name FROM {table}")
            for row in cur.fetchall():
                pg.entity_cache[f"{etype}:{row[1]}"] = (table, row[0])
    print(f"  Entity cache loaded: {len(pg.entity_cache)} entries")

    # 写 chapter_year_mapping
    cym_count = 0
    for ch, year_data in aggregator.chapter_year_map.items():
        result = pg.write_chapter_year_mapping(ch, year_data)
        if result is not None:
            cym_count += 1
    print(f"  chapter_year_mapping: {cym_count} written")

    # 写 master_timeline
    mt_count = 0
    for mt_event in aggregator.master_events:
        result = pg.write_master_timeline(mt_event)
        if result is not None:
            mt_count += 1
    print(f"  master_timeline: {mt_count} written")

    # 写 character_snapshots
    snap_count = 0
    for snap in snapshots:
        snap_id = pg.write_character_snapshot(snap)
        if snap_id and snap_id > 0:
            snap_count += 1
    print(f"  character_snapshots: {snap_count} written")

    # 写 realm_timeline
    realm_count = 0
    for char_name, realms in aggregator.realm_timeline.items():
        for i, realm in enumerate(realms):
            end_ch = realms[i+1]["start_chapter"] - 1 if i+1 < len(realms) else None
            result = pg.write_realm_timeline(
                char_name, realm["realm_stage"],
                realm["start_chapter"], end_ch,
                realm.get("start_year"),
                realm.get("confidence", "estimated"),
            )
            if result is not None:
                realm_count += 1
    print(f"  character_realm_timeline: {realm_count} written")

    # Commit
    try:
        pg.commit()
        print("\n  All aggregation data committed successfully!")
    except Exception as e:
        print(f"\n  ERROR: Commit failed: {e}")
        pg.conn.rollback()
    finally:
        pg.close()

    print(f"\n=== Backfill complete ===")


if __name__ == "__main__":
    main()
