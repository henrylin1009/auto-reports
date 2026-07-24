# -*- coding: utf-8 -*-
"""零設定通用抽取機 — C 版。①定位交給 LLM,其餘走 schema.py 規則。

用法(半自動,LLM=你/Claude):
  1. candidates(path, cls) → 倒出所有候選頁文字(程式不預選,LLM 自己挑)
  2. LLM 讀候選 → 判斷「明細表在哪頁」+ 讀出 [(品名, 當期金額)...] + 錨
  3. check(rows, anchor) → 用 schema.py 規則對桶 + 對帳,過才收
"""
import re
import pdfplumber
import schema as S


def balance_sheet_anchor(path, cls):
    """讀資產負債表對應科目的當期金額(仟元)=最權威的外部錨。
       Trading 應與明細表合計『完全相等』;OCI/AC 因含權益/評價僅供合理範圍。
       字元湯(兆豐)讀不到 → 回 None,退回 unified 座標對帳把關。"""
    lab = S.ANCHOR_BS[cls]
    code = {"Trading": "12000", "OCI": "12100", "AC": "12200"}[cls]
    with pdfplumber.open(path) as pdf:
        for pg in pdf.pages:
            t = pg.extract_text() or ""
            # 連換行一起正規化:資產側標籤常被斷行拆散(「…金融資\n產」),只去空格會漏。
            flat = re.sub(r"\s", "", t)
            # 必須是『真正的資產負債表』(有負債權益總計),否則會誤中附註頁的同名子項。
            if "資產負債表" not in flat or ("負債及權益總計" not in flat and "負債總計" not in flat):
                continue
            # 掃『每一個』標籤/代碼命中,排除權益側同名項(「…金融資產未實現損益」),
            # 取後面第一個含逗號大數。同名的資產側才是我們要的外錨。
            for m in list(re.finditer(re.escape(lab), flat)) + \
                     list(re.finditer(code + r"(?:透過|按)", flat)):
                tail = flat[m.end():m.end() + 10]
                if tail.startswith("未實現") or tail.startswith("損益"):
                    continue                      # 權益側評價準備,不是資產 → 跳過
                num = re.search(r"\d{1,3}(?:,\d{3})+", flat[m.start():m.start() + 120])
                if num:
                    return int(num.group().replace(",", ""))
    return None


def _bs_pages(path, cap=2):
    """擷取『真正的資產負債表』頁(供 LLM 讀外錨),回傳 page_rows 座標對齊文字。
       含負債權益總計才算(避免抓到附註)。用『代碼|標籤|本期|去年』對齊格式餵 LLM——
       這是業界 layout-aware linearization:標籤折行、數字分欄都靠對齊保留關聯,
       不再是被 extract_text 打散的線性文字(通用,非 per-format)。"""
    import unified
    out = []
    with pdfplumber.open(path) as pdf:
        for i, pg in enumerate(pdf.pages):
            t = pg.extract_text() or ""
            if "資產負債表" in t and ("負債及權益總計" in t or "負債總計" in t):
                aligned = "\n".join(" | ".join(cells) for _, cells in unified.page_rows(pg))
                out.append((i, aligned))
                if len(out) >= cap:
                    break
    return out


def resolve_bs_anchor(path, cls):
    """外錨解析:先用 regex 快速路徑(乾淨新格式);失敗(None)才交 LLM
       (自動處理舊格式:債務工具投資別名、流動+非流動相加、斷行分欄)。
       回傳 (外錨仟元 or None, 來源'regex'/'llm'/None)。"""
    a = balance_sheet_anchor(path, cls)
    if a is not None:
        return a, "regex"
    import llm_reader
    a = llm_reader.read_bs_anchor(_bs_pages(path), S.ANCHOR_BS[cls])
    return (a, "llm") if a is not None else (None, None)


