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
import re
import shutil
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

import build_launch  # noqa: E402
import check_platform  # noqa: E402
import check_store_pages  # noqa: E402
import check_sheet_links  # noqa: E402
import build_i18n  # noqa: E402
import build_seo  # noqa: E402
import site_i18n  # noqa: E402
import build_features  # noqa: E402
import check_comments  # noqa: E402
import check_wrangler_pin  # noqa: E402
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


def fill_tester_links(root: pathlib.Path) -> None:
    """Both closed-test links set to valid values, pages rebuilt (as Ra'uf's fill will be)."""
    p = root / "src/testers.json"
    t = json.loads(p.read_text())
    t["group_url"] = build_features.GROUP_PREFIX + "sorting-geography-testers"
    t["optin_url"] = build_features.OPTIN_URL
    p.write_text(json.dumps(t))
    build_features.build(root)


def set_one_link(root: pathlib.Path) -> None:
    p = root / "src/testers.json"
    t = json.loads(p.read_text())
    t["group_url"] = build_features.GROUP_PREFIX + "sorting-geography-testers"
    p.write_text(json.dumps(t))
    build_features.build(root)


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
# 18.10: every response leaves through withSecurityHeaders.
launch_case("W8: fetch() returns route() unwrapped (no security headers)", True, lambda r: edit(
    r, "src/worker.js", "return withSecurityHeaders(await route(request, env, ctx));", "return route(request, env, ctx);"))
launch_case("W8b: route() answers before the serveAsset fall-through", True, lambda r: edit(
    r, "src/worker.js", "    return serveAsset(request, env, Date.now());\n}", "    return serveAsset(request, env, Date.now());\n    return null;\n}"))


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

# Round 2 follow-up: the daily CI run is F1's whole fix.
launch_case("schedule trigger removed from ci.yml", True, lambda r: edit(
    r, ".github/workflows/ci.yml", "  schedule:\n    - cron: '17 6 * * *'\n", ""))
launch_case("cron commented out", True, lambda r: edit(
    r, ".github/workflows/ci.yml", "    - cron: '17 6 * * *'", "    # - cron: '17 6 * * *'"))
launch_case("cron made weekly", True, lambda r: edit(
    r, ".github/workflows/ci.yml", "'17 6 * * *'", "'17 6 * * 1'"))

# ---- 18.9 terms + press kit ---------------------------------------------------
feature_case("'190 questions' typed by hand outside a region", True, add_para(
    "There are 190 questions.", page="terms/index.html", anchor="<h1>Terms</h1>"))
feature_case("'195 countries' typed by hand", True, add_para(
    "All 195 countries.", page="press/index.html", anchor="<h1>Press kit</h1>"))
feature_case("data version typed by hand", True, add_para(
    "Data version v089.", page="press/index.html", anchor="<h1>Press kit</h1>"))
feature_case("facts.json moved, pages not rebuilt", True, lambda r: (r / "src/facts.json").write_text(
    (r / "src/facts.json").read_text().replace('"axes": 190', '"axes": 191')))
feature_case("press facts region deleted", True, lambda r: edit(
    r, "press/index.html", "<!-- feature:press-facts -->", "<!-- gone -->"))
launch_case("press release line typed by hand", True, lambda r: edit(
    r, "press/index.html", "<!-- launch:press-release -->", "10 December 2026 <!-- launch:press-release -->"))
store_case("press page loses its contact", True, lambda r: edit(
    r, "press/index.html", 'href="mailto:support@sortinggeography.com?subject=Press"', 'href="mailto:x@example.com"'))
store_case("terms page deleted", True, lambda r: (r / "terms/index.html").unlink())
store_case("sitemap drops the press page", True, lambda r: edit(
    r, "sitemap.xml", "  <url><loc>https://sortinggeography.com/press/</loc></url>\n", ""))


def todo_case(name, mutate, expect_red, links=True):
    root = copy_site()
    try:
        if links:
            fill_tester_links(root)
        mutate(root)
        red = bool(build_features.todos(root))
    finally:
        shutil.rmtree(root)
    ok = red == expect_red
    print(f"{'ok  ' if ok else 'FAIL'} todo     {'red  ' if red else 'green'} {name}")
    if not ok:
        failures.append(f"todo: {name}")


# Every placeholder is filled today (Empty Cup Media LLC, Nevada; Ra'uf 2026-11-19),
# so the clean tree must pass and a placeholder put back in ANY form must go red
# (review-share 18.9b B2, B3, and upper case). Comments are never served (the
# worker strips them, B5; test_launch.mjs proves it), so they are not scanned.
TODO = '<span class="todo">x</span>'
todo_case("all placeholders filled today: deploy allowed", lambda r: None, False)
todo_case("placeholder back in terms", lambda r: edit(
    r, "terms/index.html", "Empty Cup Media LLC", TODO), True)
todo_case("placeholder back in press", lambda r: edit(
    r, "press/index.html", "<td>Empty Cup Media LLC</td>", "<td>" + TODO + "</td>"), True)
todo_case("uppercase <SPAN CLASS=\"TODO\">", lambda r: edit(
    r, "terms/index.html", "Empty Cup Media LLC", '<SPAN CLASS="TODO">x</SPAN>'), True)
todo_case("single-quoted class='todo'", lambda r: edit(
    r, "terms/index.html", "Empty Cup Media LLC", "<span class='todo'>x</span>"), True)
todo_case("todo next to another class", lambda r: edit(
    r, "terms/index.html", "Empty Cup Media LLC", '<span class="todo note">x</span>'), True)
todo_case("todo as an unquoted class", lambda r: edit(
    r, "press/index.html", "<td>Empty Cup Media LLC</td>", "<td><span class=todo>x</span></td>"), True)
todo_case("todo class on a div, not a span", lambda r: edit(
    r, "terms/index.html", "<h1>Terms</h1>", '<h1>Terms</h1><div class="x todo">x</div>'), True)
todo_case("span tags stripped, 'to be confirmed' left as plain text", lambda r: edit(
    r, "terms/index.html", "Empty Cup Media LLC", "Empty Cup Media LLC or Inc., to be confirmed by Ra'uf"), True)
todo_case("'[todo' left as plain text", lambda r: edit(
    r, "press/index.html", "<td>Empty Cup Media LLC</td>", "<td>[todo: suffix]</td>"), True)
todo_case("a class merely containing 'todo' (todo-list) is not a placeholder", lambda r: edit(
    r, "terms/index.html", "<h1>Terms</h1>", '<h1>Terms</h1><div class="todo-list">x</div>'), False)


