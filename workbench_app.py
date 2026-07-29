# -*- coding: utf-8 -*-
"""複核台(S1 總覽 / S2 裁示台 / S3 抄列台)。docs/plan_ui_redesign.md 的落地。

    streamlit run workbench_app.py

只做 2023+(§一裁示①)。直接 import 既有模組,不經 HTTP —— 寫入一律走既有出口
(fill.py submit/requeue、buckets.SYN),**不新增任何接受分支**。
"""
import glob
import json
import os
import re

import streamlit as st

import buckets
import config
import facts as facts_mod
import fill
import locate
import rules
import transcribe
from core import queue as queue_mod

st.set_page_config(page_title="複核台", layout="wide")

CUTOFF_YEAR = 2023


def _2023_docs():
    return sorted(d for d in fill._all_docs() if int(d[:4]) >= CUTOFF_YEAR)


def _split(doc):
    period, bank, code = doc.split("_")
    return period, bank, code


@st.cache_data(ttl=60)
def _load_index_cached(sig_key):
    return fill._load_index()


def _index():
    # fill._pdf_signature() 已經比 pdf_cache/ 的 mtime,這裡只是給 st.cache_data
    # 一把可雜湊的鑰匙,行為與 CLI 版 fill.py 完全一致(同一份 work/index.json)。
    return _load_index_cached(tuple(fill._pdf_signature()))


def _cell_status(cells, blocked_by_cell, index, doc, cls):
    key = f"{doc}|{cls}"
    if key in cells:
        return "done"
    if key in blocked_by_cell:
        return "blocked"
    if index["cells"].get(doc, {}).get(cls):
        return "todo"
    return "na"  # 錨讀不到或無候選頁 —— 2023+ 範圍內基準是 0,但欄位仍留著防假設過期


# ---------------------------------------------------------------- 總覽 ----
def page_overview():
    st.title("總覽 · 2023+")
    cells = facts_mod.load()
    blocked_by_cell = queue_mod.by_cell()
    index = _index()
    docs = _2023_docs()

    periods = sorted({_split(d)[0] for d in docs}, reverse=True)
    columns = sorted({(_split(d)[1], _split(d)[2]) for d in docs})
    banks = sorted({b for b, _ in columns})
    codes = sorted({c for _, c in columns})

    with st.sidebar:
        st.header("篩選")
        f_bank = st.multiselect("銀行", banks, default=banks)
        f_code = st.multiselect("代碼", codes, default=codes)
        f_status = st.selectbox("狀態", ["全部", "只看待抄", "只看卡住"])

    columns = [(b, c) for b, c in columns if b in f_bank and c in f_code]

    n_done = n_todo = n_blocked = n_na = 0
    grid = {}
    for period in periods:
        for bank, code in columns:
            doc = f"{period}_{bank}_{code}"
            if doc not in docs:
                grid[(period, bank, code)] = None  # 空白:那期沒這份檔
                continue
            states = [_cell_status(cells, blocked_by_cell, index, doc, cls)
                      for cls in locate.CLASSES]
            n_done += states.count("done")
            n_todo += states.count("todo")
            n_blocked += states.count("blocked")
            n_na += states.count("na")
            grid[(period, bank, code)] = states

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("已抄(格×類)", n_done)
    c2.metric("可抄", n_todo)
    c3.metric("卡住", n_blocked)
    c4.metric("無候選頁", n_na)

    def _fmt(states):
        if states is None:
            return ""
        done = states.count("done")
        total = sum(1 for s in states if s != "na")
        if total == 0:
            return "—"
        mark = " ⚠" if "blocked" in states else ""
        return f"{done}/{total}{mark}"

    if f_status == "只看待抄":
        keep = lambda states: states and any(s == "todo" for s in states)
    elif f_status == "只看卡住":
        keep = lambda states: states and any(s == "blocked" for s in states)
    else:
        keep = lambda states: True

    header = st.columns([1] + [1] * len(columns))
    header[0].markdown("**期別**")
    for i, (bank, code) in enumerate(columns):
        header[i + 1].markdown(f"**{bank} {code}**")

    for period in periods:
        row_states = [grid[(period, bank, code)] for bank, code in columns]
        if not any(keep(s) for s in row_states):
            continue
        row = st.columns([1] + [1] * len(columns))
        row[0].write(period)
        for i, (bank, code) in enumerate(columns):
            states = grid[(period, bank, code)]
            label = _fmt(states)
            cell = row[i + 1]
            if not keep(states):
                cell.write("")
                continue
            if cell.button(label or "·", key=f"cell_{period}_{bank}_{code}",
                            disabled=(states is None)):
                st.session_state["picked_doc"] = f"{period}_{bank}_{code}"
                st.session_state["nav"] = "抄列台" if "todo" in (states or []) else "裁示台"
                st.rerun()

    if st.session_state.get("picked_doc"):
        doc = st.session_state["picked_doc"]
        with st.expander(f"{doc} 細節", expanded=True):
            for cls in locate.CLASSES:
                s = _cell_status(cells, blocked_by_cell, index, doc, cls)
                st.write(f"- **{cls}**:{s}")


