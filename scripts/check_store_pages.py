#!/usr/bin/env python3
"""The pages the store listings point at (Story 18.9).

Offline, for CI (no network): the files the stores and AdMob need exist and
say what they must.

  - /support/ and /privacy/ exist and each carries a working contact address;
  - /privacy.html is gone from the tree (the worker 301s it to /privacy/, which
    the app's kPrivacyUrl still relies on), and the worker still has that rule;
  - /app-ads.txt holds exactly the AdMob publisher line, in the IAB format;
  - robots.txt lets every crawler that matters reach the site and app-ads.txt
    (read with Python's own robots.txt parser, not a regex);
  - the sitemap lists the support and privacy pages.

The LIVE half (each URL answers 200 on the deployed site) is
scripts/check_live.py, run after a deploy.

    python3 scripts/check_store_pages.py
"""
from __future__ import annotations

import pathlib
import re
import sys
import urllib.robotparser

ROOT = pathlib.Path(__file__).resolve().parent.parent

# The AdMob account Sorting History already uses (its site's app-ads.txt,
# read 2026-11-19); the same account serves Sorting Geography (plan, Tue 17 Nov).
APP_ADS_LINE = "google.com, pub-8713191393304948, DIRECT, f08c47fec0942fa0"
IAB_LINE = re.compile(r"^[a-z0-9.-]+\.[a-z]{2,},\s*pub-\d{16},\s*(?:DIRECT|RESELLER)(?:,\s*[0-9a-f]+)?$")
SUPPORT_EMAIL = "support@sortinggeography.com"
CRAWLERS = ["*", "Googlebot", "Google-adstxt", "Mediapartners-Google", "AdsBot-Google", "Applebot"]


def check(root: pathlib.Path = ROOT) -> list[str]:
    bad: list[str] = []

    for page in ("support/index.html", "privacy/index.html", "terms/index.html", "press/index.html"):
        p = root / page
        if not p.is_file():
            bad.append(f"{page} is missing")
            continue
        text = p.read_text(encoding="utf-8")
        if not re.search(rf'href="mailto:{re.escape(SUPPORT_EMAIL)}(?:\?[^"]*)?"', text):
            bad.append(f"{page}: no mailto link to {SUPPORT_EMAIL}")
        if "<title>" not in text:
            bad.append(f"{page}: no <title>")

    # Story 20.3b: the closed-test page. It is for invited testers, so it stays
    # out of search (noindex, not in the sitemap) but must exist and carry the
    # contact address testers report to.
    tp = root / "testers/index.html"
    if not tp.is_file():
        bad.append("testers/index.html is missing (the Google Play closed-test page)")
    else:
        tt = tp.read_text(encoding="utf-8")
        if not re.search(rf'href="mailto:{re.escape(SUPPORT_EMAIL)}(?:\?[^"]*)?"', tt):
            bad.append(f"testers/index.html: no mailto link to {SUPPORT_EMAIL}")
        if not re.search(r'<meta\s+name="robots"\s+content="[^"]*\bnoindex\b[^"]*"\s*/?>', tt, re.I):
            bad.append("testers/index.html: no <meta name=\"robots\" content=\"noindex\">")

    if (root / "privacy.html").exists():
        bad.append("privacy.html is back at the root; the page lives at /privacy/ (the worker 301s the old name)")
    worker = (root / "src" / "worker.js").read_text(encoding="utf-8")
    if not re.search(r"pathname === '/privacy\.html'\)\s*\{\s*return Response\.redirect\(`\$\{url\.origin\}/privacy/`, 301\)", worker):
        bad.append("src/worker.js no longer 301s /privacy.html to /privacy/ (the app links to /privacy.html)")

    ads = root / "app-ads.txt"
    if not ads.is_file():
        bad.append("app-ads.txt is missing")
    else:
        lines = [ln.strip() for ln in ads.read_text(encoding="utf-8").splitlines()
                 if ln.strip() and not ln.strip().startswith("#")]
        for ln in lines:
            if not IAB_LINE.match(ln):
                bad.append(f"app-ads.txt: not an IAB app-ads.txt line: {ln!r}")
        if APP_ADS_LINE not in lines:
            bad.append(f"app-ads.txt: the publisher line is missing: {APP_ADS_LINE!r}")

    robots = root / "robots.txt"
    rp = urllib.robotparser.RobotFileParser()
    rp.parse(robots.read_text(encoding="utf-8").splitlines() if robots.is_file() else [])
    for agent in CRAWLERS:
        for path in ("/", "/app-ads.txt", "/support/", "/privacy/"):
            if not rp.can_fetch(agent, f"https://sortinggeography.com{path}"):
                bad.append(f"robots.txt blocks {agent} from {path}")

    sitemap = (root / "sitemap.xml").read_text(encoding="utf-8")
    for loc in ("https://sortinggeography.com/support/", "https://sortinggeography.com/privacy/",
                "https://sortinggeography.com/terms/", "https://sortinggeography.com/press/"):
        if f"<loc>{loc}</loc>" not in sitemap:
            bad.append(f"sitemap.xml does not list {loc}")
    if "sortinggeography.com/testers/" in sitemap:
        bad.append("sitemap.xml lists /testers/; the tester page is for invited people, not search")
    return bad


if __name__ == "__main__":
    problems = check()
    if problems:
        print("store pages check FAILED (Story 18.9):")
        for b in problems:
            print("  " + b)
        sys.exit(1)
    print("ok   support, privacy, app-ads.txt, robots.txt and sitemap in place")
