#!/usr/bin/env python3
"""
批量生成全书时间窗口（跳过已处理的 700-1000 章）
"""

import asyncio
import json
import os
import re
import sys
from collections import defaultdict

import asyncpg
import httpx

PG_DSN = os.getenv("PG_DSN", "postgresql://postgres:postgres@localhost:5432/amo_canon")

LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:8001/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen3.5-plus")


async def get_events_in_range(conn, start_chapter: int, end_chapter: int) -> dict[int, list[str]]:
    rows = await conn.fetch("""
        SELECT chapter, event_name
        FROM events
        WHERE chapter >= $1 AND chapter <= $2
          AND worldline_id = 'canon' AND is_deleted = false
        ORDER BY chapter, id
    """, start_chapter, end_chapter)

    events_by_chapter: dict[int, list[str]] = defaultdict(list)
    for r in rows:
        events_by_chapter[r["chapter"]].append(r["event_name"])
    return dict(events_by_chapter)


async def llm_generate_windows(events_by_chapter: dict[int, list[str]], start_chapter: int, end_chapter: int) -> list[dict]:
    events_text = ""
    for ch in sorted(events_by_chapter.keys()):
        events = events_by_chapter[ch]
        events_text += f"\n第{ch}章:\n"
        for e in events:
            events_text += f"  - {e}\n"

    prompt = f"""你是《凡人修仙传》的剧情分析专家。请根据以下章节的事件列表，将其划分为合理的"时间窗口"（剧情段落）。

## 章节范围
第{start_chapter}章 ~ 第{end_chapter}章

## 事件列表
{events_text}

## 划分要求
1. 每个时间窗口应该是一个完整的剧情单元（如：一次冒险、一场战斗、一段修炼、一次相遇等）
2. 每个窗口控制在 8-20 章，不要太细也不要太粗
3. 窗口描述要概括整个段落的核心剧情，不是某一章的事件
4. 描述格式："地点/背景·核心事件"，控制在 15 字以内
5. 在重要剧情转折点切分（如：地点变化、主线任务变化、重要人物出场/离场）

## 输出格式
返回 JSON 数组，每个元素包含：
- chapter_start: 起始章节
- chapter_end: 结束章节
- description: 剧情概括（15字以内）
- key_events: 该段的2-3个关键事件名

只返回 JSON 数组，不要其他内容。"""

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{LLM_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {LLM_API_KEY}"},
            json={
                "model": LLM_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 4096,
                "temperature": 0.3,
            },
        )

    if resp.status_code != 200:
        print(f"LLM error: {resp.status_code} - {resp.text}")
        return []

    content = resp.json()["choices"][0]["message"]["content"]

    match = re.search(r'\[[\s\S]*\]', content)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError as e:
            print(f"JSON parse error: {e}")
            return []

    print(f"No JSON found in response")
    return []


async def process_range(conn, range_start: int, range_end: int, output_file: str):
    """处理一个章节范围"""
    print(f"\n{'='*60}")
    print(f"处理 {range_start}-{range_end} 章")
    print(f"{'='*60}")

    events = await get_events_in_range(conn, range_start, range_end)
    print(f"共 {sum(len(v) for v in events.values())} 个事件，覆盖 {len(events)} 个章节")

    all_windows = []
    batch_size = 50

    for batch_start in range(range_start, range_end + 1, batch_size):
        batch_end = min(batch_start + batch_size - 1, range_end)
        print(f"  处理 {batch_start}-{batch_end} 章...")

        batch_events = {ch: evts for ch, evts in events.items()
                       if batch_start <= ch <= batch_end}

        if not batch_events:
            print(f"    无事件数据，跳过")
            continue

        windows = await llm_generate_windows(batch_events, batch_start, batch_end)
        all_windows.extend(windows)
        print(f"    生成 {len(windows)} 个窗口")

    # 保存到文件
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(all_windows, f, ensure_ascii=False, indent=2)

    print(f"\n{range_start}-{range_end} 章生成 {len(all_windows)} 个窗口，保存到 {output_file}")
    return all_windows


async def main():
    if not LLM_API_KEY:
        print("错误: 未找到 LLM_API_KEY")
        return

    conn = await asyncpg.connect(PG_DSN)
    await conn.execute("SET search_path TO amo")
    print("已连接数据库")

    # 要处理的范围（跳过已处理的 700-1000）
    ranges = [
        (1, 200),
        (201, 400),
        (401, 600),
        (601, 699),
        (1001, 1100),
        (1101, 1200),
        (1201, 1261),
    ]

    all_results = {}

    for range_start, range_end in ranges:
        output_file = f"/Users/tt/code/myproject/AMO/scripts/import/time_windows_{range_start}_{range_end}.json"
        windows = await process_range(conn, range_start, range_end, output_file)
        all_results[(range_start, range_end)] = windows

    await conn.close()

    # 汇总
    print("\n" + "=" * 60)
    print("汇总")
    print("=" * 60)
    total = 0
    for (s, e), windows in all_results.items():
        print(f"  {s:4d}-{e:4d}: {len(windows):3d} 个窗口")
        total += len(windows)
    print(f"  总计: {total} 个窗口（不含已处理的 700-1000 章）")


if __name__ == "__main__":
    asyncio.run(main())