# -------------------------------------------------------------- 裁示台 ----
def page_dispose():
    st.title("裁示台 · 分桶對不到")
    todo = queue_mod.pending()
    blocked = [e for e in todo if e["source"] == "blocked"]
    if not blocked:
        st.success("沒有卡住的名字。")
        return

    by_cell = {}
    for e in blocked:
        by_cell.setdefault(e["cell_key"], []).append(e)

    cell_key = st.selectbox("格子", sorted(by_cell))
    entries = by_cell[cell_key]
    doc, cls = cell_key.split("|", 1)

    st.caption(f"{len(entries)} 個名字待裁示 · 來源 {entries[0]['ref'].get('path')}")

    for e in entries:
        st.markdown(f"### 「{e['name']}」")
        st.write(f"提案:{e['suggested'] or '(無 —— 規則沒有關鍵字命中)'}　·　{e['why']}")
        options = [""] + config.BUCKETS
        default = options.index(e["suggested"]) if e["suggested"] in options else 0
        col1, col2 = st.columns([2, 3])
        bucket = col1.selectbox("歸桶", options, index=default,
                                 key=f"bucket_{cell_key}_{e['name']}")
        reason = col2.text_input("理由(進 buckets.py 註解)",
                                  value=e["why"], key=f"reason_{cell_key}_{e['name']}")
        if st.button(f"送出「{e['name']}」→「{bucket}」", key=f"submit_{cell_key}_{e['name']}",
                     disabled=not bucket):
            _confirm_bucket(e["name"], bucket, reason)
            st.success(f"「{e['name']}」已收錄進 buckets.SYN(bucket.py),"
                       f"需要 git diff 審過再 commit。")
            st.rerun()

    st.divider()
    if st.button("這格全部裁完了 → requeue(放回待抄佇列)"):
        p = entries[0]["ref"]["path"]
        if os.path.exists(p):
            os.remove(p)
        st.success("已放回佇列,回總覽可以再抄一次。")
        st.session_state.pop("picked_doc", None)
        st.rerun()


def _confirm_bucket(name, bucket, reason):
    """把人工裁示寫進 buckets.SYN。**這是唯一寫入點**,對應 fill.py 印出的指示
    「請使用者審核後收錄進 buckets.SYN」——不是新發明的接受分支。"""
    norm = buckets.norm(name)
    if norm in buckets._SYN_N:
        return
    text = open("buckets.py", encoding="utf-8").read()
    marker = "SYN = {"
    idx = text.index(marker) + len(marker)
    insertion = (f'\n    # {reason}(工作台裁示,{_today()})\n'
                 f'    {name!r}: {bucket!r},')
    new_text = text[:idx] + insertion + text[idx:]
    open("buckets.py", "w", encoding="utf-8").write(new_text)
    buckets._SYN_N[norm] = bucket  # 讓本次 session 立刻生效,不必重啟


