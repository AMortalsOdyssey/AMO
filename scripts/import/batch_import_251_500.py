#!/usr/bin/env python3
"""AMO 251-500 章批量导入 — 串行执行 + 自动验证"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from datetime import datetime

PYTHON = "/Users/tt/code/myproject/AMO/server/.venv/bin/python3"
SCRIPT = "/Users/tt/code/myproject/AMO/scripts/import/run_import.py"
OUTPUT_DIR = Path("/Users/tt/code/myproject/AMO/scripts/import/output")
LOG_FILE = Path("/Users/tt/code/myproject/AMO/scripts/import/batch_import_251_500.log")
SERVER_DIR = "/Users/tt/code/myproject/AMO/server"

BATCHES = [
    (251, 270), (271, 290), (291, 310), (311, 330), (331, 350),
    (351, 370), (371, 390), (391, 410), (411, 430), (431, 450),
    (451, 470), (471, 490), (491, 500),
]

totals = {"entities": 0, "events": 0, "relations": 0, "lore_rules": 0, "errors": 0, "db_errors": 0, "cost": 0.0}
failed_batches = []
batch_results = []

def log(msg):
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")

def find_latest_run():
    runs = sorted(OUTPUT_DIR.glob("run_*"), key=lambda p: p.stat().st_mtime, reverse=True)
    return runs[0] if runs else None

def verify_batch(run_dir):
    result = {"db_errors": 0, "entities": 0, "events": 0, "relations": 0, "lore_rules": 0, "errors": 0, "cost": 0.0}
    # Check DB errors in main.log
    main_log = run_dir / "main.log"
    if main_log.exists():
        content = main_log.read_text()
        result["db_errors"] = content.count("DB error")
    # Read run_summary.json
    summary_file = run_dir / "run_summary.json"
    if summary_file.exists():
        d = json.loads(summary_file.read_text())
        result["entities"] = d.get("entities_total", 0)
        result["events"] = d.get("events_total", 0)
        result["relations"] = d.get("relations_total", 0)
        result["lore_rules"] = d.get("lore_rules_total", 0)
        result["errors"] = d.get("errors", 0)
        result["cost"] = d.get("llm_usage", {}).get("total_price_usd", 0.0)
    return result

def main():
    log("=" * 50)
    log(f"AMO 251-500 批量导入开始 — 共 {len(BATCHES)} 批")
    log("=" * 50)

    global_start = time.time()

    for i, (start, end) in enumerate(BATCHES):
        batch_num = i + 1
        log(f"")
        log(f"--- 批次 {batch_num}/{len(BATCHES)}: 第{start}-{end}章 ---")
        batch_start = time.time()

        # Run import
        try:
            proc = subprocess.run(
                [PYTHON, SCRIPT, "--start", str(start), "--end", str(end)],
                cwd=SERVER_DIR,
                capture_output=False,
                timeout=7200,  # 2 hour timeout per batch
            )
        except subprocess.TimeoutExpired:
            log(f"  TIMEOUT: 批次 {batch_num} 超时 (2小时)")
            failed_batches.append(f"{batch_num}:{start}-{end}:timeout")
            continue
        except Exception as e:
            log(f"  EXCEPTION: {e}")
            failed_batches.append(f"{batch_num}:{start}-{end}:exception")
            continue

        batch_duration = int((time.time() - batch_start) / 60)

        # Find latest run and verify
        run_dir = find_latest_run()
        if not run_dir:
            log(f"  ERROR: 找不到 run 输出目录")
            failed_batches.append(f"{batch_num}:{start}-{end}:no_output")
            continue

        run_id = run_dir.name.replace("run_", "")
        v = verify_batch(run_dir)

        # Accumulate totals
        for key in ["entities", "events", "relations", "lore_rules", "errors", "db_errors"]:
            totals[key] += v[key]
        totals["cost"] += v["cost"]

        batch_results.append({"batch": batch_num, "range": f"{start}-{end}", "run_id": run_id, "duration": batch_duration, **v})

        log(f"  run_id={run_id} | {batch_duration}分钟 | E={v['entities']} Ev={v['events']} R={v['relations']} LR={v['lore_rules']} | errors={v['errors']} db_errors={v['db_errors']} | ${v['cost']:.2f}")

        if v["db_errors"] > 0:
            log(f"  ⚠️ 发现 {v['db_errors']} 个 DB error!")
            failed_batches.append(f"{batch_num}:{start}-{end}:db_errors={v['db_errors']}")

    total_duration = int((time.time() - global_start) / 60)

    log("")
    log("=" * 50)
    log("AMO 251-500 批量导入完成")
    log("=" * 50)
    log(f"总耗时: {total_duration} 分钟 ({total_duration/60:.1f} 小时)")
    log(f"总实体: {totals['entities']}")
    log(f"总事件: {totals['events']}")
    log(f"总关系: {totals['relations']}")
    log(f"总代价规则: {totals['lore_rules']}")
    log(f"总errors: {totals['errors']}")
    log(f"总DB errors: {totals['db_errors']}")
    log(f"总费用: ${totals['cost']:.2f}")

    if failed_batches:
        log("")
        log("⚠️ 有问题的批次:")
        for fb in failed_batches:
            log(f"  - {fb}")
    else:
        log("✅ 所有批次无 DB error")

    # Save summary JSON
    summary = {
        "total_duration_min": total_duration,
        "totals": totals,
        "failed_batches": failed_batches,
        "batch_results": batch_results,
    }
    summary_path = Path("/Users/tt/code/myproject/AMO/scripts/import/batch_251_500_summary.json")
    with open(summary_path, "w") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    log(f"汇总已保存: {summary_path}")
    log("=" * 50)

if __name__ == "__main__":
    main()
