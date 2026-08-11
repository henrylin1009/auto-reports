# -*- coding: utf-8 -*-
"""把 pdf_cache/ 正規化成 pdf_cache_norm/ —— 只做一件事:拿掉空密碼的權限旗標。

**為什麼需要**(2026-07-29 實測):89 份裡有 46 份(52%)帶「不允許文字擷取」
的權限位元(空 owner password,公開財報的樣板設定)。pdfium / pdfplumber 忽略它,
但 Camelot 的後端(pypdf/pdfminer)遵守它 → 直接拋
`Text extraction is not allowed`,那半批語料一頁都讀不到。

第一次量 Camelot 得到 32%(對照手刻的 50%),看起來像「Camelot 比較差」,
其實是它只讀到一半的檔案。**沒有這一步,任何跨引擎比較都是假的。**
"""
import glob
import os

from pypdf import PdfReader, PdfWriter

SRC, DST = 'pdf_cache', 'pdf_cache_norm'


def norm_path(doc):
    """有正規化副本就用它,沒有就退回原檔。"""
    p = os.path.join(DST, f'{doc}.pdf')
    return p if os.path.exists(p) else os.path.join(SRC, f'{doc}.pdf')


def build(force=False):
    os.makedirs(DST, exist_ok=True)
    made = skipped = failed = 0
    for src in sorted(glob.glob(f'{SRC}/*.pdf')):
        dst = os.path.join(DST, os.path.basename(src))
        if os.path.exists(dst) and not force:
            skipped += 1
            continue
        try:
            r = PdfReader(src)
            if r.is_encrypted:
                r.decrypt('')                    # 公開財報一律空密碼
            w = PdfWriter()
            for pg in r.pages:
                w.add_page(pg)
            with open(dst, 'wb') as f:
                w.write(f)
            made += 1
        except Exception as e:                   # noqa: BLE001
            failed += 1
            print(f'  FAIL {os.path.basename(src)}: {type(e).__name__}: {e}')
    print(f'正規化完成:新建 {made}  已存在 {skipped}  失敗 {failed}')


if __name__ == '__main__':
    build()
