# -*- coding: utf-8 -*-
"""通用視覺化層。R3(`docs/plan_v6_一台機器.md`)。

**判準只有一句話,寫在這裡兌現:換一份 `schema.yaml`,這支code 要照樣畫得出
矩陣、逐桶表、時間序列、缺漏標示。** `test_viz_generic.py` 用一份完全不提
銀行、債券、任何本專案字眼的假 schema(3 實體 × 4 期 × 3 桶)證明這件事,
那份假 schema 進 repo 當回歸測試 —— 沒有它,「脫鉤」只是把程式碼搬到
另一個檔案,不是真的脫鉤。

**這支不准 `import config`,不准出現任何銀行名字、`US10Y`、`BANKHUE` 這類
題目專屬的東西。** 那些留在 `make_web.py`(題目層),通用層只認
`schema.Schema` 這一個契約。

輸出是**自足的單檔 HTML**(同 `make_web.py` 的既有規範,`test_report.py`
E4 驗過的那條:離線可看、無外部 http(s) 請求)——用 SVG 畫時間序列,
不掛任何圖表函式庫。
"""
import html as _html


def _esc(s):
    return _html.escape(str(s), quote=True)


def _cell_completeness(schema, cell_map):
    """一格(period|entity)裡,`{dimension}_{bucket}` 齊全度。
    回 `(非 null 數, 總數)`。`cell_map` 是 None 時整格視為 0/total。
    """
    total = len(schema.dimensions) * len(schema.buckets)
    if not cell_map:
        return 0, total
    n = sum(1 for dim in schema.dimensions for bk in schema.buckets
            if cell_map.get(schema.cell_key(dim.id, bk.id)) is not None)
    return n, total


def _matrix_section(schema, periods, basis_table):
    rows = []
    for period in periods:
        cells = []
        for ent in schema.entities:
            cm = basis_table.get(f"{period}|{ent.id}")
            n, total = _cell_completeness(schema, cm)
            cls = "missing" if n == 0 else ("full" if n == total else "partial")
            cells.append(
                f'<td class="cell {cls}" title="{_esc(ent.label)} {_esc(period)}">'
                f'{n}/{total}</td>')
        rows.append(f"<tr><th>{_esc(period)}</th>{''.join(cells)}</tr>")
    header = "".join(f"<th>{_esc(e.label)}</th>" for e in schema.entities)
    return (f'<section id="matrix"><h2>矩陣</h2>'
            f'<table class="matrix"><thead><tr><th>{_esc(schema.period_label)}</th>'
            f'{header}</tr></thead><tbody>{"".join(rows)}</tbody></table></section>')


def _bucket_table_section(schema, period, basis_table):
    """逐桶表:給定一期,實體 × (維度,桶) 的完整值表。"""
    cols = [(dim, bk) for dim in schema.dimensions for bk in schema.buckets]
    header = "".join(f"<th>{_esc(dim.label)}·{_esc(bk.label)}</th>" for dim, bk in cols)
    rows = []
    for ent in schema.entities:
        cm = basis_table.get(f"{period}|{ent.id}") or {}
        tds = []
        for dim, bk in cols:
            v = cm.get(schema.cell_key(dim.id, bk.id))
            tds.append(f'<td class="{"na" if v is None else ""}">'
                       f'{"—" if v is None else _esc(v)}</td>')
        rows.append(f"<tr><th>{_esc(ent.label)}</th>{''.join(tds)}</tr>")
    return (f'<section id="bucket-table"><h2>逐桶表 · {_esc(period)}</h2>'
            f'<table class="bucket"><thead><tr><th>{_esc(schema.entity_label)}</th>'
            f'{header}</tr></thead><tbody>{"".join(rows)}</tbody></table></section>')