# B1: the REAL deploy path. Run the copied site's own `build_features.py --game`
# against a fake game that matches the site, so the only possible red is the
# placeholder. Deleting `+ todos()` from the --game list must turn the second
# case green and fail this suite.
def matching_game(package: str = build_features.PACKAGE) -> pathlib.Path:
    g = fake_game(False, False, False)
    (g / "app/assets/data").mkdir(parents=True)
    (g / "packages/sort_platform/lib/src/l10n").mkdir(parents=True)
    facts = build_features.load_facts(ROOT)
    axes = {f"a{i}": {} for i in range(facts["axes"] - 1)}
    axes["highest_point_m"] = {"PT": float(facts["pt_highest_point_m"])}
    d = {"version": f"dataset-{facts['dataset_version']}-x", "axes": axes,
         "facets": {"continent": {f"C{i}": "x" for i in range(facts["countries"])}}}
    (g / "app/assets/data/dataset_runtime.json").write_text(json.dumps(d))
    (g / "packages/sort_platform/lib/src/l10n/shipped_locales.gen.dart").write_text(
        "const List<String> kShippedLocaleTags = <String>[\n"
        + "".join(f"  '{t}',\n" for t in facts["languages"]) + "];\n")
    (g / "app/android/app").mkdir(parents=True)
    (g / "app/android/app/build.gradle.kts").write_text(
        f'android {{\n    defaultConfig {{\n        applicationId = "{package}"\n    }}\n}}\n')
    for cmd in (["add", "-A"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "facts"]):
        subprocess.run(["git", "-C", str(g), *cmd], check=True)
    return g


def deploy_case(name, mutate, expect_red, package=build_features.PACKAGE, links=True):
    root, g = copy_site(), matching_game(package)
    try:
        if links:
            fill_tester_links(root)
        mutate(root)
        r = subprocess.run([sys.executable, str(root / "scripts/build_features.py"),
                            "--game", str(g), "--ref", "main"], capture_output=True, text=True)
        red = r.returncode != 0
    finally:
        shutil.rmtree(root)
        shutil.rmtree(g)
    ok = red == expect_red
    print(f"{'ok  ' if ok else 'FAIL'} deploy   {'red  ' if red else 'green'} {name}")
    if not ok:
        failures.append(f"deploy: {name}")
        print("     " + (r.stdout + r.stderr).strip().replace("\n", "\n     ")[:600])


deploy_case("--game on today's site against a matching game", lambda r: None, False)
deploy_case("--game with a placeholder open in terms", lambda r: edit(
    r, "terms/index.html", "Empty Cup Media LLC", TODO), True)
# 20.3b: the tester page's links are todo spans until Ra'uf has them.
# 20.3c: open tester links -> the page is not served -> --game passes; once the
# links are set the page is served and checked like any other.
deploy_case("--game with today's tester links still open (page not served)", lambda r: None, False, links=False)
deploy_case("--game with one tester link set, the other still open", lambda r: set_one_link(r), False, links=False)
deploy_case("--game with both links set and a placeholder put back in the page", lambda r: edit(
    r, "testers/index.html", "Become a tester</h1>", "Become a tester</h1><p><span class=\"todo\">x</span></p>"), True)
deploy_case("--game when the game's applicationId differs", lambda r: None, True, package="com.example.other")


def facts_case(name, game_over, expect_red):
    g = pathlib.Path(tempfile.mkdtemp(prefix="sg-game-"))
    try:
        (g / "app/assets/data").mkdir(parents=True)
        (g / "packages/sort_platform/lib/src/l10n").mkdir(parents=True)
        real = {"version": "dataset-v089-abc", "axes": {f"a{i}": {} for i in range(190)},
                "facets": {"continent": {f"C{i}": "x" for i in range(195)}}}
        real["axes"]["highest_point_m"] = {"PT": 2351.0}
        del real["axes"]["a0"]
        langs = ["en"]
        real, langs = game_over(real, langs)
        (g / "app/assets/data/dataset_runtime.json").write_text(json.dumps(real))
        (g / "packages/sort_platform/lib/src/l10n/shipped_locales.gen.dart").write_text(
            "const List<String> kShippedLocaleTags = <String>[\n" + "".join(f"  '{t}',\n" for t in langs) + "];\n")
        for cmd in (["init", "-q", "-b", "main"], ["add", "-A"],
                    ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "x"]):
            subprocess.run(["git", "-C", str(g), *cmd], check=True)
        red = bool(build_features.compare_facts(build_features.load_facts(ROOT),
                                                build_features.game_facts(g, "main")))
    finally:
        shutil.rmtree(g)
    ok = red == expect_red
    print(f"{'ok  ' if ok else 'FAIL'} facts    {'red  ' if red else 'green'} {name}")
    if not ok:
        failures.append(f"facts: {name}")


def axes_plus_one(d, l):
    d["axes"]["extra"] = {}
    return d, l


def new_version(d, l):
    d["version"] = "dataset-v090-x"
    return d, l


def german_ships(d, l):
    return d, l + ["de"]


def pt_changes(d, l):
    d["axes"]["highest_point_m"]["PT"] = 2350.0
    return d, l


facts_case("game matches facts.json", lambda d, l: (d, l), False)
facts_case("game gains an axis", axes_plus_one, True)
facts_case("game moves to v090", new_version, True)
facts_case("German ships", german_ships, True)
facts_case("Portugal's highest point changes", pt_changes, True)

# Ra'uf 2026-11-19: no streak claim either way.
feature_case("'no streak to lose' typed into the home page", True, lambda r: edit(
    r, "index.html", "<h1>Put the world in order</h1>", "<h1>Put the world in order</h1>\n  <p>No streak to lose.</p>"))
feature_case("'Daily streak' put back into privacy", True, lambda r: edit(
    r, "privacy/index.html", "your scores and your", "your scores, your Daily streak and your"))
feature_case("a streak line inside a generated region", True, lambda r: edit(
    r, "privacy/index.html", "<!-- feature:privacy-summary -->", "<!-- feature:privacy-summary --><li>Keep your streak.</li>"))

# 18.9c: '<!--' and '-->' only inside real comments, so the worker's
# HTMLRewriter strip and test_served.mjs's split agree on every page.
def comment_case(name: str, expect_red: bool, mutate=None) -> None:
    root = copy_site()
    try:
        if mutate:
            mutate(root)
        red = bool(check_comments.check(root))
    finally:
        shutil.rmtree(root)
    ok = red == expect_red
    print(f"{'ok  ' if ok else 'FAIL'} comment  {'red  ' if red else 'green'} {name}")
    if not ok:
        failures.append(f"comment: {name}")


H1 = "<h1>Terms</h1>"
comment_case("today's pages", False)
comment_case("an ordinary comment added to the body", False, lambda r: edit(
    r, "terms/index.html", H1, H1 + "<!-- a note -->"))
comment_case("'<!--' inside an inline script", True, lambda r: edit(
    r, "terms/index.html", H1, H1 + '<script>var a = "<!-- x";</script>'))
comment_case("'-->' inside an inline script", True, lambda r: edit(
    r, "terms/index.html", H1, H1 + '<script>if (a-->0) {}</script>'))
comment_case("'<!--' inside a style", True, lambda r: edit(
    r, "terms/index.html", H1, H1 + '<style>p::after { content: "<!--"; }</style>'))