def candidates(path, cls):
    """回傳 [(page_index, text)]:含該分類標題的頁,並依 SOURCE 做『範圍分區』收斂。
       用文件自身結構(頁首含『明細表』= 明細表區,否則主附註區)把兩區分開:
         OCI/AC(要主附註)→ 排除明細表頁;Trading(要明細表)→ 優先明細表頁。
       這修掉「44 頁全丟給 LLM、被同名明細表吸走挑錯」(如富邦 OCI 讀到明細表)。
       保底:分區過濾後為空 → 退回全部候選(寧可多餵,不可漏;挑錯仍有對帳/防呆接住)。"""
    titles = S.TITLES[cls]
    want_detail = "明細表" in S.SOURCE[cls]        # Trading 要明細表;OCI/AC 要主附註
    hits = []
    with pdfplumber.open(path) as pdf:
        for i, pg in enumerate(pdf.pages):
            t = pg.extract_text() or ""
            if not any(kw in t for kw in titles):
                continue
            head = "\n".join(t.splitlines()[:4])    # 只看頁首,避免正文交叉引用「明細表」誤判
            is_detail = "明細表" in head
            if _is_soup(t):
                t = _coord_text(pg)                 # 字元湯 → 座標重組(黑箱①取行)
            hits.append((i, t, is_detail))
    if want_detail:
        pref = [(i, t) for i, t, d in hits if d]
    else:
        pref = [(i, t) for i, t, d in hits if not d]
    return pref or [(i, t) for i, t, _ in hits]     # 保底:空則退回全部


def _is_soup(text):
    """偵測字元湯:很多單字行(表格被打散成一字一行)。"""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    singles = sum(1 for l in lines if len(l) <= 2 and re.search(r"[一-鿿]", l))
    return singles >= 6


def _coord_text(page):
    """座標重組:把散開的字元依 x/y 還原成『品名 數字 數字』的行,餵給 LLM。"""
    import unified
    rows = unified.page_rows(page)
    return "\n".join(" ".join(cells) for _, cells in rows)


def check(rows, anchor, cls=None, bs_anchor=None, groups=None):
    """LLM 讀出的 [(品名, 當期金額)] + 錨 → 對桶 + 對帳(內錨:表合計)。
       bs_anchor(資產負債表外錨)給定時做交叉驗證:
         Trading → 表合計必須 == 資產負債表(抓錯表最強護欄);
         OCI/AC  → 資產負債表含權益/評價,只當合理上界(抽到總額不得超過它)。
       回傳 dict:{桶:億元, 股票:億元, _pass, _cross, ...}。"""
    buckets = {b: 0 for b in S.BUCKETS}
    stock = 0
    bsum = esum = 0
    unknown = []
    extra_named = []          # 具名保留 reconcile-only 列(評價調整/減損…),供類層 _class 用
    for name, v in rows:
        if S.is_reconcile_only(name):
            esum += v
            extra_named.append((name, v))
            continue
        b = S.bucket_of(name)
        if b:
            buckets[b] += v
            bsum += v
        elif S.is_equity(name):
            stock += v          # 股票不入 7 桶對帳(債券子表);Trading 另計
        else:
            unknown.append(name)   # schema 沒見過 → 待 LLM 臨場判斷
    total = bsum + esum + stock
    ok = S.reconciles(bsum, esum + stock, anchor)

    # 外錨交叉驗證(#2):表的總合計必須 == 資產負債表(防抓錯同名表)。
    # 三類統一「必須相等」——前提:OCI 連權益工具一起抽(股票桶)、AC 吸收減損,
    # 讀『整則』的總合計(非債券小計),故三類皆等於資產負債表,不再分類別。
    # 外錨交叉驗證,含「比值荒謬→不採信」保險:外錨經 LLM 讀後仍與內錨差 >3 倍/<1/3,
    # 幾乎必是外錨抓錯行(同科目不可能差幾倍)→ 不硬擋,退回內部對帳+小計自洽把關。
    cross = None
    cross_unreliable = False
    if bs_anchor is not None and anchor:
        if abs(anchor - bs_anchor) <= max(S.RECON_ABS, S.RECON_REL * abs(bs_anchor)):
            cross = True
        else:
            ratio = abs(bs_anchor) / abs(anchor)
            if ratio > 3 or ratio < 1 / 3:
                cross = None
                cross_unreliable = True          # 外錨明顯壞 → 忽略,不誤殺
            else:
                cross = False                    # 中度不符 → 真可疑,硬擋
        if cross is False:
            ok = False

    # 分組小計自洽(#1/#4):每段 rows 加總須==該段印出的小計。
    # 補償誤差(A桶多讀、B桶少讀同額)只要跨小計段就被抓;位數看錯也多半破壞某段小計。
    # 僅在「該段有印小計」時驗,查不到就跳過(不製造假警報)。
    subtotal_fail = []
    if groups:
        for g in groups:
            sub = g.get("subtotal")
            if sub is None:
                continue
            s = sum(v for _, v in g.get("rows", []))
            if abs(s - sub) > max(S.RECON_ABS, S.RECON_REL * abs(sub)):
                subtotal_fail.append({"section": g.get("section", ""),
                                      "rows_sum": s, "printed": sub, "diff": s - sub})
        if subtotal_fail:
            ok = False

    res = {b: round(buckets[b] / S.THOUSAND_TO_YI, 2) for b in S.BUCKETS}
    res["股票"] = round(stock / S.THOUSAND_TO_YI, 2)
    res["_pass"] = ok
    res["_cross"] = cross
    res["_cross_unreliable"] = cross_unreliable
    res["_bucket_sum"] = bsum
    res["_extra_sum"] = esum + stock
    res["_anchor"] = anchor
    res["_bs_anchor"] = bs_anchor
    res["_unknown"] = unknown
    res["_extra_named"] = extra_named    # [(品名, 仟元)] 例:[("評價調整", -19600000)]
    res["_bucket_sum_k"] = bsum          # Σ各桶(仟元,精確)——#2 算術反推用
    res["_stock_sum_k"] = stock          # 股票(仟元,精確)——#2 算術反推用
    res["_subtotal_fail"] = subtotal_fail
    return res