def _timeseries_svg(schema, periods, basis_table, dim, bucket):
    """一個(維度,桶)組合,各實體隨期別的折線圖。純 SVG,無外部依賴。"""
    key = schema.cell_key(dim.id, bucket.id)
    series = {}
    for ent in schema.entities:
        vals = []
        for period in periods:
            cm = basis_table.get(f"{period}|{ent.id}") or {}
            vals.append(cm.get(key))
        series[ent.id] = vals

    all_vals = [v for vals in series.values() for v in vals if v is not None]
    lo, hi = (min(all_vals), max(all_vals)) if all_vals else (0, 1)
    if lo == hi:
        lo, hi = lo - 1, hi + 1
    W, H, PAD = 560, 200, 30
    n = max(len(periods) - 1, 1)

    def xy(i, v):
        x = PAD + (W - 2 * PAD) * i / n
        y = H - PAD - (H - 2 * PAD) * (v - lo) / (hi - lo)
        return x, y

    palette = ["#2563eb", "#dc2626", "#16a34a", "#d97706", "#7c3aed", "#0891b2"]
    paths, dots, legend = [], [], []
    for idx, ent in enumerate(schema.entities):
        color = palette[idx % len(palette)]
        pts = [(i, v) for i, v in enumerate(series[ent.id]) if v is not None]
        if len(pts) >= 2:
            d = " ".join(f"{'M' if k == 0 else 'L'}{xy(i, v)[0]:.1f},{xy(i, v)[1]:.1f}"
                        for k, (i, v) in enumerate(pts))
            paths.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="2"/>')
        for i, v in pts:
            x, y = xy(i, v)
            dots.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="{color}"/>')
        legend.append(f'<span class="leg"><i style="background:{color}"></i>'
                      f'{_esc(ent.label)}</span>')

    axis_labels = "".join(
        f'<text x="{xy(i, lo)[0]:.1f}" y="{H-8}" font-size="10" text-anchor="middle">'
        f'{_esc(p)}</text>' for i, p in enumerate(periods))
    svg = (f'<svg viewBox="0 0 {W} {H}" width="{W}" height="{H}">'
          f'<rect x="0" y="0" width="{W}" height="{H}" fill="none"/>'
          f'{"".join(paths)}{"".join(dots)}{axis_labels}</svg>')
    return (f'<section id="timeseries"><h2>時間序列 · {_esc(dim.label)}·{_esc(bucket.label)}</h2>'
            f'<div class="legend">{"".join(legend)}</div>{svg}</section>')


def _css():
    return """
    body{font-family:-apple-system,"PingFang TC","Noto Sans TC",sans-serif;margin:24px;
      color:#1a1a1a;background:#fff}
    table{border-collapse:collapse;margin:12px 0}
    th,td{border:1px solid #ddd;padding:4px 8px;font-size:13px;text-align:right}
    th{text-align:left;background:#f7f7f8}
    .cell.full{background:#e7f5ea}
    .cell.partial{background:#fff7e0}
    .cell.missing{background:repeating-linear-gradient(45deg,#f2f2f2,#f2f2f2 4px,#e5e5e5 4px,#e5e5e5 8px)}
    td.na{color:#999}
    .legend{display:flex;gap:14px;margin:6px 0;font-size:12px}
    .leg i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:4px}
    """


def render(schema, periods, table, basis_id=None, title=None):
    """`schema`:`schema.Schema`。`periods`:期別字串 list,舊到新。
    `table`:`{basis_id: {"{period}|{entity_id}": {cell_key: 數字或 None}}}`
    ——直接對應 `data.json` 的 `wide`/`wide_cost` 形狀,呼叫端不必轉換。

    回傳自足的 HTML 字串。**純函數,不寫檔**——寫檔是呼叫端的事。
    """
    basis_id = basis_id or schema.bases[0].id
    basis_table = table.get(basis_id) or {}

    matrix = _matrix_section(schema, periods, basis_table)
    latest = periods[-1] if periods else None
    bucket_table = _bucket_table_section(schema, latest, basis_table) if latest else ""
    timeseries = (_timeseries_svg(schema, periods, basis_table,
                                  schema.dimensions[0], schema.buckets[0])
                 if periods and schema.dimensions and schema.buckets else "")

    return f"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">
<title>{_esc(title or schema.title)}</title><style>{_css()}</style></head>
<body>
<h1>{_esc(title or schema.title)}</h1>
<p class="hint">口徑:{_esc(next((b.label for b in schema.bases if b.id == basis_id), basis_id))}</p>
{matrix}
{bucket_table}
{timeseries}
</body></html>"""
