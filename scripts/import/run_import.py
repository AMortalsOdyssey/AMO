#!/usr/bin/env python3
"""
AMO 小说完整导入脚本 v2.0
严格按照 novel-import-complete-guide.md + three-db-ddl-design.md + canon-extraction-pipeline.md 实施

多阶段抽取流水线：
  Stage 0: 章节预处理（清洗、分窗口、跨章缓冲）
  Stage 1: 实体抽取（Character/Faction/Location/Artifact/Technique/SpiritBeast）
  Stage 2: 事件抽取（绑定 Stage 1 实体）
  Stage 3: 关系抽取（角色关系/势力归属/物品持有/功法修炼）
  Stage 4: 时间线抽取（世界纪年推算、境界变化、章节-年份映射）
  Stage 5: 实体归一（alias_map + 指代消解 + 冲突检测）
  Stage 6: 跨章聚合（角色快照、境界时间线、master_timeline）
  Stage 7: 三库写入（PG 18表 + Neo4j 7节点12关系 + Zilliz 4集合）

用法:
  python3 scripts/import/run_import.py --start 1 --end 50
  python3 scripts/import/run_import.py --start 1 --end 2 --dry-run
  python3 scripts/import/run_import.py --replay --start 5 --end 10
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
from typing import Any

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
    "model": os.environ.get("LLM_MODEL", "gpt-5.4-2026-03-05"),
}

CHAPTERS_DIR = Path(__file__).parent.parent.parent / "book" / "chapters"
OUTPUT_DIR = Path(__file__).parent / "output"
EMBEDDING_DIM = 4096

# 跨章上下文缓冲大小
CROSS_CHAPTER_BUFFER = 500

# ============================================================
# LLM Pricing Config (per 1M tokens)
# ============================================================

LLM_PRICING = {
    "gemini-3.1-pro-preview": {
        "input_per_million": 1.25,   # USD per 1M input tokens
        "output_per_million": 5.0,   # USD per 1M output tokens
    },
    # 可在此添加更多模型价格
    "default": {
        "input_per_million": 1.0,
        "output_per_million": 3.0,
    },
}

def get_llm_pricing(model: str) -> dict:
    """获取模型定价，找不到则用 default"""
    return LLM_PRICING.get(model, LLM_PRICING["default"])


# ============================================================
# LLM Usage Tracker
# ============================================================

class LLMUsageTracker:
    """Thread-safe LLM usage tracker"""

    def __init__(self, model: str):
        self.model = model
        self.pricing = get_llm_pricing(model)
        self._lock = threading.Lock()
        self._records: list[dict] = []  # 每次调用的记录
        self._chapter_stats: dict[int, dict] = {}  # ch_num -> aggregated stats

    def record_usage(self, chapter: int, stage: str,
                     input_tokens: int | None, output_tokens: int | None,
                     source: str = "api"):
        """
        记录一次 LLM 调用
        source: "api" = 从 API 响应获取, "unavailable" = API 未返回 usage
        """
        total_tokens = None
        price = None

        if input_tokens is not None and output_tokens is not None:
            total_tokens = input_tokens + output_tokens
            price = (
                input_tokens * self.pricing["input_per_million"] / 1_000_000 +
                output_tokens * self.pricing["output_per_million"] / 1_000_000
            )

        record = {
            "timestamp": datetime.now().isoformat(),
            "chapter": chapter,
            "stage": stage,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "price_usd": round(price, 6) if price else None,
            "source": source,  # "api" | "unavailable"
        }

        with self._lock:
            self._records.append(record)

            # 累加到章节统计
            if chapter not in self._chapter_stats:
                self._chapter_stats[chapter] = {
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                    "price_usd": 0.0,
                    "calls": 0,
                    "unavailable_calls": 0,
                }
            cs = self._chapter_stats[chapter]
            cs["calls"] += 1
            if source == "unavailable":
                cs["unavailable_calls"] += 1
            else:
                cs["input_tokens"] += input_tokens or 0
                cs["output_tokens"] += output_tokens or 0
                cs["total_tokens"] += total_tokens or 0
                cs["price_usd"] += price or 0

    def get_summary(self) -> dict:
        """返回总汇总"""
        with self._lock:
            total_input = sum(r["input_tokens"] or 0 for r in self._records if r["source"] == "api")
            total_output = sum(r["output_tokens"] or 0 for r in self._records if r["source"] == "api")
            total_price = sum(r["price_usd"] or 0 for r in self._records if r["source"] == "api")
            total_calls = len(self._records)
            unavailable_calls = sum(1 for r in self._records if r["source"] == "unavailable")

            return {
                "model": self.model,
                "pricing": self.pricing,
                "summary": {
                    "total_input_tokens": total_input,
                    "total_output_tokens": total_output,
                    "total_tokens": total_input + total_output,
                    "total_price_usd": round(total_price, 4),
                    "total_calls": total_calls,
                    "unavailable_calls": unavailable_calls,
                },
                "per_chapter": dict(self._chapter_stats),
                "records": list(self._records),
            }

    def save_to_file(self, filepath: Path):
        """保存到 JSON 文件"""
        data = self.get_summary()
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


# Global tracker, will be initialized in run_import
_usage_tracker: LLMUsageTracker | None = None
_current_chapter: int = 0  # 当前正在处理的章节


# ============================================================
# Logging Setup
# ============================================================

# 全局 logger（稍后在 run_import 中配置 handler）
log = logging.getLogger("amo-import")
log.setLevel(logging.INFO)

# Stage-specific loggers
log_stage2 = logging.getLogger("amo-import.stage2")
log_stage3 = logging.getLogger("amo-import.stage3")
log_stage4 = logging.getLogger("amo-import.stage4")


class ChapterContextFilter(logging.Filter):
    """为日志添加 ch=XX 上下文"""
    def filter(self, record):
        global _current_chapter
        record.ch = _current_chapter if _current_chapter > 0 else "-"
        return True


def setup_logging(run_dir: Path):
    """配置多文件日志"""
    # 清理已有 handlers
    for logger in [log, log_stage2, log_stage3, log_stage4]:
        logger.handlers.clear()
        logger.setLevel(logging.INFO)

    # 格式：带章节号
    main_fmt = logging.Formatter("%(asctime)s [%(levelname)s] [ch=%(ch)s] %(message)s")
    stage_fmt = logging.Formatter("%(asctime)s [%(levelname)s] [ch=%(ch)s] %(message)s")

    ch_filter = ChapterContextFilter()

    # 1. Main logger -> console + main.log
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(main_fmt)
    console_handler.addFilter(ch_filter)
    log.addHandler(console_handler)

    main_file = logging.FileHandler(run_dir / "main.log", encoding="utf-8")
    main_file.setFormatter(main_fmt)
    main_file.addFilter(ch_filter)
    log.addHandler(main_file)

    # 2. Stage 2 logger -> stage2.log (也输出到 main.log)
    s2_file = logging.FileHandler(run_dir / "stage2.log", encoding="utf-8")
    s2_file.setFormatter(stage_fmt)
    s2_file.addFilter(ch_filter)
    log_stage2.addHandler(s2_file)
    log_stage2.propagate = False  # 不传播到 root，自己管
    # 同时也写到 main.log
    log_stage2.addHandler(main_file)

    # 3. Stage 3 logger -> stage3.log
    s3_file = logging.FileHandler(run_dir / "stage3.log", encoding="utf-8")
    s3_file.setFormatter(stage_fmt)
    s3_file.addFilter(ch_filter)
    log_stage3.addHandler(s3_file)
    log_stage3.propagate = False
    log_stage3.addHandler(main_file)

    # 4. Stage 4 logger -> stage4.log
    s4_file = logging.FileHandler(run_dir / "stage4.log", encoding="utf-8")
    s4_file.setFormatter(stage_fmt)
    s4_file.addFilter(ch_filter)
    log_stage4.addHandler(s4_file)
    log_stage4.propagate = False
    log_stage4.addFilter(ch_filter)
    log_stage4.addHandler(main_file)

# ============================================================
# Data Classes
# ============================================================

@dataclass
class SourceQuote:
    chapter: int
    char_start: int
    char_end: int
    quote: str
    confidence: str = "high"

@dataclass
class ExtractedEntity:
    entity_type: str       # Character/Faction/Location/Artifact/Technique/SpiritBeast
    name: str
    aliases: list[str] = field(default_factory=list)
    attributes: dict = field(default_factory=dict)
    first_chapter: int = 0
    source_quotes: list[dict] = field(default_factory=list)
    confidence: str = "high"

@dataclass
class ExtractedEvent:
    event_name: str
    event_type: str
    chapter: int
    chapter_end: int | None = None
    event_detail: str = ""
    result: str = ""
    primary_character: str = ""
    participants: list[dict] = field(default_factory=list)
    location: str = ""
    time_hint: str = ""
    realm_changes: dict = field(default_factory=dict)
    source_quotes: list[dict] = field(default_factory=list)
    confidence: str = "high"

@dataclass
class ExtractedRelation:
    from_entity: str
    from_type: str
    to_entity: str
    to_type: str
    relation_type: str
    relation_label: str       # RELATION/BELONGS_TO/OWNS/MASTERS/LOCATED_IN/BONDED_TO/CAUSES
    attributes: dict = field(default_factory=dict)
    valid_from_chapter: int = 0
    valid_until_chapter: int | None = None
    source_quotes: list[dict] = field(default_factory=list)
    confidence: str = "high"

@dataclass
class TimelineEntry:
    chapter: int
    time_hint: str = ""
    estimated_year: int | None = None
    year_end: int | None = None
    confidence: str = "estimated"
    realm_changes: dict = field(default_factory=dict)
    reasoning: str = ""

@dataclass
class ExtractedLoreRule:
    """代价/规则抽取结果"""
    category: str  # cultivation_risk/social_rule/character_rule/resource_rule/combat_rule/world_rule
    sub_category: str | None = None
    rule_name: str = ""
    description: str = ""
    trigger_condition: str | None = None
    consequence_type: str | None = None
    consequence_detail: str | None = None
    delay_type: str = "immediate"  # immediate/years_later/realm_trigger/conditional
    severity: str = "medium"
    source_chapters: list[int] = field(default_factory=list)
    source_quote: str | None = None
    confidence: str = "high"

@dataclass
class ChapterExtraction:
    chapter_num: int
    chapter_title: str
    checksum: str = ""
    entities: list[ExtractedEntity] = field(default_factory=list)
    events: list[ExtractedEvent] = field(default_factory=list)
    relations: list[ExtractedRelation] = field(default_factory=list)
    timeline: TimelineEntry | None = None
    lore_rules: list[ExtractedLoreRule] = field(default_factory=list)  # 新增：代价/规则

@dataclass
class CharacterSnapshot:
    character_name: str
    realm_stage: str
    chapter_start: int
    chapter_end: int | None = None
    year_start: int | None = None
    year_end: int | None = None
    knowledge_cutoff: int = 0
    equipment: dict = field(default_factory=dict)
    techniques: list[str] = field(default_factory=list)
    spirit_beasts: list[str] = field(default_factory=list)
    faction: str | None = None
    location: str | None = None
    persona_prompt: str = ""
    personality_traits: list[str] = field(default_factory=list)

# ============================================================
# Stage 0: 章节预处理
# ============================================================

def read_chapter(chapter_num: int) -> tuple[str, str, str]:
    """读取指定章节, 返回 (title, content, checksum)"""
    pattern = f"{chapter_num:04d}_*"
    matches = sorted(CHAPTERS_DIR.glob(pattern))
    matches = [m for m in matches if not re.search(r" \d+\.txt$", str(m))]
    if not matches:
        raise FileNotFoundError(f"Chapter {chapter_num} not found with pattern {pattern}")

    filepath = matches[0]
    content = filepath.read_text(encoding="utf-8", errors="replace")

    # 文本清洗
    content = content.replace('\ufeff', '').replace('\u200b', '')
    content = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', content)  # 控制字符
    content = re.sub(r' {2,}', ' ', content)  # 多空格

    lines = content.strip().split("\n", 1)
    title = lines[0].strip()
    body = lines[1].strip() if len(lines) > 1 else ""

    checksum = hashlib.md5(body.encode()).hexdigest()
    return title, body, checksum


def get_chapter_tail(chapter_num: int) -> str:
    """获取上一章尾部作为跨章上下文"""
    try:
        _, body, _ = read_chapter(chapter_num)
        return body[-CROSS_CHAPTER_BUFFER:] if len(body) > CROSS_CHAPTER_BUFFER else body
    except FileNotFoundError:
        return ""


# ============================================================
# LLM 调用封装
# ============================================================

def call_llm(prompt: str, max_tokens: int = 4096, stage: str = "unknown") -> str:
    """
    调用 LLM，返回文本响应。内置重试。
    自动记录 token 消耗到全局 tracker。
    """
    global _usage_tracker, _current_chapter

    max_retries = 5  # 增加到 5 次重试
    for attempt in range(max_retries):
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
                    "max_tokens": max_tokens,
                    "temperature": 0.1,
                },
                timeout=180,
            )
            resp.raise_for_status()
            data = resp.json()

            # 尝试获取 usage 信息
            usage = data.get("usage", {})
            input_tokens = usage.get("prompt_tokens")
            output_tokens = usage.get("completion_tokens")

            # 记录到 tracker
            if _usage_tracker:
                if input_tokens is not None and output_tokens is not None:
                    _usage_tracker.record_usage(
                        chapter=_current_chapter,
                        stage=stage,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        source="api"
                    )
                else:
                    # API 未返回 usage
                    _usage_tracker.record_usage(
                        chapter=_current_chapter,
                        stage=stage,
                        input_tokens=None,
                        output_tokens=None,
                        source="unavailable"
                    )

            # 安全获取响应内容
            choices = data.get("choices")
            if not choices or len(choices) == 0:
                raise ValueError("LLM API returned empty choices")
            message = choices[0].get("message")
            if not message:
                raise ValueError("LLM API returned no message in choice")
            content = message.get("content", "")
            return content
        except Exception as e:
            log.warning(f"LLM call attempt {attempt+1}/{max_retries} failed: {e}")
            if attempt == max_retries - 1:
                # 最后一次重试失败，返回空字符串而不是抛异常（允许跳过）
                log.error(f"LLM call failed after {max_retries} attempts, returning empty response")
                return ""
            # 指数退避: 5s, 10s, 20s, 40s
            time.sleep(5 * (2 ** attempt))
    return ""


def parse_llm_json(text: str) -> dict:
    """从 LLM 响应中解析 JSON，多级 fallback"""
    # 尝试提取 ```json ... ```
    json_match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    if json_match:
        text = json_match.group(1)
    else:
        json_match = re.search(r"\{.*\}", text, re.DOTALL)
        if json_match:
            text = json_match.group(0)

    # 修复常见 JSON 问题
    text = re.sub(r",\s*}", "}", text)
    text = re.sub(r",\s*]", "]", text)
    text = text.replace('\ufeff', '').replace('\u200b', '')

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # 分数组 fallback
        data = {}
        for key in ("entities", "events", "relations", "time_mentions", "realm_changes", "year_estimation"):
            match = re.search(rf'"{key}"\s*:\s*(\[.*?\])\s*[,}}]', text, re.DOTALL)
            if match:
                arr_text = re.sub(r",\s*]", "]", re.sub(r",\s*}", "}", match.group(1)))
                try:
                    data[key] = json.loads(arr_text)
                except json.JSONDecodeError:
                    pass
            else:
                # 尝试匹配对象
                match = re.search(rf'"{key}"\s*:\s*(\{{.*?\}})\s*[,}}]', text, re.DOTALL)
                if match:
                    obj_text = re.sub(r",\s*}", "}", match.group(1))
                    try:
                        data[key] = json.loads(obj_text)
                    except json.JSONDecodeError:
                        pass
        if data:
            return data
        raise json.JSONDecodeError("All parsing failed", text, 0)


# ============================================================
# Stage 1: 实体抽取
# ============================================================

ENTITY_PROMPT = """你是《凡人修仙传》世界观专家。从以下章节文本中抽取所有实体。

