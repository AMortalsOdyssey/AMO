#!/usr/bin/env python3
"""
轻量级年龄修复脚本

问题：411-500 章的 world_year 被错误设置为 126-128 岁，应该从 180 岁开始累加。
方案：读取每章原文，用 LLM 识别时间流逝，累积计算准确年龄。

用法:
  python3 scripts/import/fix_chapter_years.py --dry-run   # 预览不写库
  python3 scripts/import/fix_chapter_years.py             # 执行修复
"""

import os
import re
import json
import time
import argparse
import logging
from pathlib import Path
from typing import Optional

import requests
import psycopg2

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

LLM_CONFIG = {
    "api_key": os.environ.get("LLM_API_KEY", ""),
    "base_url": os.environ.get("LLM_BASE_URL", "http://localhost:8001/v1"),
    "model": os.environ.get("LLM_MODEL", "gemini-3.1-pro-preview"),
}

CHAPTERS_DIR = Path(__file__).parent.parent.parent / "book" / "chapters"

# 起始锚点
START_CHAPTER = 411
END_CHAPTER = 500
BASE_CHAPTER = 410
BASE_YEAR = 180  # ch410 = 180岁

# LLM 价格 (per 1M tokens)
INPUT_PRICE = 1.25
OUTPUT_PRICE = 5.0

LOG_FILE = Path(__file__).parent / "fix_chapter_years.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, mode="w"),
        logging.StreamHandler(),
    ]
)
log = logging.getLogger(__name__)

# ============================================================
# LLM 调用
# ============================================================

PROMPT_TEMPLATE = """你是一个小说时间分析专家。根据下面这章小说内容，判断这一章中【实际经过】了多少时间。

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

章节内容：
{content}

这章【实际经过】了多少年？只返回数字："""


def call_llm(content: str, max_retries: int = 3) -> tuple[float, int, int]:
    """调用 LLM 估算时间流逝，返回 (years, input_tokens, output_tokens)"""
    # 截取章节关键部分（开头+结尾），减少 token
    if len(content) > 6000:
        content = content[:3000] + "\n...\n" + content[-3000:]

    prompt = PROMPT_TEMPLATE.format(content=content)

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
                # 合理性检查：单章不可能超过 100 年
                if years > 100:
                    years = 0
                return years, input_tokens, output_tokens
            return 0, input_tokens, output_tokens

        except Exception as e:
            log.warning(f"LLM 调用失败 (attempt {attempt+1}): {e}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)

    return 0, 0, 0


def read_chapter(chapter_num: int) -> Optional[str]:
    """读取章节原文"""
    pattern = f"{chapter_num:04d}_*.txt"
    files = list(CHAPTERS_DIR.glob(pattern))
    # 排除 " 2.txt" 副本
    files = [f for f in files if " 2.txt" not in f.name]
    if not files:
        return None
    return files[0].read_text(encoding="utf-8")


# ============================================================
# 数据库更新
# ============================================================

def update_database(chapter_years: dict[int, int], dry_run: bool = False):
    """更新 chapter_year_mapping 和 master_timeline 表"""
    if dry_run:
        log.info("DRY RUN 模式，不写入数据库")
        return

    conn = psycopg2.connect(**PG_CONFIG)
    cur = conn.cursor()

    try:
        # 1. 更新 chapter_year_mapping
        for chapter_num, world_year in chapter_years.items():
            cur.execute("""
                UPDATE amo.chapter_year_mapping
                SET world_year = %s
                WHERE chapter_num = %s
            """, (world_year, chapter_num))
        log.info(f"更新 chapter_year_mapping: {cur.rowcount} 行")

        # 2. 更新 master_timeline（根据 chapter_start 更新 world_year）
        for chapter_num, world_year in chapter_years.items():
            cur.execute("""
                UPDATE amo.master_timeline
                SET world_year = %s
                WHERE chapter_start = %s
            """, (world_year, chapter_num))
        log.info(f"更新 master_timeline: 完成")

        # 3. 更新 events 表的 world_year
        for chapter_num, world_year in chapter_years.items():
            cur.execute("""
                UPDATE amo.events
                SET world_year = %s
                WHERE chapter_start = %s
            """, (world_year, chapter_num))
        log.info(f"更新 events: 完成")

        conn.commit()
        log.info("数据库更新成功")

    except Exception as e:
        conn.rollback()
        log.error(f"数据库更新失败: {e}")
        raise
    finally:
        cur.close()
        conn.close()


# ============================================================
# 主流程
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="修复 411-500 章的年龄数据")
    parser.add_argument("--dry-run", action="store_true", help="预览模式，不写数据库")
    parser.add_argument("--start", type=int, default=START_CHAPTER, help="起始章节")
    parser.add_argument("--end", type=int, default=END_CHAPTER, help="结束章节")
    args = parser.parse_args()

    log.info(f"开始修复章节年龄: ch{args.start}-{args.end}")
    log.info(f"基准点: ch{BASE_CHAPTER} = {BASE_YEAR}岁")

    current_year = BASE_YEAR
    chapter_years = {}
    total_input_tokens = 0
    total_output_tokens = 0

    for chapter_num in range(args.start, args.end + 1):
        content = read_chapter(chapter_num)
        if not content:
            log.warning(f"ch{chapter_num}: 文件不存在，跳过")
            chapter_years[chapter_num] = current_year
            continue

        # 调用 LLM 估算时间流逝
        years_passed, in_tokens, out_tokens = call_llm(content)
        total_input_tokens += in_tokens
        total_output_tokens += out_tokens

        current_year += years_passed
        chapter_years[chapter_num] = int(round(current_year))

        log.info(f"ch{chapter_num}: +{years_passed:.1f}年 → {int(round(current_year))}岁")

        # 简单限流
        time.sleep(0.5)

    # 统计
    cost = (total_input_tokens * INPUT_PRICE + total_output_tokens * OUTPUT_PRICE) / 1_000_000
    log.info(f"\n统计:")
    log.info(f"  处理章节: {args.start}-{args.end} ({args.end - args.start + 1} 章)")
    log.info(f"  年龄范围: {chapter_years[args.start]}岁 → {chapter_years[args.end]}岁")
    log.info(f"  Token 用量: input={total_input_tokens:,}, output={total_output_tokens:,}")
    log.info(f"  预估费用: ${cost:.2f}")

    # 输出结果
    print("\n修复结果预览:")
    print("-" * 40)
    for ch in [411, 420, 430, 450, 480, 500]:
        if ch in chapter_years:
            print(f"  ch{ch}: {chapter_years[ch]}岁")
    print("-" * 40)

    # 写入数据库
    update_database(chapter_years, dry_run=args.dry_run)

    # 保存结果到文件
    output_file = Path(__file__).parent / "chapter_years_fix.json"
    with open(output_file, "w") as f:
        json.dump(chapter_years, f, indent=2)
    log.info(f"结果已保存到: {output_file}")


if __name__ == "__main__":
    main()
