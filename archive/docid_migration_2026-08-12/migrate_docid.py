#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一次性遷移:`{YYYYMM}_{代碼}_AI{n}` → `{YYYYMM}_{銀行名}_{個體|合併}`。

    python3 migrate_docid.py            # dry-run:只印計畫,不動任何檔
    python3 migrate_docid.py --write    # 真的改

**這支是一次性的,跑完就該進 archive/。** 它存在的唯一理由是把既有 479 個
檔案 + facts.db 從舊命名搬到新命名;新資料一律由 `docid.make()` 直接產生
正確的名字,不會再經過這裡(鐵律 7:不准長第二條路徑)。

## 三個要人決定的地方,都寫死在這裡而不是猜

1. **口徑從封面判**(`locate.basis_of`),不從舊檔名的 AI 編號推 ——
   AI 編號早就不帶意義(見 `docid.py` 檔頭)。
2. **封面判不出口徑的 10 份搬進 `archive/`**(2018–2020 掃描影像,
   事實庫零筆,對發布零影響 —— 實測過)。使用者 2026-08-12 裁示。
3. **`202102_5847_AI2` 與 `_AI3` 撞名**:sha256 逐字相同(同一份 PDF 被
   重複抓兩次,`build.py:176` 早就為它寫過特例),但抄出來的內容不同 ——
   AI2 只抄了 2 列、AI3 抄了 7 列。**留 AI3**,理由是它抄得完整;
   AI2 那筆是同一份文件的殘缺抽取,不是另一份文件的資料。
   ⚠️ 這是**有損**的一步,所以要明講:AI2 的 2 列被丟掉。
