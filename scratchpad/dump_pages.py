import sys, pdfplumber
path, kw = sys.argv[1], sys.argv[2]
with pdfplumber.open(path) as pdf:
    for i, pg in enumerate(pdf.pages):
        t = pg.extract_text() or ""
        if kw in t:
            print(f"\n===== PAGE {i} =====")
            print(t)
