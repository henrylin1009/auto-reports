# -*- coding: utf-8 -*-
"""分節探針:附註標題「九、」切章節,量它能不能取代擴頁。零版型知識的部分只有
一條:中文數字 + 、 開頭的行 = 一個附註章節的開頭。"""
import re, sys, glob, json, collections
sys.path.insert(0, ".")
import locate

CN = "一二三四五六七八九十百零壹貳參肆伍陸柒捌玖拾"
# 行首(允許前導空白)中文數字(字間可有空白)+ 、
HEAD = re.compile(r"^[ \t　]{0,4}((?:[%s][ 　]{0,2}){1,4})、" % CN)

def heads(texts):
    """→ [(page, line_idx, 標題全行)] 依序"""
    out = []
    for p, t in enumerate(texts):
        for li, ln in enumerate(t.split("\n")):
            m = HEAD.match(ln)
            if m:
                out.append((p, li, ln.strip(), re.sub(r"[ 　]", "", m.group(1))))
    return out

def sections(texts):
    """→ [{no, title, start:(p,li), end:(p,li)}] 只保留編號遞增的主序列。"""
    hs = heads(texts)
    return hs

if __name__ == "__main__":
    for path in sorted(glob.glob("pdf_cache/*.pdf"))[:3]:
        loc = locate.locate(path)
        hs = heads(loc.texts)
        print("="*30, loc.name, "頁數", len(loc.texts), "標題數", len(hs))
        for h in hs[:60]:
            print(f"  p{h[0]:>3} L{h[1]:>2} [{h[3]}] {h[2][:40]}")
