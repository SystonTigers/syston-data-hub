import os, json, sys, time
import requests
from bs4 import BeautifulSoup

# ---- Config (from workflow env) ----
FIX_LR = os.environ.get("FA_FIXTURES_LRCODE", "").strip()
RES_LR = os.environ.get("FA_RESULTS_LRCODE", "").strip()
TAB_LR = os.environ.get("FA_TABLE_LRCODE", "").strip()

OUT_DIR = "data"
os.makedirs(OUT_DIR, exist_ok=True)

# ---- Helper: polite GET with retry ----
def get_html(url, tries=3, timeout=20):
    for i in range(tries):
        try:
            r = requests.get(url, timeout=timeout, headers={
                "User-Agent": "Mozilla/5.0 (compatible; SystonBot/1.0)"
            })
            if r.status_code == 200 and r.text:
                return r.text
            print(f"[warn] {url} HTTP {r.status_code} (attempt {i+1}/{tries})")
        except Exception as e:
            print(f"[warn] {url} error {e} (attempt {i+1}/{tries})")
        time.sleep(2*(i+1))
    raise RuntimeError(f"Failed to fetch after {tries} attempts: {url}")

# ---- Parsers (robust-ish; tolerate FA layout quirks) ----
def parse_fixtures(html):
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    # The FA site uses tables; we’ll look for rows that have date/home/away/time/venue cells
    for tr in soup.select("tr"):
        tds = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        if len(tds) < 4:
            continue
        # very common order (varies by league): Date | KO | Home | Away | Venue (sometimes KO after teams)
        txt = " | ".join(tds).lower()
        if ("vs" in txt or "v " in txt) and any(k in txt for k in ["venue", "ground", "park"]):
            # Best-effort extraction
            date = tds[0]
            ko   = tds[1] if ":" in tds[1] else (tds[2] if ":" in tds[2] else "")
            # Home/Away guess: find the "vs" split
            joined = " ".join(tds)
            if " vs " in joined:
                left, right = joined.split(" vs ", 1)
                # Heuristics: often left contains date/ko; strip those tokens if present
                parts_l = [p for p in left.split() if ":" not in p]  # naive
                parts_r = right.split()
                home = " ".join(parts_l[-3:]) if parts_l else ""
                away = " ".join(parts_r[:3]) if parts_r else ""
            else:
                # fallback: try columns 2/3 as teams
                home = tds[2] if len(tds) > 2 else ""
                away = tds[3] if len(tds) > 3 else ""

            # venue guess
            venue = ""
            for cell in tds[::-1]:
                if any(k in cell.lower() for k in ["venue", "park", "ground", "school", "field"]):
                    venue = cell
                    break

            if date and home and away:
                rows.append({
                    "date": date, "type": "League", "home": home, "away": away,
                    "venue": venue, "ko": ko
                })
    return rows

def parse_results(html):
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for tr in soup.select("tr"):
        tds = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        if len(tds) < 4:
            continue
        txt = " | ".join(tds).lower()
        # look for a typical "Home X - Y Away" cell somewhere
        score_cell = None
        for cell in tds:
            if "-" in cell and any(c.isdigit() for c in cell):
                score_cell = cell
                break
        if score_cell and ("vs" in txt or " - " in score_cell):
            # best-effort parse
            date = tds[0]
            hs, as_ = None, None
            home, away = "", ""
            # try "Home X - Y Away"
            parts = score_cell.split("-")
            if len(parts) == 2:
                left, right = parts
                # last number on the left, first number on the right
                try:
                    hs = int([p for p in left.split() if p.isdigit()][-1])
                except: pass
                try:
                    as_ = int([p for p in right.split() if p.isdigit()][0])
                except: pass
                # remove numbers to get team names approx
                home = left.replace(str(hs) if hs is not None else "", "").strip()
                away = right.replace(str(as_) if as_ is not None else "", "").strip()
            if date and home and away and hs is not None and as_ is not None:
                rows.append({
                    "date": date, "type": "League",
                    "home": home, "away": away, "homeScore": hs, "awayScore": as_,
                    "venue": "", "ko": "", "notes": "", "status": "FT"
                })
    return rows

def parse_table(html):
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    # Find first table with headings that look like a league table
    table = None
    for t in soup.find_all("table"):
        head = (t.find("thead") or t).get_text(" ", strip=True).lower()
        if all(k in head for k in ["p", "w", "d", "l"]) and any(k in head for k in ["gd", "goal"]):
            table = t
            break
    if not table:
        return rows
    for tr in table.find_all("tr"):
        ths = [th.get_text(" ", strip=True) for th in tr.find_all("th")]
        tds = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        if tds and len(tds) >= 6:
            # crude: Pos Team P W D L GF GA GD Pts (order varies; we keep strings)
            rows.append(tds)
    return rows

# ---- Build URLs (FA Full-Time uses ?selectedLeague= params or /fixtures/…/…html with keys)
def fixtures_url(lrcode: str) -> str:
    # Use the “fixtures list” permalink that includes the league round code
    return f"https://fulltime.thefa.com/fixtures.html?selectedLeague={lrcode}&selectedSeason=&selectedFixtureGroupAgeGroup=0&selectedFixtureDateStatus=&selectedRelatedFixtureOption=3"

def results_url(lrcode: str) -> str:
    return f"https://fulltime.thefa.com/results.html?selectedLeague={lrcode}&selectedSeason=&selectedFixtureGroupAgeGroup=0&selectedRelatedFixtureOption=3"

def table_url(lrcode: str) -> str:
    return f"https://fulltime.thefa.com/table.html?selectedLeague={lrcode}"

def main():
    if not (FIX_LR and RES_LR and TAB_LR):
        print("❌ Missing FA_*_LRCODE env vars")
        sys.exit(1)

    # 1) Fixtures
    try:
        f_html = get_html(fixtures_url(FIX_LR))
        fixtures = parse_fixtures(f_html)
    except Exception as e:
        print("Fixtures fetch/parse failed:", e)
        fixtures = []

    # 2) Results
    try:
        r_html = get_html(results_url(RES_LR))
        results = parse_results(r_html)
    except Exception as e:
        print("Results fetch/parse failed:", e)
        results = []

    # 3) Table
    try:
        t_html = get_html(table_url(TAB_LR))
        table = parse_table(t_html)
    except Exception as e:
        print("Table fetch/parse failed:", e)
        table = []

    # write JSON
    with open(os.path.join(OUT_DIR, "fixtures.json"), "w", encoding="utf-8") as f:
        json.dump(fixtures, f, ensure_ascii=False, indent=2)
    with open(os.path.join(OUT_DIR, "results.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    with open(os.path.join(OUT_DIR, "table.json"), "w", encoding="utf-8") as f:
        json.dump(table, f, ensure_ascii=False, indent=2)

    print(f"✅ Wrote {len(fixtures)} fixtures, {len(results)} results, {len(table)} table rows")

if __name__ == "__main__":
    main()

