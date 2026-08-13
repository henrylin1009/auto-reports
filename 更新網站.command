#!/bin/bash
# 雙擊我:由 facts/ 重建 data.json → 上傳 GitHub Pages。
# 抄列本身請先跑 Claude Code 的 /fill(或本機工作台 python3 server.py)。
# 只需在有新財報時跑(H1約8月、年報約隔年3-4月)。
#
# ⚠️ 2026-08-10 修:原本第 1 步叫的是 `bridge_v2.py`,那支已經隨舊管線一起刪掉。
#    整條發佈路徑因此斷了近三週 —— 線上網站停在 2026-07-24 的舊管線資料,
#    而本機所有重建成果從來沒上得去。現在改叫 `build.py`(唯一的寫入者)。
cd "$(dirname "$0")" || exit 1
PY=$([ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)

echo "========================================"
echo "   更新 銀行債券報表 網站"
echo "========================================"
echo ""
# CI 只認 main 分支的 data.json(.github/workflows/report.yml)。
# ⚠️ 2026-08-14 改成**擋下來**:原本只印一行警告然後照樣往下跑,
#    結果是「按了、也 commit 了、也 push 了,但網站沒動」—— 而且看起來完全成功。
#    實測踩過:r0-fix-tests 分支領先 main 14 個 commit,線上停在舊資料。
BR=$(git rev-parse --abbrev-ref HEAD)
if [ "$BR" != "main" ]; then
  echo "❌ 目前在 $BR 分支,但發佈流程只跟 main —— 在這裡按下去網站不會更新。"
  echo ""
  echo "   先合併回 main:"
  echo "       git checkout main && git merge $BR"
  echo "   然後再跑一次這個按鈕。"
  echo ""
  read -p "按 Enter 關閉"; exit 1
fi

echo "[1/3] 先看一次會改動什麼(不寫檔)…"
if ! "$PY" build.py --diff; then
  echo ""; echo "❌ 建置失敗,把上面訊息截給協助者。"
  read -p "按 Enter 關閉"; exit 1
fi

echo ""
# ⚠️ 要看的是最後那段「與**線上 data.json** 的差異」——
#    它上面那份 288 個單位的差異比較基準是 2026-07-27 的凍結快照,每次都一樣,
#    回答不了「我這次改了什麼」。特別盯兩個數字:「有值 → null」與「數字改變」。
read -p "最後那段「與線上 data.json 的差異」看起來對嗎?繼續請按 Enter,不對請按 Ctrl-C 中止 "

echo ""
echo "[2/3] 由 facts/ 重建 data.json …"
if ! "$PY" build.py --write; then
  echo ""; echo "❌ 寫入失敗,把上面訊息截給協助者。"
  read -p "按 Enter 關閉"; exit 1
fi

echo ""
echo "[3/3] 上傳 GitHub(網頁自動更新)…"
# 分支檢查已在最前面擋掉,跑到這裡一定在 main。
# ⚠️ 判斷層(buckets.py/config.py)一起 commit:manifest 存了它們的 sha256,
#    只推 data.json 會讓「發布的數字」與「算出它的規則」在 repo 裡對不起來。
git add data.json build_manifest.json buckets.py config.py taxonomy/
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
