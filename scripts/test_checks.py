#!/usr/bin/env python3
"""Mutation tests for the site's two guards (Story 18.8).

A check that cannot fail is not a check. Each case copies the site to a temp
directory, breaks one thing on purpose, and asserts the guard goes RED; the
untouched copy must be GREEN, and a few look-alikes that are fine must stay
green too (so the guard is not just red at everything).

    python3 scripts/test_checks.py
"""
from __future__ import annotations

import pathlib
import shutil
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

import build_launch  # noqa: E402
import check_platform  # noqa: E402

RELEASE = build_launch.release_ms(ROOT)
EARLY = RELEASE - 30 * build_launch.DAY_MS        # a month before: store-link rule asleep
failures: list[str] = []


def copy_site() -> pathlib.Path:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="sg-site-"))
    for item in ROOT.iterdir():
        if item.name in {".git", ".wrangler", "node_modules"}:
            continue
        if item.is_dir():
            shutil.copytree(item, tmp / item.name)
        else:
            shutil.copy2(item, tmp / item.name)
    return tmp


def edit(root: pathlib.Path, rel: str, old: str, new: str) -> None:
    p = root / rel
    text = p.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"test setup: {old!r} not found in {rel}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


def launch_case(name: str, expect_red: bool, mutate=None, now_ms: int = EARLY) -> None:
    root = copy_site()
    try:
        if mutate:
            mutate(root)
        red = bool(build_launch.check(root, now_ms=now_ms))
    finally:
        shutil.rmtree(root)
    ok = red == expect_red
    print(f"{'ok  ' if ok else 'FAIL'} launch   {'red  ' if red else 'green'} {name}")
    if not ok:
        failures.append(f"launch: {name}")


def platform_case(name: str, expect_red: bool, mutate=None) -> None:
    root = copy_site()
    try:
        if mutate:
            mutate(root)
        red = bool(check_platform.check(check_platform.targets(root), root))
    finally:
        shutil.rmtree(root)
    ok = red == expect_red
    print(f"{'ok  ' if ok else 'FAIL'} platform {'red  ' if red else 'green'} {name}")
    if not ok:
        failures.append(f"platform: {name}")


HERO = "<h1>Put the world in order</h1>"
PRIV_H1 = "<h1>Privacy</h1>"


def add_para(text: str, page: str = "privacy.html", anchor: str = PRIV_H1):
    return lambda r: edit(r, page, anchor, anchor + f"\n  <p>{text}</p>")


# ---- the launch guard -------------------------------------------------------
launch_case("the site as committed", False)
launch_case("hand-typed date in a paragraph", True, add_para("Out on 10 December 2026."))
launch_case("hand-typed 'December 10th'", True, add_para("Arrives December 10th."))
launch_case("ISO date in JSON-LD", True, lambda r: edit(
    r, "index.html", "</head>",
    '<script type="application/ld+json">{"datePublished":"2026-12-10"}</script>\n</head>'))
launch_case("'Out now' in an Open Graph tag", True, lambda r: edit(
    r, "index.html", '<meta property="og:type"',
    '<meta property="og:title" content="Sorting Geography: out now">\n<meta property="og:type"'))
launch_case("'coming soon' wrapped across two lines", True, add_para("The game is coming\n    soon."))
launch_case("'In development' tag put back", True, lambda r: edit(
    r, "index.html", HERO, '<span class="tag">In development</span>\n  ' + HERO))
launch_case("a generated region edited by hand", True, lambda r: edit(
    r, "index.html", '<p class="launch-date">Out now.</p>', '<p class="launch-date">Out now!</p>'))
launch_case("the constant moved, pages not rebuilt", True, lambda r: edit(
    r, "src/launch.js", f"RELEASE_UTC_MS = {RELEASE};",
    f"RELEASE_UTC_MS = {RELEASE + build_launch.DAY_MS};"))
launch_case("the countdown region removed from the home page", True, lambda r: edit(
    r, "index.html", "<!-- launch:hero-countdown -->", "<!-- gone -->"))
launch_case("store link missing 6 days before release", True,
            now_ms=RELEASE - 6 * build_launch.DAY_MS)
