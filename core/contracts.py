# -*- coding: utf-8 -*-
"""資料契約。**唯一知道磁碟形狀的地方**(僅限 Ring 1 讀寫的那部分)。

磁碟格式與現行 `facts/` 逐欄相同,一個欄位都不准加減 —— `REQUIRED_REC` /
`OPTIONAL_REC` / `REQUIRED_ROW` / `OPTIONAL_ROW` 直接照抄 `facts.py`。

**鐵則 3(使用者裁示)**:`parse_cell` / `Row` / `Record` **不准把「分不出桶」
寫成不合法**。契約層只管來源、結構、型別,分類是別層的事。今天
`facts.validate()` 本來就不 import `buckets`,所以這件事天然成立;
本檔刻意不加任何「桶」相關檢查,防止之後有人順手加。
"""
import facts

REQUIRED_REC = facts.REQUIRED_REC
OPTIONAL_REC = facts.OPTIONAL_REC
REQUIRED_ROW = facts.REQUIRED_ROW
OPTIONAL_ROW = facts.OPTIONAL_ROW


class Row:
    def __init__(self, name, cols, group=None):
        self.name = name
        self.cols = dict(cols)
        self.group = group

    def to_raw(self):
        d = {"name": self.name, "cols": dict(self.cols)}
        if self.group is not None:
            d["group"] = self.group
        return d


class Record:
    def __init__(self, doc, cls, source_page, source_kind, total_col,
                 printed_total, rows, printed_totals=None, note=None, _by=None):
        self.doc = doc
        self.cls = cls
        self.source_page = source_page
        self.source_kind = source_kind
        self.total_col = total_col
        self.printed_total = printed_total
        self.rows = list(rows)
        self.printed_totals = printed_totals
        self.note = note
        self._by = _by

    def to_raw(self):
        d = {"doc": self.doc, "class": self.cls, "source_page": self.source_page,
             "source_kind": self.source_kind, "total_col": self.total_col,
             "printed_total": self.printed_total,
             "rows": [r.to_raw() for r in self.rows]}
        if self.printed_totals is not None:
            d["printed_totals"] = self.printed_totals
        if self.note is not None:
            d["note"] = self.note
        if self._by is not None:
            d["_by"] = self._by
        return d


class Cell:
    def __init__(self, key, records):
        self.key = key
        self.records = list(records)

    def to_raw(self):
        return [r.to_raw() for r in self.records]


def _parse_row(raw, tag):
    missing = [f for f in REQUIRED_ROW if f not in raw]
    if missing:
        raise ValueError(f"{tag}: 缺必要欄位 {missing}")
    unknown = [f for f in raw if f not in REQUIRED_ROW + OPTIONAL_ROW]
    if unknown:
        raise ValueError(f"{tag}: 出現未知欄位 {unknown}")
    if not isinstance(raw["name"], str) or not raw["name"]:
        raise ValueError(f"{tag}: name 不是非空字串")
    if not isinstance(raw["cols"], dict):
        raise ValueError(f"{tag}: cols 不是 dict")
    for col, val in raw["cols"].items():
        if isinstance(val, bool) or not isinstance(val, int):
            raise ValueError(f"{tag}: cols[{col!r}] 不是 int:{val!r}")
    return Row(raw["name"], raw["cols"], raw.get("group"))


def _parse_record(raw, tag):
    missing = [f for f in REQUIRED_REC if f not in raw]
    if missing:
        raise ValueError(f"{tag}: 缺必要欄位 {missing}")
    unknown = [f for f in raw if f not in REQUIRED_REC + OPTIONAL_REC]
    if unknown:
        raise ValueError(f"{tag}: 出現未知欄位 {unknown}")
    if not raw["rows"]:
        raise ValueError(f"{tag}: rows 為空")
    rows = [_parse_row(r, f"{tag}.rows[{i}]") for i, r in enumerate(raw["rows"])]
    if raw.get("printed_totals") is not None:
        pt = raw["printed_totals"]
        if not isinstance(pt, dict):
            raise ValueError(f"{tag}: printed_totals 不是 dict")
        for col, val in pt.items():
            if not isinstance(col, str):
                raise ValueError(f"{tag}: printed_totals key 不是字串:{col!r}")
            if isinstance(val, bool) or not isinstance(val, int):
                raise ValueError(f"{tag}: printed_totals[{col!r}] 不是 int:{val!r}")
    return Record(raw["doc"], raw["class"], raw["source_page"], raw["source_kind"],
                  raw["total_col"], raw["printed_total"], rows,
                  printed_totals=raw.get("printed_totals"), note=raw.get("note"),
                  _by=raw.get("_by"))


def parse_cell(key, raw_records):
    """→ Cell。不合格就 raise,**不修資料**。"""
    k_doc, k_cls = key.split("|", 1)
    records = []
    for i, raw in enumerate(raw_records):
        tag = f"{key}[{i}]"
        rec = _parse_record(raw, tag)
        if rec.doc != k_doc or rec.cls != k_cls:
            raise ValueError(f"{tag}: key 與內容不一致 key={k_doc}|{k_cls} "
                              f"內容={rec.doc}|{rec.cls}")
        total_col_seen = any(rec.total_col in r.cols for r in rec.rows)
        if not total_col_seen:
            raise ValueError(f"{tag}: total_col {rec.total_col!r} 沒有出現在任何一列的 cols 裡")
        records.append(rec)
    return Cell(key, records)


def dump_cell(cell):
    """Cell → raw。滿足 `dump_cell(parse_cell(x)) == x`。"""
    return cell.to_raw()


def validate(cells):
    """轉呼叫 `facts.validate` 當第二 oracle —— 兩者必須逐條一致。"""
    raw = {key: (cell.to_raw() if isinstance(cell, Cell) else cell)
           for key, cell in cells.items()}
    return facts.validate(raw)