comment_case("'-->' inside an attribute", True, lambda r: edit(
    r, "terms/index.html", H1, H1 + '<p title="a-->b">x</p>'))
comment_case("'<!--' inside a single-quoted attribute", True, lambda r: edit(
    r, "terms/index.html", H1, H1 + "<p data-x='<!--'>x</p>"))
comment_case("a stray '-->' in page text", True, lambda r: edit(
    r, "terms/index.html", H1, H1 + "<p>a --> b</p>"))
comment_case("a comment never closed", True, lambda r: edit(
    r, "terms/index.html", H1, H1 + "<!-- open"))
comment_case("a comment that opens another inside it", True, lambda r: edit(
    r, "terms/index.html", H1, H1 + "<!-- a <!-- b -->"))
comment_case("an escaped &lt;!-- in text is fine", False, lambda r: edit(
    r, "terms/index.html", H1, H1 + "<p>&lt;!-- shown as text</p>"))

# 18.9c: the wrangler CI tests is the wrangler that deploys.
def pin_case(name: str, expect_red: bool, mutate=None) -> None:
    root = copy_site()
    try:
        if mutate:
            mutate(root)
        red = bool(check_wrangler_pin.check(root))
    finally:
        shutil.rmtree(root)
    ok = red == expect_red
    print(f"{'ok  ' if ok else 'FAIL'} pin      {'red  ' if red else 'green'} {name}")
    if not ok:
        failures.append(f"pin: {name}")


RB = "docs/DEPLOY-RUNBOOK.md"
pin_case("today: CI and deploy both 4.74.0", False)
pin_case("deploy step moved to another version", True, lambda r: edit(
    r, RB, "npx --yes wrangler@4.74.0 deploy\n", "npx --yes wrangler@4.75.0 deploy\n"))
pin_case("CI moved to another version", True, lambda r: edit(
    r, ".github/workflows/ci.yml", "WRANGLER: npx --yes wrangler@4.74.0", "WRANGLER: npx --yes wrangler@4.75.0"))
pin_case("deploy step back to bare wrangler deploy", True, lambda r: edit(
    r, RB, "npx --yes wrangler@4.74.0 deploy\n", "wrangler deploy\n"))
pin_case("deploy step back to wrangler@3", True, lambda r: edit(
    r, RB, "npx --yes wrangler@4.74.0 deploy\n", "npx -y wrangler@3 deploy\n"))
pin_case("deploy command deleted from Step 4", True, lambda r: edit(
    r, RB, "npx --yes wrangler@4.74.0 deploy\n", "\n"))
pin_case("an unpinned deploy line beside the pinned one", True, lambda r: edit(
    r, RB, "npx --yes wrangler@4.74.0 deploy\n", "npx --yes wrangler@4.74.0 deploy\nwrangler deploy --env staging\n"))
pin_case("a second pinned deploy line on another version", True, lambda r: edit(
    r, RB, "npx --yes wrangler@4.74.0 deploy\n", "npx --yes wrangler@4.74.0 deploy\nnpx --yes wrangler@4.75.0 deploy\n"))
pin_case("'npx wrangler deploy' added to Step 4 (no flag, no version)", True, lambda r: edit(
    r, RB, "npx --yes wrangler@4.74.0 deploy\n", "npx --yes wrangler@4.74.0 deploy\nnpx wrangler deploy\n"))
pin_case("'cd . && wrangler deploy' added to Step 4", True, lambda r: edit(
    r, RB, "npx --yes wrangler@4.74.0 deploy\n", "npx --yes wrangler@4.74.0 deploy\ncd . && wrangler deploy\n"))
pin_case("README back to a bare wrangler deploy", True, lambda r: edit(
    r, "README.md", "npx --yes wrangler@4.74.0 deploy ", "wrangler deploy "))
pin_case("README on another version", True, lambda r: edit(
    r, "README.md", "npx --yes wrangler@4.74.0 deploy ", "npx --yes wrangler@4.75.0 deploy "))
pin_case("a bare deploy in prose elsewhere in the runbook", True, lambda r: edit(
    r, RB, "`npx --yes wrangler@4.74.0 deploy --dry-run`", "`wrangler deploy --dry-run`"))
pin_case("a new doc in docs/ with 'npx -y wrangler@3 deploy'", True, lambda r: (r / "docs/NOTE.md").write_text("Run `npx -y wrangler@3 deploy`.\n"))
pin_case("CI loose to a major (wrangler@4)", True, lambda r: edit(
    r, ".github/workflows/ci.yml", "WRANGLER: npx --yes wrangler@4.74.0", "WRANGLER: npx --yes wrangler@4"))

# 18.5: the welcome email reads the facts through a generated module.
feature_case("src/facts.gen.js hand-edited", True, lambda r: (r / "src/facts.gen.js").write_text(
    (r / "src/facts.gen.js").read_text().replace('"axes": 190', '"axes": 200')))
feature_case("src/facts.gen.js deleted", True, lambda r: (r / "src/facts.gen.js").unlink())

# ---- 20.9: the game links only to sheets the site has ------------------------------
def sheet_game(files: dict[str, str]) -> pathlib.Path:
    g = pathlib.Path(tempfile.mkdtemp(prefix="sg-game-"))
    roster = {"_meta": {}, "countries": {iso: {} for iso in ("AD", "AE", "FR")}}
    files = {"pipeline/roster/countries.json": json.dumps(roster), "app/lib/main.dart": "void main() {}\n", **files}
    for rel, text in files.items():
        (g / rel).parent.mkdir(parents=True, exist_ok=True)
        (g / rel).write_text(text)
    for cmd in (["init", "-q", "-b", "main"], ["add", "-A"],
                ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "x"]):
        subprocess.run(["git", "-C", str(g), *cmd], check=True)
    return g


def sheets(root, langs):
    for lang in langs:
        for iso in ("ad", "ae", "fr"):
            p = root / check_sheet_links.sheet_path(lang, iso)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("<!doctype html><html><body><h1>x</h1></body></html>")


def sheet_case(name, dart, expect_red, have=(), extra=None):
    files = {} if dart is None else {check_sheet_links.SHEET_URL_DART: dart}
    files.update(extra or {})
    g, root = sheet_game(files), copy_site()
    try:
        sheets(root, have)
        red = bool(check_sheet_links.check(g, "main", root))
    finally:
        shutil.rmtree(g)
        shutil.rmtree(root)
    ok = red == expect_red
    print(f"{'ok  ' if ok else 'FAIL'} sheets   {'red  ' if red else 'green'} {name}")
    if not ok:
        failures.append(f"sheets: {name}")


def const(body):
    return f"const Set<String> kCountrySheetLanguages = <String>{{{body}}};\n"


