# Bank Bond Portfolio Analysis — Automated Reporting Pipeline

An end-to-end pipeline that extracts, validates, and visualizes the bond investment
portfolios of major Taiwanese banks directly from their statutory financial reports.

For each bank it parses the bond holdings broken down by **accounting classification**
— FVTPL (Trading), FVOCI (OCI), and Amortized Cost (AC) — and by **instrument type**
(government bonds, corporate bonds, bank debentures, money-market instruments), then
produces an **interactive web dashboard** and an Excel report with native charts.

**Live dashboard:** https://henrylin1009.github.io/auto-reports/

Banks currently covered (extensible): CTBC (5841), Cathay (5835), Fubon (5836),
Mega (5843), E.Sun (5847). Source: entity-level (non-consolidated) semi-annual reports
from the Taiwan Market Observation Post System (`doc.twse.com.tw`).

## Highlights

- **PDF parsing at scale** — extracts figures from footnotes across ~80 financial-report
  PDFs with heterogeneous layouts, including one bank whose disclosure is a coordinate-based
  "securities division" table requiring word-level (x/y) reconstruction.
- **Three-layer checksum validation** — every extracted figure is reconciled
  (pure-securities subtotal → total less derivatives/valuation → full-table tie-out),
  so a mis-extraction is flagged rather than silently returned.
- **Honest data model** — distinguishes a *true zero position* from *no data*
  (e.g. two banks' 2020H1 reports are scanned image PDFs with no text layer, marked as
  "no data" instead of 0).
- **Interactive dashboard** — headline KPIs, cross-bank comparison, time-series trends,
  and a bank × instrument heatmap; users can choose which instruments count toward
  "holdings" and filter which banks are shown, all recomputed client-side.
- **Self-updating** — the reporting period range extends automatically each year;
  adding a new bank requires no code changes to the visualizations.

## Architecture

TWSE blocks cloud/data-center IP ranges (listing sometimes works, downloads frequently
fail). The pipeline is therefore split into a **fetch** step that must run on a
Taiwan-based machine, and a **render-only** step that runs in the cloud:

| Step | Where it runs | What it does |
|---|---|---|
| Fetch + parse | Local machine (Taiwan) | Downloads reports, parses, validates, writes `data.json` + Excel |
| Publish | GitHub Actions | Reads the committed `data.json`, renders the site, deploys to GitHub Pages (never touches TWSE) |

## Deliverables

| Deliverable | Audience | How it's produced |
|---|---|---|
| **Interactive dashboard** (GitHub Pages) | Viewers / reviewers | Local data build → push → GitHub Actions publishes |
| **`銀行債券_完整報表.xlsx`** (wide table + native Excel charts) | Anyone who needs the file | `python3 build_report.py` |
| **Double-click desktop tool** (`.exe` / `.app`) | Non-technical users | Packaged by GitHub Actions, downloaded from Artifacts |

## Usage

### A. Build the report locally
```bash
pip install -r requirements.txt
python3 build_report.py            # fetch latest reports → xlsx + data.json
```
The period range extends automatically to the current year (from 2020); charts default to
the most recent 6 periods — no code changes needed for future filings.

### B. Update the website (build locally → publish via GitHub)
```bash
python3 build_report.py
git add data.json 銀行債券_完整報表.xlsx
git commit -m "update data" && git push
```
On push, `.github/workflows/report.yml` runs **render-only** (reads the committed
`data.json`, draws the site, deploys Pages; it does not fetch from TWSE).
One-time setup: repo **Settings → Pages → Source = "GitHub Actions"**.

### C. Package the desktop tool
`.github/workflows/build-exe.yml` uses GitHub's Windows / macOS runners to package
`app.py` into a single binary (packaging does not require TWSE access). Download from the
run's Artifacts:
- `銀行債券報表-Windows` (`.exe`)
- `銀行債券報表-Mac` (`.zip`: binary + launcher `.command`)

The user runs it **in Taiwan** (so TWSE is reachable): double-click (on macOS, right-click →
Open once to pass Gatekeeper) → ~2–3 minutes → the `.xlsx` appears in the same folder.

## Files

| File | Purpose |
|---|---|
| `build_report.py` | Main entry point (header `CONFIG`: chart gap width, size, number of periods shown) |
| `extract3.py` / `extract2.py` | Core parsing + three-layer checksum validation |
| `extract_megabank.py` | Dedicated coordinate-based parser for Mega's securities-division table |
| `resolve.py` | Robust file resolution: finds the "entity-level" report (codes vary by bank/year, e.g. AI2/AI3) |
| `make_web.py` | Renders the **interactive dashboard** from `data.json` (KPIs + cross-bank comparison + trends + heatmap; selectable instruments, filterable banks) — used by GitHub Actions |
| `app.py` | Desktop-tool entry point (for PyInstaller packaging) |
| `run.sh` | cron entry point for a Taiwan-based server (optional) |

## Notes on data integrity

- **Mega (5843)** — instrument detail comes from its "securities-division change table"
  (coordinate-based layout, unlike other banks' summary tables; handled by
  `extract_megabank.py`). Its securities division holds **no Trading positions**, so
  Trading is 0 — a genuine zero, not missing data.
- **True zero vs. no data** — the 2020H1 entity reports for Cathay and E.Sun are scanned
  image PDFs with no text layer and cannot be parsed, so they are marked `null`
  ("no data", shown hatched on the dashboard) rather than 0. Any report whose extracted
  text is too short (`len(text) < 2000`) is automatically classified as no-data.
- **Trustworthy by construction** — the three-layer checksum flags mis-extractions instead
  of silently returning wrong numbers.
- **Fully unattended operation** requires a Taiwan/Asia VPS running `run.sh` via cron
  (GitHub's cloud runners are blocked by TWSE).

## Tech stack

Python · pdfplumber (PDF parsing) · openpyxl (native Excel charts) · Chart.js
(dashboard) · GitHub Actions (CI/CD, cross-platform packaging, Pages deployment).
