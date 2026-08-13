#!/usr/bin/env bash
# 排程用進入點:抓當期財報 → 由 facts/ 重建 data.json → 產出 site/ → 歸檔 + log。
# cron 範例(每月5日 03:00 跑,涵蓋 H1(約8月)與年報(約3-4月)發布,含補正):
#   0 3 5 * * /path/to/work/run.sh
#
# ⚠️ 2026-08-14 修:原本跑的是 `build_report.py --refresh`,那支已隨舊管線刪除,
#    所以這支腳本自那時起**每次執行都必然失敗**(set -e + 找不到檔案)。
#    現在改走唯一入口 `app.py`,與 `更新網站.command` 同一條路徑。
#
# ⚠️ 這支**不 push**。發佈到公開網站一律走 `更新網站.command`(有人工確認關卡),
#    排程只負責把本機資料算到最新,不代替人按下發佈。
set -euo pipefail
cd "$(dirname "$0")"

PY=$([ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)

STAMP="$(date +%Y%m%d)"
mkdir -p output logs
LOG="logs/run_${STAMP}.log"

echo "=== $(date '+%F %T') 開始 ===" >> "$LOG"
{
    "$PY" app.py fetch          # 抓最新財報(需要台灣網路,TWSE 擋雲端 IP)
    "$PY" app.py build --write  # 由 facts/ 重建 data.json
    "$PY" make_web.py           # 產出 site/index.html + 圖1/圖2.png
} >> "$LOG" 2>&1 || {
    echo "=== $(date '+%F %T') 失敗,詳見上方錯誤 ===" >> "$LOG"
    exit 1
}

if [ -f site/index.html ]; then
    cp -f site/index.html "output/index_${STAMP}.html"
    cp -f site/index.html "output/index_latest.html"
fi
echo "=== $(date '+%F %T') 成功 → output/index_${STAMP}.html ===" >> "$LOG"