当前章节：第{chapter_num}章 {chapter_title}
{context_hint}

【正文】
{content}

输出**纯JSON**（不要markdown代码块、不要任何其他文字）：
{{
  "entities": [
    {{
      "entity_type": "Character/Faction/Location/Artifact/Technique/SpiritBeast",
      "name": "标准名称（最常用的称呼）",
      "aliases": ["别名1", "别名2"],
      "attributes": {{
        "gender": "male/female/unknown",
        "description": "简要描述（20字内）",
        "faction_type": "sect/family/organization/country",
        "location_type": "country/region/city/sect/mountain/secret_realm",
        "item_type": "weapon/armor/accessory/storage/flying/medicine",
        "technique_type": "cultivation/attack/defense/auxiliary",
        "grade": "等阶（如有）",
        "species": "物种（灵兽用）",
        "is_major": true/false
      }},
      "source_quotes": [{{"quote": "原文摘录20-80字", "char_start": 0, "char_end": 100}}],
      "confidence": "high/medium/low"
    }}
  ]
}}

规则：
1. 每条必须有source_quotes原文依据，没有依据不要输出
2. 只抽取本章明确提到的实体，不推测
3. 同一实体只输出一次，别名放aliases
4. 人名需区分角色vs仅提及的历史人物vs泛指
5. 组织/门派统一用Faction，地点用Location
6. "他/她/这位前辈"等代词不要作为独立实体
7. attributes只填本章有证据的字段
8. 如果实体在已知实体列表中已存在，优先复用已知的标准名称，不要随意改写（如"神秘瓶子"已存在，不要改成"神秘小瓶"）"""


def extract_entities(chapter_num: int, title: str, content: str,
                     known_entities: list[str], prev_tail: str) -> list[ExtractedEntity]:
    """Stage 1: 实体抽取"""
    context_hint = ""
    if known_entities:
        context_hint += f"\n已知实体（前序章节）：{', '.join(known_entities[:80])}\n"
    if prev_tail:
        context_hint += f"\n上一章尾部（上下文）：\n{prev_tail}\n"

    prompt = ENTITY_PROMPT.format(
        chapter_num=chapter_num,
        chapter_title=title,
        content=content[:15000],
        context_hint=context_hint,
    )

    text = call_llm(prompt, stage="stage1_entity")
    if not text or not text.strip():
        log.warning(f"ch{chapter_num}: Entity extraction returned empty, skipping")
        return []
    data = parse_llm_json(text)

    entities = []
    for e in data.get("entities", []):
        etype = e.get("entity_type", "Character")
        if etype in ("Organization", "Sect", "Group"):
            etype = "Faction"
        if etype in ("Herb", "Medicine", "Pill"):
            etype = "Artifact"  # 灵草丹药归入物品
        if etype in ("Puppet",):
            etype = "Artifact"

        name = e.get("name", "").strip()
        if not name or len(name) > 50:
            continue

        entities.append(ExtractedEntity(
            entity_type=etype,
            name=name,
            aliases=[a for a in e.get("aliases", []) if a and a != name],
            attributes=e.get("attributes", {}),
            first_chapter=chapter_num,
            source_quotes=e.get("source_quotes", []),
            confidence=e.get("confidence", "high"),
        ))
    return entities


# ============================================================
# Stage 2: 事件抽取
# ============================================================

EVENT_PROMPT = """你是《凡人修仙传》世界观专家。从以下章节中抽取关键事件。

当前章节：第{chapter_num}章 {chapter_title}

【已识别实体】
{entity_list}

【正文】
{content}

输出**纯JSON**：
{{
  "events": [
    {{
      "event_name": "事件名（简洁描述，20字以内）",
      "event_type": "realm_breakthrough/major_battle/faction_event/relationship_change/location_move/world_event/item_acquisition/character_death/time_marker",
      "event_detail": "详情（100字以内）",
      "result": "事件结果/影响",
      "primary_character": "主要角色名",
      "participants": [{{"name": "角色名", "role": "protagonist/antagonist/witness/victim"}}],
      "location": "发生地点",
      "time_hint": "原文中的时间描述（如'三年后'、'数月之后'）",
      "realm_changes": {{"角色名": "新境界"}},
      "source_quotes": [{{"quote": "原文摘录20-150字", "char_start": 0, "char_end": 100}}],
      "confidence": "high/medium/low"
    }}
  ]
}}

规则：
1. 只抽取有实际影响的事件，不抽取日常对话和过渡描写
2. 境界突破必须抽取
3. 关系变化（结为道侣、反目成仇）必须抽取
4. 位置迁移（离开某地、进入某地）必须抽取
5. 保留原文中的时间描述time_hint，供后续时间线推算
6. 必须有source_quotes原文依据"""


def extract_events(chapter_num: int, title: str, content: str,
                   entities: list[ExtractedEntity]) -> list[ExtractedEvent]:
    """Stage 2: 事件抽取"""
    entity_list = ", ".join(f"{e.entity_type}:{e.name}" for e in entities)

    prompt = EVENT_PROMPT.format(
        chapter_num=chapter_num,
        chapter_title=title,
        content=content[:15000],
        entity_list=entity_list or "（本章暂无已识别实体）",
    )

    text = call_llm(prompt, stage="stage2_event")
    if not text or not text.strip():
        log_stage2.warning(f"Event extraction returned empty, skipping")
        return []
    log_stage2.info(f"Event extraction completed")
    data = parse_llm_json(text)

    events = []
    for ev in data.get("events", []):
        name = ev.get("event_name", "").strip()
        if not name:
            continue
        events.append(ExtractedEvent(
            event_name=name[:200],
            event_type=ev.get("event_type", "world_event"),
            chapter=chapter_num,
            event_detail=ev.get("event_detail", ""),
            result=ev.get("result", ""),
            primary_character=ev.get("primary_character", ""),
            participants=ev.get("participants", []),
            location=ev.get("location", ""),
            time_hint=ev.get("time_hint", ""),
            realm_changes=ev.get("realm_changes", {}),
            source_quotes=ev.get("source_quotes", []),
            confidence=ev.get("confidence", "high"),
        ))
    return events


# ============================================================
# Stage 3: 关系抽取
# ============================================================

RELATION_PROMPT = """你是《凡人修仙传》世界观专家。从以下章节中抽取实体间的关系。

当前章节：第{chapter_num}章 {chapter_title}

【已识别实体】
{entity_list}

【正文】
{content}

