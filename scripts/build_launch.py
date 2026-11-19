#!/usr/bin/env python3
"""Write every launch date and launch phrase into the pages (Story 18.8).

The release moment lives in ONE place, src/launch.js (RELEASE_UTC_MS). This
script reads it and fills the generated regions of every page:

    <!-- launch:NAME -->  ...generated, never hand-edited...  <!-- /launch:NAME -->

Each page carries BOTH states, "pre" (the countdown and the date) and "out"
("Out now" and both store badges). The worker stamps <html data-launch> from the
same constant, so the same URL flips at the moment with no redeploy and with
JavaScript off; countdown.js flips an open page live.

    python3 scripts/build_launch.py           # rewrite the regions
    python3 scripts/build_launch.py --check   # CI: fail on anything stale or stray

--check fails when:
  1. a region is not what this script would write (someone hand-edited it, or
     the constant moved and the pages were not rebuilt);
  2. the release date, in any spelling, or a launch phrase ("comes to",
     "coming soon", "out now", "in development", "release date" ...) appears in a
     served page OUTSIDE a generated region, including meta and Open Graph tags
     and JSON-LD, so a hand-typed date can never drift from the constant;
  3. a store link is still missing within STORE_LINK_DEADLINE_DAYS of the
     moment (a missing link shows that store's badge as "Coming soon", which is
     only true if that store really is late).

Copy is Sally's (ux/website/refresh-2026-11-19/_build.py, 217ef0b6): the date
sentence, the time line, "Out now on Android and iOS.", the chip wording.
Platform wording follows Ra'uf 2026-11-18: Android and iOS together, Android
first, badges Google Play then App Store at the same height.
"""
from __future__ import annotations

import html
import pathlib
import re
import sys
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

ROOT = pathlib.Path(__file__).resolve().parent.parent
LAUNCH_JS = ROOT / "src" / "launch.js"

# Store listings. None = not known yet: the badge then renders unlinked with a
# small "Coming soon" note on that badge only. Check 3 turns CI red if one is
# still None a week before the moment.
#   Google Play: the package id is fixed (app/android/app/build.gradle.kts).
#   App Store: the numeric id exists only once the App Store Connect record does.
STORES = [
    ("google", "Google Play",
     "https://play.google.com/store/apps/details?id=com.emptycupmedia.sorting_geography"),
    ("apple", "App Store", None),
]
STORE_LINK_DEADLINE_DAYS = 7

PLATFORMS_SHORT = "Android and iOS"

DAY_MS = 86_400_000


def release_ms(root: pathlib.Path = ROOT) -> int:
    text = (root / "src" / "launch.js").read_text(encoding="utf-8")
    m = re.search(r"export const RELEASE_UTC_MS = (\d+);", text)
    if not m:
        raise SystemExit("src/launch.js: no `export const RELEASE_UTC_MS = <ms>;` line")
    return int(m.group(1))