_CLS_NAME = {"Trading": "透過損益按公允價值衡量之金融資產",
             "OCI": "透過其他綜合損益按公允價值衡量之金融資產",
             "AC": "按攤銷後成本衡量之債務工具投資"}


def auto_extract(path, cls, models=("deepseek-chat", "deepseek-reasoner", "deepseek-reasoner"),
                 source=None, measure=None, use_bs=True):
    """端到端(DeepSeek 讀值):候選頁 → LLM 讀 → 對桶 + 對帳。
       第一手 deepseek-chat(V3,快);對帳不過 → 自動重讀並升級 deepseek-reasoner。
       source/measure:覆寫來源表/取值欄(雙值抽取:帳面 pass vs 公允 pass 各傳不同)。
       回傳最後一次 check() 結果(含 _pass/_cross/_page/_tries),或 {'_error':...}。"""
    import llm_reader
    cands = candidates(path, cls)
    if not cands:
        return {"_error": "無候選頁"}
    bs, bs_src = resolve_bs_anchor(path, cls) if use_bs else (None, None)
    last = None
    for k, model in enumerate(models, 1):
        got = llm_reader.read_note(
            cands, cls, cls_title=S.TITLES[cls][0],
            cls_name=_CLS_NAME[cls], measure=measure or S.MEASURE[cls],
            source=source or S.SOURCE[cls], model=model)
        res = check(got["rows"], got["anchor"], cls=cls, bs_anchor=bs, groups=got.get("groups"))
        res["_page"] = got.get("page")
        res["_tries"] = k
        res["_model"] = model
        res["_bs_src"] = bs_src
        # 方法1 防呆:LLM 自報讀的是哪種表,須符合 SOURCE 指定。
        # 非對稱:公允 pass(source=明細表)必須讀明細表(讀主附註=兆豐股票成本 bug);
        #   帳面 pass(source=主附註)OCI/AC 必須主附註,但 Trading 讀明細表也對(明細表有成本欄)。
        st = got.get("source_type")
        if "明細表" in (source or S.SOURCE[cls]):
            ok_type = (st == "明細表")
        else:
            ok_type = (st == "主附註") or (cls == "Trading")
        res["_source_type"] = st
        res["_source_header"] = got.get("header")
        res["_source_type_ok"] = ok_type            # 軟旗標:併入待人工,不硬擋
        last = res
        if res["_pass"]:            # 過對帳(含交叉)→ 收工,不再重讀
            return res
    return last                     # 全試完仍不過 → 回最後一次(標記未過,待人工)


def _valuation_adj_kw(extra_named):
    """(僅交叉檢查用)從具名 reconcile-only 列挑出『評價調整』字樣者,回傳仟元加總。
       主要值改用算術反推(見 auto_extract_dual);此函式只當對照,措辭變了會漏是已知。"""
    kw = ("評價調整", "評價損益", "評價（損）益", "評價(損)益", "公允價值變動")
    return sum(v for n, v in (extra_named or [])
               if any(k in str(n).replace(" ", "") for k in kw))


def _yi(v):
    return None if v is None else round(v / S.THOUSAND_TO_YI, 2)


# #3:哪些類要跑「公允 pass」(讀明細表補『逐桶』公允)。只有 Trading 需要。
#   Trading:某些家主附註股票列=取得成本,必須讀明細表才拿到公允 → 跑。
#   OCI:逐桶公允只在明細表(兆豐/中信 是湯/無表→常 N/A),報酬低成本高 → 不跑。
#        整類公允總額改由 BS 錨免費取得,逐桶只給帳面(成本)。
#   AC:攤銷後成本即正解,無逐桶市價需求 → 不跑。
# 結論:除 Trading 外全部單 pass —— 心智模型「只有 Trading 特殊」。
_FAIR_PASS_CLASSES = ("Trading",)


