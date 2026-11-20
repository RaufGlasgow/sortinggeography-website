#!/usr/bin/env python3
"""Search and link-preview tags on every served page, from one place (Story 18.3).

Each page's <head> carries one generated region:

    <!-- seo:head --> ...generated... <!-- /seo:head -->

holding the canonical URL (from the page's path) and Open Graph (og:type,
og:site_name, og:url = canonical, og:title = the page's <title>, og:description
= its meta description), and, on each language's home page, JSON-LD
(schema.org WebSite + the publisher). Nothing is typed by hand per page.

    python3 scripts/build_seo.py           # fill the regions
    python3 scripts/build_seo.py --check   # CI: every page has exactly one current region

--check fails when a page has no region or a stale or hand-edited one, a
second canonical or og: tag outside it, no <title> or description, JSON-LD
that does not parse or lacks @context/@type, or hreflang links without
x-default and the page itself. Design-independent: Ra'uf's chosen look
(18.3) changes the markup around it, not these tags.
"""
from __future__ import annotations

import html
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SITE = "https://sortinggeography.com"
IGNORED = {"docs", "src", "scripts", "node_modules", ".git", ".github", ".wrangler", "functions"}
REGION = re.compile(r"(<!-- seo:head -->)(.*?)(<!-- /seo:head -->)", re.S)
PUBLISHER = "Empty Cup Media LLC"        # terms/index.html (Ra'uf 2026-11-19)


def pages(root: pathlib.Path = ROOT) -> list[pathlib.Path]:
    return sorted(p for p in root.rglob("*.html") if not (set(p.relative_to(root).parts) & IGNORED))


def url_of(rel: str) -> str:
    if rel == "index.html":
        return SITE + "/"
    if rel.endswith("/index.html"):
        return f"{SITE}/{rel[:-len('index.html')]}"
    return f"{SITE}/{rel}"


def _attr(text: str, pattern: str) -> str | None:
    m = re.search(pattern, text, re.S)
    return html.unescape(m.group(1)).strip() if m else None


def title_of(text: str) -> str | None:
    return _attr(text, r"<title>(.*?)</title>")


def description_of(text: str) -> str | None:
    return _attr(text, r'<meta name="description" content="([^"]*)">')


def lang_of(text: str) -> str:
    return _attr(text, r'<html\b[^>]*\blang="([^"]+)"') or "en"


def region(rel: str, text: str) -> str:
    e = lambda s: html.escape(s, quote=True)
    url = url_of(rel)
    title, desc = title_of(text) or "", description_of(text) or ""
    out = [f'<link rel="canonical" href="{url}">',
           '<meta property="og:type" content="website">',
           '<meta property="og:site_name" content="Sorting Geography">',
           f'<meta property="og:url" content="{url}">',
           f'<meta property="og:title" content="{e(title)}">',
           f'<meta property="og:description" content="{e(desc)}">']
    if rel == "index.html" or re.fullmatch(r"[a-z]{2,3}(?:-[a-z0-9]{2,4})?/index\.html", rel):
        ld = {"@context": "https://schema.org", "@type": "WebSite", "name": "Sorting Geography", "url": url,
              "inLanguage": lang_of(text), "description": desc,
              "publisher": {"@type": "Organization", "name": PUBLISHER}}
        out.append('<script type="application/ld+json">' + json.dumps(ld, ensure_ascii=False, sort_keys=True) + "</script>")
    return "\n" + "\n".join(out) + "\n"


def render(rel: str, text: str) -> str:
    return REGION.sub(lambda m: m.group(1) + region(rel, text) + m.group(3), text)


def check(root: pathlib.Path = ROOT) -> list[str]:
    bad = []
    for p in pages(root):
        rel = str(p.relative_to(root))
        text = p.read_text(encoding="utf-8")
        regions = REGION.findall(text)
        if len(regions) != 1:
            bad.append(f"{rel}: {len(regions)} seo:head regions (needs exactly one in <head>)")
            continue
        if not title_of(text) or not description_of(text):
            bad.append(f"{rel}: no <title> or meta description")
        if render(rel, text) != text:
            bad.append(f"{rel}: the seo:head region is stale or hand-edited; run scripts/build_seo.py")
        rest = REGION.sub(" ", text)
        if re.search(r'rel="canonical"|property="og:', rest):
            bad.append(f"{rel}: a canonical or og: tag outside the generated region")
        for m in re.finditer(r'<script type="application/ld\+json">(.*?)</script>', text, re.S):
            try:
                ld = json.loads(m.group(1))
                if not (ld.get("@context") and ld.get("@type")):
                    bad.append(f"{rel}: JSON-LD without @context/@type")
            except ValueError as err:
                bad.append(f"{rel}: JSON-LD does not parse ({err})")
        hl = re.findall(r'<link rel="alternate" hreflang="([^"]+)" href="([^"]+)">', text)
        if hl:
            langs = {h for h, _ in hl}
            if "x-default" not in langs:
                bad.append(f"{rel}: hreflang links without x-default")
            if url_of(rel) not in {u for _, u in hl}:
                bad.append(f"{rel}: hreflang links that do not include the page itself")
    return bad


def build(root: pathlib.Path = ROOT) -> None:
    for p in pages(root):
        rel = str(p.relative_to(root))
        text = p.read_text(encoding="utf-8")
        new = render(rel, text)
        if new != text:
            p.write_text(new, encoding="utf-8")
            print(f"wrote {rel}")


if __name__ == "__main__":
    if "--check" in sys.argv[1:]:
        problems = check()
        if problems:
            print("seo check FAILED (Story 18.3):")
            for b in problems:
                print("  " + b)
            sys.exit(1)
        print(f"ok   seo: canonical, Open Graph and structured data on {len(pages())} pages")
    else:
        build()
