#!/bin/bash
set -e
cd /Users/tt/code/myproject/AMO/scripts/import
LOG_FILE="batch_import_501_1000.log"

for start in 601 651 701 751 801 851 901 951; do
    end=$((start + 49))
    echo "$(date): Starting batch $start - $end" | tee -a "$LOG_FILE"
    python3 batch_import_501_1000.py --start $start --end $end 2>&1 | tee -a "$LOG_FILE"
    echo "$(date): Completed batch $start - $end" | tee -a "$LOG_FILE"
    sleep 3
done

echo "$(date): ALL BATCHES COMPLETED!" | tee -a "$LOG_FILE"