URL_LINE = "const kSheetBase = 'https://sortinggeography.com/countries/';\n"
sheet_case("no sheet file on main, nothing links: no link yet", None, False)
sheet_case("the set empty: no link", URL_LINE + const(""), False)
sheet_case("en linked, every en sheet on the site", URL_LINE + const("'en'"), False, have=["en"])
sheet_case("en linked, no sheets on the site", URL_LINE + const("'en'"), True)
sheet_case("en linked, one sheet missing", URL_LINE + const("'en'"), True, have=["en"],
           extra={"pipeline/roster/countries.json": json.dumps({"countries": {"AD": {}, "AE": {}, "FR": {}, "ZW": {}}})})
sheet_case("de linked, only en sheets on the site", URL_LINE + const("'en', 'de'"), True, have=["en"])
sheet_case("en and pt-pt linked, both on the site", URL_LINE + const("'en', 'pt-pt'"), False, have=["en", "pt-pt"])
sheet_case("a tag in upper case", URL_LINE + const("'pt-PT'"), True, have=["pt-PT"])
sheet_case("a double-quoted tag", URL_LINE + const('"en"'), True, have=["en"])
sheet_case("a tag twice", URL_LINE + const("'en', 'en'"), True, have=["en"])
sheet_case("the constant written another way", URL_LINE + "final kCountrySheetLanguages = {'en'};\n", True, have=["en"])
sheet_case("the constant twice", URL_LINE + const("") + const("'en'"), True, have=["en"])
sheet_case("an interpolated $lang/countries link in another file", None, True,
           extra={"app/lib/play/other.dart": "String u(l, i) => 'https://sortinggeography.com/$l/countries/$i/';\n"})
sheet_case("Uri.https('sortinggeography.com', '/countries/...') in another file", None, True,
           extra={"app/lib/play/other.dart": "final u = Uri.https('sortinggeography.com', '/countries/$iso/');\n"})
sheet_case("countries before the host on the line", None, True,
           extra={"packages/x/lib/y.dart": "const p = '/countries/'; const h = 'SortingGeography.com';\n"})
sheet_case("host in a constant, '$kHost/countries/$iso/' on the next line", None, True,
           extra={"app/lib/play/other.dart": "const kHost = 'https://sortinggeography.com';\nString u(i) =>\n    '$kHost/countries/$i/';\n"})
sheet_case("host + '/countries/' concatenated across lines", None, True,
           extra={"app/lib/play/other.dart": "final u = kSiteOrigin +\n    '/countries/' + iso;\n"})
sheet_case("'countries/axes' in a comment is not a path", None, False,
           extra={"app/lib/shell/t.dart": "// draws only unlocked countries/axes\n"})
sheet_case("the privacy link alone is not a sheet link", None, False,
           extra={"app/lib/shell/seam.dart": "const u = 'https://sortinggeography.com/privacy.html';\n"})
sheet_case("a sheet link built in another file", None, True,
           extra={"app/lib/play/elsewhere.dart": "const u = 'https://sortinggeography.com/de/countries/';\n"})


def sheet_git_case(name, game_for, ref, expect_red):
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="sg-bad-"))
    root = copy_site()
    try:
        red = bool(check_sheet_links.check(game_for(tmp), ref, root))
    finally:
        shutil.rmtree(tmp)
        shutil.rmtree(root)
    ok = red == expect_red
    print(f"{'ok  ' if ok else 'FAIL'} sheets   {'red  ' if red else 'green'} {name}")
    if not ok:
        failures.append(f"sheets: {name}")


def real_game(tmp):
    g = sheet_game({})
    shutil.rmtree(tmp)
    shutil.move(str(g), str(tmp))
    return tmp


def not_the_game(tmp):
    (tmp / "README").write_text("x")
    for cmd in (["init", "-q", "-b", "main"], ["add", "-A"],
                ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "x"]):
        subprocess.run(["git", "-C", str(tmp), *cmd], check=True)
    return tmp


# review S1: any git failure must fail, never read as "no sheet link yet".
sheet_git_case("the real game at a real ref", real_game, "main", False)
sheet_git_case("--game path that does not exist", lambda tmp: tmp / "nope", "main", True)
sheet_git_case("--game folder that is not a git repo", lambda tmp: tmp, "main", True)
sheet_git_case("--ref that does not exist (origin/mian)", real_game, "origin/mian", True)
sheet_git_case("a git repo that is not the game (no roster)", not_the_game, "main", True)


def raises_case(name, fn):
    """Each git guard on its own: the two overlap in check(), so each needs its own red."""
    g = sheet_game({})
    try:
        try:
            fn(g)
            red = False
        except check_sheet_links.GitFailed:
            red = True
    finally:
        shutil.rmtree(g)
    print(f"{'ok  ' if red else 'FAIL'} sheets   {'red  ' if red else 'green'} {name}")
    if not red:
        failures.append(f"sheets: {name}")


raises_case("require_ref refuses a ref that does not exist", lambda g: check_sheet_links.require_ref(g, "origin/mian"))
raises_case("sheet_link_files refuses when git grep fails", lambda g: check_sheet_links.sheet_link_files(g, "origin/mian"))

# 18.8b: no same-day promise in launch copy (team-lead 2026-11-20, fallback A).
HERO_P = "<h1>Put the world in order</h1>"
for name, para in [
    ("'same day' typed into the home page", "<p>On both platforms the same day.</p>"),
    ("'on both on' typed into the home page", "<p>The same game on both on launch.</p>"),
    ("'together' typed into the home page", "<p>Android and iOS together.</p>"),
    ("a platform tied to another date", "<p>Coming to Android and iOS on 3 March 2027.</p>"),
    ("'at the same time' typed into the home page", "<p>On Android and iOS at the same time.</p>"),
    ("'simultaneously' typed into the home page", "<p>Android and iOS launch simultaneously.</p>"),
    ("'simultaneous' typed into the home page", "<p>A simultaneous launch on Android and iOS.</p>"),
]:
    launch_case(name, True, lambda r, para=para: edit(r, "index.html", HERO_P, HERO_P + "\n  " + para))
launch_case("'same day' only inside a comment", False, lambda r: edit(
    r, "index.html", HERO_P, HERO_P + "\n  <!-- never promise the same day -->"))
launch_case("'same day' inside a comment that holds a '>'", False, lambda r: edit(
    r, "index.html", HERO_P, HERO_P + "\n  <!-- launch copy -> never promise the same day -->"))
launch_case("the platforms named without a date", False, lambda r: edit(
    r, "index.html", HERO_P, HERO_P + "\n  <p>For Android and iOS.</p>"))


def generator_case(name, extra, region, expect_red):
    real = build_launch.regions
    def patched(ms, stores=build_launch.STORES, *a, **kw):
        out = real(ms, stores, *a, **kw)
        out[region] = out[region] + extra
        return out
    build_launch.regions = patched
    root = copy_site()
    try:
        # Pages NOT rebuilt: only the scan of the generated text itself can say 'no same-day promise'.
        red = any("no same-day promise" in b for b in build_launch.check(root, now_ms=EARLY))
    finally:
        build_launch.regions = real
        shutil.rmtree(root)
    ok = red == expect_red
    print(f"{'ok  ' if ok else 'FAIL'} launch   {'red  ' if red else 'green'} {name}")
    if not ok:
        failures.append(f"launch: {name}")