launch_case("store link missing at the moment itself", True, now_ms=RELEASE)
launch_case("look-alike: '10 decimals' is not the date", False, add_para("Shown to 10 decimals."))
launch_case("look-alike: a date in a comment", False, lambda r: edit(
    r, "privacy.html", PRIV_H1, PRIV_H1 + "\n  <!-- out now on 10 December -->"))

# ---- the platform guard -----------------------------------------------------
platform_case("the site as committed", False)
platform_case("'iPhone' in copy", True, add_para("Play it on your iPhone or Android phone."))
platform_case("'iPad' in copy", True, add_para("Looks great on an iPad and on Android tablets."))
platform_case("App Store alone", True, add_para("Download it from the App Store."))
platform_case("Google Play alone", True, add_para("Download it from Google Play."))
platform_case("Android alone", True, add_para("Made for Android."))
platform_case("iOS alone", True, add_para("Made for iOS."))
platform_case("Apple first: 'iOS and Android'", True, add_para("For iOS and Android."))
platform_case("Apple first: 'Apple or Google'", True, add_para("Between you and Apple or Google."))
platform_case("App Store badge alone, alt text only", True, lambda r: edit(
    r, "index.html", HERO, '<div><img src="x.svg" alt="Download on the App Store"></div>\n  ' + HERO))
platform_case("meta description names iOS alone", True, lambda r: edit(
    r, "index.html", "</head>", '<meta name="twitter:description" content="A game for iOS.">\n</head>'))
platform_case("README says iPhone", True, lambda r: edit(
    r, "README.md", "for Android\nand iOS.", "for iPhone\nand Android."))
platform_case("robots.txt comment names Apple alone", True, lambda r: edit(
    r, "robots.txt", "User-agent: *", "# Applebot welcome\n\nApple crawlers too\n\nUser-agent: *"))
platform_case("look-alike: '-apple-system' font in a style attribute", False, add_para(
    '<span style="font-family:-apple-system">Plain text</span>'))
platform_case("look-alike: 'Android and iOS' in order", False, add_para("For Android and iOS."))

# ---- review round 1 ----------------------------------------------------------
# F2: the worker wiring that makes the flip happen at all.
launch_case("W6: worker falls through to env.ASSETS.fetch", True, lambda r: edit(
    r, "src/worker.js", "return serveAsset(request, env, Date.now());", "return env.ASSETS.fetch(request);"))
launch_case("W7: run_worker_first = false", True, lambda r: edit(
    r, "wrangler.toml", "run_worker_first = true", "run_worker_first = false"))
launch_case("W7b: run_worker_first line deleted", True, lambda r: edit(
    r, "wrangler.toml", "run_worker_first = true", ""))
launch_case("W6b: serveAsset import dropped", True, lambda r: edit(
    r, "src/worker.js", "import { serveAsset } from './pages.js';", ""))


# F1: the out sentence never names a store that has no link.
def out_case(name, stores, must_name):
    gen = build_launch.regions(RELEASE, stores)
    names = "on Android and iOS" in gen["hero-countdown"].split('class="only-post"')[1]
    ok = names == must_name
    print(f"{'ok  ' if ok else 'FAIL'} out      {name}")
    if not ok:
        failures.append(f"out: {name}")


G = ("google", "Google Play", "https://play.google.com/x")
A = ("apple", "App Store", "https://apps.apple.com/x")
out_case("both links: 'Out now on Android and iOS'", [G, A], True)
out_case("App Store link missing: just 'Out now'", [G, ("apple", "App Store", None)], False)
out_case("Google Play link missing: just 'Out now'", [("google", "Google Play", None), A], False)
launch_case("out sentence hand-edited to name both stores", True, lambda r: edit(
    r, "index.html", '<p class="launch-date">Out now.</p>', '<p class="launch-date">Out now on Android and iOS.</p>'))

if failures:
    print(f"\n{len(failures)} mutation case(s) wrong:")
    for f in failures:
        print("  " + f)
    sys.exit(1)
print("\nok   every break went red, every clean case stayed green")
