#!/usr/bin/env python3
"""
find_dependents.py — the EDGAR inversion: find who quietly depends on a company.

Small suppliers disclose their dependency on big customers. So instead of
searching for suppliers directly, you search the PRIME's name across all SEC
filings, drop the prime itself, and what's left is the list of (mostly small)
companies whose own filings name that prime — its suppliers, customers and
partners.

Something a generic "fetch one company's filing" EDGAR tool can't do.

Use it three ways:
  * CLI:      python find_dependents.py "AeroVironment" --forms 10-K
  * Library:  from find_dependents import find_dependents; find_dependents("...")
  * MCP:      python server.py   (exposes find_dependents as a tool an AI can call)

Notes:
  * SEC full-text search covers filings from 2001 to present.
  * Searching a bare company name returns that company's OWN filings first, so
    you must scan the FULL result set to reach the dependents ranked below them
    — hence a high default limit. The prime is then excluded by name.
  * SEC fair-access: descriptive User-Agent required, <=10 req/sec. Self-throttled.
  * Industry (SIC) comes back inline in the search response — no extra calls.
"""

import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

FTS_URL = "https://efts.sec.gov/LATEST/search-index"
PAGE_SIZE = 100          # SEC FTS returns up to 100 hits per page
FTS_MAX_FROM = 10000     # SEC caps deep pagination at 10,000 results
MIN_INTERVAL = 0.15      # seconds between requests (~6-7 req/s, under the 10/s cap)

# display_names look like:  "AeroVironment Inc  (AVAV)  (CIK 0001368622)"
# or, with no ticker:       "Some Private Supplier LLC  (CIK 0001234567)"
_DN_RE = re.compile(r"^(?P<name>.*?)\s*(?:\((?P<ticker>[A-Z0-9.\-]{1,10})\)\s*)?\(CIK\s*(?P<cik>\d{10})\)\s*$")

# Compact SIC → label map for the categories this turns up most; falls back to
# the raw code. (SIC is the industry classifier EDGAR returns inline.)
SIC_LABELS = {
    "3812": "Search/Detection/Nav/Guidance", "3760": "Guided Missiles & Space Vehicles",
    "3761": "Guided Missiles & Space Vehicles", "3728": "Aircraft Parts",
    "3721": "Aircraft", "3724": "Aircraft Engines", "3663": "Comms Equipment",
    "3669": "Comms Equipment", "3670": "Electronic Components", "3672": "Printed Circuit Boards",
    "3674": "Semiconductors", "3679": "Electronic Components", "3690": "Electrical Machinery/Batteries",
    "3691": "Storage Batteries", "3620": "Electrical Industrial Apparatus", "3621": "Motors & Generators",
    "3714": "Motor Vehicle Parts", "3790": "Transportation Equipment", "3825": "Instruments/Measuring",
    "3827": "Optical Instruments", "3826": "Lab/Analytical Instruments",
    "7372": "Prepackaged Software", "7373": "Computer Integrated Systems", "7389": "Business Services",
    "4911": "Electric Services", "4899": "Communications Services", "3480": "Ordnance",
    "3489": "Ordnance & Accessories",
}


class RateLimiter:
    def __init__(self, min_interval=MIN_INTERVAL):
        self.min_interval = min_interval
        self._last = 0.0

    def wait(self):
        dt = time.time() - self._last
        if dt < self.min_interval:
            time.sleep(self.min_interval - dt)
        self._last = time.time()


def get_ua():
    ua = os.environ.get("SEC_UA", "").strip()
    if not ua or "@" not in ua:
        sys.stderr.write(
            "WARNING: set SEC_UA to a real 'Name email@domain' string, e.g.\n"
            '  export SEC_UA="Your Name you@example.com"\n'
            "SEC returns 403 without a descriptive User-Agent.\n\n"
        )
        ua = ua or "find_dependents (set SEC_UA)"
    return ua