generator_case("the generator itself writes 'same day'", "<p>Both on the same day.</p>", "when", True)
generator_case("the generator writes 'together' in the press line", " on Android and iOS together", "press-release", True)
generator_case("the generator adds a harmless sentence", "<p>Sort the world.</p>", "when", False)

# ---- 20.3b: the Google Play closed-test page ------------------------------------
TP = "testers/index.html"
WHY = "This test runs on Google Play, so it is for Android only."
todo_case("tester links still open today: the unserved page's placeholders do not count", lambda r: None, False, links=False)
todo_case("a placeholder on a SERVED page still counts while the tester page is unserved", lambda r: edit(
    r, "terms/index.html", "Empty Cup Media LLC", TODO), True, links=False)


def served_case(name, mutate, expect_red, links=False):
    root = copy_site()
    try:
        if links:
            fill_tester_links(root)
        mutate(root)
        red = bool(build_features.check(root))
    finally:
        shutil.rmtree(root)
    ok = red == expect_red
    print(f"{'ok  ' if ok else 'FAIL'} served   {'red  ' if red else 'green'} {name}")
    if not ok:
        failures.append(f"served: {name}")


AI = ".assetsignore"
served_case("links open, testers listed in .assetsignore (today)", lambda r: None, False)
served_case("links open, testers line removed from .assetsignore", lambda r: edit(r, AI, "testers\n", ""), True)
served_case("links set, page rebuilt: testers line gone", lambda r: None, False, links=True)
served_case("links set but the testers line left in .assetsignore", lambda r: (r / AI).write_text(
    (r / AI).read_text() + "testers\n"), True, links=True)
served_case("links open and the home page links to /testers/", lambda r: edit(
    r, "index.html", "<h1>Put the world in order</h1>", '<h1>Put the world in order</h1><p><a href="/testers/">Test it</a></p>'), True)
served_case("links set and the home page links to /testers/", lambda r: (fill_tester_links(r), edit(
    r, "index.html", "<h1>Put the world in order</h1>", '<h1>Put the world in order</h1><p><a href="/testers/">Test it</a></p>')), False)
platform_case("tester page names Android alone, with its reason", False)
platform_case("the reason sentence removed from the tester page", True, lambda r: edit(
    r, TP, "This test runs on", "This test is on"))
platform_case("another page copies the reason sentence and names Android alone", True, lambda r: edit(
    r, "support/index.html", "<h1>Support</h1>", "<h1>Support</h1><p>Install it from Google Play.</p><p>" + WHY + "</p>"))
platform_case("Android alone on another page is still red", True, lambda r: edit(
    r, "support/index.html", "<h1>Support</h1>", "<h1>Support</h1><p>Install it from Google Play.</p>"))
platform_case("tester page still may not say iPhone", True, lambda r: edit(
    r, TP, "<h1>Become a tester</h1>", "<h1>Become a tester</h1><p>Not on iPhone yet.</p>"))
platform_case("tester page still may not name the App Store alone", True, lambda r: edit(
    r, TP, "<h1>Become a tester</h1>", "<h1>Become a tester</h1><p>The App Store comes later.</p>"))
feature_case("'14 days in a row' typed by hand on the tester page", True, lambda r: edit(
    r, TP, "<h1>Become a tester</h1>", "<h1>Become a tester</h1><p>It lasts 14 days in a row.</p>"))
feature_case("'12 testers' typed by hand (Google's count stays off the page)", True, lambda r: edit(
    r, TP, "<h1>Become a tester</h1>", "<h1>Become a tester</h1><p>We need 12 testers.</p>"))
feature_case("testers.json days changed, page not rebuilt", True, lambda r: (r / "src/testers.json").write_text(
    (r / "src/testers.json").read_text().replace('"days": 14', '"days": 15')))
feature_case("a tester region deleted", True, lambda r: edit(
    r, TP, "<!-- feature:testers-join -->", "<!-- gone -->"))
store_case("tester page deleted", True, lambda r: (r / TP).unlink())
store_case("tester page loses noindex", True, lambda r: edit(r, TP, '<meta name="robots" content="noindex">\n', ""))
store_case("tester page loses its contact", True, lambda r: edit(
    r, TP, 'href="mailto:support@sortinggeography.com?subject=Tester"', 'href="mailto:x@example.com"'))
store_case("tester page added to the sitemap", True, lambda r: edit(
    r, "sitemap.xml", "</urlset>", "  <url><loc>https://sortinggeography.com/testers/</loc></url>\n</urlset>"))


def testers_json_case(name, value, expect_red):
    root = copy_site()
    try:
        p = root / "src/testers.json"
        t = json.loads(p.read_text())
        t.update(value)
        p.write_text(json.dumps(t))
        try:
            build_features.load_testers(root)
            red = False
        except SystemExit:
            red = True
    finally:
        shutil.rmtree(root)
    ok = red == expect_red
    print(f"{'ok  ' if ok else 'FAIL'} testers  {'red  ' if red else 'green'} {name}")
    if not ok:
        failures.append(f"testers: {name}")


testers_json_case("both links null (today)", {}, False)
testers_json_case("valid group and opt-in links", {"group_url": build_features.GROUP_PREFIX + "x",
                                                   "optin_url": build_features.OPTIN_URL}, False)
testers_json_case("group link on another site", {"group_url": "https://example.com/g/x"}, True)
testers_json_case("group link with no group name", {"group_url": build_features.GROUP_PREFIX}, True)
testers_json_case("opt-in link for another package", {"optin_url": "https://play.google.com/apps/testing/com.example"}, True)
testers_json_case("opt-in link is the store page, not the test", {"optin_url": "https://play.google.com/store/apps/details?id=" + build_features.PACKAGE}, True)
testers_json_case("days not a number", {"days": "14"}, True)
testers_json_case("days is true (bool is an int in Python)", {"days": True}, True)
testers_json_case("days zero", {"days": 0}, True)
testers_json_case("group link with a quote that leaves the href", {"group_url": build_features.GROUP_PREFIX + 'x" onmouseover="alert(1)'}, True)
testers_json_case("group link with an empty name and slash", {"group_url": build_features.GROUP_PREFIX + "/"}, True)
testers_json_case("group link with a path after the name", {"group_url": build_features.GROUP_PREFIX + "x/y"}, True)
testers_json_case("group name with dots, dashes, underscores", {"group_url": build_features.GROUP_PREFIX + "sorting-geo.testers_1"}, False)


def built_link_case(name, url, must_not, expect_red=True):
    """The link as BUILT into the page: escaped even if a future validator slipped."""
    out = build_features._link_or_todo(url, "x")
    red = must_not in out
    ok = red == (not expect_red)
    print(f"{'ok  ' if ok else 'FAIL'} link     {'raw  ' if red else 'safe '} {name}")
    if not ok:
        failures.append(f"link: {name}")


