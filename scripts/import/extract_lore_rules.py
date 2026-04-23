#!/usr/bin/env python3
"""
AMO Lore Rules Extraction Script
从凡人修仙传前150章中提取世界观规则，写入 PG lore_rules 表。

6 类规则：
1. cultivation_risk  - 修炼风险（强行突破反噬、心魔、丹毒等）
2. social_rule       - 社会规则（以大欺小禁忌、尊卑礼仪、因果纠缠等）
3. character_rule    - 角色约束（鼎炉、双修、血脉等特殊约束）
4. resource_rule     - 资源规则（灵石经济、禁物代价、装备限制等）
5. combat_rule       - 战斗规则（境界碾压、跨境代价、逃跑机制等）
6. world_rule        - 世界法则（天劫、秘境、契约、地域治理等）
"""

import hashlib
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path

import psycopg2
import requests

# ── Config ──────────────────────────────────────────────────

LLM_CONFIG = {
    "base_url": os.environ.get("LLM_BASE_URL", "http://localhost:8001/v1"),
    "api_key": os.environ.get("LLM_API_KEY", ""),
    "model": os.environ.get("LLM_MODEL", "gemini-3.1-pro-preview"),
}

PG_CONFIG = {
    "host": os.environ.get("AMO_PG_HOST", "localhost"),
    "port": int(os.environ.get("AMO_PG_PORT", "5432")),
    "user": os.environ.get("AMO_PG_USER", "postgres"),
    "password": os.environ.get("AMO_PG_PASSWORD", "postgres"),
    "dbname": os.environ.get("AMO_PG_DB", "amo_canon"),
    "options": os.environ.get("AMO_PG_OPTIONS", "-csearch_path=amo"),
}

CHAPTERS_DIR = Path(__file__).parent.parent.parent / "book" / "chapters"
OUTPUT_DIR = Path(__file__).parent / "output"
RUN_ID = str(uuid.uuid4())[:8]

# ── Chapter Reader ──────────────────────────────────────────

def read_chapter(chapter_num: int) -> str | None:
    pattern = f"{chapter_num:04d}_"
    for f in sorted(CHAPTERS_DIR.iterdir()):
        if f.name.startswith(pattern) and f.suffix == ".txt":
            # Skip continuation files (ending with " 2.txt", " 3.txt")
            if re.search(r" \d+\.txt$", f.name):
                continue
            content = f.read_text(encoding="utf-8", errors="replace")
            content = content.replace("\ufeff", "").replace("\u200b", "")
            content = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", content)
            return content.strip()
    return None


def read_chapter_batch(start: int, end: int) -> str:
    """Read multiple chapters as one text block for better context."""
    texts = []
    for ch in range(start, end + 1):
        text = read_chapter(ch)
        if text:
            lines = text.split("\n", 1)
            title = lines[0].strip()
            body = lines[1].strip() if len(lines) > 1 else ""
            texts.append(f"=== 第{ch}章 {title} ===\n{body}")
    return "\n\n".join(texts)


# ── LLM Call ────────────────────────────────────────────────

