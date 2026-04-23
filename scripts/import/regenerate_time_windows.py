#!/usr/bin/env python3
"""
基于 events 表自动生成更细粒度的时间窗口。

策略：
1. 将整本书按章节分段，每段约 10-20 章
2. 每个时间窗口的描述基于该段内的重要事件自动生成
3. 优先在重要事件（major_battle, world_event）附近切分
"""

import asyncio
import logging
from collections import defaultdict

import asyncpg

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

PG_DSN = os.getenv("PG_DSN", "postgresql://postgres:postgres@localhost:5432/amo_canon")

# 目标窗口大小
TARGET_WINDOW_SIZE = 15  # 章
MIN_WINDOW_SIZE = 8
MAX_WINDOW_SIZE = 25


async def main():
    conn = await asyncpg.connect(PG_DSN)
    await conn.execute("SET search_path TO amo")
    log.info("已连接数据库")

    try:
        # 1. 获取所有事件，按章节分组
        events = await conn.fetch("""
            SELECT chapter, event_name, event_type
            FROM events
            WHERE worldline_id = 'canon' AND is_deleted = false
            ORDER BY chapter
        """)
        log.info(f"加载 {len(events)} 个事件")

        # 按章节分组
        events_by_chapter: dict[int, list[dict]] = defaultdict(list)
        for e in events:
            events_by_chapter[e["chapter"]].append({
                "name": e["event_name"],
                "type": e["event_type"],
            })

        if not events_by_chapter:
            log.warning("没有事件数据")
            return

        # 2. 获取章节范围
        min_chapter = min(events_by_chapter.keys())
        max_chapter = max(events_by_chapter.keys())
        log.info(f"章节范围: {min_chapter} - {max_chapter}")

        # 3. 生成时间窗口
        windows = []
        current_start = min_chapter

        while current_start <= max_chapter:
            # 计算目标结束章节
            target_end = current_start + TARGET_WINDOW_SIZE

            # 在目标范围内寻找最佳切分点（重要事件之后）
            best_end = target_end

            # 检查 [target_end - 5, target_end + 5] 范围内是否有重要事件
            for ch in range(max(target_end - 5, current_start + MIN_WINDOW_SIZE),
                          min(target_end + 5, max_chapter + 1)):
                chapter_events = events_by_chapter.get(ch, [])
                # 检查是否有重要事件（适合作为窗口结束点）
                for e in chapter_events:
                    if e["type"] in ("major_battle", "world_event", "faction_event"):
                        # 在重要事件之后切分
                        if current_start + MIN_WINDOW_SIZE <= ch <= current_start + MAX_WINDOW_SIZE:
                            best_end = ch
                            break

            # 确保不超过最大章节
            best_end = min(best_end, max_chapter)

            # 生成窗口描述
            window_events = []
            for ch in range(current_start, best_end + 1):
                window_events.extend(events_by_chapter.get(ch, []))

            # 选取最重要的事件作为描述
            important_events = [e for e in window_events if e["type"] in ("major_battle", "world_event")]
            if not important_events:
                important_events = window_events[:3]

            description = "·".join([e["name"][:15] for e in important_events[:3]])
            if len(description) > 50:
                description = description[:47] + "..."

            windows.append({
                "chapter_start": current_start,
                "chapter_end": best_end,
                "description": description or f"第{current_start}-{best_end}章",
            })

            current_start = best_end + 1

        log.info(f"生成 {len(windows)} 个时间窗口")

        # 4. 预览生成的窗口
        print("\n=== 生成的时间窗口预览 ===\n")
        for i, w in enumerate(windows, 1):
            span = w["chapter_end"] - w["chapter_start"]
            print(f"{i:3d}. 第{w['chapter_start']:4d}-{w['chapter_end']:4d}章 ({span:2d}章) | {w['description']}")

        # 5. 确认是否写入
        print("\n" + "=" * 60)
        confirm = input("是否写入数据库？(y/N): ").strip().lower()
        if confirm != "y":
            log.info("已取消")
            return

        # 6. 清空旧数据并写入新数据
        await conn.execute("DELETE FROM time_windows WHERE worldline_id = 'canon'")
        log.info("已清空旧的时间窗口")

        for w in windows:
            await conn.execute("""
                INSERT INTO time_windows (chapter_start, chapter_end, description, worldline_id)
                VALUES ($1, $2, $3, 'canon')
            """, w["chapter_start"], w["chapter_end"], w["description"])

        log.info(f"已写入 {len(windows)} 个新时间窗口")

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
