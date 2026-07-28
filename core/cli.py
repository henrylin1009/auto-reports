# -*- coding: utf-8 -*-
"""唯一入口。只做參數分派,零業務邏輯。

    python3 -m core anchors            # 對 facts/ 涵蓋的 15 份 PDF 產生 anchors/
    python3 -m core anchors --verify   # 重新推導並逐項比對
    python3 -m core status             # 印:facts 格數 / anchors 份數 / 覆蓋率
"""
import glob
import os
import sys

from core import store


def _docs_from_facts():
    cells = store.load_facts()
    return sorted({key.split("|")[0] for key in cells})


def cmd_anchors(argv):
    docs = _docs_from_facts()
    if "--verify" in argv:
        diffs = store.verify_anchors(docs)
        print(f"{len(docs)} 份文件,anchors 逐項比對:{len(docs) - len(diffs)} 相符 / {len(diffs)} 不符")
        for doc, stored, fresh in diffs:
            print(f"  ✗ {doc}\n    記錄:{stored}\n    重推:{fresh}")
        return 0 if not diffs else 1
    for doc in docs:
        store.build_anchors(doc)
        print(f"  → anchors/{doc}.json")
    print(f"{len(docs)} 份文件已產生 anchors/")
    return 0


def cmd_status(argv):
    cells = store.load_facts()
    n_anchor_files = len(glob.glob(f"{store.ANCHORS_DIR}/*.json"))
    docs = _docs_from_facts()
    covered = sum(1 for d in docs if os.path.exists(f"{store.ANCHORS_DIR}/{d}.json"))
    print(f"facts:   {len(cells)} 格 / {len(docs)} 份文件")
    print(f"anchors: {n_anchor_files} 份檔案")
    print(f"覆蓋率:  {covered}/{len(docs)} 份文件有對應 anchors")
    return 0


COMMANDS = {"anchors": cmd_anchors, "status": cmd_status}


def main(argv):
    if not argv or argv[0] not in COMMANDS:
        print(f"用法: python3 -m core {{{'|'.join(COMMANDS)}}} [選項]")
        return 2
    return COMMANDS[argv[0]](argv[1:])


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
