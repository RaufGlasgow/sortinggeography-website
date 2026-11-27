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

import site_i18n  # noqa: E402  (scripts/ is on sys.path when run as a script)

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


def badges(stores=STORES, s: dict | None = None, root_prefix: str = "") -> str:
    s = s or site_i18n.strings("en")
    out = []
    for key, name, url in stores:
        alt = html.escape(s["badgeGoogleAlt"] if key == "google" else s["badgeAppleAlt"], quote=True)
        if key == "google":
            art = (f'<span class="badge-art badge-google"><img src="{root_prefix}images/google-play-badge.png" '
                   f'alt="{alt}" width="646" height="250"></span>')
        else:
            art = (f'<span class="badge-art badge-apple"><img src="{root_prefix}images/app-store-badge.svg" '
                   f'alt="{alt}" width="120" height="40"></span>')
        if url:
            out.append(f'<a class="badge" href="{html.escape(url)}" rel="noopener">{art}</a>')
        else:
            out.append(f'<span class="badge badge-late">{art}<small>{html.escape(s["badgeComingSoon"])}</small></span>')
    return '<div class="badges">' + "".join(out) + "</div>"


def all_linked(stores=STORES) -> bool:
    """Review F1: the "out" sentence names the platforms only when EVERY store
    has a link. Until then it says just "Out now" (Ra'uf 2026-11-18: one
    headline for both; a late store's own badge carries "Coming soon"), so the
    page can never claim a store that has no listing to link to."""
    return all(url for _k, _n, url in stores)


def out_platforms(stores=STORES) -> str:
    return f" on {PLATFORMS_SHORT}" if all_linked(stores) else ""