def call_llm(prompt: str, max_tokens: int = 8192) -> str:
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
                    "max_tokens": max_tokens,
                    "temperature": 0.1,
                },
                timeout=180,
            )
            if resp.status_code == 200:
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                usage = data.get("usage", {})
                print(f"    tokens: {usage.get('prompt_tokens', '?')}/{usage.get('completion_tokens', '?')}")
                return content
            else:
                print(f"    LLM error {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            print(f"    LLM exception: {e}")
        time.sleep(3 * (attempt + 1))
    return ""


def parse_json_from_llm(text: str) -> list[dict]:
    # Find JSON array in response
    match = re.search(r"\[[\s\S]*\]", text)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    # Try line-by-line JSON objects
    results = []
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                results.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return results


# ── Extraction Prompt ───────────────────────────────────────

EXTRACTION_PROMPT = """你是《凡人修仙传》世界观规则分析专家。请从以下章节原文中提取**隐含的世界观规则**。

规则是指这个世界运行的底层法则、社会规范、修炼原理、战斗规律等。不是具体事件，而是**可复用的通用法则**。

## 6 类规则

1. **cultivation_risk** — 修炼风险：强行突破反噬、走火入魔、心魔、丹毒积累、功法冲突、寿元消耗等
2. **social_rule** — 社会规则：以大欺小禁忌、门派等级制度、因果纠缠、散修生存法则、交易规则等
3. **character_rule** — 角色约束：特定身份的行为限制、道侣关系约束、师徒义务等
4. **resource_rule** — 资源规则：灵石经济规律、丹药副作用、法宝认主条件、灵草采集规则等
5. **combat_rule** — 战斗规则：境界压制倍率、法宝等级限制、逃跑成功条件、同阶胜负因素等
6. **world_rule** — 世界法则：天道规则、秘境规律、结界原理、传送限制、寿元上限等

## 输出要求

返回 JSON 数组，每条规则包含：
```json
[
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
    "source_chapters": [章节号],
    "source_quote": "原文引用（20-50字，证明此规则存在）"
  }}
]
```

## 重要
- 每条规则必须有原文依据（source_quote）
- 不要编造原文中没有的规则
- 注重提取**通用规则**而非一次性事件
- 同一规则只提取一次，取最佳原文引用
- 尽可能多提取，不要遗漏

## 原文

{text}

请提取所有能找到的世界观规则，以 JSON 数组格式返回："""


# ── Extraction Pipeline ─────────────────────────────────────

def extract_rules_from_batch(start_ch: int, end_ch: int) -> list[dict]:
    """Extract lore rules from a batch of chapters."""
    print(f"  Reading chapters {start_ch}-{end_ch}...")
    text = read_chapter_batch(start_ch, end_ch)
    if not text:
        print(f"    No text found for chapters {start_ch}-{end_ch}")
        return []

    # Truncate if too long (keep ~60K chars for context window)
    if len(text) > 60000:
        text = text[:60000] + "\n...(截断)"

    prompt = EXTRACTION_PROMPT.format(text=text)
    print(f"  Calling LLM for chapters {start_ch}-{end_ch} ({len(text)} chars)...")
    response = call_llm(prompt)
    if not response:
        print(f"    No response for chapters {start_ch}-{end_ch}")
        return []

    rules = parse_json_from_llm(response)
    print(f"    Extracted {len(rules)} rules from chapters {start_ch}-{end_ch}")
    return rules


def deduplicate_rules(all_rules: list[dict]) -> list[dict]:
    """Deduplicate rules by name similarity."""
    seen = {}
    for rule in all_rules:
        name = rule.get("rule_name", "").strip()
        if not name:
            continue
        # Simple dedup by exact name
        key = name.lower()
        if key not in seen:
            seen[key] = rule
        else:
            # Merge source_chapters
            existing = seen[key]
            existing_chs = set(existing.get("source_chapters", []))
            new_chs = set(rule.get("source_chapters", []))
            existing["source_chapters"] = sorted(existing_chs | new_chs)
    return list(seen.values())


# ── PG Writer ───────────────────────────────────────────────

def write_rules_to_pg(rules: list[dict]):
    """Write extracted rules to PostgreSQL lore_rules table."""
    conn = psycopg2.connect(**PG_CONFIG)
    cur = conn.cursor()
    written = 0
    skipped = 0

    for rule in rules:
        try:
            cur.execute("SAVEPOINT rule_write")
            cur.execute("""
                INSERT INTO lore_rules (
                    category, sub_category, rule_name, description,
                    trigger_condition, consequence_type, consequence_detail,
                    delay_type, severity, source_chapters, source_quote,
                    confidence, worldline_id, extraction_run
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'canon', %s)
                ON CONFLICT (rule_name, worldline_id) DO UPDATE SET
                    description = EXCLUDED.description,
                    source_chapters = EXCLUDED.source_chapters,
                    source_quote = COALESCE(EXCLUDED.source_quote, lore_rules.source_quote)
                RETURNING id
            """, (
                rule.get("category", "world_rule"),
                rule.get("sub_category"),
                rule.get("rule_name", "unknown"),
                rule.get("description", ""),
                rule.get("trigger_condition"),
                rule.get("consequence_type"),
                rule.get("consequence_detail"),
                rule.get("delay_type", "immediate"),
                rule.get("severity", "medium"),
                json.dumps(rule.get("source_chapters", []), ensure_ascii=False),
                rule.get("source_quote"),
                "high",
                RUN_ID,
            ))
            cur.execute("RELEASE SAVEPOINT rule_write")
            written += 1
        except Exception as e:
            cur.execute("ROLLBACK TO SAVEPOINT rule_write")
            skipped += 1
            print(f"    Skip rule '{rule.get('rule_name', '?')}': {e}")

    conn.commit()
    conn.close()
    print(f"  PG: {written} written, {skipped} skipped")
    return written


# ── Main ────────────────────────────────────────────────────

def main():
    print(f"=== AMO Lore Rules Extraction ===")
    print(f"Run ID: {RUN_ID}")
    print(f"Chapters: 1-150, batch size: 10")
    print()

    # Output dir
    run_dir = OUTPUT_DIR / f"lore_rules_{RUN_ID}"
    run_dir.mkdir(parents=True, exist_ok=True)

    all_rules = []

    # Process in batches of 10 chapters
    for batch_start in range(1, 151, 10):
        batch_end = min(batch_start + 9, 150)
        print(f"\n[Batch {batch_start}-{batch_end}]")

        rules = extract_rules_from_batch(batch_start, batch_end)

        # Save batch output
        batch_file = run_dir / f"rules_ch{batch_start:03d}_{batch_end:03d}.json"
        with open(batch_file, "w", encoding="utf-8") as f:
            json.dump(rules, f, ensure_ascii=False, indent=2)

        all_rules.extend(rules)
        print(f"  Cumulative: {len(all_rules)} rules")

        # Rate limit between batches
        time.sleep(2)

    # Deduplicate
    print(f"\n=== Deduplication ===")
    print(f"  Before: {len(all_rules)} rules")
    unique_rules = deduplicate_rules(all_rules)
    print(f"  After:  {len(unique_rules)} rules")

    # Save final output
    final_file = run_dir / "all_rules_deduped.json"
    with open(final_file, "w", encoding="utf-8") as f:
        json.dump(unique_rules, f, ensure_ascii=False, indent=2)

    # Category breakdown
    from collections import Counter
    cats = Counter(r.get("category", "unknown") for r in unique_rules)
    print(f"\n  Category breakdown:")
    for cat, count in cats.most_common():
        print(f"    {cat}: {count}")

    # Write to PG
    print(f"\n=== Writing to PostgreSQL ===")
    written = write_rules_to_pg(unique_rules)

    # Summary
    print(f"\n=== Summary ===")
    print(f"  Run ID: {RUN_ID}")
    print(f"  Chapters processed: 1-150")
    print(f"  Total rules extracted: {len(all_rules)}")
    print(f"  Unique rules: {len(unique_rules)}")
    print(f"  Written to PG: {written}")
    print(f"  Output: {run_dir}")

    # Save summary
    summary = {
        "run_id": RUN_ID,
        "chapters": "1-150",
        "total_extracted": len(all_rules),
        "unique_rules": len(unique_rules),
        "written_to_pg": written,
        "categories": dict(cats),
    }
    with open(run_dir / "summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