built_link_case("a quote in a link is escaped when built", 'https://g/x" onmouseover="a', '" onmouseover="')
built_link_case("an angle bracket in a link is escaped when built", "https://g/<script>", "<script>")


# Ra'uf's pick 2026-11-20 ("Platforms first"), word for word in the When? line.
RAUF_WHEN = "The same game for Android and iOS, on phones and tablets. It launches on 10 December 2026."
when_text = build_launch.regions(RELEASE)["when"]
ok = RAUF_WHEN in when_text and build_launch.regions(RELEASE)["hero-countdown"].find(
    "The same game for Android and iOS. It launches on 10 December 2026.") != -1
print(f"{'ok  ' if ok else 'FAIL'} launch   {'green' if ok else 'red  '} Ra'uf's platforms-first wording, word for word")
if not ok:
    failures.append("launch: Ra'uf's platforms-first wording")


# ---- 18.4: every game language on the site ---------------------------------------
def publish(root, lang="de", change=None):
    """Publish a language with stand-in strings ("DE· " + English, placeholders and
    tags kept), as the translation pipeline's output will be, then rebuild."""
    en = json.loads((root / "src/i18n/site_en.arb").read_text())
    arb = {"@@locale": lang}
    for k, v in en.items():
        if not k.startswith("@"):
            arb[k] = f"{lang.upper()}· {v}"
    if change:
        change(arb)
    site_i18n.arb_path(lang, root).write_text(json.dumps(arb, ensure_ascii=False))
    langs = json.loads((root / "src/site_languages.json").read_text())
    langs["published"] = sorted(set(langs["published"]) | {lang})
    langs["served"] = sorted(set(langs.get("served", [])) | {lang})   # as if the game shipped it
    (root / "src/site_languages.json").write_text(json.dumps(langs))
    build_i18n.build(root)


def broken_links(root):
    """CI's 'no broken internal links' step, over every page, built language pages included."""
    from urllib.parse import urlparse
    bad = []
    for p in sorted(root.rglob("*.html")):
        if set(p.relative_to(root).parts) & {"docs", "src", "scripts", "node_modules", ".git", ".github", ".wrangler"}:
            continue
        for target in re.findall(r'(?:href|src)\s*=\s*"([^"]+)"', p.read_text(encoding="utf-8")):
            u = urlparse(target)
            if u.scheme or target.startswith(("#", "mailto:", "//")):
                continue
            if not (p.parent / u.path).resolve().exists():
                bad.append(f"{p.relative_to(root)} -> {target}")
    return bad


def i18n_problems(root):
    return (build_i18n.gates(root) + build_launch.check(root, now_ms=EARLY)
            + check_platform.check(check_platform.targets(root), root) + check_comments.check(root)
            + broken_links(root))


def i18n_case(name, setup, expect_red, inspect=None):
    root = copy_site()
    try:
        setup(root)
        bad = i18n_problems(root)
        red = bool(bad)
        if inspect and not red:
            inspect(root)
    except AssertionError as e:
        red, bad = None, [f"inspection failed: {e}"]
    except SystemExit as e:     # a build that refuses is red too
        red, bad = True, [str(e)]
    finally:
        shutil.rmtree(root)
    ok = red == expect_red
    print(f"{'ok  ' if ok else 'FAIL'} i18n     {'red  ' if red else 'green'} {name}" + ("" if ok else f"  <- {bad[:2]}"))
    if not ok:
        failures.append(f"i18n: {name}: {bad[:2]}")


def de_page_right(root):
    de = (root / "de/index.html").read_text()
    en = (root / "index.html").read_text()
    assert '<html lang="de">' in de
    assert "10. Dezember 2026" in de, "the launch date in German, from CLDR"
    assert "<li>Kanada</li>" in de, "country names from CLDR"
    assert 'href="../style.css"' in de and 'src="../countdown.js"' in de
    assert 'name="lang" value="de"' in de, "signups from /de/ are stored as de"
    for page in (de, en):
        for lg, href in (("en", "https://sortinggeography.com/"), ("de", "https://sortinggeography.com/de/"),
                         ("x-default", "https://sortinggeography.com/")):
            assert f'<link rel="alternate" hreflang="{lg}" href="{href}">' in page, (lg, "hreflang reciprocal")
    assert "<loc>https://sortinggeography.com/de/</loc>" in (root / "sitemap.xml").read_text()
    assert "<h1>DE· Put the world in order</h1>" in de, "the heading is the German string"
    assert "<h1>Put the world in order</h1>" not in de, "no English heading left"
    sup = (root / "de/support/index.html").read_text()
    assert '<html lang="de">' in sup and "<h1>DE· Support</h1>" in sup, "support translated"
    assert 'href="../../style.css"' in sup and 'href="../privacy/"' in sup, "privacy link stays in German"
    assert 'href="../../credits.html"' in sup and 'href="../../terms/"' in sup, "English-only pages from the site root"
    assert "DE· Yes. Every question" in sup, "the generated answers are in the page's language"
    assert re.search(r'DE· Very little[^<]*<a href="\.\./privacy/">', sup), "a link inside a translated string stays in the language"
    assert '<link rel="canonical" href="https://sortinggeography.com/de/support/">' in sup
    pr = (root / "de/privacy/index.html").read_text()
    assert '<html lang="de">' in pr and '<div lang="en">' in pr, "the English policy, marked English"
    assert "DE· This privacy policy is in English" in pr, "the one-line note in the page's language"
    assert "<h1>Privacy</h1>" in pr and 'href="../support/"' in pr, "the English text, links kept in the language"
    for page in ("index.html", "support/index.html", "de/support/index.html", "de/privacy/index.html"):
        assert "href=\"https://sortinggeography.com/de/" in (root / page).read_text() or page == "index.html" or "hreflang" in (root / page).read_text()


i18n_case("today: English only, nothing published", lambda r: None, False)
i18n_case("German published and fully translated: built right", lambda r: publish(r), False, de_page_right)
i18n_case("the English policy links to the sources page: it still resolves on /de/privacy/", lambda r: (edit(
    r, "privacy/index.html", "<h1>Privacy</h1>", '<h1>Privacy</h1>\n  <p><a href="../credits.html">Sources</a></p>'),
    publish(r)), False, lambda r: None if 'href="../../credits.html">Sources' in (r / "de/privacy/index.html").read_text()
    else (_ for _ in ()).throw(AssertionError("the sources link was not re-rooted")))
i18n_case("a German value left in English", lambda r: publish(r, change=lambda a: a.update(heroTitle="Put the world in order")), True)
i18n_case("...unless allow_identical lists it", lambda r: ((r / "src/i18n/allow_identical.json").write_text(
    json.dumps({"de": ["heroTitle"]})), publish(r, change=lambda a: a.update(heroTitle="Put the world in order"))), False)
i18n_case("allow_identical names a key that does not exist", lambda r: ((r / "src/i18n/allow_identical.json").write_text(
    json.dumps({"de": ["noSuchKey"]})), publish(r)), True)