"""
import argparse
import glob
import json
import os
import re
import shutil
import sqlite3
import sys

import config
import docid
import locate

#: 帶 doc id 的狀態目錄。**檔名與內容都要改** —— 只改檔名會讓 `facts/` 裡
#: `{"202504_5847_AI3|OCI": ...}` 這種內嵌鍵指向不存在的文件。
STATE_DIRS = ["pdf_cache", "pdf_cache_norm", "facts", "anchors", "decisions",
              "v4/raw", "v4/ledger", "work", "out", "results", "pillar3_cache"]

ARCHIVE_DIR = "archive/unknown_basis_2026-08-12"

#: 原始碼裡也**硬編**了大量 doc id(定位提示表、黃金集、測試基準、註解舉例)——
#: 實測 180 處 / 45 個檔。手改必錯,所以走跟資料同一份對照表做文字替換:
#: **查得到才換,查不到原樣留著**,於是測試裡的假 id(`209904_...`)與已決定
#: 丟棄的那份(`202102_5847_AI2`,留在歷史註解裡)都不會被誤動。
SOURCE_GLOBS = ["*.py", "*.js", "*.md", "*.yaml", "core/*.py", "v4/*.py",
                "sim/*.py", "web/*.js", "golden/*.py", "docs/*.md"]

#: 不要碰的原始碼 —— `archive/` 與 `legacy/` 是歷史,改了會讓「當時長什麼樣」
#: 這條線斷掉;這支自己也不能改(它必須留著舊格式的正則)。
SOURCE_SKIP = ("archive/", "legacy/", "scratchpad/", "migrate_docid.py", "docid.py")

#: 撞名時留哪一份。見檔頭第 3 點。
COLLISION_KEEP = {"202102_玉山_個體": "202102_5847_AI3"}

#: ⚠️ **尾端不能用 `\b`。** 實測踩過:`work/rejected/202204_5841_AI3__Trading.json`
#: 這種 `{doc}__{類別}` 的檔名,`AI3` 後面接的是底線(也是 word 字元),
#: `\b` 不成立 → 整批人工裁示狀態(blocked/rejected)靜靜沒被改到。
#: 改用 `(?!\d)`:擋住 `AI35` 被當成 `AI3`,但底線、點、引號都照樣接得上。
_OLD_RE = re.compile(r"(?<!\d)(\d{6})_(\d{4})_AI(\d)(?!\d)")


def build_mapping():
    """→ `(mapping, unknown, collisions)`。

    `mapping`  舊 doc id → 新 doc id(已解決撞名)
    `unknown`  封面判不出口徑的舊 doc id(要搬 archive)
    `collisions` 新名 → [被它吃掉的舊名, ...](只列真的多對一的)
    """
    mapping, unknown = {}, []
    by_new = {}
    for p in sorted(glob.glob("pdf_cache/*.pdf")):
        old = os.path.basename(p)[:-4]
        m = _OLD_RE.fullmatch(old)
        if not m:
            continue
        period, code = m.group(1), m.group(2)
        bank = config.BANKS.get(code)
        if not bank:
            raise SystemExit(f"✗ {old}:代碼 {code} 不在 config.BANKS,先補設定再跑")
        basis = locate.locate(p).basis
        if basis not in docid.BASES:
            unknown.append(old)
            continue
        new = docid.make(period, bank, basis)
        mapping[old] = new
        by_new.setdefault(new, []).append(old)

    collisions = {n: olds for n, olds in by_new.items() if len(olds) > 1}
    for new, olds in collisions.items():
        keep = COLLISION_KEEP.get(new)
        if keep not in olds:
            raise SystemExit(
                f"✗ {new} 由 {olds} 撞名,但 COLLISION_KEEP 沒說留哪一份。\n"
                f"  這是要人決定的事(哪一份抄得完整),不准由程式猜。")
        for o in olds:
            if o != keep:
                mapping.pop(o, None)          # 落選的那份:不搬,資料丟棄
    return mapping, unknown, collisions


def rewrite_text(text, mapping):
    """把文字裡所有舊 doc id 換成新的。**逐個查表,查不到就原樣留著** ——
    盲目正則替換會把沒在計畫裡的名字(例如已決定丟棄的那份)也改掉。"""
    return _OLD_RE.sub(lambda m: mapping.get(m.group(0), m.group(0)), text)


def migrate_files(mapping, unknown, write):
    """搬檔 + 改內容。回傳 (改名數, 改內容數, 搬進 archive 數, 丟棄數)。"""
    renamed = content = archived = dropped = 0
    for d in STATE_DIRS:
        if not os.path.isdir(d):
            continue
        # `**/*` 才涵蓋得到子目錄 —— `work/blocked/`、`work/rejected/`、
        # `out/pages/` 都在第二層,只掃一層會把人工裁示狀態整批漏掉。
        for p in sorted(glob.glob(f"{d}/**/*", recursive=True)):
            if os.path.isdir(p):
                continue
            base = os.path.basename(p)
            stem, ext = os.path.splitext(base)

            if stem in unknown:
                dst = os.path.join(ARCHIVE_DIR, d.replace("/", "_"), base)
                print(f"  archive  {p} → {dst}")
                if write:
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    shutil.move(p, dst)
                archived += 1
                continue

            m = _OLD_RE.fullmatch(stem)
            if m and stem not in mapping:
                print(f"  丟棄     {p}(撞名落選,見 COLLISION_KEEP)")
                if write:
                    os.remove(p)
                dropped += 1
                continue

            # **檔名不一定「整個」就是 doc id** —— `work/blocked/{doc}__{類別}.json`
            # 與 `out/pages/{doc}_p38.png` 都是「doc id + 後綴」。用替換而不是
            # 查表,才涵蓋得到這兩種(漏掉的後果是人工裁示狀態沒跟著改名)。
            new_stem = rewrite_text(stem, mapping)
            # ⚠️ 用**這個檔自己的目錄**組新路徑,不是用頂層的 `d` ——
            # 遞迴掃描之後用 `d` 會把子目錄整個抹平(實測把
            # `work/rejected/x.json` 搬成 `work/x.json`,連 `out/report/` 都被搬走)。
            new_p = os.path.join(os.path.dirname(p), new_stem + ext)

            # 內容:只有文字檔要改(PDF 是二進位,跳過)
            if ext in (".json", ".jsonl", ".txt", ".md"):
                try:
                    raw = open(p, encoding="utf-8").read()
                except (UnicodeDecodeError, IsADirectoryError):
                    raw = None
                if raw is not None:
                    new_raw = rewrite_text(raw, mapping)
                    if new_raw != raw:
                        print(f"  內容     {p}")
                        if write:
                            open(p, "w", encoding="utf-8").write(new_raw)
                        content += 1

            if new_p != p:
                print(f"  改名     {p} → {new_p}")
                if write:
                    os.rename(p, new_p)
                renamed += 1
    return renamed, content, archived, dropped


def migrate_sources(mapping, write):
    """原始碼裡硬編的 doc id 一起換。回傳改到的檔數。"""
    n = 0
    seen = set()
    for pat in SOURCE_GLOBS:
        for p in sorted(glob.glob(pat)):
            if p in seen or any(s in p for s in SOURCE_SKIP):
                continue
            seen.add(p)
            try:
                raw = open(p, encoding="utf-8").read()
            except (UnicodeDecodeError, IsADirectoryError):
                continue
            new = rewrite_text(raw, mapping)
            if new != raw:
                print(f"  原始碼   {p}")
                if write:
                    open(p, "w", encoding="utf-8").write(new)
                n += 1
    return n


def migrate_db(mapping, unknown, write, db="facts.db"):
    """三張表的 `doc` 欄。撞名落選與 unknown 的列**刪掉**,不留孤兒。"""
    if not os.path.exists(db):
        return {}
    con = sqlite3.connect(db)
    stats = {}
    try:
        for table in ("documents", "observations", "rulings"):
            docs = [r[0] for r in con.execute(f"select distinct doc from {table}")]
            upd = dele = 0
            for old in docs:
                if old in unknown or (_OLD_RE.fullmatch(old) and old not in mapping):
                    n = con.execute(f"select count(*) from {table} where doc=?",
                                    (old,)).fetchone()[0]
                    if write:
                        con.execute(f"delete from {table} where doc=?", (old,))
                    dele += n
                elif old in mapping:
                    n = con.execute(f"select count(*) from {table} where doc=?",
                                    (old,)).fetchone()[0]
                    if write:
                        con.execute(f"update {table} set doc=? where doc=?",
                                    (mapping[old], old))
                    upd += n
            stats[table] = (upd, dele)
        if write:
            con.commit()
    finally:
        con.close()
    return stats


def main(argv=None):
    ap = argparse.ArgumentParser(description="doc id 遷移:代碼+AI編號 → 銀行名+口徑")
    ap.add_argument("--write", action="store_true", help="真的改(預設只印計畫)")
    a = ap.parse_args(argv)

    mapping, unknown, collisions = build_mapping()

    print(f"對照表 {len(mapping)} 筆(例:"
          f"{list(mapping.items())[0][0]} → {list(mapping.items())[0][1]})")
    if collisions:
        print(f"\n撞名 {len(collisions)} 組:")
        for new, olds in collisions.items():
            keep = COLLISION_KEEP[new]
            print(f"  {new} ← {olds};留 {keep},其餘丟棄")
    print(f"\n封面判不出口徑 {len(unknown)} 份 → {ARCHIVE_DIR}/")
    for u in unknown:
        print(f"  {u}")

    print(f"\n{'=== 實際執行 ===' if a.write else '=== dry-run(不動任何檔)==='}")
    r, c, ar, dr = migrate_files(mapping, unknown, a.write)
    src = migrate_sources(mapping, a.write)
    stats = migrate_db(mapping, unknown, a.write)

    print(f"\n檔案:改名 {r} · 改內容 {c} · 進 archive {ar} · 丟棄 {dr} · 原始碼 {src}")
    for t, (u, d) in stats.items():
        print(f"DB {t}: 更新 {u} 列 · 刪除 {d} 列")
    if not a.write:
        print("\n(dry-run:什麼都沒動。加 --write 才會真的改)")


if __name__ == "__main__":
    main()
