#!/bin/bash
# 雙擊我:開工作台。R4(docs/plan_v6_一台機器.md)。
# 沒有 .venv 就先建、裝依賴 —— clone 下來第一次雙擊也能動。
cd "$(dirname "$0")" || exit 1

if [ ! -x .venv/bin/python ]; then
  echo "第一次執行,建立虛擬環境並安裝依賴(約 1 分鐘)…"
  python3 -m venv .venv || { echo "❌ 找不到 python3,請先安裝 Python 3。"; read -p "按 Enter 關閉"; exit 1; }
  .venv/bin/pip install -q -r requirements.txt || { echo "❌ 安裝依賴失敗。"; read -p "按 Enter 關閉"; exit 1; }
fi

echo "========================================"
echo "   銀行債券投資分析 —— 工作台"
echo "========================================"
echo ""
.venv/bin/python app.py serve
