#!/usr/bin/env python3
"""Generate credits.html from the SHIPPED dataset's own verification receipts.

Every value in Sorting Geography carries its source, that source's URL and its
publication year. This page is that record, rendered — not a hand-written list
that drifts from what the app actually ships.

Attribution is not optional politeness here: World Bank WDI, Our World in Data
and GeoNames all ship under CC BY, which REQUIRES credit. An app-store release
without this page is a licence breach.

    python3 scripts/build_credits.py path/to/dataset.json
"""
from __future__ import annotations

import html
import json
import sys
from collections import defaultdict
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "credits.html"


def collect(dataset: dict) -> dict[str, dict]:
    """axis_id -> {source, url, vintage}, read from the first record that has a
    receipt. Every record on an axis carries the same declared source (gate 1,
    'source uniformity', enforces it), so the first is representative."""
    out: dict[str, dict] = {}
    for axis_id, countries in sorted(dataset.get("axes", {}).items()):
        for _iso, rec in countries.items():
            v = rec.get("verification") or {}
            if v.get("declared_source"):
                out[axis_id] = {
                    "source": v["declared_source"],
                    "url": v.get("source_url") or "",
                    "vintage": v.get("vintage") or "",
                }
                break
    return out


def render(axis_sources: dict[str, dict], version: str) -> str:
    by_source: dict[tuple[str, str], list[str]] = defaultdict(list)
    for axis_id, info in axis_sources.items():
        by_source[(info["source"], info["url"])].append(axis_id)

    rows = []
    for (source, url), axes in sorted(by_source.items()):
        pretty = ", ".join(a.replace("_", " ") for a in sorted(axes))
        link = (f'<a href="{html.escape(url)}" rel="noopener noreferrer nofollow">'
                f'{html.escape(source)}</a>') if url else html.escape(source)
        rows.append(
            f"    <tr>\n      <td>{link}</td>\n"
            f"      <td class=\"axes\">{html.escape(pretty)}</td>\n    </tr>"
        )

    return TEMPLATE.format(
        rows="\n".join(rows),
        n_axes=len(axis_sources),
        n_sources=len(by_source),
        version=html.escape(version),
    )


TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Data sources — Sorting Geography</title>
<meta name="description" content="Every figure in Sorting Geography, and where it came from.">
<link rel="stylesheet" href="style.css">
</head>
<body>
<header class="bar">
  <a class="wordmark" href="index.html">Sorting&nbsp;Geography</a>
  <nav><a href="index.html">Home</a> <a href="privacy.html">Privacy</a></nav>
</header>

<main class="prose">
  <h1>Where the numbers come from</h1>
  <p class="lede">
    Sorting Geography is a game about real figures, so every value it shows carries
    a receipt: the organisation that published it, a link to that publication, and
    the year the figure describes. This page lists all of them.
  </p>
  <p>
    It is generated from the dataset the app actually ships — currently
    <strong>{n_axes} measures</strong> drawn from <strong>{n_sources} sources</strong>
    (dataset <code>{version}</code>) — not maintained by hand, so it cannot drift
    from what you see in the game.
  </p>
  <p>
    Where a figure is redistributed by an intermediary, both are named: "FAO (via
    World Bank WDI)" means the World Bank republished the FAO's number, and both
    deserve the credit.
  </p>

  <table class="sources">
    <thead><tr><th>Source</th><th>Used for</th></tr></thead>
    <tbody>
{rows}
    </tbody>
  </table>

  <h2>Licences</h2>
  <p>
    Most of this data is published under
    <a href="https://creativecommons.org/licenses/by/4.0/" rel="noopener noreferrer">CC BY 4.0</a>,
    which permits reuse with attribution — this page is that attribution. Some sources
    carry their own terms, and a few restrict commercial use; where that is so we either
    hold permission or the measure does not ship. We would rather lose a question than
    use a figure we have no right to.
  </p>
  <p>
    Country outlines come from <a href="https://www.naturalearthdata.com/" rel="noopener noreferrer">Natural Earth</a>
    (public domain). Place names and capitals come from
    <a href="https://www.geonames.org/" rel="noopener noreferrer">GeoNames</a> (CC BY 4.0).
    Time-zone data comes from the <a href="https://www.iana.org/time-zones" rel="noopener noreferrer">IANA Time Zone Database</a> (public domain).
  </p>

  <h2>Found something wrong?</h2>
  <p>
    Data goes stale and sources revise their figures. If a number looks wrong, say so
    and we will check it against the source and correct it — every value is traceable
    to exactly one publication, which is what makes that possible.
  </p>
</main>

<footer class="bar foot">
  <span>Sorting Geography</span>
  <nav><a href="privacy.html">Privacy</a> <a href="credits.html">Data sources</a></nav>
</footer>
</body>
</html>
"""


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: build_credits.py <dataset.json>", file=sys.stderr)
        return 2
    data = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    axis_sources = collect(data)
    if not axis_sources:
        print("no verification receipts found — refusing to write a page "
              "that claims sources it cannot show", file=sys.stderr)
        return 1
    OUT.write_text(render(axis_sources, data.get("version", "unknown")), encoding="utf-8")
    print(f"credits.html: {len(axis_sources)} axes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