def http_get_json(url, ua, limiter):
    limiter.wait()
    req = urllib.request.Request(url, headers={
        "User-Agent": ua,
        "Accept": "application/json",
        "Accept-Encoding": "gzip, deflate",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            import gzip
            raw = gzip.decompress(raw)
        return json.loads(raw.decode("utf-8", "replace"))


def parse_display_name(dn):
    m = _DN_RE.match(dn.strip())
    if not m:
        return {"name": dn.strip(), "ticker": "", "cik": ""}
    return {"name": m.group("name").strip(), "ticker": (m.group("ticker") or "").strip(), "cik": m.group("cik")}


def filing_url(cik, _id):
    """Build an EDGAR filing URL from the FTS _id (accession:document)."""
    if not _id or ":" not in _id or not cik:
        return ""
    accession, _, doc = _id.partition(":")
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/{doc}"


def fetch_filers(query, forms, max_scan, ua, limiter):
    """Page through the full result set, yielding one record per filer per hit."""
    phrase = f'"{query}"'  # exact phrase; handles multi-word names like "Lockheed Martin"
    scanned = 0
    frm = 0
    total = None
    while scanned < max_scan and frm < FTS_MAX_FROM:
        params = {"q": phrase, "from": frm}
        if forms:
            params["forms"] = forms
        data = http_get_json(FTS_URL + "?" + urllib.parse.urlencode(params), ua, limiter)
        hits = data.get("hits", {})
        if total is None:
            total = hits.get("total", {}).get("value", 0)
            sys.stderr.write(f"  full-text matches for {phrase}"
                             f"{' in ' + forms if forms else ''}: {total} "
                             f"(scanning up to {min(total, max_scan)})\n")
        page = hits.get("hits", [])
        if not page:
            break
        for h in page:
            src = h.get("_source", {})
            names = src.get("display_names", []) or []
            sics = src.get("sics", []) or []
            for i, dn in enumerate(names):
                info = parse_display_name(dn)
                info["sic"] = sics[i] if i < len(sics) else ""
                info["form"] = src.get("form", "")
                info["file_date"] = src.get("file_date", "")
                info["id"] = h.get("_id", "")
                yield info
        scanned += len(page)
        frm += PAGE_SIZE
        if total is not None and frm >= total:
            break


def find_dependents(prime, forms="10-K", limit=2000, ua=None):
    """Return the companies whose own filings name `prime` (prime itself removed),
    ranked by how often each names it.

    Each row: {cik, name, ticker, sic, industry, filings, forms, latest, latest_url}.
    This is the importable core — the CLI and the MCP server both call it.
    """
    if ua is None:
        ua = get_ua()
    limiter = RateLimiter()
    prime_norm = re.sub(r"[^a-z0-9]", "", prime.lower())

    agg = {}
    for f in fetch_filers(prime, forms, limit, ua, limiter):
        cik = f["cik"]
        if not cik:
            continue
        # Exclude the company itself (its own filings dominate the top of the results).
        if prime_norm and prime_norm in re.sub(r"[^a-z0-9]", "", f["name"].lower()):
            continue
        rec = agg.setdefault(cik, {
            "name": f["name"], "ticker": f["ticker"], "cik": cik, "sic": f["sic"],
            "industry": SIC_LABELS.get(f["sic"], "") or f"SIC {f['sic']}" if f["sic"] else "",
            "filings": 0, "forms": set(), "latest": "", "latest_url": "",
        })
        rec["filings"] += 1
        if f["form"]:
            rec["forms"].add(f["form"])
        if f["file_date"] > rec["latest"]:
            rec["latest"] = f["file_date"]
            rec["latest_url"] = filing_url(cik, f["id"])

    rows = sorted(agg.values(), key=lambda r: (r["filings"], r["latest"]), reverse=True)
    for r in rows:  # sets aren't JSON-serialisable — flatten to a string
        r["forms"] = ",".join(sorted(r["forms"])) if isinstance(r["forms"], set) else r["forms"]
    return rows


def main():
    ap = argparse.ArgumentParser(description="EDGAR inversion — find the companies that name a given company as a dependency.")
    ap.add_argument("prime", help='Company name to invert on, e.g. "AeroVironment"')
    ap.add_argument("--forms", default="10-K", help='Form filter (comma-sep), default 10-K. Use "" for all forms.')
    ap.add_argument("--limit", type=int, default=2000, help="Max filings to scan (default 2000; raise for very common names).")
    ap.add_argument("--out", default="dependents", help="Output basename for .csv/.json (default: dependents).")
    args = ap.parse_args()

    rows = find_dependents(args.prime, args.forms, args.limit)

    if not rows:
        print('\nNo dependents found. Try --forms "" (all forms), raise --limit, or check the exact name.')
        return
    print(f"\nDependents that name '{args.prime}' (company excluded) — {len(rows)} companies, "
          f"ranked by how often they file it:\n")
    hdr = f"{'#':>3}  {'Company':40}  {'Ticker':6}  {'CIK':10}  {'Fil':>3}  {'Latest':10}  Industry"
    print(hdr); print("-" * len(hdr))
    for i, r in enumerate(rows, 1):
        print(f"{i:>3}  {r['name'][:40]:40}  {r['ticker'][:6]:6}  {r['cik']:10}  "
              f"{r['filings']:>3}  {r['latest']:10}  {r['industry'][:30]}")

    with open(args.out + ".json", "w") as fh:
        json.dump(rows, fh, indent=2)
    with open(args.out + ".csv", "w", newline="") as fh:
        cols = ["cik", "name", "ticker", "sic", "industry", "filings", "forms", "latest", "latest_url"]
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader(); w.writerows(rows)
    print(f"\nWrote {args.out}.csv and {args.out}.json")
    print("These are candidates — which are material, current and real is your call.")


if __name__ == "__main__":
    main()