def regions(ms: int, stores=STORES, lang: str = "en", root: pathlib.Path = ROOT,
            root_prefix: str | None = None) -> dict[str, str]:
    """name -> generated HTML, in the page's language (Story 18.4). Every launch
    word comes from src/i18n/site_<lang>.arb; dates and times from CLDR."""
    s = site_i18n.strings(lang, root)
    c = site_i18n.cldr(lang, ms)
    e = html.escape
    plat = s["platformsShort"]
    linked = all_linked(stores)
    rp = root_prefix if root_prefix is not None else ("../" if lang != "en" else "")
    units = [("d", s["countdownDays"]), ("h", s["countdownHours"]), ("m", s["countdownMinutes"]),
             ("s", s["countdownSeconds"])]
    tiles = "".join(f'<span class="cd-unit"><b data-u="{k}">0</b><span>{e(n)}</span></span>'
                    for k, n in units)
    f = site_i18n.fill
    out_line = f(s["launchOutNowOn"], platforms=plat) if linked else s["launchOutNow"]
    return {
        "hero-chip": (f'<span class="tag only-pre">{e(f(s["launchChip"], date=c["chip"]))}</span>'
                      f'<span class="tag only-post">{e(s["launchOutNow"])}</span>'),
        "hero-countdown": (
            '<div class="launch">'
            '<div class="only-pre">'
            # Platforms first, as the When? line (Ra'uf 2026-11-20).
            f'<p class="launch-date">{e(f(s["launchDateLine"], platforms=plat, date=c["date"]))}</p>'
            f'<p class="launch-time">{e(f(s["launchTimeLine"], lisbon=c["lisbon"], utc=c["utc"]))}</p>'
            # The timer is decoration: hidden until countdown.js runs, and
            # hidden from screen readers, which read the sentence above.
            f'<div class="countdown" data-release="{ms}" hidden aria-hidden="true">{tiles}</div>'
            '</div>'
            '<div class="only-post">'
            f'<p class="launch-date">{e(out_line)}.</p>'
            f'{badges(stores, s, rp)}'
            '</div>'
            '</div>'),
        "press-release": (
            f'<span class="only-pre">{e(f(s["pressReleasePre"], date=c["date"], lisbon=c["lisbon"], utc=c["utc"]))}</span>'
            f'<span class="only-post">{e(f(s["pressReleasePostOn"], platforms=plat, date=c["date"]) if linked else f(s["pressReleasePost"], date=c["date"]))}</span>'),
        "when": (
            f'<h2 class="only-pre">{e(s["whenTitlePre"])}</h2><h2 class="only-post">{e(s["whenTitlePost"])}</h2>'
            # Ra'uf's pick 2026-11-20, "Platforms first", word for word.
            f'<p class="only-pre">{e(f(s["whenPre"], platforms=plat, date=c["date"]))}</p>'
            f'<p class="only-post">{e(f(s["whenPostOn"], platforms=plat) if linked else s["whenPost"])}</p>'),
        "sheet-play": (
            '<div class="launch a-play-ls">'
            '<div class="only-pre">'
            f'<p class="a-cd-line">{e(f(s["launchDateLine"], platforms=plat, date=c["date"]))}</p>'
            f'<p class="a-play-cta"><a class="btn btn-sm" href="{rp}#notify">{e(s["navGetNotified"])}</a></p>'
            '</div>'
            '<div class="only-post">'
            f'<p class="ls-out">{e(out_line)}.</p>'
            f'{badges(stores, s, rp)}'
            '</div>'
            '</div>'),
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


# No promise that both platforms arrive on the same day (team-lead 2026-11-20):
# under fallback A, Android can miss the release date, so launch copy names the
# date and the platforms, never the two tied together. Scanned in the
# generated text (every store state) and in every served page outside comments.
SAME_DAY = [
    ("'same day'", re.compile(r"\bsame\s+day\b", re.I)),
    ("'on both on'", re.compile(r"\bon\s+both\s+on\b", re.I)),
    ("'together' (both platforms at once)", re.compile(r"\btogether\b", re.I)),
    ("'at the same time'", re.compile(r"\bat\s+the\s+same\s+time\b", re.I)),
    ("'simultaneous(ly)'", re.compile(r"\bsimultaneous(?:ly)?\b", re.I)),
    ("a platform tied to a date", re.compile(
        r"\b(?:Android|iOS)\b[^<.]{0,40}?\bon\s+\d{1,2}\s+[A-Z][a-z]+\s+\d{4}\b")),
]


def same_day_claims(text: str) -> list[str]:
    plain = re.sub(r"<[^>]+>", " ", strip_comments(text))
    return [what for what, pat in SAME_DAY if pat.search(plain)]


def check(root: pathlib.Path = ROOT, now_ms: int | None = None) -> list[str]:
    ms = release_ms(root)
    bad: list[str] = []
    seen: set[str] = set()
    for p in served_pages(root):
        rel = p.relative_to(root)
        text = p.read_text(encoding="utf-8")
        rp = "../" * (len(rel.parts) - 1)
        gen = regions(ms, lang=site_i18n.page_lang(text), root=root, root_prefix=rp)   # 18.4: each page in its language
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
    for state, lang in [(st, lg) for st in ([(k, n, None) for k, n, _ in STORES], STORES)
                        for lg in ["en", *site_i18n.published(root)]]:
        for name, frag in regions(ms, state, lang, root).items():
            for what in same_day_claims(frag):
                bad.append(f"launch region {name}: {what} (no same-day promise)")
    for p in served_pages(root):
        for what in same_day_claims(p.read_text(encoding="utf-8")):
            bad.append(f"{p.relative_to(root)}: {what} (no same-day promise)")
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
    # Story 18.10: fetch() hands every request to route() and wraps the answer
    # in the security headers; route() ends in the serveAsset fall-through.
    route = re.search(r"^async\s+function\s+route\(\s*request\s*,\s*env\s*,\s*ctx\s*\)\s*\{(.*?)^\}", code, re.S | re.M)
    if not route or not re.search(r"\breturn\s+serveAsset\(\s*request\s*,\s*env\s*,\s*Date\.now\(\)\s*\)\s*;\s*$",
                                  route.group(1)):
        bad.append("src/worker.js: route() no longer ends in `return serveAsset(request, env, Date.now());`")
    if not re.search(r"async\s+fetch\(\s*request\s*,\s*env\s*,\s*ctx\s*\)\s*\{\s*return\s+withSecurityHeaders\(\s*await\s+route\(\s*request\s*,\s*env\s*,\s*ctx\s*\)\s*\)\s*;\s*\}", code):
        bad.append("src/worker.js: fetch() must be exactly `return withSecurityHeaders(await route(request, env, ctx));`")
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
    ms = release_ms(root)
    for p in served_pages(root):
        text = p.read_text(encoding="utf-8")
        rel = p.relative_to(root)
        rp = "../" * (len(rel.parts) - 1)
        new = render(text, regions(ms, lang=site_i18n.page_lang(text), root=root, root_prefix=rp), str(rel))
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
