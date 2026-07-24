#!/bin/bash
# 雙擊我:把本機已抽好的資料橋接進 data.json → 上傳 GitHub Pages。
# 抽取本身(Gemini)請先跑: python3 batch_v2.py
# 只需在有新財報時跑(H1約8月、年報約隔年3-4月)。
cd "$(dirname "$0")" || exit 1

echo "========================================"
echo "   更新 銀行債券報表 網站"
echo "========================================"
echo ""
echo "[1/2] 橋接 extract_v2_results → data.json …"
if ! python3 bridge_v2.py; then
  echo ""; echo "❌ 橋接失敗,把上面訊息截給協助者。"
  read -p "按 Enter 關閉"; exit 1
fi

echo ""
echo "[2/2] 上傳 GitHub(網頁自動更新)…"
git add data.json
if git commit -m "更新資料 $(date +%F)"; then
  git push && echo "✅ 已上傳,網頁 2-3 分鐘後更新"
else
  echo "(資料沒變動,不需上傳)"
fi

echo ""
echo "網址(給 mentor / 同事看):"
echo "   https://henrylin1009.github.io/auto-reports/"
echo ""
read -p "按 Enter 關閉視窗"
