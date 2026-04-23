#!/usr/bin/env python3
"""
使用 LLM 基于事件列表生成时间窗口划分和描述。
"""

import asyncio
import json
import logging
import os
from collections import defaultdict

import asyncpg
import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

PG_DSN = os.getenv("PG_DSN", "postgresql://postgres:postgres@localhost:5432/amo_canon")

# LLM 配置
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:8001/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen3.5-plus")


async def get_events_in_range(conn, start_chapter: int, end_chapter: int) -> dict[int, list[str]]:
    """获取指定章节范围的事件，按章节分组"""
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
    """调用 LLM 生成时间窗口划分"""

    # 构建事件文本
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

示例：
[
  {{"chapter_start": 700, "chapter_end": 709, "description": "玉矶阁混战·获苍坤遗宝", "key_events": ["韩立与南陇侯联手破禁", "韩立获苍坤遗宝"]}},
  {{"chapter_start": 710, "chapter_end": 718, "description": "掩月宗·救南宫婉", "key_events": ["韩立潜入掩月宗", "韩立南宫婉联手围攻"]}}
]

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
        log.error(f"LLM error: {resp.status_code} - {resp.text}")
        return []

    content = resp.json()["choices"][0]["message"]["content"]

    # 解析 JSON
    import re
    # 尝试找到 JSON 数组
    match = re.search(r'\[[\s\S]*\]', content)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError as e:
            log.error(f"JSON parse error: {e}")
            log.error(f"Content: {content}")
            return []

    log.error(f"No JSON found in response: {content}")
    return []


async def main():
    global LLM_API_KEY

    # 从环境变量或 .env 读取 API key
    if not LLM_API_KEY:
        # 尝试从 server/.env 读取
        env_path = "/Users/tt/code/myproject/AMO/server/.env"
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    if line.startswith("LLM_API_KEY="):
                        os.environ["LLM_API_KEY"] = line.split("=", 1)[1].strip().strip('"')
                        break

    LLM_API_KEY = os.getenv("LLM_API_KEY", "")

    if not LLM_API_KEY:
        log.error("需要设置 LLM_API_KEY 环境变量")
        return

    conn = await asyncpg.connect(PG_DSN)
    await conn.execute("SET search_path TO amo")
    log.info("已连接数据库")

    try:
        # 处理 700-900 章
        start, end = 700, 900
        log.info(f"获取 {start}-{end} 章的事件...")

        events = await get_events_in_range(conn, start, end)
        log.info(f"共 {sum(len(v) for v in events.values())} 个事件，覆盖 {len(events)} 个章节")

        # 分批处理（每批约 50 章，避免 prompt 太长）
        all_windows = []
        batch_size = 50

        for batch_start in range(start, end + 1, batch_size):
            batch_end = min(batch_start + batch_size - 1, end)
            log.info(f"处理 {batch_start}-{batch_end} 章...")

            batch_events = {ch: evts for ch, evts in events.items()
                          if batch_start <= ch <= batch_end}

            if not batch_events:
                continue

            windows = await llm_generate_windows(batch_events, batch_start, batch_end)
            all_windows.extend(windows)
            log.info(f"  生成 {len(windows)} 个窗口")

        # 输出结果
        print("\n" + "=" * 70)
        print(f"700-900 章时间窗口划分结果（共 {len(all_windows)} 个）")
        print("=" * 70 + "\n")

        for i, w in enumerate(all_windows, 1):
            span = w["chapter_end"] - w["chapter_start"]
            print(f"{i:2d}. 第{w['chapter_start']:4d}-{w['chapter_end']:4d}章 ({span+1:2d}章)")
            print(f"    描述: {w['description']}")
            if w.get("key_events"):
                print(f"    关键: {' / '.join(w['key_events'][:3])}")
            print()

        # 保存到文件供审核
        output_file = "/Users/tt/code/myproject/AMO/scripts/import/time_windows_700_900.json"
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(all_windows, f, ensure_ascii=False, indent=2)
        log.info(f"结果已保存到 {output_file}")

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
