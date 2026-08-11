# -*- coding: utf-8 -*-
"""讀 `schema.yaml`(或任何符合同一形狀的檔案)。R3(`docs/plan_v6_一台機器.md`)。

**這支只給 `viz_generic.py` 用。** 抽取/分桶/口徑判準完全不讀這裡 ——
那一層的設定源照樣是 `config.py`,換這份檔案不會改變任何發布數字。

`load(path)` 回傳一個 `Schema`,是 `viz_generic.py` 認得的唯一契約:
實體、期別、維度、桶、口徑、格 key 的組法。**通用層不准比這個契約多知道
任何事**(不准 import `config.py`、不准認得任何銀行名字)—— 這是 R3-3
的判準能夠成立的前提:認得越少,換一份 schema 才越可能照樣畫得出來。
"""
import dataclasses
import json

import yaml


@dataclasses.dataclass(frozen=True)
class Item:
    id: str
    label: str


@dataclasses.dataclass(frozen=True)
class Schema:
    title: str
    entity_label: str
    period_label: str
    entities: tuple
    dimensions: tuple
    buckets: tuple
    bases: tuple
    cell_key_format: str

    def cell_key(self, dimension_id, bucket_id):
        return self.cell_key_format.format(dimension=dimension_id, bucket=bucket_id)


def _items(raw):
    return tuple(Item(id=x["id"], label=x.get("label", x["id"])) for x in raw)


def load(path="schema.yaml"):
    raw = yaml.safe_load(open(path, encoding="utf-8"))
    return Schema(
        title=raw.get("title", ""),
        entity_label=raw.get("entity_label", "實體"),
        period_label=raw.get("period_label", "期別"),
        entities=_items(raw["entities"]),
        dimensions=_items(raw["dimensions"]),
        buckets=_items(raw["buckets"]),
        bases=_items(raw.get("bases") or [{"id": "value", "label": "數值"}]),
        cell_key_format=raw.get("cell_key_format", "{dimension}_{bucket}"),
    )


def load_data(path="data.json"):
    """讀 schema 描述的那個 data_source。**通用層唯一認得的資料形狀**:
    `{period: {entity: {cell_key: 數字或 null}}}`(每個 basis 各一份)。

    這支把 `data.json` 現有的扁平 key(`"{period}|{entity}"`)轉成巢狀,
    通用層本身不處理這個轉換 —— 它不該知道真實資料是怎麼存的。
    """
    d = json.load(open(path, encoding="utf-8"))
    return d
