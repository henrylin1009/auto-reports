# -*- coding: utf-8 -*-
"""oracle 黃金回歸:拿舊管線手工核過的桶值(data.json),逐桶抽考新管線輸出。

為什麼要做:新管線的「綠燈」= 明細表各桶加總 == BS 錨,只證明【總額對】。
歸錯桶(如公債↔公司債對調)總額照樣對、照樣顯綠 —— 對帳對分桶免疫。
故需一條獨立來源逐桶比:data.json 是舊管線分開核過的桶值,當第三方裁判。

口徑注意(關鍵——別把口徑錯配誤判成分桶錯,見 oracle-basis-mismatch 記憶):
- 只比【兩邊都有、無歧義】的三桶:公債 / 公司債 / 金融債。
  (舊管線的『其他』口徑不同、也沒撈貨幣市場/資產基礎/股票,不納入比對。)
- oracle(data.json)各類衡量基礎不一致:OCI 存【取得成本】、Trading 存【公允】、AC 存【帳面】。
  故對齊要分欄取:OCI→新管線 buckets[桶]['成本']、Trading/AC→['值']。
  (拿 oracle 成本比新管線公允會憑空生出一堆假差=債券未實現損益,非分桶錯。)
- 半年報主附註 cost=NA(成本欄=None),OCI 該欄取不到→自動跳過(無成本可對,非錯)。
- 新結果單位是【千元】,÷1e5 換算成【億】對齊 oracle。
- 容差預設 1%(版面/四捨五入),差超過就列出來人看。

用法:python test_oracle.py           # 比對 extract_v2_results.json 已有的格
"""
import json
import os

RESULTS = "extract_v2_results.json"
ORACLE = "data.json"
CMP_BUCKETS = ("公債", "公司債", "金融債")
REL_TOL = 0.01                          # 1% 相對容差
THOUSAND_TO_YI = 1e5                     # 千元 → 億(1億 = 1e8元 = 1e5千元)

# 代碼 → 中文行名(對齊 batch_v2.BANK)
BANK = {"5835": "國泰", "5836": "富邦", "5841": "中信", "5843": "兆豐", "5847": "玉山"}
# 期別碼 → 半/全年(對齊 extract_v2.PERIOD:02半年、04年報)
PERIOD_TAG = {"02": "H1", "04": "H2"}


def _oracle_key(name):
    """檔名(YYYYMM_代碼_型別)→ oracle 期別鍵 'YYYYH1|中文行名';判不出回 None。"""
    parts = name.split("_")
    period, code = parts[0], parts[1]
    year, pcode = period[:4], period[4:6]
    bank = BANK.get(code)
    tag = PERIOD_TAG.get(pcode)
    if not bank or not tag:
        return None
    return f"{year}{tag}|{bank}"


def run():
    if not os.path.exists(RESULTS):
        print(f"沒有 {RESULTS},先跑 batch_v2.py")
        return
    results = json.load(open(RESULTS, encoding="utf-8"))
    oracle = json.load(open(ORACLE, encoding="utf-8"))["data"]
    diffs, checked, skipped = [], 0, 0
    for name, rec in results.items():
        okey = _oracle_key(name)
        if not okey or okey not in oracle or not oracle[okey]:
            skipped += 1
            continue
        for cls, r in rec.get("cls", {}).items():
            if cls not in oracle[okey]:
                continue
            ob = oracle[okey][cls]                       # {桶: 億}
            buckets = r.get("buckets", {})
            col = "成本" if cls == "OCI" else "值"        # 同 oracle 衡量基礎
            for b in CMP_BUCKETS:
                ov = ob.get(b)
                raw = (buckets.get(b) or {}).get(col)
                if ov is None or raw is None:
                    continue
                nv = raw / THOUSAND_TO_YI                 # 千元 → 億
                checked += 1
                if abs(nv - ov) > REL_TOL * max(abs(ov), 1):
                    diffs.append(
                        f"{okey} {cls} {b}:新={nv:.2f} vs oracle={ov:.2f} 億"
                        f"(差 {abs(nv - ov):.2f})")
    print("=" * 56)
    print(f"oracle 逐桶回歸:比對 {checked} 桶值,差異 {len(diffs)}(跳過 {skipped} 份無對照)")
    print("=" * 56)
    for d in diffs:
        print("  ✗", d)
    if not diffs and checked:
        print("  ✅ 三桶全部對得上 oracle —— 分桶無誤")
    print("=" * 56)


if __name__ == "__main__":
    run()
