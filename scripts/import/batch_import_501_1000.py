#!/usr/bin/env python3
"""
AMO 批量导入脚本: 501-1000 章
修复世界时间线问题：使用累积年份计算

基于 run_import.py，但修改时间线抽取逻辑：
- 不再让 LLM 估算绝对年份
- 改为估算每章"经过了多少时间"，然后累积计算

锚点: ch500 = 204 岁

用法:
  python3 scripts/import/batch_import_501_1000.py --start 501 --end 550 --dry-run
  python3 scripts/import/batch_import_501_1000.py --start 501 --end 1000
"""

import os
import sys
import json
import re
import uuid
import hashlib
import time
import argparse
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import requests
import psycopg2
import psycopg2.extras
from neo4j import GraphDatabase
from pymilvus import connections, Collection

# ============================================================
# 配置
# ============================================================

PG_CONFIG = {
    "host": os.environ.get("AMO_PG_HOST", "localhost"),
    "port": int(os.environ.get("AMO_PG_PORT", "5432")),
    "user": os.environ.get("AMO_PG_USER", "postgres"),
    "password": os.environ.get("AMO_PG_PASSWORD", "postgres"),
    "dbname": os.environ.get("AMO_PG_DB", "amo_canon"),
    "options": os.environ.get("AMO_PG_OPTIONS", "-csearch_path=amo"),
}

NEO4J_CONFIG = {
    "uri": os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
    "user": os.environ.get("NEO4J_USER", "neo4j"),
    "password": os.environ.get("NEO4J_PASSWORD", "neo4j"),
}

ZILLIZ_CONFIG = {
    "uri": os.environ.get("ZILLIZ_URI", "http://localhost:19530"),
    "token": os.environ.get("ZILLIZ_TOKEN", ""),
    "db_name": os.environ.get("ZILLIZ_DB", "ai_social_memory"),
}

EMBEDDING_CONFIG = {
    "base_url": os.environ.get("EMBEDDING_BASE_URL", "http://localhost:8002/v1"),
    "api_key": os.environ.get("EMBEDDING_API_KEY", ""),
    "model": os.environ.get("EMBEDDING_MODEL", "qwen3_embedding_8b_20250716_V1"),
}

LLM_CONFIG = {
    "api_key": os.environ.get("LLM_API_KEY", ""),
    "base_url": os.environ.get("LLM_BASE_URL", "http://localhost:8001/v1"),
    "model": os.environ.get("LLM_MODEL", "gemini-3.1-pro-preview"),
}

CHAPTERS_DIR = Path(__file__).parent.parent.parent / "book" / "chapters"
OUTPUT_DIR = Path(__file__).parent / "output"
EMBEDDING_DIM = 4096
CROSS_CHAPTER_BUFFER = 500

# 累积年份计算锚点
BASE_CHAPTER = 500
BASE_YEAR = 204  # ch500 = 204 岁

# LLM 价格 (per 1M tokens)
INPUT_PRICE = 1.25
OUTPUT_PRICE = 5.0

LOG_FILE = Path(__file__).parent / "batch_import_501_1000.log"

# ============================================================
# Logging Setup
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, mode="a"),
        logging.StreamHandler(),
    ]
)
log = logging.getLogger(__name__)
log_stage4 = logging.getLogger("stage4")

# ============================================================
# 累积年份计算 (核心修复)
# ============================================================

TIME_PASSED_PROMPT = """你是一个小说时间分析专家。根据下面这章小说内容，判断这一章中【实际经过】了多少时间。

重要规则：
1. 只统计【章节叙事中实际流逝】的时间（如"三月后"、"闭关一年"、"过了数日"）
2. 角色回忆、对话中提到的时间【不算】（如"当年如何如何"、"修炼了xx年才到这境界"）
3. 大多数章节是连续叙事，没有时间跳跃，应该返回 0
4. 只返回一个数字（年为单位），不要解释

转换参考：
- 连续叙事/数日/数天 = 0
- 数月 = 0.3
- 半年 = 0.5
- 一年/两年/三年 = 1/2/3
- 数年 = 2
- 数十年 = 10
- 百年 = 100

章节内容：
{content}

这章【实际经过】了多少年？只返回数字："""


