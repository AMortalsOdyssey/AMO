#!/bin/bash
# AMO 批量导入: 501-1000 章
# 分批执行，每批 50 章
# 每批会自动从 DB 查询上一批的最终年份作为锚点

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_FILE="${SCRIPT_DIR}/batch_import_501_1000.log"

echo "=== AMO Batch Import: 501-1000 ===" | tee -a "$LOG_FILE"
echo "Started at: $(date)" | tee -a "$LOG_FILE"
echo "Log file: $LOG_FILE"

# 定义批次（每批 50 章）
batches=(
    "501 550"
    "551 600"
    "601 650"
    "651 700"
    "701 750"
    "751 800"
    "801 850"
    "851 900"
    "901 950"
    "951 1000"
)

# 运行每个批次
for batch in "${batches[@]}"; do
    read start end <<< "$batch"
    echo "" | tee -a "$LOG_FILE"
    echo "========================================" | tee -a "$LOG_FILE"
    echo "Processing chapters $start - $end" | tee -a "$LOG_FILE"
    echo "Started at: $(date)" | tee -a "$LOG_FILE"
    echo "========================================" | tee -a "$LOG_FILE"

    # 执行导入（自动从 DB 获取锚点）
    python3 "${SCRIPT_DIR}/batch_import_501_1000.py" \
        --start "$start" \
        --end "$end" \
        2>&1 | tee -a "$LOG_FILE"

    exit_code=${PIPESTATUS[0]}

    if [ $exit_code -ne 0 ]; then
        echo "ERROR: Batch $start-$end failed with exit code $exit_code" | tee -a "$LOG_FILE"
        echo "Stopping at: $(date)" | tee -a "$LOG_FILE"
        exit $exit_code
    fi

    echo "Batch $start-$end completed at: $(date)" | tee -a "$LOG_FILE"

    # 短暂休息
    echo "Sleeping 5 seconds before next batch..." | tee -a "$LOG_FILE"
    sleep 5
done

echo "" | tee -a "$LOG_FILE"
echo "=== All batches completed ===" | tee -a "$LOG_FILE"
echo "Finished at: $(date)" | tee -a "$LOG_FILE"
