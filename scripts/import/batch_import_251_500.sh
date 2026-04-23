#!/bin/bash
# AMO 251-500 章批量导入脚本
# 20章一批，串行执行，每批自动验证

set -euo pipefail

PYTHON="/Users/tt/code/myproject/AMO/server/.venv/bin/python3"
SCRIPT="/Users/tt/code/myproject/AMO/scripts/import/run_import.py"
OUTPUT_DIR="/Users/tt/code/myproject/AMO/scripts/import/output"
LOG_FILE="/Users/tt/code/myproject/AMO/scripts/import/batch_import_251_500.log"

cd /Users/tt/code/myproject/AMO/server

# 批次定义
BATCHES=(
    "251 270"
    "271 290"
    "291 310"
    "311 330"
    "331 350"
    "351 370"
    "371 390"
    "391 410"
    "411 430"
    "431 450"
    "451 470"
    "471 490"
    "491 500"
)

TOTAL_BATCHES=${#BATCHES[@]}
BATCH_NUM=0
FAILED_BATCHES=()
TOTAL_ENTITIES=0
TOTAL_EVENTS=0
TOTAL_RELATIONS=0
TOTAL_LORE_RULES=0
TOTAL_ERRORS=0
TOTAL_DB_ERRORS=0
START_TIME=$(date +%s)

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

log "=========================================="
log "AMO 251-500 批量导入开始"
log "共 $TOTAL_BATCHES 批"
log "=========================================="

for batch in "${BATCHES[@]}"; do
    read -r START END <<< "$batch"
    BATCH_NUM=$((BATCH_NUM + 1))
    BATCH_START=$(date +%s)

    log ""
    log "--- 批次 $BATCH_NUM/$TOTAL_BATCHES: 第${START}-${END}章 ---"

    # 运行导入
    $PYTHON "$SCRIPT" --start "$START" --end "$END" 2>&1 | tail -5

    # 找到最新的 run 目录
    LATEST_RUN=$(ls -td "$OUTPUT_DIR"/run_* 2>/dev/null | head -1)
    if [ -z "$LATEST_RUN" ]; then
        log "ERROR: 找不到 run 输出目录"
        FAILED_BATCHES+=("$BATCH_NUM:${START}-${END}:no_output")
        continue
    fi

    RUN_ID=$(basename "$LATEST_RUN" | sed 's/run_//')
    BATCH_END=$(date +%s)
    BATCH_DURATION=$(( (BATCH_END - BATCH_START) / 60 ))

    # 验证：检查 DB error
    DB_ERRORS=$(grep -c "DB error" "$LATEST_RUN/main.log" 2>/dev/null || echo "0")

    # 验证：读取 run_summary.json
    if [ -f "$LATEST_RUN/run_summary.json" ]; then
        ENTITIES=$($PYTHON -c "import json; d=json.load(open('$LATEST_RUN/run_summary.json')); print(d.get('entities_total', 0))")
        EVENTS=$($PYTHON -c "import json; d=json.load(open('$LATEST_RUN/run_summary.json')); print(d.get('events_total', 0))")
        RELATIONS=$($PYTHON -c "import json; d=json.load(open('$LATEST_RUN/run_summary.json')); print(d.get('relations_total', 0))")
        LORE_RULES=$($PYTHON -c "import json; d=json.load(open('$LATEST_RUN/run_summary.json')); print(d.get('lore_rules_total', 0))")
        ERRORS=$($PYTHON -c "import json; d=json.load(open('$LATEST_RUN/run_summary.json')); print(d.get('errors', 0))")
        PRICE=$($PYTHON -c "import json; d=json.load(open('$LATEST_RUN/run_summary.json')); print(d.get('llm_usage', {}).get('total_price_usd', 0))")
    else
        ENTITIES=0; EVENTS=0; RELATIONS=0; LORE_RULES=0; ERRORS=0; PRICE=0
    fi

    # 累计
    TOTAL_ENTITIES=$((TOTAL_ENTITIES + ENTITIES))
    TOTAL_EVENTS=$((TOTAL_EVENTS + EVENTS))
    TOTAL_RELATIONS=$((TOTAL_RELATIONS + RELATIONS))
    TOTAL_LORE_RULES=$((TOTAL_LORE_RULES + LORE_RULES))
    TOTAL_ERRORS=$((TOTAL_ERRORS + ERRORS))
    TOTAL_DB_ERRORS=$((TOTAL_DB_ERRORS + DB_ERRORS))

    log "  run_id=$RUN_ID | ${BATCH_DURATION}分钟 | E=$ENTITIES Ev=$EVENTS R=$RELATIONS LR=$LORE_RULES | errors=$ERRORS db_errors=$DB_ERRORS | \$$PRICE"

    # DB error > 0 时标记（但不停止，继续执行）
    if [ "$DB_ERRORS" -gt 0 ]; then
        log "  ⚠️ 发现 $DB_ERRORS 个 DB error！"
        FAILED_BATCHES+=("$BATCH_NUM:${START}-${END}:db_errors=${DB_ERRORS}")
    fi
done

END_TIME=$(date +%s)
TOTAL_DURATION=$(( (END_TIME - START_TIME) / 60 ))

log ""
log "=========================================="
log "AMO 251-500 批量导入完成"
log "=========================================="
log "总耗时: ${TOTAL_DURATION} 分钟"
log "总实体: $TOTAL_ENTITIES"
log "总事件: $TOTAL_EVENTS"
log "总关系: $TOTAL_RELATIONS"
log "总代价规则: $TOTAL_LORE_RULES"
log "总errors: $TOTAL_ERRORS"
log "总DB errors: $TOTAL_DB_ERRORS"

if [ ${#FAILED_BATCHES[@]} -gt 0 ]; then
    log ""
    log "⚠️ 有问题的批次:"
    for fb in "${FAILED_BATCHES[@]}"; do
        log "  - $fb"
    done
else
    log "✅ 所有批次无 DB error"
fi

log "=========================================="
