# edgar-dependents

**Find the companies that quietly depend on another company — straight from SEC filings.**

Most EDGAR tools fetch *one* company's filing. This does the inverse: give it a
name and it surfaces every *other* filer whose own SEC filings name that company
— the suppliers, customers, and partners who disclose the relationship in their
risk factors. One command, the whole dependency web.

## Why

Public companies disclose who they depend on. A small supplier will state, in its
10-K, that one big customer is a large share of its revenue. That signal is
buried in full-text search and nobody aggregates it. This does: search the
*customer's* name across all filings, drop the customer itself, and what's left
is the dependency map — ranked by how often each filer names it.

## Example

```
$ export SEC_UA="Aston Monnach founder@noxarquant.com"
$ python find_dependents.py "AeroVironment" --forms 10-K

Dependents that name 'AeroVironment' (company excluded) — 49 companies:
  #  Company                         Ticker  Fil  Latest      Industry
  1  KRATOS DEFENSE & SECURITY       KTOS    16   2026-02-23  Guided Missiles & Space Vehicles
  3  SPARTON CORP                            9    2018-10-29  Printed Circuit Boards
  5  Red Cat Holdings                RCAT    5    2026-03-19  (drones)
  9  Amprius Technologies            AMPX    4    2026-03-06  Batteries
 13  FLIR SYSTEMS                            4    2012-02-29  Search/Detection/Nav/Guidance
 14  DUCOMMUN                        DCO     3    2026-05-08  Aircraft Parts
```

From filings alone it reconstructs the supply chain — batteries, EO/IR optics,
aerostructures, electronics — around the named company.

## Install & use

- Python 3.8+, **standard library only** — no dependencies.
- SEC requires a descriptive User-Agent. Set `SEC_UA` to `"Your Name your@email"`.
- Run:
  ```
  python find_dependents.py "<company>" [--forms 10-K] [--limit 2000]
  ```
- Prints a ranked table and writes `dependents.csv` / `dependents.json`.

Respects SEC fair-access: descriptive UA, under 10 req/sec, self-throttled.

## Use it as an MCP (drive it with an AI)

The same inversion is exposed as an [MCP](https://modelcontextprotocol.io) tool,
so an AI (e.g. Claude) can call it mid-conversation — "who depends on Lockheed
Martin?" — and get the ranked list back to reason over.

```
pip install mcp
export SEC_UA="Your Name you@email.com"
python server.py
```

Add it to Claude Desktop's `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "edgar-dependents": {
      "command": "python",
      "args": ["/full/path/to/server.py"],
      "env": { "SEC_UA": "Your Name you@email.com" }
    }
  }
}
```

It exposes one tool, `find_dependents(company, forms="10-K", limit=2000)`,
returning the ranked dependents as structured data. The cleaning logic lives in
`find_dependents.py` and is importable as a library too:

```python
from find_dependents import find_dependents
rows = find_dependents("Lockheed Martin", forms="10-K,10-Q")
```

## Notes

- SEC full-text search covers filings from 2001 to present.
- Industry comes from the SIC code the search returns inline — no extra calls.
- The tool surfaces *candidates*. Which are material, current, and real is your
  call — it hands you the haystack and marks where the needles tend to be.

---

Built by **Aston Monnach** — I build MCP servers and data pipelines that wire
messy real-world data into AI.
Maker of **[NoxarQuant](https://noxarquant.com)** — quant-grade trade intelligence.

**Build & contract enquiries:** founder@noxarquant.com

*MIT licensed — use it freely.*