def _today():
    import datetime
    return datetime.date.today().isoformat()


# -------------------------------------------------------------- 抄列台 ----
def page_transcribe():
    st.title("抄列台 · 待抄")
    cells = facts_mod.load()
    rejected = fill._rejected_keys()
    index = _index()
    docs = _2023_docs()

    todo_cells = []
    for doc in sorted(docs, key=fill._doc_sort_key):
        for cls in locate.CLASSES:
            key = f"{doc}|{cls}"
            if key in cells or key in rejected:
                continue
            if index["cells"].get(doc, {}).get(cls):
                todo_cells.append((doc, cls))

    if not todo_cells:
        st.success("2023+ 範圍內沒有待抄的格子了。")
        return

    default = st.session_state.get("picked_doc")
    labels = [f"{d}｜{c}" for d, c in todo_cells]
    default_idx = 0
    if default:
        for i, (d, c) in enumerate(todo_cells):
            if d == default:
                default_idx = i
                break
    picked = st.selectbox("選一格", labels, index=default_idx)
    doc, cls = todo_cells[labels.index(picked)]

    loc = locate.locate(f"pdf_cache/{doc}.pdf")
    pages = list(loc.pages[cls])
    anchor = loc.anchors[cls]

    st.info(f"錨(BS 合計)= {anchor:,} 仟元　·　候選頁(0-based)= {pages}")
    with st.expander("抄列規矩", expanded=False):
        st.text(fill.RULES)

    col_img, col_form = st.columns([1, 1])

    with col_img:
        page_i = st.selectbox("頁面", pages, format_func=lambda p: f"p.{p + 1}")
        img = _render_page(doc, page_i)
        st.image(img, use_container_width=True)

    with col_form:
        st.caption("直接編輯 JSON(格式同 fill.py 印出的規矩),對應 work/current.json。")
        template = json.dumps(
            {"records": [{"source_page": pages[0] + 1, "source_kind": "附註",
                          "total_col": "", "printed_total": anchor,
                          "rows": [{"name": "", "group": "", "cols": {}}]}]},
            ensure_ascii=False, indent=1)
        raw = st.text_area("records JSON", value=template, height=420,
                            key=f"raw_{doc}_{cls}")
        if st.button("送出(走 fill.py submit,六道檢查照跑)"):
            _submit(doc, cls, pages, raw)


@st.cache_data(ttl=3600)
def _render_page(doc, page_i):
    import pypdfium2 as pdf
    d = pdf.PdfDocument(f"pdf_cache/{doc}.pdf")
    page = d[page_i]
    return page.render(scale=1.6).to_pil()


def _submit(doc, cls, pages, raw):
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as ex:
        st.error(f"JSON 格式錯:{ex}")
        return
    os.makedirs(fill.WORK_DIR, exist_ok=True)
    json.dump({"doc": doc, "cls": cls, "level": 0, "pages": pages, "retries": 0},
              open(fill.PENDING, "w", encoding="utf-8"))
    cur = fill.WORK_DIR + "/current_ui.json"
    json.dump(data, open(cur, "w", encoding="utf-8"), ensure_ascii=False)

    import io
    import contextlib
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            fill.cmd_submit(cur)
    except SystemExit:
        pass
    out = buf.getvalue()
    st.text(out)
    if out.startswith("PASS"):
        st.success("已歸檔。")
        st.session_state.pop("picked_doc", None)
    elif out.startswith("BLOCKED"):
        st.warning("卡在分類表缺口,去裁示台處理。")
    st.rerun()


# ---------------------------------------------------------------- main ----
def main():
    nav_default = st.session_state.get("nav", "總覽")
    page = st.sidebar.radio("畫面", ["總覽", "裁示台", "抄列台"],
                             index=["總覽", "裁示台", "抄列台"].index(nav_default))
    st.session_state["nav"] = page
    if page == "總覽":
        page_overview()
    elif page == "裁示台":
        page_dispose()
    else:
        page_transcribe()


if __name__ == "__main__":
    main()