def moment(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def date_text(ms: int) -> str:
    d = moment(ms).astimezone(ZoneInfo("Europe/Lisbon"))
    return f"{d.day} {d.strftime('%B')} {d.year}"          # 10 December 2026


def chip_date(ms: int) -> str:
    d = moment(ms).astimezone(ZoneInfo("Europe/Lisbon"))
    return f"{d.day} {d.strftime('%B')}"                    # 10 December


def time_line(ms: int) -> str:
    lis = moment(ms).astimezone(ZoneInfo("Europe/Lisbon")).strftime("%H:%M")
    utc = moment(ms).strftime("%H:%M")
    return f"At {lis} in Lisbon, which is {utc} UTC."


def badges(stores=STORES) -> str:
    out = []
    for key, name, url in stores:
        alt = "Get it on Google Play" if key == "google" else "Download on the App Store"
        if key == "google":
            art = (f'<span class="badge-art badge-google"><img src="images/google-play-badge.png" '
                   f'alt="{alt}" width="646" height="250"></span>')
        else:
            art = (f'<span class="badge-art badge-apple"><img src="images/app-store-badge.svg" '
                   f'alt="{alt}" width="120" height="40"></span>')
        if url:
            out.append(f'<a class="badge" href="{html.escape(url)}" rel="noopener">{art}</a>')
        else:
            out.append(f'<span class="badge badge-late">{art}<small>Coming soon</small></span>')
    return '<div class="badges">' + "".join(out) + "</div>"


def out_platforms(stores=STORES) -> str:
    """Review F1: the "out" sentence names the platforms only when EVERY store
    has a link. Until then it says just "Out now" (Ra'uf 2026-11-18: one
    headline for both; a late store's own badge carries "Coming soon"), so the
    page can never claim a store that has no listing to link to."""
    return f" on {PLATFORMS_SHORT}" if all(url for _k, _n, url in stores) else ""


def regions(ms: int, stores=STORES) -> dict[str, str]:
    """name -> generated HTML. Every launch word on the site comes from here."""
    on = out_platforms(stores)
    units = [("d", "days"), ("h", "hours"), ("m", "minutes"), ("s", "seconds")]
    tiles = "".join(f'<span class="cd-unit"><b data-u="{k}">0</b><span>{n}</span></span>'
                    for k, n in units)
    return {
        "hero-chip": (f'<span class="tag only-pre">Out {chip_date(ms)}</span>'
                      '<span class="tag only-post">Out now</span>'),
        "hero-countdown": (
            '<div class="launch">'
            '<div class="only-pre">'
            f'<p class="launch-date">Sorting Geography comes to {PLATFORMS_SHORT} on {date_text(ms)}.</p>'
            f'<p class="launch-time">{time_line(ms)}</p>'
            # The timer is decoration: hidden until countdown.js runs, and
            # hidden from screen readers, which read the sentence above.
            f'<div class="countdown" data-release="{ms}" hidden aria-hidden="true">{tiles}</div>'
            '</div>'
            '<div class="only-post">'
            f'<p class="launch-date">Out now{on}.</p>'
            f'{badges(stores)}'
            '</div>'
            '</div>'),
        "press-release": (
            f'<span class="only-pre">{date_text(ms)}, {time_line(ms)[3:-1]}, '
            f'on {PLATFORMS_SHORT} together</span>'
            f'<span class="only-post">Out now{on}, since {date_text(ms)}</span>'),
        "when": (
            '<h2 class="only-pre">When?</h2><h2 class="only-post">Get the game</h2>'
            f'<p class="only-pre">Sorting Geography comes to {PLATFORMS_SHORT} on {date_text(ms)}, '
            'on phones and tablets, the same game on both on the same day.</p>'
            f'<p class="only-post">Out now{on}, on phones and tablets.</p>'),
    }


REGION = re.compile(r"(<!-- launch:([a-z0-9-]+) -->)(.*?)(<!-- /launch:\2 -->)", re.S)


def served_pages(root: pathlib.Path = ROOT) -> list[pathlib.Path]:
    ignored = {"docs", "src", "scripts", "node_modules", ".git", ".github", ".wrangler"}
    return sorted(p for p in root.rglob("*.html")
                  if not (set(p.relative_to(root).parts) & ignored))


def render(text: str, gen: dict[str, str], where: str) -> str:
    def sub(m):
        name = m.group(2)
        if name not in gen:
            raise SystemExit(f"{where}: unknown launch region '{name}'")
        return m.group(1) + gen[name] + m.group(4)
    return REGION.sub(sub, text)


def forbidden_patterns(ms: int) -> list[tuple[str, re.Pattern]]:
    """The release date in every spelling a person might hand-type, plus the
    launch phrases. Built FROM the constant, so moving the date moves the net."""
    d = moment(ms).astimezone(ZoneInfo("Europe/Lisbon"))
    month, mon = d.strftime("%B"), d.strftime("%b")
    day, y, mm = d.day, d.year, d.month
    m_alt = f"(?:{month}|{mon})\\b\\.?"
    dates = [
        rf"\b0?{day}(?:st|nd|rd|th)?\s+(?:of\s+)?{m_alt}",           # 10 December, 10th Dec
        rf"\b{m_alt}\s+0?{day}(?:st|nd|rd|th)?\b",                   # December 10, Dec 10th
        rf"\b{y}-{mm:02d}-{day:02d}\b",                              # 2026-12-10
        rf"\b0?{day}[/.]0?{mm}[/.]{y}\b",                            # 10/12/2026, 10.12.2026
        rf"\b0?{mm}/0?{day}/{y}\b",                                  # 12/10/2026
        rf"\b{ms // 1000}",                                          # epoch seconds / ms
    ]
    phrases = [
        r"\bcom(?:es|ing)\s+(?:to|soon|out)\b",
        r"\bout\s+now\b",
        r"\bin\s+development\b",
        r"\brelease\s+date\b",
        r"\b(?:has|have)\s+not\s+(?:yet\s+)?been\s+released\b",
        r"\bnot\s+(?:yet\s+)?released\b",
        r"\bavailable\s+now\b",
        r"\bnow\s+available\b",
    ]
    return ([("release date", re.compile(p, re.I)) for p in dates]
            + [("launch phrase", re.compile(p, re.I)) for p in phrases])


def strip_regions(text: str) -> str:
    # Blank generated regions but keep line numbers.
    return REGION.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), text)


def strip_comments(text: str) -> str:
    return re.sub(r"<!--.*?-->", lambda m: re.sub(r"[^\n]", " ", m.group(0)), text, flags=re.S)