def get_latest_year_from_db(before_chapter: int) -> tuple[int, int] | None:
    """
    从数据库获取指定章节之前的最近年份记录
    返回 (chapter_num, world_year) 或 None
    """
    try:
        conn = psycopg2.connect(**PG_CONFIG)
        cur = conn.cursor()
        cur.execute("""
            SELECT chapter_num, world_year
            FROM amo.chapter_year_mapping
            WHERE chapter_num < %s
            ORDER BY chapter_num DESC
            LIMIT 1
        """, (before_chapter,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row:
            return (row[0], row[1])
        return None
    except Exception as e:
        log.warning(f"Failed to get latest year from DB: {e}")
        return None


class CumulativeYearTracker:
    """累积年份追踪器"""

    def __init__(self, base_chapter: int, base_year: int):
        self.base_chapter = base_chapter
        self.base_year = base_year
        self.current_year = float(base_year)
        self.current_chapter = base_chapter
        self.chapter_years: dict[int, int] = {base_chapter: base_year}
        self._lock = threading.Lock()

    def estimate_time_passed(self, content: str) -> tuple[float, int, int]:
        """调用 LLM 估算章节时间流逝，返回 (years, input_tokens, output_tokens)"""
        # 截取章节关键部分
        if len(content) > 6000:
            content = content[:3000] + "\n...\n" + content[-3000:]

        prompt = TIME_PASSED_PROMPT.format(content=content)

        for attempt in range(3):
            try:
                resp = requests.post(
                    f"{LLM_CONFIG['base_url']}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {LLM_CONFIG['api_key']}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": LLM_CONFIG["model"],
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.1,
                        "max_tokens": 50,
                    },
                    timeout=30,
                )
                resp.raise_for_status()
                data = resp.json()

                answer = data["choices"][0]["message"]["content"].strip()
                input_tokens = data.get("usage", {}).get("prompt_tokens", 0)
                output_tokens = data.get("usage", {}).get("completion_tokens", 0)

                # 解析数字
                match = re.search(r"[\d.]+", answer)
                if match:
                    years = float(match.group())
                    # 合理性检查：单章不可能超过 200 年
                    if years > 200:
                        log.warning(f"Time passed {years} seems too large, capping to 100")
                        years = 100
                    return years, input_tokens, output_tokens
                return 0, input_tokens, output_tokens

            except Exception as e:
                log.warning(f"LLM call failed (attempt {attempt+1}): {e}")
                if attempt < 2:
                    time.sleep(2 ** attempt)

        return 0, 0, 0

    def process_chapter(self, chapter_num: int, content: str) -> tuple[int, float]:
        """
        处理一章，返回 (world_year, time_passed)
        注意：必须按章节顺序调用！
        """
        with self._lock:
            if chapter_num <= self.current_chapter:
                # 已处理过或非顺序
                return self.chapter_years.get(chapter_num, int(self.current_year)), 0

            # 估算时间流逝
            time_passed, _, _ = self.estimate_time_passed(content)
            self.current_year += time_passed
            self.current_chapter = chapter_num
            world_year = int(round(self.current_year))
            self.chapter_years[chapter_num] = world_year

            log.info(f"ch{chapter_num}: +{time_passed:.1f}年 → {world_year}岁")

            return world_year, time_passed

    def get_year(self, chapter_num: int) -> int:
        """获取章节年份（如果已处理）"""
        return self.chapter_years.get(chapter_num, int(self.current_year))


# 全局实例
_year_tracker: Optional[CumulativeYearTracker] = None


def init_year_tracker():
    """初始化年份追踪器"""
    global _year_tracker
    _year_tracker = CumulativeYearTracker(BASE_CHAPTER, BASE_YEAR)
    return _year_tracker


# ============================================================
# 导入 run_import.py 的其他组件
# ============================================================

# 从 run_import.py 导入所有需要的组件
sys.path.insert(0, str(Path(__file__).parent))
from run_import import (
    # Data classes
    ExtractedEntity, ExtractedEvent, ExtractedRelation, TimelineEntry,
    CharacterSnapshot, ChapterExtraction, ExtractedLoreRule,
    # LLM functions
    call_llm, parse_llm_json, get_embedding,
    # Stage functions
    extract_entities, extract_events, extract_relations, extract_lore_rules,
    # Normalizer & Aggregator
    EntityNormalizer, CrossChapterAggregator,
    # DB Writers
    PGWriter, Neo4jWriter, ZillizWriter,
    # Utils
    read_chapter as _read_chapter_tuple, get_chapter_tail, save_aggregated_output,
    cross_db_consistency_check,
    # Tracker
    LLMUsageTracker,
    # Prompts (for timeline)
    TIMELINE_PROMPT,
    # Constants
    CROSS_CHAPTER_BUFFER as _CROSS_CHAPTER_BUFFER,
    # Global tracker reference for call_llm
    _usage_tracker,
)

# 导入 run_import 模块用于设置全局变量
import run_import as _run_import


def init_usage_tracker(model: str):
    """初始化 LLM usage tracker（设置到 run_import 模块）"""
    _run_import._usage_tracker = LLMUsageTracker(model)
    _run_import._current_chapter = 0
    return _run_import._usage_tracker


def read_chapter(chapter_num: int) -> Optional[str]:
    """读取章节内容（仅返回 body）"""
    try:
        title, body, checksum = _read_chapter_tuple(chapter_num)
        return body
    except FileNotFoundError:
        return None


def get_chapter_title(chapter_num: int) -> Optional[str]:
    """读取章节标题"""
    try:
        title, body, checksum = _read_chapter_tuple(chapter_num)
        return title
    except FileNotFoundError:
        return None


# ============================================================
# 修改后的 Timeline 抽取
# ============================================================

def extract_timeline_cumulative(chapter_num: int, title: str, content: str,
                                 time_anchors: str, year_tracker: CumulativeYearTracker) -> TimelineEntry:
    """
    Stage 4: 时间线抽取（使用累积年份计算）

    关键修改：不再让 LLM 估算绝对年份，而是：
    1. 用简单 prompt 估算"这章经过了多少时间"
    2. 累积到 year_tracker 中
    3. 同时保留境界变化抽取
    """
    # 先处理年份累积
    world_year, time_passed = year_tracker.process_chapter(chapter_num, content)

    # 然后用原有逻辑抽取境界变化（但不用它的 year_estimation）
    prompt = TIMELINE_PROMPT.format(
        chapter_num=chapter_num,
        chapter_title=title,
        content=content[:12000],
        time_anchors=time_anchors or "暂无已知锚点",
    )

    realm_changes = {}
    time_hints = []

    try:
        text = call_llm(prompt, max_tokens=2048, stage="stage4_timeline")
        log_stage4.info(f"Timeline extraction completed for ch{chapter_num}")
        data = parse_llm_json(text)

        # 只取境界变化和时间提示，不用它的年份估算
        for rc in data.get("realm_changes", []):
            char_name = rc.get("character", "")
            to_realm = rc.get("to_realm", "")
            if char_name and to_realm:
                realm_changes[char_name] = to_realm

        for tm in data.get("time_mentions", []):
            time_hints.append(tm.get("text", ""))

    except Exception as e:
        log.warning(f"Timeline extraction failed for ch{chapter_num}: {e}")

    return TimelineEntry(
        chapter=chapter_num,
        time_hint="; ".join(time_hints) if time_hints else f"+{time_passed:.1f}年",
        estimated_year=world_year,  # 使用累积计算的年份
        year_end=None,
        confidence="cumulative",  # 标记为累积计算
        realm_changes=realm_changes,
        reasoning=f"累积计算: ch{chapter_num-1}→ch{chapter_num} +{time_passed:.1f}年",
    )


# ============================================================
# 主导入函数
# ============================================================

def run_batch_import(start_chapter: int, end_chapter: int, dry_run: bool = False,
                     skip_neo4j: bool = False, skip_zilliz: bool = False):
    """执行批量导入"""
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = OUTPUT_DIR / f"batch_501_1000_{run_id}"
    run_dir.mkdir(parents=True, exist_ok=True)

    log.info(f"=== Batch Import Started ===")
    log.info(f"Run ID: {run_id}")
    log.info(f"Chapters: {start_chapter} - {end_chapter}")
    log.info(f"Dry run: {dry_run}")
    log.info(f"Output dir: {run_dir}")
    log.info(f"Base year anchor: ch{BASE_CHAPTER} = {BASE_YEAR}岁")

    # 初始化追踪器
    init_usage_tracker(LLM_CONFIG["model"])
    year_tracker = init_year_tracker()

    # 初始化组件
    normalizer = EntityNormalizer()
    aggregator = CrossChapterAggregator()

    # 初始化 DB writers
    pg_writer = PGWriter(PG_CONFIG, run_id)

    neo4j_writer = None
    if not skip_neo4j:
        try:
            neo4j_writer = Neo4jWriter(NEO4J_CONFIG)
            log.info("Neo4j connected")
        except Exception as e:
            log.warning(f"Neo4j connection failed: {e}")

    zilliz_writer = None
    if not skip_zilliz:
        try:
            zilliz_writer = ZillizWriter(ZILLIZ_CONFIG)
            log.info("Zilliz connected")
        except Exception as e:
            log.warning(f"Zilliz connection failed: {e}")

    stats = {
        "run_id": run_id,
        "started_at": datetime.now().isoformat(),
        "chapters_processed": 0,
        "entities_total": 0,
        "events_total": 0,
        "relations_total": 0,
        "lore_rules_total": 0,
        "snapshots_total": 0,
        "errors": 0,
    }

    # 上下文缓冲
    prev_content_buffer = ""
    time_anchors = f"ch{BASE_CHAPTER} = {BASE_YEAR}岁（韩立年龄）"
    known_entities: list[str] = []  # 已知实体列表

    # 处理每章
    for ch_num in range(start_chapter, end_chapter + 1):
        log.info(f"=== Processing Chapter {ch_num} ===")

        # 设置当前章节号（用于 call_llm 记录）
        _run_import._current_chapter = ch_num

        content = read_chapter(ch_num)
        if not content:
            log.warning(f"  Chapter {ch_num} not found, skipping")
            continue

        title = get_chapter_title(ch_num) or f"第{ch_num}章"

        # 拼接上下文
        full_content = prev_content_buffer + "\n\n" + content if prev_content_buffer else content

        # ========== Stage 1: 实体抽取 ==========
        entities = extract_entities(ch_num, title, full_content[:15000], known_entities, prev_content_buffer)
        log.info(f"  Stage 1: {len(entities)} entities")

        # ========== Stage 2-4: 并发抽取 ==========
        events = []
        relations = []
        timeline = None
        lore_rules = []

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {
                executor.submit(extract_events, ch_num, title, full_content[:15000], entities): "events",
                executor.submit(extract_relations, ch_num, title, full_content[:15000], entities): "relations",
                executor.submit(extract_timeline_cumulative, ch_num, title, content, time_anchors, year_tracker): "timeline",
                executor.submit(extract_lore_rules, ch_num, title, content): "lore_rules",
            }

            for future in as_completed(futures):
                task_name = futures[future]
                try:
                    result = future.result()
                    if task_name == "events":
                        events = result
                    elif task_name == "relations":
                        relations = result
                    elif task_name == "timeline":
                        timeline = result
                    elif task_name == "lore_rules":
                        lore_rules = result
                except Exception as e:
                    log.error(f"  {task_name} failed: {e}")
                    stats["errors"] += 1

        log.info(f"  Stage 2: {len(events)} events")
        log.info(f"  Stage 3: {len(relations)} relations")
        log.info(f"  Stage 4: timeline year={timeline.estimated_year if timeline else 'N/A'}")
        log.info(f"  Stage 4b: {len(lore_rules)} lore rules")

        # ========== Stage 5: 实体归一 ==========
        for entity in entities:
            normalizer.add_entity(entity)
        log.info(f"  Stage 5: {len(normalizer.canonical_entities)} canonical entities")

        # ========== Stage 6: 聚合 ==========
        extraction = ChapterExtraction(
            chapter_num=ch_num,
            chapter_title=title,
            entities=entities,
            events=events,
            relations=relations,
            timeline=timeline,
            lore_rules=lore_rules,
        )
        aggregator.add_extraction(extraction)

        # 更新统计
        stats["chapters_processed"] += 1
        stats["entities_total"] += len(entities)
        stats["events_total"] += len(events)
        stats["relations_total"] += len(relations)
        stats["lore_rules_total"] += len(lore_rules)

        if dry_run:
            log.info(f"  [dry-run] Chapter {ch_num} done")
            prev_content_buffer = content[-CROSS_CHAPTER_BUFFER:]
            # 更新已知实体列表
            for entity in entities:
                if entity.name not in known_entities:
                    known_entities.append(entity.name)
            continue

        # ========== Stage 7: 写入 DB ==========
        # 7a. PG 实体
        for entity in entities:
            pg_id = pg_writer.write_entity(entity, ch_num)
            if pg_id > 0:
                table_map = {
                    "Character": "characters", "Faction": "factions",
                    "Location": "locations", "Artifact": "items_artifacts",
                    "Technique": "techniques", "SpiritBeast": "spirit_beasts",
                }
                table = table_map.get(entity.entity_type, "characters")
                for sq in entity.source_quotes:
                    pg_writer.write_source_ref(table, pg_id, sq, ch_num)

                # Neo4j 节点
                if neo4j_writer:
                    extra = {}
                    if entity.entity_type == "Character":
                        extra["is_custom"] = False
                    elif entity.entity_type == "Location":
                        extra["location_type"] = entity.attributes.get("location_type", "")
                    neo4j_writer.write_node(entity.entity_type, pg_id, entity.name, extra)

        # 7b. PG 事件
        for event in events:
            ev_id = pg_writer.write_event(event)
            if ev_id and ev_id > 0:
                for sq in event.source_quotes:
                    pg_writer.write_source_ref("events", ev_id, sq, ch_num)

                if neo4j_writer:
                    neo4j_writer.write_node("Event", ev_id, event.event_name, {
                        "event_type": event.event_type,
                        "chapter": ch_num,
                    })

                if zilliz_writer:
                    embed_text = f"{event.event_name}: {event.event_detail}"
                    embedding = get_embedding(embed_text)
                    zilliz_writer.write_event_embedding(ev_id, embed_text, ch_num, event.event_type, embedding)

        # 7c. PG 关系
        for rel in relations:
            rel_id = pg_writer.write_relation(rel)
            if neo4j_writer and rel_id and rel_id > 0:
                from_key = f"{rel.from_type}:{rel.from_entity}"
                to_key = f"{rel.to_type}:{rel.to_entity}"
                from_cache = pg_writer.entity_cache.get(from_key)
                to_cache = pg_writer.entity_cache.get(to_key)
                if from_cache and to_cache:
                    rel_props = {"since_chapter": rel.valid_from_chapter}
                    if rel.relation_type:
                        rel_props["type"] = rel.relation_type
                    neo4j_writer.write_relationship(
                        rel.from_type, from_cache[1],
                        rel.to_type, to_cache[1],
                        rel.relation_label, rel_props
                    )

        # 7d. PG 代价/规则
        for rule in lore_rules:
            pg_writer.write_lore_rule(rule)

        # Commit per chapter
        try:
            pg_writer.commit()
        except Exception as e:
            log.error(f"  PG commit error for ch {ch_num}: {e}")
            pg_writer.conn.rollback()
            stats["errors"] += 1

        log.info(f"  Chapter {ch_num} committed (year={timeline.estimated_year if timeline else 'N/A'})")

        # 更新上下文缓冲
        prev_content_buffer = content[-CROSS_CHAPTER_BUFFER:]

        # 更新已知实体列表
        for entity in entities:
            if entity.name not in known_entities:
                known_entities.append(entity.name)

        # 更新时间锚点
        if timeline and timeline.estimated_year:
            time_anchors = f"ch{ch_num} = {timeline.estimated_year}岁"

        # 限流
        time.sleep(0.3)

    # ========== Stage 6: 跨章聚合 ==========
    log.info("=== Stage 6: Cross-chapter aggregation ===")

    snapshots = aggregator.generate_snapshots(normalizer)
    stats["snapshots_total"] = len(snapshots)
    save_aggregated_output(run_dir, "snapshots", snapshots)
    log.info(f"  Generated {len(snapshots)} character snapshots")

    save_aggregated_output(run_dir, "realm_timeline", aggregator.realm_timeline)
    save_aggregated_output(run_dir, "chapter_year_map", aggregator.chapter_year_map)
    save_aggregated_output(run_dir, "master_timeline", aggregator.master_events)

    all_entities = list(normalizer.canonical_entities.values())
    save_aggregated_output(run_dir, "entities_normalized", all_entities)
    save_aggregated_output(run_dir, "alias_map", normalizer.alias_map)

    # 保存累积年份数据
    year_data_file = run_dir / "cumulative_years.json"
    with open(year_data_file, "w") as f:
        json.dump(year_tracker.chapter_years, f, indent=2)
    log.info(f"  Saved cumulative years to {year_data_file}")

    if not dry_run:
        log.info("=== Stage 7: Writing aggregated data ===")

        # 写角色快照
        for snap in snapshots:
            pg_writer.write_character_snapshot(snap)

        # 写境界时间线
        for char_name, realms in aggregator.realm_timeline.items():
            for i, realm in enumerate(realms):
                end_ch = realms[i+1]["start_chapter"] - 1 if i+1 < len(realms) else None
                pg_writer.write_realm_timeline(
                    char_name, realm["realm_stage"],
                    realm["start_chapter"], end_ch,
                    realm.get("start_year"),
                    realm.get("confidence", "cumulative"),
                )

        # 写 master_timeline
        for mt_event in aggregator.master_events:
            pg_writer.write_master_timeline(mt_event)

        # 写 chapter_year_mapping
        for ch, year_data in aggregator.chapter_year_map.items():
            pg_writer.write_chapter_year_mapping(ch, year_data)

        # Final commit
        try:
            pg_writer.commit()
            log.info("  Aggregated data committed")
        except Exception as e:
            log.error(f"  Aggregated data commit error: {e}")
            pg_writer.conn.rollback()

    # Cleanup
    pg_writer.close()
    if neo4j_writer:
        neo4j_writer.close()
    if zilliz_writer:
        zilliz_writer.close()

    # 保存统计
    stats["completed_at"] = datetime.now().isoformat()
    stats["start_chapter"] = start_chapter
    stats["end_chapter"] = end_chapter
    stats["final_year"] = year_tracker.get_year(end_chapter)

    log.info(f"=== Import Complete ===")
    log.info(f"  Chapters: {start_chapter}-{end_chapter}")
    log.info(f"  Final year: ch{end_chapter} = {stats['final_year']}岁")
    log.info(f"  Entities: {stats['entities_total']}")
    log.info(f"  Events: {stats['events_total']}")
    log.info(f"  Relations: {stats['relations_total']}")
    log.info(f"  Errors: {stats['errors']}")

    # Write stats
    stats_file = run_dir / "run_summary.json"
    with open(stats_file, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

    return stats


# ============================================================
# CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="AMO 批量导入: 501-1000 章（累积年份计算）")
    parser.add_argument("--start", type=int, default=501, help="起始章节")
    parser.add_argument("--end", type=int, default=1000, help="结束章节")
    parser.add_argument("--base-chapter", type=int, default=None, help="锚点章节（不指定则自动从 DB 查询）")
    parser.add_argument("--base-year", type=int, default=None, help="锚点年份（不指定则自动从 DB 查询）")
    parser.add_argument("--dry-run", action="store_true", help="预览模式，不写数据库")
    parser.add_argument("--skip-neo4j", action="store_true", help="跳过 Neo4j 写入")
    parser.add_argument("--skip-zilliz", action="store_true", help="跳过 Zilliz 写入")
    args = parser.parse_args()

    # 确定锚点
    global BASE_CHAPTER, BASE_YEAR
    if args.base_chapter is not None and args.base_year is not None:
        BASE_CHAPTER = args.base_chapter
        BASE_YEAR = args.base_year
        log.info(f"Using specified anchor: ch{BASE_CHAPTER} = {BASE_YEAR}岁")
    else:
        # 尝试从数据库获取上一批的最后年份
        db_anchor = get_latest_year_from_db(args.start)
        if db_anchor:
            BASE_CHAPTER, BASE_YEAR = db_anchor
            log.info(f"Using DB anchor: ch{BASE_CHAPTER} = {BASE_YEAR}岁")
        else:
            # 使用默认锚点
            BASE_CHAPTER = 500
            BASE_YEAR = 204
            log.info(f"Using default anchor: ch{BASE_CHAPTER} = {BASE_YEAR}岁")

    run_batch_import(
        start_chapter=args.start,
        end_chapter=args.end,
        dry_run=args.dry_run,
        skip_neo4j=args.skip_neo4j,
        skip_zilliz=args.skip_zilliz,
    )


if __name__ == "__main__":
    main()
