#!/usr/bin/env python3
"""
回填脚本：从已有的 stage3 提取结果中回填 character_techniques 表和 character_snapshots.techniques 字段
不需要重新调用 LLM，直接读取现有的 JSON 文件
"""

import json
import logging
import os
from collections import defaultdict
from pathlib import Path

import asyncio
import asyncpg

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# 数据库配置 - 与 server/app/core/config.py 保持一致
PG_DSN = os.getenv("PG_DSN", "postgresql://postgres:postgres@localhost:5432/amo_canon")

# 输出目录
OUTPUT_DIR = Path(__file__).parent / "output"


async def main():
    log.info("=== 回填 MASTERS 关系到数据库 ===")

    # 1. 收集所有 MASTERS 关系
    masters_relations = []
    stage3_files = list(OUTPUT_DIR.glob("**/stage3_relations/*.json"))
    log.info(f"找到 {len(stage3_files)} 个 stage3 文件")

    for fpath in stage3_files:
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                relations = json.load(f)
            for rel in relations:
                if rel.get("relation_label") == "MASTERS" and rel.get("from_type") == "Character" and rel.get("to_type") == "Technique":
                    masters_relations.append({
                        "character_name": rel["from_entity"],
                        "technique_name": rel["to_entity"],
                        "proficiency": rel.get("attributes", {}).get("proficiency", "mastered"),
                        "first_chapter": rel.get("valid_from_chapter"),
                        "last_chapter": rel.get("valid_until_chapter"),
                    })
        except Exception as e:
            log.warning(f"读取 {fpath} 失败: {e}")

    log.info(f"收集到 {len(masters_relations)} 条 MASTERS 关系")

    # 2. 去重并按角色+功法聚合（取最早的章节）
    char_tech_map: dict[tuple[str, str], dict] = {}
    for rel in masters_relations:
        key = (rel["character_name"], rel["technique_name"])
        if key not in char_tech_map:
            char_tech_map[key] = rel
        else:
            # 取更早的章节
            existing = char_tech_map[key]
            if rel["first_chapter"] and (not existing["first_chapter"] or rel["first_chapter"] < existing["first_chapter"]):
                existing["first_chapter"] = rel["first_chapter"]
            # 更新 proficiency（mastered > learning）
            if rel["proficiency"] == "mastered" and existing["proficiency"] != "mastered":
                existing["proficiency"] = "mastered"

    log.info(f"去重后 {len(char_tech_map)} 条唯一的角色-功法关系")

    # 3. 连接数据库
    conn = await asyncpg.connect(PG_DSN)
    await conn.execute("SET search_path TO amo")
    log.info("已连接数据库")

    try:
        # 4. 获取角色名→ID映射
        rows = await conn.fetch("SELECT id, name FROM characters WHERE worldline_id = 'canon' AND is_deleted = false")
        char_name_to_id = {r["name"]: r["id"] for r in rows}
        log.info(f"加载 {len(char_name_to_id)} 个角色")

        # 5. 获取功法名→ID映射
        rows = await conn.fetch("SELECT id, name FROM techniques WHERE worldline_id = 'canon'")
        tech_name_to_id = {r["name"]: r["id"] for r in rows}
        log.info(f"加载 {len(tech_name_to_id)} 个功法")

        # 6. 写入 character_techniques 表
        inserted = 0
        skipped_no_char = 0
        skipped_no_tech = 0

        for (char_name, tech_name), rel in char_tech_map.items():
            char_id = char_name_to_id.get(char_name)
            tech_id = tech_name_to_id.get(tech_name)

            if not char_id:
                skipped_no_char += 1
                continue
            if not tech_id:
                skipped_no_tech += 1
                continue

            try:
                await conn.execute("""
                    INSERT INTO character_techniques (character_id, technique_id, relation_type,
                        first_chapter, last_chapter, proficiency, worldline_id, extraction_version)
                    VALUES ($1, $2, $3, $4, $5, $6, 'canon', 1)
                    ON CONFLICT (character_id, technique_id, worldline_id)
                    DO UPDATE SET
                        first_chapter = LEAST(character_techniques.first_chapter, EXCLUDED.first_chapter),
                        last_chapter = COALESCE(EXCLUDED.last_chapter, character_techniques.last_chapter),
                        proficiency = COALESCE(EXCLUDED.proficiency, character_techniques.proficiency),
                        updated_at = now()
                """, char_id, tech_id, rel["proficiency"], rel["first_chapter"], rel["last_chapter"], rel["proficiency"])
                inserted += 1
            except Exception as e:
                log.warning(f"写入失败 {char_name}->{tech_name}: {e}")

        log.info(f"character_techniques: 插入/更新 {inserted} 条，跳过（无角色）{skipped_no_char}，跳过（无功法）{skipped_no_tech}")

        # 7. 更新 character_snapshots.techniques 字段
        # 按角色聚合功法列表（按 first_chapter 过滤）
        char_techniques_timeline: dict[str, list[dict]] = defaultdict(list)
        for (char_name, tech_name), rel in char_tech_map.items():
            char_techniques_timeline[char_name].append({
                "technique": tech_name,
                "first_chapter": rel["first_chapter"],
                "proficiency": rel["proficiency"],
            })

        # 获取所有 snapshots
        snapshots = await conn.fetch("""
            SELECT cs.id, c.name as character_name, cs.chapter_start, cs.chapter_end, cs.techniques
            FROM character_snapshots cs
            JOIN characters c ON cs.character_id = c.id
            WHERE cs.worldline_id = 'canon'
        """)
        log.info(f"加载 {len(snapshots)} 个 snapshots")

        updated_snapshots = 0
        for snap in snapshots:
            char_name = snap["character_name"]
            chapter_start = snap["chapter_start"]

            # 获取该角色在此章节之前已掌握的功法
            char_techs = char_techniques_timeline.get(char_name, [])
            techniques_at_chapter = [
                t["technique"] for t in char_techs
                if t["first_chapter"] and t["first_chapter"] <= chapter_start
            ]

            if techniques_at_chapter:
                # 去重
                techniques_at_chapter = list(set(techniques_at_chapter))
                # 转为 JSON 字符串，因为 techniques 字段类型是 jsonb
                techniques_json = json.dumps(techniques_at_chapter, ensure_ascii=False)
                await conn.execute("""
                    UPDATE character_snapshots SET techniques = $1 WHERE id = $2
                """, techniques_json, snap["id"])
                updated_snapshots += 1

        log.info(f"更新 {updated_snapshots} 个 snapshots 的 techniques 字段")

    finally:
        await conn.close()

    log.info("=== 回填完成 ===")


if __name__ == "__main__":
    asyncio.run(main())