i18n_case("an unknown tag added to a German value (review M5)", lambda r: publish(r, change=lambda a: a.update(
    heroLede=a["heroLede"] + "<script>alert(1)</script>")), True)
i18n_case("a stray > in a German value", lambda r: publish(r, change=lambda a: a.update(heroTitle="DE· Ordne > die Welt")), True)
i18n_case("a German key missing", lambda r: publish(r, change=lambda a: a.pop("card1Text")), True)
i18n_case("an unknown key in German", lambda r: publish(r, change=lambda a: a.update(extraKey="x")), True)
i18n_case("the link tag dropped from a German value", lambda r: publish(r, change=lambda a: a.update(
    honestyText="DE· keine Links hier")), True)
i18n_case("the German page hand-edited", lambda r: (publish(r), edit(r, "de/index.html", "<h1>", "<h1>x ")), True)
i18n_case("the English page loses its hreflang once German is published", lambda r: (publish(r), edit(
    r, "index.html", '<link rel="alternate" hreflang="de" href="https://sortinggeography.com/de/">', "")), True)
i18n_case("the sitemap loses /de/", lambda r: (publish(r), edit(
    r, "sitemap.xml", "  <url><loc>https://sortinggeography.com/de/</loc></url>\n", "")), True)
i18n_case("a French page on disk, French not published", lambda r: ((r / "fr").mkdir(), (r / "fr/index.html").write_text(
    '<!doctype html><html lang="fr"><body><h1>x</h1></body></html>')), True)
i18n_case("German published but its ARB missing", lambda r: (r / "src/site_languages.json").write_text(
    json.dumps({"published": ["de"]})), True)
i18n_case("a bad language tag", lambda r: (r / "src/site_languages.json").write_text(
    json.dumps({"published": ["German"]})), True)
i18n_case("a placeholder dropped from a German launch string", lambda r: publish(r, change=lambda a: a.update(
    launchDateLine="DE· es kommt bald")), True)
i18n_case("a placeholder renamed in a German string", lambda r: publish(r, change=lambda a: a.update(
    whenPre="DE· {plattformen}, {date}")), True)


def i18n_unit(name, fn):
    """Each 18.4 guard on its own: in the full checks a missing ARB refuses first."""
    root = copy_site()
    try:
        try:
            red = bool(fn(root))
        except SystemExit:
            red = True
    finally:
        shutil.rmtree(root)
    print(f"{'ok  ' if red else 'FAIL'} i18n     {'red  ' if red else 'green'} {name}")
    if not red:
        failures.append(f"i18n: {name}")


def stray_fr(r):
    (r / "fr").mkdir()
    (r / "fr/index.html").write_text('<!doctype html><html lang="fr"><body><h1>x</h1></body></html>')
    return [b for b in build_i18n.gates(r) if "not published" in b]


def bad_tag(r):
    (r / "src/site_languages.json").write_text(json.dumps({"published": ["German"]}))
    site_i18n.published(r)      # must raise; returning at all means the tag got through
    return False


i18n_unit("gates() alone refuses a language page that is not published", stray_fr)
i18n_unit("published() alone refuses a bad language tag", bad_tag)


# ---- 18.4 pull-and-hold (pm-release 2026-11-20): a page is SERVED only once the game ships its language
def fake_site_game(root, de_status="in_progress", de_arb=True, en_override=None, drop_key=None, gate_record=True):
    g = pathlib.Path(tempfile.mkdtemp(prefix="sg-game-"))
    site = g / "pipeline/translation/site"
    site.mkdir(parents=True)
    en_text = (root / "src/i18n/site_en.arb").read_text()
    (site / "site_en.arb").write_text(en_override if en_override is not None else en_text)
    if de_arb:
        en = json.loads(en_text)
        de = {"@@locale": "de", **{k: f"DE· {v}" for k, v in en.items() if not k.startswith("@")}}
        if drop_key:
            de.pop(drop_key)
        (site / "site_de.arb").write_text(json.dumps(de, ensure_ascii=False))
    if gate_record:
        import hashlib
        rec = {lg: {"sha256": hashlib.sha256((site / site_i18n.arb_name(lg)).read_bytes()).hexdigest()}
               for lg in ("de",) if (site / site_i18n.arb_name(lg)).exists()}
        if gate_record == "stale" and rec:
            rec["de"]["sha256"] = "0" * 64
        (site / "gates.json").write_text(json.dumps(rec))
    (g / "pipeline/translation/locales.json").write_text(json.dumps({"de": {"status": de_status}, "fr": {"status": "in_progress"}}))
    for cmd in (["init", "-q", "-b", "main"], ["add", "-A"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "x"]):
        subprocess.run(["git", "-C", str(g), *cmd], check=True)
    return g