def auto_extract_dual(path, cls):
    """雙值抽取(輸出方案 B:每格 {v,ok} + 類層 _class + _meta)。
       帳面 pass:讀主附註成本欄(五家三類都有)。
       公允 pass:只對 Trading/OCI 跑(讀明細表公允欄);AC 不跑(_FAIR_PASS_CLASSES)。
       類層 _class 用『算術反推』(#2,不靠 LLM 具名):
         帳面總額 = Σ各桶成本 + 股票成本(主附註,精確仟元)
         公允總額 = 資產負債表錨(Trading/OCI=公允;AC=攤銷成本≈帳面);讀不到才退主附註合計
         評價調整 = 公允總額 − 帳面總額(措辭無關;與具名評價調整交叉檢查)
       單位:_class 皆億元。"""
    book = auto_extract(
        path, cls, source="主附註(財報正文附註);取各桶『帳面金額/取得成本』欄,非公允價值",
        measure="帳面金額/取得成本")
    bpass = bool(book.get("_pass"))

    if cls in _FAIR_PASS_CLASSES:
        fair = auto_extract(
            path, cls, source="附錄明細表;取各桶『公允價值(總額)』欄",
            measure="公允價值")
        fpass = bool(fair.get("_pass"))
    else:
        fair, fpass = {}, False                     # AC:不跑公允 pass

    cols = list(S.BUCKETS) + ["股票"]
    buckets = {}
    for b in cols:
        buckets[b] = {
            "帳面": {"v": book.get(b), "ok": True} if bpass else None,
            "公允": {"v": fair.get(b), "ok": True} if fpass else None,
        }

    # #2 算術反推:帳面總額=Σ成本;公允總額=BS錨(退主附註合計);評價調整=兩者差。
    bk = book.get("_bucket_sum_k")
    sk = book.get("_stock_sum_k")
    book_total = (bk + sk) if (bk is not None and sk is not None) else book.get("_anchor")
    fair_total = book.get("_bs_anchor")
    if fair_total is None:
        fair_total = book.get("_anchor")            # BS 錨讀不到 → 退主附註最後合計(通常=公允)
    adj = (fair_total - book_total) if (fair_total is not None and book_total is not None) else None
    adj_kw = _valuation_adj_kw(book.get("_extra_named"))   # 交叉檢查:應與 adj 相近
    klass = {"帳面總額": _yi(book_total), "公允總額": _yi(fair_total), "評價調整": _yi(adj)}

    return {
        "buckets": buckets,
        "class": klass,
        "_meta": {
            "book_page": book.get("_page"), "fair_page": fair.get("_page"),
            "book_pass": bpass, "fair_pass": fpass,
            "book_cross": book.get("_cross"), "fair_cross": fair.get("_cross"),
            "book_model": book.get("_model"), "fair_model": fair.get("_model"),
            "book_subtotal_fail": book.get("_subtotal_fail"),
            "fair_subtotal_fail": fair.get("_subtotal_fail"),
            "adj_kw_check": _yi(adj_kw),             # 具名評價調整(對照 _class.評價調整)
            "fair_pass_skipped": cls not in _FAIR_PASS_CLASSES,
            # 方法1 表型防呆:自報表型是否符 SOURCE + 頁首原文(供人核對挑對表)。
            "book_source_type": book.get("_source_type"),
            "book_source_type_ok": book.get("_source_type_ok"),
            "book_source_header": book.get("_source_header"),
            "fair_source_type": fair.get("_source_type"),
            "fair_source_type_ok": fair.get("_source_type_ok"),
            "fair_source_header": fair.get("_source_header"),
            "book_unknown": book.get("_unknown"),      # schema 對不到桶的新品名 → 待補同義字
            "fair_unknown": fair.get("_unknown"),
            "bs_src": book.get("_bs_src"),             # 外錨來源:regex(乾淨新格式)/ llm(舊格式)
            "book_cross_unreliable": book.get("_cross_unreliable"),   # 外錨比值荒謬被忽略
        },
    }


if __name__ == "__main__":
    import sys
    path, cls = sys.argv[1], sys.argv[2]
    if "--auto" in sys.argv:
        import json
        r = auto_extract(path, cls)
        print(json.dumps({k: v for k, v in r.items()}, ensure_ascii=False, indent=2))
    else:
        for i, t in candidates(path, cls):
            print(f"\n===== PAGE {i} =====\n{t}")