输出**纯JSON**：
{{
  "relations": [
    {{
      "from_entity": "实体名",
      "from_type": "Character/Faction/Location/Artifact/Technique/SpiritBeast/Event",
      "to_entity": "实体名",
      "to_type": "Character/Faction/Location/Artifact/Technique/SpiritBeast/Event",
      "relation_type": "师徒/同门/血亲/敌对/盟友/道侣/主仆/旧识/disciple/elder",
      "relation_label": "RELATION/BELONGS_TO/OWNS/MASTERS/LOCATED_IN/BONDED_TO/CAUSES/CONNECTED_TO",
      "attributes": {{"role": "disciple/inner_disciple/elder/patriarch/guest_elder", "seniority": "师兄/师弟", "proficiency": "learning/mastered"}},
      "valid_from_chapter": {chapter_num},
      "valid_until_chapter": null,
      "source_quotes": [{{"quote": "原文摘录20-80字", "char_start": 0, "char_end": 100}}],
      "confidence": "high/medium/low"
    }}
  ]
}}

关系类型说明：
- RELATION: 角色间关系（师徒/同门/血亲/敌对/盟友/道侣/主仆）
- BELONGS_TO: 角色→势力归属
- OWNS: 角色→法宝/灵兽持有
- MASTERS: 角色→功法修炼
- LOCATED_IN: 角色/势力→地点
- BONDED_TO: 角色→灵兽契约
- CAUSES: 事件→事件因果
- CONNECTED_TO: 地点→地点连通

规则：
1. 必须有source_quotes原文依据
2. 注意关系方向：师→徒、角色→势力、角色→法宝
3. 区分当前状态vs历史状态（如已离开宗门用valid_until_chapter标注）
4. 同门关系、师徒关系要明确方向和辈分
5. from_entity/to_entity 必须严格使用“已识别实体”中的标准名，不要输出简称、代称或指代（例如“玉灵”“双圣”“六道”“老宫主”“家父”“家母”都不允许）
6. 遇到“家父/家母/爱女/之女/之子/夫妇/道侣”等隐含关系时，要还原成明确的标准实体名和关系方向"""


def _resolve_relation_entity_name(
    name: str,
    entity_type: str,
    normalizer,
    chapter_alias_map: dict[str, str],
) -> str:
    if not name:
        return name

    if name in chapter_alias_map:
        return chapter_alias_map[name]

    resolved = normalizer.resolve_name(name)
    if resolved != name:
        return resolved

    candidates = []
    for entity in normalizer.get_entities_by_type(entity_type):
        if entity.name == name:
            return name
        if len(name) >= 2 and (entity.name.endswith(name) or name.endswith(entity.name)):
            candidates.append(entity.name)

    if len(candidates) == 1:
        return candidates[0]

    return name


def normalize_relations(
    relations: list[ExtractedRelation],
    normalizer,
    chapter_entities: list[ExtractedEntity],
) -> list[ExtractedRelation]:
    """在写库前统一关系端点名称，减少 alias/简称导致的裂变节点。"""
    chapter_alias_map: dict[str, str] = {}
    for entity in chapter_entities:
        chapter_alias_map[entity.name] = entity.name
        for alias in entity.aliases:
            if alias:
                chapter_alias_map[alias] = entity.name

    deduped: dict[tuple, ExtractedRelation] = {}

    for rel in relations:
        rel.from_entity = _resolve_relation_entity_name(rel.from_entity, rel.from_type, normalizer, chapter_alias_map)
        rel.to_entity = _resolve_relation_entity_name(rel.to_entity, rel.to_type, normalizer, chapter_alias_map)

        dedupe_key = (
            rel.from_type,
            rel.from_entity,
            rel.to_type,
            rel.to_entity,
            rel.relation_label,
            rel.relation_type,
            rel.valid_from_chapter,
            rel.valid_until_chapter,
        )
        existing = deduped.get(dedupe_key)
        if existing is None:
            deduped[dedupe_key] = rel
            continue

        if not existing.relation_type and rel.relation_type:
            existing.relation_type = rel.relation_type
        if rel.attributes:
            existing.attributes.update(rel.attributes)
        if rel.source_quotes:
            existing.source_quotes.extend(rel.source_quotes)
        if existing.confidence == "low" and rel.confidence != "low":
            existing.confidence = rel.confidence

    return list(deduped.values())


def extract_relations(chapter_num: int, title: str, content: str,
                      entities: list[ExtractedEntity]) -> list[ExtractedRelation]:
    """Stage 3: 关系抽取"""
    entity_list = ", ".join(f"{e.entity_type}:{e.name}" for e in entities)

    prompt = RELATION_PROMPT.format(
        chapter_num=chapter_num,
        chapter_title=title,
        content=content[:15000],
        entity_list=entity_list or "（本章暂无已识别实体）",
    )

    text = call_llm(prompt, stage="stage3_relation")
    if not text or not text.strip():
        log_stage3.warning(f"Relation extraction returned empty, skipping")
        return []
    log_stage3.info(f"Relation extraction completed")
    data = parse_llm_json(text)

    relations = []
    for r in data.get("relations", []):
        from_name = r.get("from_entity", "").strip()
        to_name = r.get("to_entity", "").strip()
        if not from_name or not to_name:
            continue
        relations.append(ExtractedRelation(
            from_entity=from_name,
            from_type=r.get("from_type", "Character"),
            to_entity=to_name,
            to_type=r.get("to_type", "Character"),
            relation_type=r.get("relation_type", ""),
            relation_label=r.get("relation_label", "RELATION"),
            attributes=r.get("attributes", {}),
            valid_from_chapter=r.get("valid_from_chapter") or chapter_num,
            valid_until_chapter=r.get("valid_until_chapter"),
            source_quotes=r.get("source_quotes", []),
            confidence=r.get("confidence", "high"),
        ))
    return relations


# ============================================================
# Stage 4: 时间线抽取
# ============================================================

TIMELINE_PROMPT = """你是《凡人修仙传》世界观专家。从以下章节中抽取时间相关信息。

当前章节：第{chapter_num}章 {chapter_title}

【已知时间锚点】
{time_anchors}

【正文】
{content}

输出**纯JSON**：
{{
  "time_mentions": [
    {{"text": "原文时间描述", "type": "relative/absolute", "quote": "包含时间描述的句子"}}
  ],
  "realm_changes": [
    {{
      "character": "角色名",
      "from_realm": "原境界（如有）",
      "to_realm": "新境界",
      "quote": "原文依据"
    }}
  ],
  "year_estimation": {{
    "estimated_year": null,
    "year_end": null,
    "reasoning": "推算依据",
    "confidence": "exact/high/estimated/inferred"
  }}
}}

已知时间体系（以韩立出生为Year 0）：
- Year 0: 韩立出生
- Year ~10: 韩立入七玄门
- Year ~11: 开始修炼

规则：
1. 不要凭空编造年份，只在有明确依据时推算
2. 记录所有时间相关的原文（"三年后"、"数十年"等）
3. 境界变化必须记录
4. 韩立的年龄/修炼时间是主要锚点"""


def extract_timeline(chapter_num: int, title: str, content: str,
                     time_anchors: str) -> TimelineEntry:
    """Stage 4: 时间线抽取"""
    prompt = TIMELINE_PROMPT.format(
        chapter_num=chapter_num,
        chapter_title=title,
        content=content[:12000],
        time_anchors=time_anchors or "暂无已知锚点",
    )

    try:
        text = call_llm(prompt, max_tokens=2048, stage="stage4_timeline")
        if not text or not text.strip():
            log_stage4.warning(f"Timeline extraction returned empty, using defaults")
            return TimelineEntry(chapter=chapter_num)
        log_stage4.info(f"Timeline extraction completed")
        data = parse_llm_json(text)
    except Exception:
        return TimelineEntry(chapter=chapter_num)

    year_est = data.get("year_estimation", {})
    realm_changes = {}
    for rc in data.get("realm_changes", []):
        char_name = rc.get("character", "")
        to_realm = rc.get("to_realm", "")
        if char_name and to_realm:
            realm_changes[char_name] = to_realm

    time_hints = []
    for tm in data.get("time_mentions", []):
        time_hints.append(tm.get("text", ""))

    return TimelineEntry(
        chapter=chapter_num,
        time_hint="; ".join(time_hints) if time_hints else "",
        estimated_year=year_est.get("estimated_year"),
        year_end=year_est.get("year_end"),
        confidence=year_est.get("confidence", "estimated"),
        realm_changes=realm_changes,
        reasoning=year_est.get("reasoning", ""),
    )


# ============================================================
# Stage 4b: 代价/规则抽取 (与 Stage 2/3/4 并发执行)
# ============================================================

LORE_RULE_PROMPT = """你是《凡人修仙传》世界观规则分析专家。从以下章节原文中提取**隐含的世界观规则**。

规则是指这个世界运行的底层法则、社会规范、修炼原理、战斗规律等。不是具体事件，而是**可复用的通用法则**。

当前章节：第{chapter_num}章 {chapter_title}

【正文】
{content}

## 6 类规则

1. **cultivation_risk** — 修炼风险：强行突破反噬、走火入魔、心魔、丹毒积累、功法冲突、寿元消耗等
2. **social_rule** — 社会规则：以大欺小禁忌、门派等级制度、因果纠缠、散修生存法则、交易规则等
3. **character_rule** — 角色约束：特定身份的行为限制、道侣关系约束、师徒义务等
4. **resource_rule** — 资源规则：灵石经济规律、丹药副作用、法宝认主条件、灵草采集规则等
5. **combat_rule** — 战斗规则：境界压制倍率、法宝等级限制、逃跑成功条件、同阶胜负因素等
6. **world_rule** — 世界法则：天道规则、秘境规律、结界原理、传送限制、寿元上限等

输出**纯JSON**：
{{
  "lore_rules": [
    {{
      "category": "cultivation_risk",
      "sub_category": "强行突破",
      "rule_name": "简短规则名（10字以内）",
      "description": "详细描述这条规则的内容（50-100字）",
      "trigger_condition": "什么情况下触发此规则",
      "consequence_type": "foundation_damage|death|enemy_pursuit|lifespan_cost|power_loss|social_penalty|resource_loss|none",
      "consequence_detail": "具体后果描述",
      "delay_type": "immediate|years_later|realm_trigger|conditional",
      "severity": "low|medium|high|fatal",
      "source_quote": "原文引用（20-50字，证明此规则存在）"
    }}
  ]
}}