def regame(g, **change):
    """A new commit on the fake game's main (e.g. de flipped back to in_progress)."""
    lp = g / "pipeline/translation/locales.json"
    data = json.loads(lp.read_text())
    data.update(change)
    lp.write_text(json.dumps(data))
    subprocess.run(["git", "-C", str(g), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", "flip"], check=True)


def hold_case(name, game_kw, steps, expect_red, inspect=None):
    root = copy_site()
    g = fake_site_game(root, **game_kw)
    try:
        bad = []
        try:
            for step in steps:
                step(g, root)
            bad = build_i18n.check_game(g, "main", root) + build_launch.check(root, now_ms=EARLY)
            if inspect and not bad:
                inspect(g, root)
        except SystemExit as e:
            bad = [str(e)]
        except build_i18n.GameError as e:
            bad = [str(e)]
        red = bool(bad)
    except AssertionError as e:
        red, bad = None, [f"inspection failed: {e}"]
    finally:
        shutil.rmtree(g)
        shutil.rmtree(root)
    ok = red == expect_red
    print(f"{'ok  ' if ok else 'FAIL'} hold     {'red  ' if red else 'green'} {name}" + ("" if ok else f"  <- {bad[:2]}"))
    if not ok:
        failures.append(f"hold: {name}")


PULL = lambda g, r: build_i18n.pull(g, "main", r)


def held_de(g, r):
    assert "de" in (r / ".assetsignore").read_text().split(), "/de/ must be in .assetsignore"
    assert (r / "de/index.html").exists(), "built"
    assert "hreflang=\"de\"" not in (r / "index.html").read_text(), "no hreflang to a held page"
    assert "/de/</loc>" not in (r / "sitemap.xml").read_text(), "a held page is not in the sitemap"


def served_de(g, r):
    assert "de" not in (r / ".assetsignore").read_text().split(), "/de/ served"
    assert "hreflang=\"de\"" in (r / "index.html").read_text()
    assert "/de/</loc>" in (r / "sitemap.xml").read_text()


hold_case("German translated, not shipped: built and HELD", {}, [PULL], False, held_de)
hold_case("German shipped: built and SERVED", {"de_status": "shipped"}, [PULL], False, served_de)
hold_case("MUTATION: German flipped back to in_progress after a served pull: --game red",
          {"de_status": "shipped"}, [PULL, lambda g, r: regame(g, de={"status": "in_progress"})], True)
hold_case("...and the next pull drops /de/ out of the served set",
          {"de_status": "shipped"}, [PULL, lambda g, r: regame(g, de={"status": "in_progress"}), PULL], False, held_de)
hold_case("served set hand-edited to include a held German", {}, [PULL, lambda g, r: (
    (r / "src/site_languages.json").write_text(json.dumps({"published": ["de"], "served": ["de"]})),
    build_i18n.build(r))], True)
hold_case("de removed from .assetsignore by hand while held", {}, [PULL, lambda g, r: edit(r, ".assetsignore", "\nde\n", "\n")], True)
hold_case("the game's site_en.arb differs from the website's", {"en_override": "{}"}, [], True)
def game_en_edit(g, r):
    f = g / "pipeline/translation/site/site_en.arb"
    f.write_text(f.read_text() + "\n")
    subprocess.run(["git", "-C", str(g), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", "en"], check=True)


hold_case("only the game's English changes after a clean pull", {}, [PULL, game_en_edit], True)
hold_case("the website's site_de.arb drifts from the game's", {}, [PULL, lambda g, r: site_i18n.arb_path("de", r).write_text(
    site_i18n.arb_path("de", r).read_text().replace("DE·", "XX·"))], True)
hold_case("a pull is needed (game has German, website never pulled)", {}, [], True)
hold_case("the game ships German with no site strings", {"de_status": "shipped", "de_arb": False}, [], True)
# 18.4a review M2: the website reads only a site file the game's CI gate passed.
hold_case("German translated but with no gate record at all: --game red", {"gate_record": False}, [], True)
hold_case("German's gate record is for another version of the file: --game red", {"gate_record": "stale"}, [], True)
def not_built(g, r):
    assert not (r / "de/index.html").exists(), "an ungated site file was built into a page"


hold_case("...and --pull will not build it", {"gate_record": "stale"}, [PULL, not_built], True)
hold_case("an incomplete German site ARB is not built", {"drop_key": "heroTitle"}, [PULL], False,
          lambda g, r: (lambda: None)() if not (r / "de/index.html").exists() else (_ for _ in ()).throw(AssertionError("built")))


def bad_game_case(name, game_for, ref):
    root = copy_site()
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="sg-bad-"))
    try:
        red = bool(build_i18n.check_game(game_for(tmp, root), ref, root))
    finally:
        shutil.rmtree(tmp)
        shutil.rmtree(root)
    print(f"{'ok  ' if red else 'FAIL'} hold     {'red  ' if red else 'green'} {name}")
    if not red:
        failures.append(f"hold: {name}")


bad_game_case("--game at a path that does not exist", lambda tmp, r: tmp / "nope", "main")
bad_game_case("--game at a folder that is not git", lambda tmp, r: tmp, "main")
bad_game_case("--game at a ref that does not exist", lambda tmp, r: fake_site_game(r), "origin/mian")


def name_rule():
    """team-lead + pm-release: site_pt_PT.arb, the game's config.site_arb_path rule."""
    want = {"de": "site_de.arb", "pt-PT": "site_pt_PT.arb", "es-419": "site_es_419.arb", "ja": "site_ja.arb"}
    ok = all(site_i18n.arb_name(k) == v for k, v in want.items()) and site_i18n.folder("pt-PT") == "pt-pt/"
    print(f"{'ok  ' if ok else 'FAIL'} hold     {'green' if ok else 'red  '} site ARB names (site_pt_PT.arb) and folders (/pt-pt/)")
    if not ok:
        failures.append("hold: naming rule")


name_rule()


# ---- 18.3: canonical, Open Graph and structured data on every page -----------------
def seo_case(name, mutate, expect_red, setup=None):
    root = copy_site()
    try:
        if setup:
            setup(root)
        mutate(root)
        red = bool(build_seo.check(root))
    finally:
        shutil.rmtree(root)
    ok = red == expect_red
    print(f"{'ok  ' if ok else 'FAIL'} seo      {'red  ' if red else 'green'} {name}")
    if not ok:
        failures.append(f"seo: {name}")


seo_case("today's pages", lambda r: None, False)
seo_case("a page's seo region removed", lambda r: edit(r, "terms/index.html", "<!-- seo:head -->", "<!-- gone -->"), True)
seo_case("og:title hand-edited", lambda r: edit(r, "press/index.html",
    '<meta property="og:title" content="Press kit — Sorting Geography">', '<meta property="og:title" content="Other">'), True)
seo_case("the title changed, region not rebuilt", lambda r: edit(r, "support/index.html",
    "<title>Support — Sorting Geography</title>", "<title>Help — Sorting Geography</title>"), True)
seo_case("a second canonical outside the region", lambda r: edit(r, "privacy/index.html",
    "</head>", '<link rel="canonical" href="https://example.com/">\n</head>'), True)
seo_case("a page with no meta description", lambda r: (edit(r, "terms/index.html",
    '<meta name="description" content="', '<meta name="x" content="'), build_seo.build(r)), True)
seo_case("JSON-LD that does not parse", lambda r: edit(r, "index.html", '"@context": "https://schema.org"', '"@context": https://schema.org'), True)
seo_case("hand-added JSON-LD in the body that does not parse", lambda r: edit(r, "press/index.html",
    "</main>", '<script type="application/ld+json">{"@type": </script>\n</main>'), True)
seo_case("hand-added JSON-LD without @context", lambda r: edit(r, "press/index.html",
    "</main>", '<script type="application/ld+json">{"@type": "Thing"}</script>\n</main>'), True)
seo_case("hand-added valid JSON-LD", lambda r: edit(r, "press/index.html",
    "</main>", '<script type="application/ld+json">{"@context": "https://schema.org", "@type": "Thing"}</script>\n</main>'), False)
seo_case("a page added with no seo region", lambda r: ((r / "new").mkdir(), (r / "new/index.html").write_text(
    '<!doctype html><html lang="en"><head><title>x</title><meta name="description" content="y"></head><body></body></html>')), True)
seo_case("hreflang without x-default", lambda r: (publish(r), edit(r, "de/index.html",
    '<link rel="alternate" hreflang="x-default" href="https://sortinggeography.com/">', "")), True)
seo_case("German published: every page's tags current", lambda r: publish(r), False)


def ld_on_german_home():
    root = copy_site()
    try:
        publish(root)
        t = (root / "de/index.html").read_text()
        ok = '"inLanguage": "de"' in t and '<link rel="canonical" href="https://sortinggeography.com/de/">' in t
    finally:
        shutil.rmtree(root)
    print(f"{'ok  ' if ok else 'FAIL'} seo      {'green' if ok else 'red  '} the German home page: its own canonical and inLanguage de")
    if not ok:
        failures.append("seo: German home")


ld_on_german_home()

if failures:
    print(f"\n{len(failures)} mutation case(s) wrong:")
    for f in failures:
        print("  " + f)
    sys.exit(1)
print("\nok   every break went red, every clean case stayed green")
