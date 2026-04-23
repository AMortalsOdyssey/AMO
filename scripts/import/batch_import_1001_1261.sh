#!/bin/bash
#
# AMO 批量导入: 1001-1261 章（人界篇最后部分）
# 分 6 批执行，每批约 50 章
#
# 用法:
#   ./batch_import_1001_1261.sh
#
# 锚点: ch1000 = 367岁（自动从 DB 获取）

set -e

cd "$(dirname "$0")"

LOG_FILE="batch_import_1001_1261.log"

echo "=== AMO Import 1001-1261 ===" | tee -a "$LOG_FILE"
echo "Started at: $(date)" | tee -a "$LOG_FILE"

# 检查 Neo4j 端口转发
if ! ps aux | grep -q "[k]ubectl.*port-forward.*7687"; then
    echo "WARNING: Neo4j port-forward not running!" | tee -a "$LOG_FILE"
    echo "Starting port-forward..." | tee -a "$LOG_FILE"
    nohup kubectl port-forward svc/neo4j 7687:7687 7474:7474 -n pocket-lover > /tmp/neo4j-pf.log 2>&1 &
    sleep 3
fi

# 批次定义: 每批 50 章，共 6 批
BATCHES=(
    "1001 1050"
    "1051 1100"
    "1101 1150"
    "1151 1200"
    "1201 1250"
    "1251 1261"
)

for batch in "${BATCHES[@]}"; do
    read -r start end <<< "$batch"
    echo "" | tee -a "$LOG_FILE"
    echo "=== Batch: ch${start}-ch${end} ===" | tee -a "$LOG_FILE"
    echo "Time: $(date)" | tee -a "$LOG_FILE"

    python3 batch_import_1001_1261.py --start "$start" --end "$end" 2>&1 | tee -a "$LOG_FILE"

    echo "Batch ch${start}-ch${end} completed at $(date)" | tee -a "$LOG_FILE"

    # 批次间间隔 5 秒
    sleep 5
done

echo "" | tee -a "$LOG_FILE"
echo "=== All batches completed ===" | tee -a "$LOG_FILE"
echo "Finished at: $(date)" | tee -a "$LOG_FILE"

# 打印统计
echo "" | tee -a "$LOG_FILE"
echo "=== Summary ===" | tee -a "$LOG_FILE"
grep "Final year:" "$LOG_FILE" | tail -1
grep "Entities:" "$LOG_FILE" | tail -1
grep "Events:" "$LOG_FILE" | tail -1
grep "Errors:" "$LOG_FILE" | tail -1