规则：
1. 每条规则必须有原文依据（source_quote）
2. 不要编造原文中没有的规则
3. 注重提取**通用规则**而非一次性事件
4. 如果本章没有明显的规则，返回空数组
5. trigger_condition 要具体描述触发时机
6. delay_type 为 conditional 时，trigger_condition 描述条件"""


def extract_lore_rules(chapter_num: int, title: str, content: str) -> list[ExtractedLoreRule]:
    """Stage 4b: 代价/规则抽取（与事件/关系/时间线并发执行）"""
    prompt = LORE_RULE_PROMPT.format(
        chapter_num=chapter_num,
        chapter_title=title,
        content=content[:12000],  # 限制长度
    )

    try:
        text = call_llm(prompt, max_tokens=2048, stage="stage4b_lore_rules")
        if not text or not text.strip():
            log.warning(f"Lore rules extraction returned empty for ch {chapter_num}")
            return []
        data = parse_llm_json(text)
    except Exception as e:
        log.warning(f"Lore rules extraction failed for ch {chapter_num}: {e}")
        return []

    rules = []
    for r in data.get("lore_rules", []):
        name = r.get("rule_name", "").strip()
        if not name:
            continue
        rules.append(ExtractedLoreRule(
            category=r.get("category", "world_rule"),
            sub_category=r.get("sub_category"),
            rule_name=name,
            description=r.get("description", ""),
            trigger_condition=r.get("trigger_condition"),
            consequence_type=r.get("consequence_type"),
            consequence_detail=r.get("consequence_detail"),
            delay_type=r.get("delay_type", "immediate"),
            severity=r.get("severity", "medium"),
            source_chapters=[chapter_num],
            source_quote=r.get("source_quote"),
            confidence=r.get("confidence", "high"),
        ))
    return rules


# ============================================================
# Stage 5: 实体归一
# ============================================================

class EntityNormalizer:
    """实体归一化：别名合并、去重、冲突检测"""

    def __init__(self):
        self.canonical_entities: dict[str, ExtractedEntity] = {}  # name -> entity
        self.alias_map: dict[str, str] = {}  # alias -> canonical_name
        self.all_aliases: dict[str, list[str]] = {}  # canonical -> [aliases]

    def _merge_into(self, existing: ExtractedEntity, entity: ExtractedEntity, canonical_name: str):
        """将新实体信息合并到已有实体"""
        # 合并 aliases
        for alias in entity.aliases:
            if alias and alias not in existing.aliases and alias != canonical_name:
                existing.aliases.append(alias)
                self._register_alias(alias, canonical_name)
        # 新实体的 name 本身也可能成为已有实体的别名
        if entity.name != canonical_name and entity.name not in existing.aliases:
            existing.aliases.append(entity.name)
            self._register_alias(entity.name, canonical_name)
        # 合并 source_quotes
        existing.source_quotes.extend(entity.source_quotes)
        # 更新 first_chapter
        if entity.first_chapter < existing.first_chapter:
            existing.first_chapter = entity.first_chapter
        # 合并 attributes（只填补空缺）
        for k, v in entity.attributes.items():
            if k not in existing.attributes or not existing.attributes[k]:
                existing.attributes[k] = v

    def _register_alias(self, alias: str, canonical_name: str):
        """注册别名，先到先得策略"""
        if not alias:
            return
        if alias in self.alias_map:
            existing_canonical = self.alias_map[alias]
            if existing_canonical != canonical_name:
                log.debug(f"Alias conflict: '{alias}' already maps to '{existing_canonical}', "
                          f"ignoring new mapping to '{canonical_name}'")
            return
        self.alias_map[alias] = canonical_name

    def add_entity(self, entity: ExtractedEntity):
        name = entity.name

        # Step 1: 检查 name 是否是已知别名
        canonical = self.alias_map.get(name)
        if canonical and canonical in self.canonical_entities:
            self._merge_into(self.canonical_entities[canonical], entity, canonical)
            return

        # Step 2: 检查 name 是否已存在同名 canonical
        if name in self.canonical_entities:
            self._merge_into(self.canonical_entities[name], entity, name)
            return

        # Step 3: 检查新实体的 aliases 是否命中已有 canonical
        for alias in entity.aliases:
            if alias in self.canonical_entities:
                log.info(f"Entity '{name}' alias '{alias}' hits existing canonical, merging into '{alias}'")
                self._merge_into(self.canonical_entities[alias], entity, alias)
                return

        # Step 4: 检查新实体的 aliases 是否已在 alias_map 中（指向某个 canonical）
        for alias in entity.aliases:
            if alias in self.alias_map:
                target_canonical = self.alias_map[alias]
                if target_canonical in self.canonical_entities:
                    log.info(f"Entity '{name}' alias '{alias}' maps to '{target_canonical}', merging")
                    self._merge_into(self.canonical_entities[target_canonical], entity, target_canonical)
                    return

        # Step 5: 真正的新实体
        self.canonical_entities[name] = entity
        for alias in entity.aliases:
            self._register_alias(alias, name)

    def resolve_name(self, name: str) -> str:
        """将名称解析为标准名"""
        return self.alias_map.get(name, name)

    def get_all_known_names(self) -> list[str]:
        """获取所有已知实体名（含别名）"""
        names = list(self.canonical_entities.keys())
        names.extend(self.alias_map.keys())
        return names

    def get_entities_by_type(self, entity_type: str) -> list[ExtractedEntity]:
        return [e for e in self.canonical_entities.values() if e.entity_type == entity_type]


# ============================================================
# Stage 6: 跨章聚合
# ============================================================

class CrossChapterAggregator:
    """跨章聚合：生成角色快照、境界时间线、master_timeline"""

    def __init__(self):
        self.chapter_extractions: list[ChapterExtraction] = []
        self.realm_timeline: dict[str, list[dict]] = {}  # char_name -> [{realm, chapter, year}]
        self.chapter_year_map: dict[int, dict] = {}  # chapter -> {year, confidence}
        self.master_events: list[dict] = []
        self.snapshots: list[CharacterSnapshot] = []
        # 新增：功法和装备时间线
        self.techniques_timeline: dict[str, list[dict]] = {}  # char_name -> [{technique, chapter}]
        self.equipment_timeline: dict[str, list[dict]] = {}  # char_name -> [{item_name, item_type, chapter}]

    def add_extraction(self, extraction: ChapterExtraction):
        self.chapter_extractions.append(extraction)

        # 收集境界变化
        if extraction.timeline and extraction.timeline.realm_changes:
            for char_name, realm in extraction.timeline.realm_changes.items():
                if char_name not in self.realm_timeline:
                    self.realm_timeline[char_name] = []
                self.realm_timeline[char_name].append({
                    "realm_stage": realm,
                    "start_chapter": extraction.chapter_num,
                    "start_year": extraction.timeline.estimated_year,
                    "confidence": extraction.timeline.confidence,
                })

        # 收集章节-年份映射
        if extraction.timeline and extraction.timeline.estimated_year is not None:
            self.chapter_year_map[extraction.chapter_num] = {
                "world_year": extraction.timeline.estimated_year,
                "year_end": extraction.timeline.year_end,
                "confidence": extraction.timeline.confidence,
            }

        # 收集功法修炼关系 (MASTERS)
        for rel in extraction.relations:
            if rel.relation_label == "MASTERS" and rel.from_type == "Character" and rel.to_type == "Technique":
                char_name = rel.from_entity
                if char_name not in self.techniques_timeline:
                    self.techniques_timeline[char_name] = []
                # 避免重复
                existing = [t for t in self.techniques_timeline[char_name] if t["technique"] == rel.to_entity]
                if not existing:
                    self.techniques_timeline[char_name].append({
                        "technique": rel.to_entity,
                        "chapter": rel.valid_from_chapter or extraction.chapter_num,
                        "proficiency": rel.attributes.get("proficiency", "mastered"),
                    })

            # 收集装备/法宝持有关系 (OWNS/BONDED_TO)
            elif rel.relation_label in ("OWNS", "BONDED_TO") and rel.from_type == "Character":
                char_name = rel.from_entity
                if char_name not in self.equipment_timeline:
                    self.equipment_timeline[char_name] = []
                existing = [e for e in self.equipment_timeline[char_name] if e["item_name"] == rel.to_entity]
                if not existing:
                    self.equipment_timeline[char_name].append({
                        "item_name": rel.to_entity,
                        "item_type": rel.to_type,  # Artifact/SpiritBeast
                        "chapter": rel.valid_from_chapter or extraction.chapter_num,
                    })

        # 收集 master_timeline 事件
        for ev in extraction.events:
            if ev.event_type in ("realm_breakthrough", "major_battle", "world_event",
                                 "character_death", "faction_event"):
                year = None
                if extraction.timeline:
                    year = extraction.timeline.estimated_year
                self.master_events.append({
                    "event_name": ev.event_name,
                    "event_type": ev.event_type,
                    "event_detail": ev.event_detail,
                    "chapter_start": ev.chapter,
                    "chapter_end": ev.chapter_end,
                    "world_year": year,
                    "primary_character": ev.primary_character,
                    "realm_changes": ev.realm_changes,
                    "location_context": ev.location,
                    "confidence": ev.confidence,
                })

    def generate_snapshots(self, normalizer: EntityNormalizer) -> list[CharacterSnapshot]:
        """为主要角色生成阶段快照，包含该时期已掌握的功法和装备"""
        characters = normalizer.get_entities_by_type("Character")
        major_chars = [c for c in characters if c.attributes.get("is_major")]
        if not major_chars:
            major_chars = characters[:10]

        snapshots = []
        for char in major_chars:
            realms = self.realm_timeline.get(char.name, [])
            char_techniques = self.techniques_timeline.get(char.name, [])
            char_equipment = self.equipment_timeline.get(char.name, [])

            if not realms:
                # 无境界变化记录，生成单一快照
                # 功法和装备：取所有已知的
                techniques = [t["technique"] for t in char_techniques]
                equipment = {e["item_name"]: e["item_type"] for e in char_equipment}
                spirit_beasts = [e["item_name"] for e in char_equipment if e["item_type"] == "SpiritBeast"]

                snapshots.append(CharacterSnapshot(
                    character_name=char.name,
                    realm_stage="unknown",
                    chapter_start=char.first_chapter,
                    knowledge_cutoff=char.first_chapter,
                    techniques=techniques,
                    equipment=equipment,
                    spirit_beasts=spirit_beasts,
                ))
                continue

            # 按章节排序境界变化
            realms.sort(key=lambda x: x["start_chapter"])
            for i, realm in enumerate(realms):
                start_ch = realm["start_chapter"]
                end_ch = realms[i+1]["start_chapter"] - 1 if i+1 < len(realms) else None

                # 聚合该时期已掌握的功法（first_chapter <= end_ch 或 <= start_ch 若无 end_ch）
                cutoff_ch = end_ch if end_ch else start_ch
                techniques = [t["technique"] for t in char_techniques if t["chapter"] <= cutoff_ch]

                # 聚合该时期持有的装备
                equipment_items = [e for e in char_equipment if e["chapter"] <= cutoff_ch]
                equipment = {e["item_name"]: e["item_type"] for e in equipment_items if e["item_type"] != "SpiritBeast"}
                spirit_beasts = [e["item_name"] for e in equipment_items if e["item_type"] == "SpiritBeast"]

                snapshots.append(CharacterSnapshot(
                    character_name=char.name,
                    realm_stage=realm["realm_stage"],
                    chapter_start=start_ch,
                    chapter_end=end_ch,
                    year_start=realm.get("start_year"),
                    knowledge_cutoff=start_ch,
                    techniques=techniques,
                    equipment=equipment,
                    spirit_beasts=spirit_beasts,
                ))

        self.snapshots = snapshots
        return snapshots


# ============================================================
# DB Writers
# ============================================================

class PGWriter:
    def __init__(self, config: dict, run_id: str):
        self.conn = psycopg2.connect(**config)
        self.conn.autocommit = False
        self.run_id = run_id
        self.entity_cache: dict[str, tuple[str, int]] = {}  # "Type:Name" -> (table, pg_id)

    def close(self):
        self.conn.close()

    def _exec(self, sql: str, params=None):
        with self.conn.cursor() as cur:
            cur.execute(sql, params)

    def _exec_returning(self, sql: str, params=None) -> int:
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
            return row[0] if row else -1

    def _safe_exec(self, savepoint: str, sql: str, params=None) -> int | None:
        """带 savepoint 的安全执行。有 RETURNING 的返回 ID，没有的返回 0"""
        self._exec(f"SAVEPOINT {savepoint}")
        try:
            with self.conn.cursor() as cur:
                cur.execute(sql, params)
                if cur.description:  # 有结果集（RETURNING）
                    row = cur.fetchone()
                    result = row[0] if row else None
                else:
                    result = 0  # 无 RETURNING 的语句（INSERT DO NOTHING 等）
            self._exec(f"RELEASE SAVEPOINT {savepoint}")
            return result
        except Exception as e:
            self._exec(f"ROLLBACK TO SAVEPOINT {savepoint}")
            log.error(f"  DB error ({savepoint}): {e}")
            return None

    # --- 实体写入 ---

    def write_entity(self, entity: ExtractedEntity, chapter_num: int) -> int:
        etype = entity.entity_type
        name = entity.name
        attrs = entity.attributes
        cache_key = f"{etype}:{name}"

        if cache_key in self.entity_cache:
            return self.entity_cache[cache_key][1]

        pg_id = None

        if etype == "Character":
            pg_id = self._safe_exec("ent_sv", """
                INSERT INTO characters (name, gender, first_chapter, is_custom, is_major,
                    worldline_id, extraction_version, extraction_run)
                VALUES (%s, %s, %s, false, %s, 'canon', 1, %s)
                ON CONFLICT (name, worldline_id) DO UPDATE SET
                    gender = COALESCE(EXCLUDED.gender, characters.gender),
                    first_chapter = LEAST(characters.first_chapter, EXCLUDED.first_chapter),
                    updated_at = now()
                RETURNING id
            """, (name, attrs.get("gender", "unknown"), chapter_num,
                  attrs.get("is_major", False), self.run_id))
            if pg_id and pg_id > 0:
                self.entity_cache[cache_key] = ("characters", pg_id)
                # 写别名
                for alias in entity.aliases:
                    self._safe_exec("alias_sv", """
                        INSERT INTO character_aliases (character_id, alias, alias_type, first_chapter, worldline_id)
                        VALUES (%s, %s, 'name', %s, 'canon')
                        ON CONFLICT (character_id, alias, worldline_id) DO NOTHING
                    """, (pg_id, alias, chapter_num))

        elif etype == "Faction":
            pg_id = self._safe_exec("ent_sv", """
                INSERT INTO factions (name, faction_type, first_chapter, description,
                    worldline_id, extraction_version)
                VALUES (%s, %s, %s, %s, 'canon', 1)
                ON CONFLICT (name, worldline_id) DO UPDATE SET
                    faction_type = COALESCE(EXCLUDED.faction_type, factions.faction_type),
                    description = COALESCE(EXCLUDED.description, factions.description),
                    updated_at = now()
                RETURNING id
            """, (name, attrs.get("faction_type"), chapter_num, attrs.get("description", "")))
            if pg_id and pg_id > 0:
                self.entity_cache[cache_key] = ("factions", pg_id)

        elif etype == "Location":
            pg_id = self._safe_exec("ent_sv", """
                INSERT INTO locations (name, location_type, first_chapter, description,
                    worldline_id, extraction_version)
                VALUES (%s, %s, %s, %s, 'canon', 1)
                ON CONFLICT (name, worldline_id) DO UPDATE SET
                    location_type = COALESCE(EXCLUDED.location_type, locations.location_type),
                    description = COALESCE(EXCLUDED.description, locations.description),
                    updated_at = now()
                RETURNING id
            """, (name, attrs.get("location_type"), chapter_num, attrs.get("description", "")))
            if pg_id and pg_id > 0:
                self.entity_cache[cache_key] = ("locations", pg_id)

        elif etype == "Artifact":
            pg_id = self._safe_exec("ent_sv", """
                INSERT INTO items_artifacts (name, item_type, grade, first_chapter, description,
                    worldline_id, extraction_version)
                VALUES (%s, %s, %s, %s, %s, 'canon', 1)
                ON CONFLICT (name, worldline_id) DO UPDATE SET
                    item_type = COALESCE(EXCLUDED.item_type, items_artifacts.item_type),
                    description = COALESCE(EXCLUDED.description, items_artifacts.description),
                    updated_at = now()
                RETURNING id
            """, (name, attrs.get("item_type"), attrs.get("grade"),
                  chapter_num, attrs.get("description", "")))
            if pg_id and pg_id > 0:
                self.entity_cache[cache_key] = ("items_artifacts", pg_id)

        elif etype == "Technique":
            pg_id = self._safe_exec("ent_sv", """
                INSERT INTO techniques (name, technique_type, grade, first_chapter, description,
                    worldline_id, extraction_version)
                VALUES (%s, %s, %s, %s, %s, 'canon', 1)
                ON CONFLICT (name, worldline_id) DO UPDATE SET
                    technique_type = COALESCE(EXCLUDED.technique_type, techniques.technique_type),
                    description = COALESCE(EXCLUDED.description, techniques.description),
                    updated_at = now()
                RETURNING id
            """, (name, attrs.get("technique_type"), attrs.get("grade"),
                  chapter_num, attrs.get("description", "")))
            if pg_id and pg_id > 0:
                self.entity_cache[cache_key] = ("techniques", pg_id)

        elif etype == "SpiritBeast":
            pg_id = self._safe_exec("ent_sv", """
                INSERT INTO spirit_beasts (name, species, grade, first_chapter, description,
                    worldline_id, extraction_version)
                VALUES (%s, %s, %s, %s, %s, 'canon', 1)
                ON CONFLICT (name, worldline_id) DO UPDATE SET
                    species = COALESCE(EXCLUDED.species, spirit_beasts.species),
                    description = COALESCE(EXCLUDED.description, spirit_beasts.description),
                    updated_at = now()
                RETURNING id
            """, (name, attrs.get("species"), attrs.get("grade"),
                  chapter_num, attrs.get("description", "")))
            if pg_id and pg_id > 0:
                self.entity_cache[cache_key] = ("spirit_beasts", pg_id)
        else:
            log.warning(f"Unknown entity type: {etype}")
            return -1

        return pg_id if pg_id and pg_id > 0 else -1

    def write_source_ref(self, target_table: str, target_id: int, sq: dict, chapter_num: int):
        quote = sq.get("quote", "")
        if not quote:
            return
        self._safe_exec("src_sv", """
            INSERT INTO source_refs (target_table, target_id, source_type, source_chapter,
                source_char_start, source_char_end, source_quote, extraction_run)
            VALUES (%s, %s, 'chapter', %s, %s, %s, %s, %s)
            ON CONFLICT (target_table, target_id, source_chapter, source_char_start) DO NOTHING
        """, (target_table, target_id, chapter_num,
              sq.get("char_start", 0), sq.get("char_end", 0),
              quote[:2000], self.run_id))

    def write_event(self, event: ExtractedEvent) -> int | None:
        primary_char_id = None
        cache_key = f"Character:{event.primary_character}"
        if cache_key in self.entity_cache:
            primary_char_id = self.entity_cache[cache_key][1]

        location_id = None
        loc_key = f"Location:{event.location}"
        if loc_key in self.entity_cache:
            location_id = self.entity_cache[loc_key][1]

        return self._safe_exec("ev_sv", """
            INSERT INTO events (event_name, event_type, chapter, chapter_end,
                event_detail, result, primary_character_id, participants, location_id,
                worldline_id, extraction_version)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'canon', 1)
            ON CONFLICT (chapter, event_name, worldline_id) DO UPDATE SET
                event_detail = EXCLUDED.event_detail,
                result = EXCLUDED.result,
                updated_at = now()
            RETURNING id
        """, (event.event_name[:200], event.event_type, event.chapter,
              event.chapter_end, event.event_detail, event.result,
              primary_char_id,
              json.dumps(event.participants, ensure_ascii=False),
              location_id))

    def write_relation(self, rel: ExtractedRelation) -> int | None:
        from_key = f"{rel.from_type}:{rel.from_entity}"
        to_key = f"{rel.to_type}:{rel.to_entity}"
        from_cache = self.entity_cache.get(from_key)
        to_cache = self.entity_cache.get(to_key)
        if not from_cache or not to_cache:
            return None

        from_id = from_cache[1]
        to_id = to_cache[1]

        if rel.relation_label == "RELATION" and rel.from_type == "Character" and rel.to_type == "Character":
            # valid_from_chapter 语义：关系首次出现的章节
            # 用 LEAST() 保留最早的起始章节，避免后续抽取覆盖为更晚的值
            return self._safe_exec("rel_sv", """
                INSERT INTO character_relations (from_character_id, to_character_id,
                    relation_type, valid_from_chapter, valid_until_chapter, attributes,
                    worldline_id, extraction_version)
                VALUES (%s, %s, %s, %s, %s, %s, 'canon', 1)
                ON CONFLICT (from_character_id, to_character_id, relation_type, worldline_id)
                DO UPDATE SET
                    valid_from_chapter = LEAST(character_relations.valid_from_chapter, EXCLUDED.valid_from_chapter),
                    valid_until_chapter = COALESCE(EXCLUDED.valid_until_chapter, character_relations.valid_until_chapter),
                    attributes = character_relations.attributes || EXCLUDED.attributes,
                    updated_at = now()
                RETURNING id
            """, (from_id, to_id, rel.relation_type, rel.valid_from_chapter,
                  rel.valid_until_chapter,
                  json.dumps(rel.attributes, ensure_ascii=False)))

        elif rel.relation_label == "BELONGS_TO" and rel.from_type == "Character" and rel.to_type == "Faction":
            # valid_from_chapter 语义：角色以某个 role 加入/处于该势力的首次记录章节
            # 唯一键包含 role，保留职位历史；同一 role 的重复抽取用 LEAST() 保留最早起始章节
            role = rel.attributes.get("role", "disciple")
            return self._safe_exec("rel_sv", """
                INSERT INTO faction_memberships (character_id, faction_id, role,
                    valid_from_chapter, valid_until_chapter, worldline_id)
                VALUES (%s, %s, %s, %s, %s, 'canon')
                ON CONFLICT (character_id, faction_id, role, worldline_id)
                DO UPDATE SET
                    valid_from_chapter = LEAST(faction_memberships.valid_from_chapter, EXCLUDED.valid_from_chapter),
                    valid_until_chapter = COALESCE(EXCLUDED.valid_until_chapter, faction_memberships.valid_until_chapter),
                    updated_at = now()
                RETURNING id
            """, (from_id, to_id, role, rel.valid_from_chapter, rel.valid_until_chapter))

        elif rel.relation_label in ("OWNS", "BONDED_TO", "CONTROLS"):
            # item_ownerships 表的 character_id 是 FK 到 characters 表
            # 只处理 Character -> Item 的关系，跳过 Faction -> Item 等
            if rel.from_type != "Character":
                log.debug(f"  Skipping item_ownership: from_type={rel.from_type} is not Character")
                return None
            # valid_from_chapter 语义：角色获得物品的首次记录章节
            # 用 LEAST() 保留最早的起始章节
            item_type_map = {"Artifact": "artifact", "SpiritBeast": "spirit_beast", "Puppet": "puppet"}
            item_type = item_type_map.get(rel.to_type, "artifact")
            return self._safe_exec("rel_sv", """
                INSERT INTO item_ownerships (character_id, item_id, item_type,
                    valid_from_chapter, valid_until_chapter, worldline_id)
                VALUES (%s, %s, %s, %s, %s, 'canon')
                ON CONFLICT (character_id, item_id, item_type, worldline_id)
                DO UPDATE SET
                    valid_from_chapter = LEAST(item_ownerships.valid_from_chapter, EXCLUDED.valid_from_chapter),
                    valid_until_chapter = COALESCE(EXCLUDED.valid_until_chapter, item_ownerships.valid_until_chapter),
                    updated_at = now()
                RETURNING id
            """, (from_id, to_id, item_type, rel.valid_from_chapter, rel.valid_until_chapter))

        elif rel.relation_label == "MASTERS" and rel.from_type == "Character" and rel.to_type == "Technique":
            # character_techniques 表：角色→功法修炼关系
            # valid_from_chapter 语义：角色开始学习/掌握该功法的首次记录章节
            proficiency = rel.attributes.get("proficiency", "mastered")
            return self._safe_exec("rel_sv", """
                INSERT INTO character_techniques (character_id, technique_id, relation_type,
                    first_chapter, last_chapter, proficiency, worldline_id, extraction_version)
                VALUES (%s, %s, %s, %s, %s, %s, 'canon', 1)
                ON CONFLICT (character_id, technique_id, worldline_id)
                DO UPDATE SET
                    first_chapter = LEAST(character_techniques.first_chapter, EXCLUDED.first_chapter),
                    last_chapter = COALESCE(EXCLUDED.last_chapter, character_techniques.last_chapter),
                    proficiency = COALESCE(EXCLUDED.proficiency, character_techniques.proficiency),
                    updated_at = now()
                RETURNING id
            """, (from_id, to_id, proficiency, rel.valid_from_chapter,
                  rel.valid_until_chapter, proficiency))

        return None

    # --- Stage 6 数据写入 ---

    def write_character_snapshot(self, snapshot: CharacterSnapshot) -> int | None:
        cache_key = f"Character:{snapshot.character_name}"
        if cache_key not in self.entity_cache:
            return None
        char_id = self.entity_cache[cache_key][1]

        faction_id = None
        if snapshot.faction:
            fk = f"Faction:{snapshot.faction}"
            if fk in self.entity_cache:
                faction_id = self.entity_cache[fk][1]

        location_id = None
        if snapshot.location:
            lk = f"Location:{snapshot.location}"
            if lk in self.entity_cache:
                location_id = self.entity_cache[lk][1]

        return self._safe_exec("snap_sv", """
            INSERT INTO character_snapshots (character_id, realm_stage,
                chapter_start, chapter_end, year_start, year_end,
                knowledge_cutoff, equipment, techniques, spirit_beasts,
                faction_id, location_id, persona_prompt, personality_traits,
                worldline_id, extraction_version)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'canon', 1)
            ON CONFLICT (character_id, realm_stage, worldline_id) DO UPDATE SET
                chapter_end = EXCLUDED.chapter_end,
                year_end = EXCLUDED.year_end,
                equipment = EXCLUDED.equipment,
                techniques = EXCLUDED.techniques,
                updated_at = now()
            RETURNING id
        """, (char_id, snapshot.realm_stage,
              snapshot.chapter_start, snapshot.chapter_end,
              snapshot.year_start, snapshot.year_end,
              snapshot.knowledge_cutoff,
              json.dumps(snapshot.equipment, ensure_ascii=False),
              json.dumps(snapshot.techniques, ensure_ascii=False),
              json.dumps(snapshot.spirit_beasts, ensure_ascii=False),
              faction_id, location_id,
              snapshot.persona_prompt, json.dumps(snapshot.personality_traits, ensure_ascii=False)))

    def write_realm_timeline(self, char_name: str, realm: str,
                             start_chapter: int, end_chapter: int | None,
                             start_year: int | None, confidence: str) -> int | None:
        cache_key = f"Character:{char_name}"
        if cache_key not in self.entity_cache:
            return None
        char_id = self.entity_cache[cache_key][1]

        return self._safe_exec("realm_sv", """
            INSERT INTO character_realm_timeline (character_id, realm_stage,
                start_chapter, start_year, end_chapter, confidence,
                worldline_id)
            VALUES (%s, %s, %s, %s, %s, %s, 'canon')
            ON CONFLICT (character_id, realm_stage, worldline_id) DO UPDATE SET
                start_year = COALESCE(EXCLUDED.start_year, character_realm_timeline.start_year),
                end_chapter = EXCLUDED.end_chapter
            RETURNING id
        """, (char_id, realm, start_chapter, start_year, end_chapter, confidence))

    def write_master_timeline(self, event: dict) -> int | None:
        primary_char_id = None
        if event.get("primary_character"):
            ck = f"Character:{event['primary_character']}"
            if ck in self.entity_cache:
                primary_char_id = self.entity_cache[ck][1]

        event_name = event["event_name"][:200]
        chapter_start = event.get("chapter_start")
        world_year = event.get("world_year")
        if world_year is None:
            return None  # master_timeline 需要年份

        if chapter_start is not None:
            existing_id = self._safe_exec("mt_find_sv", """
                SELECT id
                FROM master_timeline
                WHERE chapter_start = %s AND event_name = %s
                ORDER BY id DESC
                LIMIT 1
            """, (chapter_start, event_name))
            if existing_id:
                return self._safe_exec("mt_upd_sv", """
                    UPDATE master_timeline
                    SET world_year = %s,
                        year_end = %s,
                        chapter_end = %s,
                        event_type = %s,
                        event_detail = %s,
                        primary_character_id = %s,
                        realm_changes = %s,
                        location_context = %s,
                        confidence = %s
                    WHERE id = %s
                    RETURNING id
                """, (world_year, event.get("year_end"), event.get("chapter_end"),
                      event["event_type"], event.get("event_detail", ""),
                      primary_char_id,
                      json.dumps(event.get("realm_changes", {}), ensure_ascii=False),
                      event.get("location_context"),
                      event.get("confidence", "estimated"),
                      existing_id))

        return self._safe_exec("mt_sv", """
            INSERT INTO master_timeline (world_year, year_end,
                chapter_start, chapter_end, event_type, event_name, event_detail,
                primary_character_id, realm_changes, location_context, confidence)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (world_year, event_name) DO UPDATE SET
                year_end = EXCLUDED.year_end,
                chapter_start = COALESCE(EXCLUDED.chapter_start, master_timeline.chapter_start),
                chapter_end = COALESCE(EXCLUDED.chapter_end, master_timeline.chapter_end),
                event_type = EXCLUDED.event_type,
                event_detail = EXCLUDED.event_detail,
                primary_character_id = COALESCE(EXCLUDED.primary_character_id, master_timeline.primary_character_id),
                realm_changes = EXCLUDED.realm_changes,
                location_context = COALESCE(EXCLUDED.location_context, master_timeline.location_context),
                confidence = EXCLUDED.confidence
            RETURNING id
        """, (world_year, event.get("year_end"),
              chapter_start, event.get("chapter_end"),
              event["event_type"], event_name,
              event.get("event_detail", ""),
              primary_char_id,
              json.dumps(event.get("realm_changes", {}), ensure_ascii=False),
              event.get("location_context"),
              event.get("confidence", "estimated")))

    def write_chapter_year_mapping(self, chapter_num: int, year_data: dict) -> int | None:
        return self._safe_exec("cym_sv", """
            INSERT INTO chapter_year_mapping (chapter_num, world_year, year_end, confidence)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (chapter_num) DO UPDATE SET
                world_year = EXCLUDED.world_year,
                year_end = EXCLUDED.year_end
            RETURNING chapter_num
        """, (chapter_num, year_data["world_year"], year_data.get("year_end"),
              year_data.get("confidence", "estimated")))

    def write_lore_rule(self, rule: ExtractedLoreRule) -> int | None:
        """写入代价/规则到 lore_rules 表

        source_chapters 字段是 JSONB 类型，需要用 json.dumps() 转换 Python list
        ON CONFLICT 时使用 JSONB 操作符合并章节列表
        """
        # 将 source_chapters 转为 JSONB 格式（json.dumps 产生的字符串）
        source_chapters_json = json.dumps(rule.source_chapters)
        return self._safe_exec("lr_sv", """
            INSERT INTO lore_rules (
                category, sub_category, rule_name, description,
                trigger_condition, consequence_type, consequence_detail,
                delay_type, severity, source_chapters, source_quote,
                confidence, worldline_id, extraction_run
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, 'canon', %s)
            ON CONFLICT (rule_name, worldline_id) DO UPDATE SET
                description = EXCLUDED.description,
                trigger_condition = COALESCE(EXCLUDED.trigger_condition, lore_rules.trigger_condition),
                consequence_type = COALESCE(EXCLUDED.consequence_type, lore_rules.consequence_type),
                source_chapters = (
                    SELECT jsonb_agg(DISTINCT ch ORDER BY ch)
                    FROM jsonb_array_elements(lore_rules.source_chapters || EXCLUDED.source_chapters) AS ch
                ),
                source_quote = COALESCE(EXCLUDED.source_quote, lore_rules.source_quote)
            RETURNING id
        """, (
            rule.category,
            rule.sub_category,
            rule.rule_name[:200],
            rule.description,
            rule.trigger_condition,
            rule.consequence_type,
            rule.consequence_detail,
            rule.delay_type,
            rule.severity,
            source_chapters_json,  # JSONB 格式的字符串，通过 ::jsonb 转换
            rule.source_quote,
            rule.confidence,
            self.run_id,
        ))

    def write_audit(self, stage: str, chapter_num: int, action: str,
                    target_table: str, target_id: int, status: str, error_msg: str = None):
        self._safe_exec("audit_sv", """
            INSERT INTO extraction_audit_log (run_id, stage, chapter_num, action,
                target_table, target_id, status, error_message, started_at, completed_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now(), now())
        """, (self.run_id, stage, chapter_num, action, target_table,
              target_id or 0, status, error_msg))

    def commit(self):
        self.conn.commit()


class Neo4jWriter:
    def __init__(self, config: dict):
        self.driver = GraphDatabase.driver(config["uri"], auth=(config["user"], config["password"]))

    def close(self):
        self.driver.close()

    def write_node(self, label: str, pg_id: int, name: str, props: dict = None):
        props = props or {}
        prop_set = "".join(f", n.{k} = ${k}" for k in props)
        with self.driver.session() as session:
            session.run(
                f"MERGE (n:{label} {{id: $id}}) "
                f"SET n.name = $name, n.worldline = 'canon'" + prop_set,
                id=pg_id, name=name, **props
            )

    def write_relationship(self, from_label: str, from_id: int,
                           to_label: str, to_id: int,
                           rel_label: str, props: dict = None):
        props = props or {}
        prop_set = ", ".join(f"r.{k} = ${k}" for k in props)
        cypher = (
            f"MATCH (a:{from_label} {{id: $from_id}}) "
            f"MATCH (b:{to_label} {{id: $to_id}}) "
            f"MERGE (a)-[r:{rel_label}]->(b) "
            f"SET r.worldline = 'canon'"
        )
        if prop_set:
            cypher += f", {prop_set}"
        with self.driver.session() as session:
            session.run(cypher, from_id=from_id, to_id=to_id, **props)


class ZillizWriter:
    def __init__(self, config: dict):
        connections.connect(
            alias="default",
            uri=config["uri"],
            token=config["token"],
            db_name=config["db_name"],
        )
        self.event_col = Collection("event_embeddings")
        self.event_col.load()
        self.persona_col = Collection("persona_embeddings")
        self.persona_col.load()
        self.technique_col = Collection("technique_embeddings")
        self.technique_col.load()
        self.text_col = Collection("text_chunks")
        self.text_col.load()

    def close(self):
        connections.disconnect("default")

    def _upsert(self, collection: Collection, pk: str, data: dict):
        """幂等写入：先删后插"""
        collection.delete(expr=f'id == "{pk}"')
        collection.insert([data])

    def write_event_embedding(self, event_id: int, content: str, chapter: int,
                              event_type: str, embedding: list[float]):
        pk = f"event_{event_id}_canon_0"
        self._upsert(self.event_col, pk, {
            "id": pk,
            "embedding": embedding,
            "content": content[:8000],
            "entity_type": "event",
            "entity_id": event_id,
            "worldline_id": "canon",
            "source_chapter": chapter,
            "knowledge_cutoff": chapter,
            "world_year": 0,
            "event_type": event_type,
        })

    def write_persona_embedding(self, char_id: int, realm_stage: str,
                                content: str, chapter: int, embedding: list[float]):
        pk = f"persona_{char_id}_{realm_stage}_canon"
        self._upsert(self.persona_col, pk, {
            "id": pk,
            "embedding": embedding,
            "content": content[:8000],
            "entity_type": "character_persona",
            "entity_id": char_id,
            "realm_stage": realm_stage,
            "worldline_id": "canon",
            "knowledge_cutoff": chapter,
            "source_chapter": chapter,
        })

    def write_technique_embedding(self, tech_id: int, content: str, chapter: int,
                                  technique_type: str, embedding: list[float]):
        pk = f"technique_{tech_id}_canon_0"
        self._upsert(self.technique_col, pk, {
            "id": pk,
            "embedding": embedding,
            "content": content[:8000],
            "entity_type": "technique",
            "entity_id": tech_id,
            "worldline_id": "canon",
            "source_chapter": chapter,
            "technique_type": technique_type or "",
        })

    def write_text_chunk(self, chapter: int, chunk_idx: int,
                         content: str, char_start: int, char_end: int,
                         embedding: list[float]):
        pk = f"chunk_{chapter}_{char_start}_canon"
        self._upsert(self.text_col, pk, {
            "id": pk,
            "embedding": embedding,
            "content": content[:8000],
            "entity_type": "text_chunk",
            "chunk_idx": chunk_idx,
            "worldline_id": "canon",
            "source_chapter": chapter,
            "char_start": char_start,
            "char_end": char_end,
        })


# ============================================================
# Embedding
# ============================================================

def get_embedding(text: str, config: dict = None) -> list[float]:
    """调用 embedding API 获取真实向量"""
    if config is None:
        config = EMBEDDING_CONFIG
    try:
        resp = requests.post(
            f"{config['base_url']}/embeddings",
            headers={
                "Authorization": f"Bearer {config['api_key']}",
                "Content-Type": "application/json",
            },
            json={"input": text[:2000], "model": config["model"]},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["data"][0]["embedding"]
    except Exception as e:
        log.warning(f"Embedding API failed: {e}, using deterministic dummy")
        h = hashlib.sha256(text.encode()).digest()
        vals = [(h[i % len(h)] - 128) / 128.0 for i in range(EMBEDDING_DIM)]
        norm = sum(v*v for v in vals) ** 0.5
        return [v / norm for v in vals] if norm > 0 else vals


# ============================================================
# 中间结果持久化
# ============================================================

def save_stage_output(run_dir: Path, stage: str, chapter_num: int, data: Any):
    """保存阶段中间结果到 JSON 文件"""
    stage_dir = run_dir / stage
    stage_dir.mkdir(parents=True, exist_ok=True)
    filepath = stage_dir / f"chapter_{chapter_num:04d}.json"
    with open(filepath, "w", encoding="utf-8") as f:
        if hasattr(data, '__dataclass_fields__'):
            json.dump(asdict(data), f, ensure_ascii=False, indent=2, default=str)
        elif isinstance(data, list):
            json.dump([asdict(d) if hasattr(d, '__dataclass_fields__') else d for d in data],
                      f, ensure_ascii=False, indent=2, default=str)
        else:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)


def save_aggregated_output(run_dir: Path, name: str, data: Any):
    """保存聚合结果"""
    agg_dir = run_dir / "stage6_aggregated"
    agg_dir.mkdir(parents=True, exist_ok=True)
    filepath = agg_dir / f"{name}.json"
    with open(filepath, "w", encoding="utf-8") as f:
        if isinstance(data, list):
            json.dump([asdict(d) if hasattr(d, '__dataclass_fields__') else d for d in data],
                      f, ensure_ascii=False, indent=2, default=str)
        elif isinstance(data, dict):
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        else:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)


# ============================================================
# 跨库一致性检查
# ============================================================

def cross_db_consistency_check(pg_writer: PGWriter, neo4j_writer, zilliz_writer):
    """检查三库数据一致性"""
    errors = []

    # 1. PG角色 vs Neo4j Character节点
    if neo4j_writer:
        with pg_writer.conn.cursor() as cur:
            cur.execute("SELECT id FROM characters WHERE worldline_id='canon' AND NOT is_deleted")
            pg_ids = {row[0] for row in cur.fetchall()}

        with neo4j_writer.driver.session() as session:
            result = session.run("MATCH (c:Character {worldline:'canon'}) RETURN c.id AS id")
            neo4j_ids = {r["id"] for r in result}

        missing_in_neo4j = pg_ids - neo4j_ids
        extra_in_neo4j = neo4j_ids - pg_ids
        if missing_in_neo4j:
            errors.append(f"PG characters missing in Neo4j: {missing_in_neo4j}")
        if extra_in_neo4j:
            errors.append(f"Extra Neo4j characters not in PG: {extra_in_neo4j}")

    # 2. PG事件 vs Zilliz event_embeddings
    if zilliz_writer:
        with pg_writer.conn.cursor() as cur:
            cur.execute("SELECT id FROM events WHERE worldline_id='canon' AND NOT is_deleted")
            pg_event_ids = {row[0] for row in cur.fetchall()}
        # Zilliz 不方便全量查询，跳过

    for err in errors:
        log.warning(f"[Consistency] {err}")

    return errors


# ============================================================
# 主编排器
# ============================================================

def run_import(start_chapter: int, end_chapter: int, dry_run: bool = False, replay: bool = False):
    global _usage_tracker, _current_chapter

    run_id = str(uuid.uuid4())[:8]
    run_dir = OUTPUT_DIR / f"run_{run_id}"
    run_dir.mkdir(parents=True, exist_ok=True)

    # 初始化日志系统（写到 run 目录）
    setup_logging(run_dir)

    # 初始化 LLM usage tracker
    _usage_tracker = LLMUsageTracker(LLM_CONFIG["model"])

    log.info(f"=== AMO Import Run {run_id} | Chapter {start_chapter}-{end_chapter} | dry_run={dry_run} replay={replay} ===")
    log.info(f"Output dir: {run_dir}")

    # Init normalizer & aggregator
    normalizer = EntityNormalizer()
    aggregator = CrossChapterAggregator()

    # Init DB writers
    pg_writer = PGWriter(PG_CONFIG, run_id)
    neo4j_writer = None
    zilliz_writer = None

    if not dry_run:
        try:
            neo4j_writer = Neo4jWriter(NEO4J_CONFIG)
            log.info("Neo4j connected")
        except Exception as e:
            log.warning(f"Neo4j connection failed (will skip): {e}")

        try:
            zilliz_writer = ZillizWriter(ZILLIZ_CONFIG)
            log.info("Zilliz connected")
        except Exception as e:
            log.warning(f"Zilliz connection failed (will skip): {e}")

    # Stats
    stats = {
        "run_id": run_id,
        "chapters_processed": 0,
        "entities_total": 0,
        "events_total": 0,
        "relations_total": 0,
        "timeline_entries": 0,
        "snapshots_total": 0,
        "errors": 0,
        "entity_breakdown": {},
        "llm_calls": 0,
    }

    # Time anchors for Stage 4
    time_anchors = "Year 0: 韩立出生\nYear ~10: 韩立入七玄门\nYear ~11: 开始修炼长春功"

    # ========== Per-chapter pipeline: Stage 0-4 ==========
    for ch_num in range(start_chapter, end_chapter + 1):
        _current_chapter = ch_num  # 更新当前章节（用于日志 filter）
        log.info(f"--- Chapter {ch_num} ---")

        # Stage 0: 预处理
        try:
            title, content, checksum = read_chapter(ch_num)
        except FileNotFoundError as e:
            log.error(f"Chapter {ch_num}: {e}")
            stats["errors"] += 1
            continue

        if not content.strip():
            log.warning(f"Chapter {ch_num} is empty, skipping")
            continue

        prev_tail = get_chapter_tail(ch_num - 1) if ch_num > start_chapter else ""
        log.info(f"  Stage 0: len={len(content)}, checksum={checksum[:8]}")

        # Stage 1: 实体抽取
        log.info(f"  Stage 1: Entity extraction...")
        try:
            entities = extract_entities(
                ch_num, title, content,
                normalizer.get_all_known_names(), prev_tail
            )
            stats["llm_calls"] += 1
            log.info(f"    → {len(entities)} entities")
        except Exception as e:
            log.error(f"  Stage 1 failed for ch {ch_num}: {e}")
            entities = []
            stats["errors"] += 1

        # 更新归一化器
        for ent in entities:
            normalizer.add_entity(ent)
            etype = ent.entity_type
            stats["entity_breakdown"][etype] = stats["entity_breakdown"].get(etype, 0) + 1

        # Stage 2/3/4/4b: 并发执行（均依赖 Stage 1 的 entities，但彼此独立）
        log.info(f"  Stage 2/3/4/4b: Concurrent extraction (events/relations/timeline/lore_rules)...")
        events: list[ExtractedEvent] = []
        relations: list[ExtractedRelation] = []
        timeline: TimelineEntry = TimelineEntry(chapter=ch_num)
        lore_rules: list[ExtractedLoreRule] = []
        current_time_anchors = time_anchors  # 快照当前值，避免竞态

        def run_stage2():
            return extract_events(ch_num, title, content, entities)

        def run_stage3():
            return extract_relations(ch_num, title, content, entities)

        def run_stage4():
            return extract_timeline(ch_num, title, content, current_time_anchors)

        def run_stage4b():
            return extract_lore_rules(ch_num, title, content)

        with ThreadPoolExecutor(max_workers=4) as executor:
            future_events = executor.submit(run_stage2)
            future_relations = executor.submit(run_stage3)
            future_timeline = executor.submit(run_stage4)
            future_lore_rules = executor.submit(run_stage4b)

            # 收集 Stage 2 结果
            try:
                events = future_events.result()
                stats["llm_calls"] += 1
                log.info(f"    Stage 2 → {len(events)} events")
                log_stage2.info(f"Extracted {len(events)} events: {[e.event_name for e in events[:5]]}")
            except Exception as e:
                log.error(f"  Stage 2 failed for ch {ch_num}: {e}")
                log_stage2.error(f"Stage 2 failed: {e}")
                stats["errors"] += 1

            # 收集 Stage 3 结果
            try:
                relations = future_relations.result()
                relations = normalize_relations(relations, normalizer, entities)
                stats["llm_calls"] += 1
                log.info(f"    Stage 3 → {len(relations)} relations")
                log_stage3.info(f"Extracted {len(relations)} relations")
            except Exception as e:
                log.error(f"  Stage 3 failed for ch {ch_num}: {e}")
                log_stage3.error(f"Stage 3 failed: {e}")
                stats["errors"] += 1

            # 收集 Stage 4 结果
            try:
                timeline = future_timeline.result()
                stats["llm_calls"] += 1
                if timeline.estimated_year is not None:
                    stats["timeline_entries"] += 1
                    # 更新 time_anchors（串行更新，避免竞态）
                    time_anchors += f"\nYear ~{timeline.estimated_year}: 第{ch_num}章 {title}"
                if timeline.realm_changes:
                    log.info(f"    Stage 4 → realm changes: {timeline.realm_changes}")
                    log_stage4.info(f"Realm changes: {timeline.realm_changes}")
                else:
                    log.info(f"    Stage 4 → timeline extracted")
                log_stage4.info(f"Year estimate: {timeline.estimated_year}, time_hint: {timeline.time_hint[:50] if timeline.time_hint else 'none'}")
            except Exception as e:
                log.error(f"  Stage 4 failed for ch {ch_num}: {e}")
                log_stage4.error(f"Stage 4 failed: {e}")
                stats["errors"] += 1

            # 收集 Stage 4b 结果（代价/规则）
            try:
                lore_rules = future_lore_rules.result()
                stats["llm_calls"] += 1
                log.info(f"    Stage 4b → {len(lore_rules)} lore rules")
                if "lore_rules_total" not in stats:
                    stats["lore_rules_total"] = 0
                stats["lore_rules_total"] += len(lore_rules)
            except Exception as e:
                log.error(f"  Stage 4b failed for ch {ch_num}: {e}")
                stats["errors"] += 1

        # 组装章节抽取结果
        extraction = ChapterExtraction(
            chapter_num=ch_num,
            chapter_title=title,
            checksum=checksum,
            entities=entities,
            events=events,
            relations=relations,
            timeline=timeline,
            lore_rules=lore_rules,
        )

        # 保存中间结果
        save_stage_output(run_dir, "stage1_entities", ch_num, entities)
        save_stage_output(run_dir, "stage2_events", ch_num, events)
        save_stage_output(run_dir, "stage3_relations", ch_num, relations)
        save_stage_output(run_dir, "stage4_timeline", ch_num, timeline)
        save_stage_output(run_dir, "stage4b_lore_rules", ch_num, lore_rules)

        # Stage 5: 实体归一（持续更新）
        # normalizer 在 Stage 1 后已持续更新

        # 聚合器收集
        aggregator.add_extraction(extraction)

        stats["chapters_processed"] += 1
        stats["entities_total"] += len(entities)
        stats["events_total"] += len(events)
        stats["relations_total"] += len(relations)

        if dry_run:
            log.info(f"  [dry-run] Chapter {ch_num} done")
            continue

        # ========== Stage 7: 三库写入（per-chapter） ==========

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

                pg_writer.write_audit("entity", ch_num, "insert", table, pg_id, "completed")

        # 7b. PG 事件
        for event in events:
            ev_id = pg_writer.write_event(event)
            if ev_id and ev_id > 0:
                for sq in event.source_quotes:
                    pg_writer.write_source_ref("events", ev_id, sq, ch_num)

                # Neo4j 事件节点
                if neo4j_writer:
                    neo4j_writer.write_node("Event", ev_id, event.event_name, {
                        "event_type": event.event_type,
                        "chapter": ch_num,
                    })

                # Zilliz 事件向量
                if zilliz_writer:
                    embed_text = f"{event.event_name}: {event.event_detail}"
                    embedding = get_embedding(embed_text)
                    zilliz_writer.write_event_embedding(ev_id, embed_text, ch_num, event.event_type, embedding)

                pg_writer.write_audit("event", ch_num, "insert", "events", ev_id, "completed")

        # 7c. PG 关系
        for rel in relations:
            rel_id = pg_writer.write_relation(rel)

            # Neo4j 关系
            if neo4j_writer and rel_id and rel_id > 0:
                from_key = f"{rel.from_type}:{rel.from_entity}"
                to_key = f"{rel.to_type}:{rel.to_entity}"
                from_cache = pg_writer.entity_cache.get(from_key)
                to_cache = pg_writer.entity_cache.get(to_key)
                if from_cache and to_cache:
                    rel_props = {"since_chapter": rel.valid_from_chapter}
                    if rel.relation_type:
                        rel_props["type"] = rel.relation_type
                    if rel.valid_until_chapter:
                        rel_props["until_chapter"] = rel.valid_until_chapter
                    neo4j_writer.write_relationship(
                        rel.from_type, from_cache[1],
                        rel.to_type, to_cache[1],
                        rel.relation_label, rel_props
                    )

            if rel_id and rel_id > 0:
                table = "character_relations"
                if rel.relation_label == "BELONGS_TO":
                    table = "faction_memberships"
                elif rel.relation_label in ("OWNS", "BONDED_TO", "CONTROLS"):
                    table = "item_ownerships"
                for sq in rel.source_quotes:
                    pg_writer.write_source_ref(table, rel_id, sq, ch_num)

        # 7d. PG 代价/规则 (新增)
        for rule in lore_rules:
            rule_id = pg_writer.write_lore_rule(rule)
            if rule_id and rule_id > 0:
                pg_writer.write_audit("lore_rule", ch_num, "insert", "lore_rules", rule_id, "completed")

        # Commit per chapter
        try:
            pg_writer.commit()
        except Exception as e:
            log.error(f"  PG commit error for ch {ch_num}: {e}")
            pg_writer.conn.rollback()
            stats["errors"] += 1

        log.info(f"  Chapter {ch_num} committed. Running totals: "
                 f"E={stats['entities_total']} Ev={stats['events_total']} R={stats['relations_total']}")

    # ========== Stage 6: 跨章聚合 ==========
    log.info("=== Stage 6: Cross-chapter aggregation ===")

    # 6a. 角色快照
    snapshots = aggregator.generate_snapshots(normalizer)
    stats["snapshots_total"] = len(snapshots)
    save_aggregated_output(run_dir, "snapshots", snapshots)
    log.info(f"  Generated {len(snapshots)} character snapshots")

    # 6b. 境界时间线
    save_aggregated_output(run_dir, "realm_timeline", aggregator.realm_timeline)
    log.info(f"  Realm timeline: {len(aggregator.realm_timeline)} characters")

    # 6c. 章节年份映射
    save_aggregated_output(run_dir, "chapter_year_map", aggregator.chapter_year_map)
    log.info(f"  Chapter-year map: {len(aggregator.chapter_year_map)} entries")

    # 6d. Master timeline
    save_aggregated_output(run_dir, "master_timeline", aggregator.master_events)
    log.info(f"  Master timeline: {len(aggregator.master_events)} events")

    # 6e. 归一化实体汇总
    all_entities = list(normalizer.canonical_entities.values())
    save_aggregated_output(run_dir, "entities_normalized", all_entities)
    save_aggregated_output(run_dir, "alias_map", normalizer.alias_map)
    log.info(f"  Normalized entities: {len(all_entities)}, alias map: {len(normalizer.alias_map)}")

    if not dry_run:
        # ========== Stage 7 续: 写入聚合数据 ==========
        log.info("=== Stage 7: Writing aggregated data ===")

        # 写角色快照到 PG
        for snap in snapshots:
            snap_id = pg_writer.write_character_snapshot(snap)
            if snap_id and snap_id > 0:
                # Zilliz persona embedding
                if zilliz_writer:
                    ck = f"Character:{snap.character_name}"
                    if ck in pg_writer.entity_cache:
                        char_id = pg_writer.entity_cache[ck][1]
                        persona_text = f"{snap.character_name} {snap.realm_stage}: {snap.persona_prompt}" if snap.persona_prompt else f"{snap.character_name} {snap.realm_stage}"
                        embedding = get_embedding(persona_text)
                        zilliz_writer.write_persona_embedding(
                            char_id, snap.realm_stage, persona_text,
                            snap.chapter_start, embedding
                        )

        # 写境界时间线到 PG
        for char_name, realms in aggregator.realm_timeline.items():
            for i, realm in enumerate(realms):
                end_ch = realms[i+1]["start_chapter"] - 1 if i+1 < len(realms) else None
                pg_writer.write_realm_timeline(
                    char_name, realm["realm_stage"],
                    realm["start_chapter"], end_ch,
                    realm.get("start_year"),
                    realm.get("confidence", "estimated"),
                )

        # 写 master_timeline 到 PG
        for mt_event in aggregator.master_events:
            pg_writer.write_master_timeline(mt_event)

        # 写 chapter_year_mapping 到 PG
        for ch, year_data in aggregator.chapter_year_map.items():
            pg_writer.write_chapter_year_mapping(ch, year_data)

        # 写 technique embeddings
        if zilliz_writer:
            for tech in normalizer.get_entities_by_type("Technique"):
                tk = f"Technique:{tech.name}"
                if tk in pg_writer.entity_cache:
                    tech_id = pg_writer.entity_cache[tk][1]
                    tech_text = f"{tech.name}: {tech.attributes.get('description', '')}"
                    embedding = get_embedding(tech_text)
                    zilliz_writer.write_technique_embedding(
                        tech_id, tech_text, tech.first_chapter,
                        tech.attributes.get("technique_type", ""), embedding
                    )

        # Final commit
        try:
            pg_writer.commit()
            log.info("  Aggregated data committed")
        except Exception as e:
            log.error(f"  Aggregated data commit error: {e}")
            pg_writer.conn.rollback()
            stats["errors"] += 1

        # ========== 跨库一致性检查 ==========
        log.info("=== Cross-DB consistency check ===")
        consistency_errors = cross_db_consistency_check(pg_writer, neo4j_writer, zilliz_writer)
        if consistency_errors:
            log.warning(f"  Found {len(consistency_errors)} consistency issues")
        else:
            log.info("  All consistent!")

    # Cleanup
    pg_writer.close()
    if neo4j_writer:
        neo4j_writer.close()
    if zilliz_writer:
        zilliz_writer.close()

    # 保存 LLM usage 统计
    _current_chapter = 0  # 重置
    if _usage_tracker:
        llm_usage_file = run_dir / "llm_usage.json"
        _usage_tracker.save_to_file(llm_usage_file)
        usage_summary = _usage_tracker.get_summary()["summary"]
        log.info(f"=== LLM Usage Summary ===")
        log.info(f"  Total calls: {usage_summary['total_calls']}")
        log.info(f"  Input tokens: {usage_summary['total_input_tokens']:,}")
        log.info(f"  Output tokens: {usage_summary['total_output_tokens']:,}")
        log.info(f"  Total tokens: {usage_summary['total_tokens']:,}")
        log.info(f"  Estimated price: ${usage_summary['total_price_usd']:.4f}")
        if usage_summary['unavailable_calls'] > 0:
            log.info(f"  (Note: {usage_summary['unavailable_calls']} calls had no usage info)")

    # Final stats
    stats["completed_at"] = datetime.now().isoformat()
    stats["start_chapter"] = start_chapter
    stats["end_chapter"] = end_chapter
    stats["known_characters"] = [e.name for e in normalizer.get_entities_by_type("Character")]

    # 添加 LLM usage 到 stats
    if _usage_tracker:
        stats["llm_usage"] = _usage_tracker.get_summary()["summary"]

    log.info(f"=== Import Complete ===")
    log.info(f"Stats: {json.dumps(stats, ensure_ascii=False, indent=2)}")

    # Write stats
    stats_file = Path(__file__).parent / "import_stats.json"
    with open(stats_file, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

    # Write run summary to output dir
    summary_file = run_dir / "run_summary.json"
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

    return stats


# ============================================================
# CLI
# ============================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AMO Novel Import Pipeline v2.0")
    parser.add_argument("--start", type=int, default=1, help="Start chapter")
    parser.add_argument("--end", type=int, default=50, help="End chapter")
    parser.add_argument("--dry-run", action="store_true", help="Extract only, don't write to DB")
    parser.add_argument("--replay", action="store_true", help="Replay mode: re-extract specified chapters")
    args = parser.parse_args()

    run_import(args.start, args.end, args.dry_run, args.replay)
