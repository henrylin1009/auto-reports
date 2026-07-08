#!/usr/bin/env bash
# 排程用進入點:自動補抓當期個體檔 → 產出報表 → 歸檔(帶日期)+ latest + log。
# cron 範例(每月5日 03:00 跑,涵蓋 H1(約8月)與年報(約3-4月)發布,含補正):
#   0 3 5 * * /path/to/work/run.sh
set -euo pipefail
cd "$(dirname "$0")"

# 若有虛擬環境就啟用(沒有則用系統 python3)
[ -f .venv/bin/activate ] && source .venv/bin/activate || true

STAMP="$(date +%Y%m%d)"
mkdir -p output logs
LOG="logs/run_${STAMP}.log"

echo "=== $(date '+%F %T') 開始 ===" >> "$LOG"
if python3 build_report.py --refresh >> "$LOG" 2>&1; then
    cp -f 銀行債券_完整報表.xlsx "output/銀行債券_完整報表_${STAMP}.xlsx"
    cp -f 銀行債券_完整報表.xlsx "output/銀行債券_完整報表_latest.xlsx"
    echo "=== $(date '+%F %T') 成功 → output/銀行債券_完整報表_${STAMP}.xlsx ===" >> "$LOG"
else
    echo "=== $(date '+%F %T') 失敗,詳見上方錯誤 ===" >> "$LOG"
    exit 1
fi
