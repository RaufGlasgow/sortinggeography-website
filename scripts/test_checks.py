#!/usr/bin/env python3
"""Mutation tests for the site's guards (Stories 18.8 and 18.9).

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
import check_store_pages  # noqa: E402
import build_features  # noqa: E402
import json  # noqa: E402
import subprocess  # noqa: E402

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


def add_para(text: str, page: str = "privacy/index.html", anchor: str = PRIV_H1):
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
    r, "privacy/index.html", PRIV_H1, PRIV_H1 + "\n  <!-- out now on 10 December -->"))

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


# ---- the store-pages guard (18.9) -------------------------------------------
def store_case(name: str, expect_red: bool, mutate=None) -> None:
    root = copy_site()
    try:
        if mutate:
            mutate(root)
        red = bool(check_store_pages.check(root))
    finally:
        shutil.rmtree(root)
    ok = red == expect_red
    print(f"{'ok  ' if ok else 'FAIL'} store    {'red  ' if red else 'green'} {name}")
    if not ok:
        failures.append(f"store: {name}")


def write(rel: str, text: str):
    return lambda r: (r / rel).write_text(text, encoding="utf-8")


store_case("the site as committed", False)
store_case("support page deleted", True, lambda r: (r / "support/index.html").unlink())
store_case("privacy page deleted", True, lambda r: (r / "privacy/index.html").unlink())
store_case("support page loses its contact address", True, lambda r: edit(
    r, "support/index.html", 'href="mailto:support@sortinggeography.com"', 'href="mailto:someone@example.com"'))
store_case("privacy.html put back at the root", True, write("privacy.html", "<html></html>"))
store_case("worker loses the /privacy.html redirect", True, lambda r: edit(
    r, "src/worker.js", "if (url.pathname === '/privacy.html') {", "if (url.pathname === '/old.html') {"))
store_case("app-ads.txt deleted", True, lambda r: (r / "app-ads.txt").unlink())
store_case("app-ads.txt with a wrong publisher id", True, write(
    "app-ads.txt", "google.com, pub-0000000000000000, DIRECT, f08c47fec0942fa0\n"))
store_case("app-ads.txt with a malformed extra line", True, lambda r: (r / "app-ads.txt").write_text(
    (r / "app-ads.txt").read_text() + "google.com pub-8713191393304948 DIRECT\n"))
store_case("robots.txt blocks everyone", True, write("robots.txt", "User-agent: *\nDisallow: /\n"))
store_case("robots.txt blocks only the AdMob crawler", True, lambda r: (r / "robots.txt").write_text(
    (r / "robots.txt").read_text().replace("User-agent: Google-adstxt\nAllow: /", "User-agent: Google-adstxt\nDisallow: /")))
store_case("robots.txt blocks app-ads.txt by path", True, lambda r: (r / "robots.txt").write_text(
    "User-agent: *\nDisallow: /app-ads.txt\n"))
store_case("sitemap drops the support page", True, lambda r: edit(
    r, "sitemap.xml", "  <url><loc>https://sortinggeography.com/support/</loc></url>\n", ""))
store_case("look-alike: a comment line in app-ads.txt", False, lambda r: (r / "app-ads.txt").write_text(
    "# Sorting Geography\n" + (r / "app-ads.txt").read_text()))

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


# F3: the pages describe main as it is.
def feature_case(name: str, expect_red: bool, mutate=None, flags=None) -> None:
    root = copy_site()
    try:
        if flags is not None:
            (root / "src/features.json").write_text(json.dumps(flags))
            build_features.build(root)
        if mutate:
            mutate(root)
        red = bool(build_features.check(root))
        if flags is not None:
            # Every state's text must also pass the platform and launch guards.
            red = red or bool(check_platform.check(check_platform.targets(root), root)) \
                or bool(build_launch.check(root, now_ms=EARLY))
    finally:
        shutil.rmtree(root)
    ok = red == expect_red
    print(f"{'ok  ' if ok else 'FAIL'} feature  {'red  ' if red else 'green'} {name}")
    if not ok:
        failures.append(f"feature: {name}")


ALL_ON = {"analytics": True, "analytics_switch": True, "unlock": True}
feature_case("the site as committed", False)
feature_case("all features on: built text passes every guard", False, flags=ALL_ON)
feature_case("analytics on, no switch: built text passes", False,
             flags={"analytics": True, "analytics_switch": False, "unlock": False})
feature_case("features.json flipped, pages not rebuilt", True, lambda r: (r / "src/features.json").write_text(
    json.dumps(ALL_ON)))
feature_case("PostHog typed into the privacy page by hand", True, add_para("Usage numbers go to PostHog."))
feature_case("Restore purchases typed into support by hand", True, add_para(
    "Use Restore purchases in Settings.", page="support/index.html", anchor="<h1>Support</h1>"))
feature_case("the switch label typed by hand", True, add_para("Turn off Share anonymous usage numbers."))
feature_case("an analytics region deleted", True, lambda r: edit(
    r, "privacy/index.html", "<!-- feature:privacy-analytics -->", "<!-- gone -->"))


def built_text(flags) -> str:
    root = copy_site()
    try:
        (root / "src/features.json").write_text(json.dumps(flags))
        build_features.build(root)
        return (root / "privacy/index.html").read_text() + (root / "support/index.html").read_text()
    finally:
        shutil.rmtree(root)


on_text = built_text(ALL_ON)
for name, cond in [
    ("F4: IP wording is 'discarded on arrival, never stored' wherever the IP is named",
     on_text.count("discarded on arrival, never stored") >= 3 and "Never your IP" not in on_text),
    ("F5: no 'sends nothing anywhere' in any state",
     "sends nothing anywhere" not in on_text and "sends nothing anywhere" not in built_text(
         {"analytics": False, "analytics_switch": False, "unlock": False})),
]:
    print(f"{'ok  ' if cond else 'FAIL'} wording  {name}")
    if not cond:
        failures.append(f"wording: {name}")


# F3 --game: features.json against a fake game repo's main.
def fake_game(unlock: bool, posthog: bool, switch: bool) -> pathlib.Path:
    g = pathlib.Path(tempfile.mkdtemp(prefix="sg-game-"))
    (g / "app/lib/shell").mkdir(parents=True)
    (g / "packages/sort_platform").mkdir(parents=True)
    (g / "app/lib/shell/paid_unlock_seam.dart").write_text(
        f"const bool kPaidUnlockEnabled = {'true' if unlock else 'false'};\n")
    (g / "app/pubspec.yaml").write_text("dependencies:\n  flutter:\n    sdk: flutter\n"
                                        + ("  posthog_flutter: ^5.0.0\n" if posthog else ""))
    (g / "packages/sort_platform/pubspec.yaml").write_text("dependencies:\n  meta: any\n")
    (g / "app/lib/settings.dart").write_text(
        ("const label = 'Share anonymous usage numbers';\n" if switch else "const label = 'Sound';\n"))
    for cmd in (["init", "-q", "-b", "main"], ["add", "-A"],
                ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "x"]):
        subprocess.run(["git", "-C", str(g), *cmd], check=True)
    return g


def game_case(name, game_state, flags, expect_red):
    g = fake_game(*game_state)
    try:
        red = bool(build_features.compare(flags, build_features.game_features(g, "main")))
    finally:
        shutil.rmtree(g)
    ok = red == expect_red
    print(f"{'ok  ' if ok else 'FAIL'} game     {'red  ' if red else 'green'} {name}")
    if not ok:
        failures.append(f"game: {name}")


OFF = {"analytics": False, "analytics_switch": False, "unlock": False}
game_case("main has nothing, pages claim nothing", (False, False, False), OFF, False)
game_case("pages claim the unlock, main has it off", (False, False, False), {**OFF, "unlock": True}, True)
game_case("pages claim analytics, main has no posthog_flutter", (False, False, False),
          {**OFF, "analytics": True}, True)
game_case("pages claim the switch, main has no such row", (False, True, False),
          {"analytics": True, "analytics_switch": True, "unlock": False}, True)
game_case("main turned the unlock on, pages say nothing", (True, False, False), OFF, True)
game_case("main ships PostHog, pages say no numbers are sent", (False, True, False), OFF, True)
game_case("everything on both sides", (True, True, True), ALL_ON, False)


if failures:
    print(f"\n{len(failures)} mutation case(s) wrong:")
    for f in failures:
        print("  " + f)
    sys.exit(1)
print("\nok   every break went red, every clean case stayed green")
