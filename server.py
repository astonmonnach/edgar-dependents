#!/usr/bin/env python3
"""
MCP server for edgar-dependents — exposes the EDGAR inversion as a tool an AI
can call. Point Claude (or any MCP client) at this and it can, in the middle of
a conversation, pull the list of companies that quietly depend on a given one.

Run it:
    export SEC_UA="Your Name you@email.com"     # SEC requires a descriptive UA
    pip install mcp
    python server.py

Add it to Claude Desktop (claude_desktop_config.json):
    {
      "mcpServers": {
        "edgar-dependents": {
          "command": "python",
          "args": ["/full/path/to/server.py"],
          "env": { "SEC_UA": "Your Name you@email.com" }
        }
      }
    }
"""
from mcp.server.fastmcp import FastMCP

from find_dependents import find_dependents as _find_dependents

mcp = FastMCP("edgar-dependents")


@mcp.tool()
def find_dependents(company: str, forms: str = "10-K", limit: int = 2000) -> list[dict]:
    """Find the companies whose own SEC filings name `company` — its suppliers,
    customers and partners — ranked by how often each one names it.

    This is the inverse of a normal EDGAR lookup: instead of fetching one
    company's filing, it searches every filing for the company's name, drops the
    company itself, and returns the (mostly smaller) filers that disclose a
    relationship with it. Useful for reconstructing a supply chain or dependency
    web straight from public filings.

    Args:
        company: the company to invert on, e.g. "AeroVironment".
        forms:   SEC form filter, comma-separated (default "10-K"). Use "" for all forms.
        limit:   maximum filings to scan (default 2000; raise for very common names).

    Returns:
        A list of dependents, each: {cik, name, ticker, sic, industry, filings,
        forms, latest, latest_url}. Ordered by filing count (strongest signal first).
        These are candidates — which are material, current and real is the caller's judgement.

    Note: set the SEC_UA environment variable to "Your Name you@email.com";
    the SEC requires a descriptive User-Agent or it returns 403.
    """
    return _find_dependents(company, forms=forms, limit=limit)


if __name__ == "__main__":
    mcp.run()
