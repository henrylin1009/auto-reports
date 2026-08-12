# -*- coding: utf-8 -*-
"""`docid.py` 的測試。

**每一條斷言都附一個注入案例** —— 證明這道檢查真的會失敗。恆真的檢查
比沒有檢查更糟(它讓人以為驗過了),見 `memory/checks-must-fail`。
"""
import docid

PASS = FAIL = 0


def ck(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name}")


def raises(fn, *a):
    try:
        fn(*a)
        return False
    except docid.BadDocId:
        return True


print("test_docid.py —— doc id 解析/組裝")
print("=" * 60)

# D1 往返 -------------------------------------------------------------------
for period, bank, basis in [("202504", "玉山", "個體"),
                            ("202301", "中信", "合併"),
                            ("201802", "國泰", "個體")]:
    d = docid.make(period, bank, basis)
    ck(f"D1 {d} 往返一致", docid.parse(d) == (period, bank, basis))

ck("D1 inject:期別被改成 5 位數 → make 必須拒絕",
   raises(docid.make, "20250", "玉山", "個體"))
ck("D1 inject:銀行名含底線 → make 必須拒絕(會讓解析歧義)",
   raises(docid.make, "202504", "玉_山", "個體"))
ck("D1 inject:口徑寫成 AI3 → make 必須拒絕",
   raises(docid.make, "202504", "玉山", "AI3"))

# D2 舊格式一律拒絕 ---------------------------------------------------------
#    靜靜接受兩種格式 = 兩套慣例並存,那是這個 repo 反覆出事的形狀(鐵律 7)。
ck("D2 舊格式 202504_5847_AI3 必須被拒絕", raises(docid.parse, "202504_5847_AI3"))
ck("D2 舊格式 is_valid 為 False", not docid.is_valid("202504_5847_AI3"))
ck("D2 新格式 is_valid 為 True", docid.is_valid("202504_玉山_個體"))

# D3 壞輸入 -----------------------------------------------------------------
for bad in ["", None, "玉山", "202504_玉山", "202504_玉山_個體_多餘",
            "2025_玉山_個體", "202504__個體"]:
    ck(f"D3 {bad!r} 必須被拒絕", raises(docid.parse, bad))

# D4 取值 -------------------------------------------------------------------
d = "202504_玉山_個體"
ck("D4 period_of", docid.period_of(d) == "202504")
ck("D4 bank_of 回名字不是代碼", docid.bank_of(d) == "玉山")
ck("D4 basis_label_of", docid.basis_label_of(d) == "個體")
ck("D4 code_of 反查得到代碼", docid.code_of(d) == "5847")
ck("D4 code_of 認不得的銀行回 None",
   docid.code_of("202504_不存在的銀行_個體") is None)

# D5 封面 vs 檔名 —— 這是整份改名最重要的一道閘門 --------------------------
ck("D5 一致 → 回 None", docid.verify_basis("202504_玉山_個體", "個體") is None)
ck("D5 不一致 → 回訊息",
   isinstance(docid.verify_basis("202504_玉山_個體", "合併"), str))
ck("D5 訊息要指名封面是權威",
   "封面是權威" in (docid.verify_basis("202504_玉山_個體", "合併") or ""))

# **「不知道」不等於「打架」**(鐵律 9)。封面判不出來時不准報成不一致 ——
# 那會讓「掃描影像的封面」跟「真的拿錯檔」變成同一個可觀察狀態。
ck("D5 封面判不出(?) → 不算不一致",
   docid.verify_basis("202504_玉山_個體", "?") is None)
ck("D5 封面是空字串 → 不算不一致",
   docid.verify_basis("202504_玉山_個體", "") is None)

ck("D5 inject:把兩個口徑對調也必須被抓到",
   docid.verify_basis("202301_中信_合併", "個體") is not None)

print("=" * 60)
print(f"PASS: {PASS}  FAIL: {FAIL}")
print("RESULT:", "PASS" if FAIL == 0 else "FAIL")
raise SystemExit(1 if FAIL else 0)
