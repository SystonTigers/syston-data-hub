# Syston Data Hub

This repo fetches FA Full-Time data (fixtures, results, table) and writes JSON into `/data` for the Google Sheets automation to ingest.

- Scheduler: every 30 minutes (06:00–23:59 UTC)
- Manual run: Actions → “Fetch FA Full-Time JSON”
- Outputs:
  - `data/fixtures.json`
  - `data/results.json`
  - `data/table.json`

Update your LR codes in `.github/workflows/fetch-fa.yml`.