def check(root: pathlib.Path = ROOT, now_ms: int | None = None) -> list[str]:
    ms = release_ms(root)
    gen = regions(ms)
    bad: list[str] = []
    seen: set[str] = set()
    for p in served_pages(root):
        rel = p.relative_to(root)
        text = p.read_text(encoding="utf-8")
        if render(text, gen, str(rel)) != text:
            bad.append(f"{rel}: a launch region is stale or hand-edited; run scripts/build_launch.py")
        seen.update(m.group(2) for m in REGION.finditer(text))
        # Meta tags, JSON-LD and attributes are scanned too: only comments and
        # generated regions are exempt.
        # The whole text, not line by line: prose wraps, and "Out" at the end
        # of one line with "now" on the next is still the phrase.
        rest = strip_comments(strip_regions(text))
        for what, pat in forbidden_patterns(ms):
            for m in pat.finditer(rest):
                i = rest.count("\n", 0, m.start()) + 1
                snippet = " ".join(rest[max(0, m.start() - 40):m.end() + 40].split())
                bad.append(f"{rel}:{i}: {what} outside a generated region: ...{snippet}...")
    if "hero-countdown" not in seen:
        bad.append("no page carries the hero-countdown region")
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    bad += worker_wiring(root)
    bad += ci_schedule(root)
    if now_ms >= ms - STORE_LINK_DEADLINE_DAYS * DAY_MS:
        for _key, name, url in STORES:
            if not url:
                bad.append(f"{name}: no store link, {STORE_LINK_DEADLINE_DAYS} days or less before "
                           "the release; its badge would say 'Coming soon' at launch")
    return bad


def worker_wiring(root: pathlib.Path = ROOT) -> list[str]:
    """Review F2: the two lines that make the flip happen at all. Without them
    the worker never stamps data-launch, every no-JavaScript visitor and crawler
    keeps the countdown after the moment, and a browser test (countdown.js
    flips the page) hides it."""
    import tomllib
    bad = []
    worker = (root / "src" / "worker.js").read_text(encoding="utf-8")
    code = re.sub(r"//[^\n]*", "", worker)
    if not re.search(r"\breturn\s+serveAsset\(\s*request\s*,\s*env\s*,\s*Date\.now\(\)\s*\)\s*;\s*\}\s*,\s*\};", code):
        bad.append("src/worker.js: the fall-through no longer ends in `return serveAsset(request, env, Date.now());`")
    if re.search(r"\bASSETS\.fetch\(", code):
        bad.append("src/worker.js: calls env.ASSETS.fetch directly; pages must go through serveAsset (src/pages.js)")
    if not re.search(r"^import\s*\{[^}]*\bserveAsset\b[^}]*\}\s*from\s*'\./pages\.js';", worker, re.M):
        bad.append("src/worker.js: does not import serveAsset from ./pages.js")
    try:
        cfg = tomllib.loads((root / "wrangler.toml").read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as e:
        return bad + [f"wrangler.toml unreadable: {e}"]
    if cfg.get("assets", {}).get("run_worker_first") is not True:
        bad.append("wrangler.toml: [assets] run_worker_first is not true, so the worker never sees page requests")
    return bad


def ci_schedule(root: pathlib.Path = ROOT) -> list[str]:
    """Review round 2 follow-up: the daily run IS the F1 fix. Without a
    schedule nothing re-runs the store-link deadline before the moment."""
    ci = root / ".github" / "workflows" / "ci.yml"
    try:
        text = ci.read_text(encoding="utf-8")
    except OSError:
        return [".github/workflows/ci.yml is missing"]
    text = re.sub(r"(?m)^\s*#.*$", "", text)
    m = re.search(r"(?m)^on:\s*\n((?:[ \t]+.*\n|\s*\n)+)", text)
    on_block = m.group(1) if m else ""
    if not re.search(r"(?m)^[ \t]+schedule:\s*\n[ \t]+-[ \t]*cron:[ \t]*['\"]?[0-9*/,\- ]+ [0-9*/,\- ]+ \*[ \t]+\*[ \t]+\*['\"]?[ \t]*$", on_block):
        return [".github/workflows/ci.yml: no daily `schedule: - cron:` under `on:`; the store-link "
                "deadline would never re-run on its own (review F1)"]
    return []


def build(root: pathlib.Path = ROOT) -> None:
    gen = regions(release_ms(root))
    for p in served_pages(root):
        text = p.read_text(encoding="utf-8")
        new = render(text, gen, str(p.relative_to(root)))
        if new != text:
            p.write_text(new, encoding="utf-8")
            print(f"wrote {p.relative_to(root)}")


if __name__ == "__main__":
    if "--check" in sys.argv[1:]:
        problems = check()
        if problems:
            print("launch check FAILED (Story 18.8: every date and launch phrase comes from src/launch.js):")
            for b in problems:
                print("  " + b)
            sys.exit(1)
        print(f"ok   launch regions current; release {moment(release_ms()).isoformat()}")
    else:
        build()
