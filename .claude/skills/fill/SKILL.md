---
name: fill
description: 抄列迴圈 —— 把財報候選頁的表格抄成 rows 並驗收歸檔。使用者說「跑抄列」
             「繼續抄」「fill」或直接打 /fill 時使用。
---

# 抄列迴圈

重複以下步驟,直到看見 `ALL DONE`:

1. `python3 fill.py next`
2. 照它印出的規矩,把來源頁的表格抄成 JSON,寫到 `work/current.json`
3. `python3 fill.py submit work/current.json`
4. 看結果:
   - `PASS` → 回到步驟 1
   - `RETRY` → 讀它附上的新頁,重抄一次,再 submit(不要跳過,不要回步驟 1)
   - `REJECT` → 回到步驟 1
   - `ALL DONE` → 結束,回報 `python3 fill.py status`
   - `pdf_cache/ 是空的` → 照它印的指示跑 `python3 resolve.py` 抓 PDF,再重試

## 鐵律

- **只抄,不判斷。** 不分桶、不正規化、不翻譯、不改錯字。
- **抄不出來就寫 `{"records": []}`。** 猜一個數字比留白糟糕得多 ——
  留白會被擋下來進人審佇列,猜錯的數字會通過檢查然後上網站。
- **不要修改 `fill.py`、`transcribe.py` 或任何檢查邏輯。** 抄不過是資料的事,不是程式的事。
  如果你覺得檢查有 bug,停下來告訴使用者,不要自己改。
- **不要記住前面抄過什麼。** 每一格都是獨立的;進度存在檔案裡,不在你的記憶裡。
  context 快滿了也照樣繼續 —— 被壓縮或重開之後 `fill.py next` 一樣接得下去。
- 一次只處理一格。不要為了「效率」一次讀好幾格。
- 每一格開始前都跑 `python3 fill.py next` 重新取得工單,不要沿用上一格記得的頁碼或格式猜測。
