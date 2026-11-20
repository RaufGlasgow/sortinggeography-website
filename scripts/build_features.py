#!/usr/bin/env python3
"""Privacy and support text that depends on what the game does TODAY (18.9, F3).

The pages describe the game repo's main as it is, never a feature still being
built (team-lead ruling on review-share's F3, 2026-11-19). Three switches, in
src/features.json:

    analytics         the PostHog sink ships (posthog_flutter is a dependency;
                      Story 20.10)
    analytics_switch  Settings has "Share anonymous usage numbers" (Story 6.12)
    unlock            the paid unlock is on (kPaidUnlockEnabled = true; 6.3)

Each feature-dependent passage lives in a region of the page:

    <!-- feature:NAME -->  ...generated from FRAGMENTS below...  <!-- /feature:NAME -->

and its text for BOTH states is kept here, so a block taken out is ready to
put back: flip the switch in the same release as the feature, run this script,
commit both.

    python3 scripts/build_features.py                # rewrite the regions
    python3 scripts/build_features.py --check        # CI: regions current, no stray claim
    python3 scripts/build_features.py --game PATH    # BEFORE A DEPLOY: features.json
                                                      # matches the game repo's main

--check (CI, offline) fails when a region is stale or hand-edited, or when a
served page names a switched-off feature outside a region ("PostHog",
"Restore purchases", "subscription" ...).

Facts (src/facts.json, Story 18.9 press kit): the question count, the country
count, the data version, the shipped languages and one worked example. The
press and terms text reads them; a number typed by hand outside a region
("190 questions") fails --check; --game compares each with the game's main.

Placeholders: <span class="todo">...</span> marks something only Ra'uf can
supply (the legal entity). --game fails while any served page carries one, so
a page with a placeholder can be built and reviewed but never deployed.

--game reads the game repo's origin/main (git show, nothing checked out) and
fails when features.json says a feature is on that main does not have, or off
when main has it: either way the privacy page would be false. It cannot run in
this public repo's CI (the game repo is private), so it is a deploy step
(docs/DEPLOY-RUNBOOK.md), never skipped: no path, no deploy.
"""
from __future__ import annotations

import html
import json
import pathlib
import re
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import site_i18n  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
FEATURES = ("analytics", "analytics_switch", "unlock")
SWITCH_LABEL = "Share anonymous usage numbers"
IP_LINE = "discarded on arrival, never stored"          # F4: the one wording


def load_flags(root: pathlib.Path = ROOT) -> dict[str, bool]:
    data = json.loads((root / "src" / "features.json").read_text(encoding="utf-8"))
    flags = {k: data.get(k) for k in FEATURES}
    bad = [k for k, v in flags.items() if not isinstance(v, bool)]
    if bad:
        raise SystemExit(f"src/features.json: {', '.join(bad)} must be true or false")
    if flags["analytics_switch"] and not flags["analytics"]:
        raise SystemExit("src/features.json: analytics_switch needs analytics")
    return flags


FACT_KEYS = ("dataset_version", "axes", "countries", "languages", "pt_highest_point_m")
LANG_NAMES = {"en": "English", "de": "German", "pt-PT": "Portuguese (Portugal)", "nl": "Dutch",
              "es-419": "Spanish (Latin America)", "fr": "French", "ja": "Japanese",
              "it": "Italian", "ru": "Russian"}


def load_facts(root: pathlib.Path = ROOT) -> dict:
    facts = json.loads((root / "src" / "facts.json").read_text(encoding="utf-8"))
    missing = [k for k in FACT_KEYS if k not in facts]
    if missing:
        raise SystemExit(f"src/facts.json: missing {', '.join(missing)}")
    unknown = [t for t in facts["languages"] if t not in LANG_NAMES]
    if unknown:
        raise SystemExit(f"src/facts.json: no display name for {unknown}; add it to LANG_NAMES")
    return facts


# The Google Play closed test (Story 20.3b): src/testers.json holds the two
# links Ra'uf gets when he makes the testers' group and the closed test, and
# Google's own numbers. A null link renders as a todo span, so the page can be
# built and reviewed now but --game refuses the deploy until both are real.
PACKAGE = "com.emptycupmedia.sorting_geography"     # --game checks it against main
GROUP_PREFIX = "https://groups.google.com/g/"
# A group name is letters, digits, dot, dash, underscore; nothing that could
# leave the href attribute (review-share T1).
GROUP_URL = re.compile(r"https://groups\.google\.com/g/[A-Za-z0-9._-]+")
OPTIN_URL = f"https://play.google.com/apps/testing/{PACKAGE}"


def load_testers(root: pathlib.Path = ROOT) -> dict:
    t = json.loads((root / "src" / "testers.json").read_text(encoding="utf-8"))
    for k in ("group_url", "optin_url", "days"):
        if k not in t:
            raise SystemExit(f"src/testers.json: missing {k}")
    # bool is an int in Python: refuse it explicitly (review-share T2).
    if type(t["days"]) is not int or t["days"] < 1:
        raise SystemExit("src/testers.json: days must be a whole number above 0")
    g, o = t["group_url"], t["optin_url"]
    if g is not None and not (isinstance(g, str) and GROUP_URL.fullmatch(g)):
        raise SystemExit(f"src/testers.json: group_url must be null or {GROUP_PREFIX}<name> "
                         "(letters, digits, '.', '-', '_')")
    if o is not None and o != OPTIN_URL:
        raise SystemExit(f"src/testers.json: optin_url must be null or exactly {OPTIN_URL}")
    return t


# Story 20.3c (team-lead 2026-11-20): until BOTH tester links are real, the
# tester page is not served at all. build() lists it in .assetsignore (Cloudflare
# then never uploads it: /testers/ is a 404), check() fails if that line and
# testers.json disagree or if any served page links to /testers/, and todos()
# looks only at served pages, so --game passes with its placeholders present.
# Once both links are set, build() drops the line and the page is checked as any.
TESTERS_IGNORE = "testers"
ASSETSIGNORE = ".assetsignore"


def testers_served(t: dict) -> bool:
    return t["group_url"] is not None and t["optin_url"] is not None


def ignored(root: pathlib.Path = ROOT) -> set[str]:
    """Top-level names Cloudflare does not serve (.assetsignore, one per line)."""
    f = root / ASSETSIGNORE
    if not f.exists():
        return set()
    return {ln.strip().strip("/") for ln in f.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.strip().startswith("#")}


def is_served(p: pathlib.Path, root: pathlib.Path = ROOT) -> bool:
    return p.relative_to(root).parts[0] not in ignored(root)


def assetsignore_text(root: pathlib.Path, served: bool) -> str:
    f = root / ASSETSIGNORE
    lines = f.read_text(encoding="utf-8").splitlines() if f.exists() else []
    lines = [ln for ln in lines if ln.strip().strip("/") != TESTERS_IGNORE]
    if not served:
        lines.append(TESTERS_IGNORE)
    return "\n".join(lines) + "\n"


def context(root: pathlib.Path = ROOT, flags: dict | None = None) -> dict:
    ctx = dict(load_flags(root) if flags is None else flags)
    ctx.setdefault("root", root)
    ctx.setdefault("facts", load_facts(root))
    ctx.setdefault("testers", load_testers(root))
    return ctx


def languages_text(tags) -> str:
    names = [LANG_NAMES[t] for t in tags]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


# ---------------------------------------------------------------------------
# The text. Each fragment takes the flags and returns the region's HTML.
# ---------------------------------------------------------------------------

def privacy_summary(f):
    out = []
    if f["analytics"]:
        line = ("The app sends anonymous usage numbers so we can see which questions are too hard. "
                f"Your IP address is {IP_LINE}; no advertising ID, nothing that identifies you.")
        if f["analytics_switch"]:
            line += " You can switch them off in Settings."
        out.append(f"<li>{line}</li>")
    else:
        out.append("<li>The app sends no usage statistics of its own.</li>")
    if f["unlock"]:
        out.append("<li>If you buy the unlock that removes ads, Google Play or the App Store "
                   "takes the payment. We never see your payment details.</li>")
    return "\n    ".join(out)


def privacy_connection(f):
    uses = ["to show ads"]
    if f["analytics"]:
        uses.append("to send the anonymous usage numbers described below")
    if f["unlock"]:
        uses.append("to check a purchase with the store")
    if len(uses) == 1:
        tail = uses[0]
    else:
        tail = ", ".join(uses[:-1]) + " and " + uses[-1]
    # F5: true in every state. No puzzle waits on a connection; what does go
    # out is listed right here.
    return ("<p>\n    All the country data ships inside the app, so playing needs no connection and "
            f"nothing you do waits on one.\n    The app uses the internet only {tail}.\n  </p>")


def privacy_analytics(f):
    if not f["analytics"]:
        return ("<h2>Usage statistics</h2>\n  <p>\n    The app sends no usage statistics of its own: "
                "nothing about how you play is sent to us.\n    Apart from a result you choose to share, "
                "the only data that leaves the device is what\n    Google's ad software receives, "
                "described above.\n  </p>")
    switch = ""
    if f["analytics_switch"]:
        switch = ("\n  <p>\n    They are on unless you switch them off: in Settings, turn off\n    "
                  f"<strong>{SWITCH_LABEL}</strong>, and the app sends none from then on.\n  </p>")
    return f"""<h2>Anonymous usage statistics</h2>
  <p>
    To understand which questions are too hard and where people give up, the app
    sends anonymous usage numbers: for example that a puzzle was finished, on which
    question, at which difficulty and with what score, and whether an ad was shown.
    Each one also carries the app's version, the version of its country data, and
    whether the device runs Android or iOS.
  </p>
  <p>
    They go to PostHog, an analytics service, in its European Union region. They are
    anonymous: they carry no name, no email, no advertising ID, no location and no
    other personal data. Your IP address is {IP_LINE}, and every event also asks
    PostHog not to work out a location from it. There is no question about this when
    you start the app. The only link between one event and the next is a random
    number the app makes up when it is first installed, which is not tied to you,
    your device's advertising ID or anything outside this app. We look at them only
    as totals, never at one player.
  </p>{switch}"""


def privacy_unlock(f):
    if not f["unlock"]:
        return ""
    return """<h2>Buying the unlock</h2>
  <p>
    Every question, every country and the Daily are free. A purchase removes the ads,
    and does nothing else. The payment is handled entirely by Google Play or the App
    Store, under your account there; we never see your card, your name or your store
    account. The app keeps only a note on your device that the unlock is owned, and
    asks the store to confirm it.
  </p>"""


# Story 18.4: the support answers in the page's own language, from
# src/i18n/site_<lang>.arb (every state of every switch is a key there).
def _s(f) -> dict:
    return f.get("s") or site_i18n.strings("en", f.get("root", ROOT))


def _w(text: str) -> str:
    """A site string into a region: escaped, except its own inline tags (<a>, <strong>)."""
    parts = re.split(r"(</?(?:em|a|strong)\b[^>]*>)", text)
    return "".join(p if re.fullmatch(r"</?(?:em|a|strong)\b[^>]*>", p or "") else html.escape(p, quote=False)
                   for p in parts)


def support_free(f):
    s = _s(f)
    text = s["supportFreeText"] + (" " + s["supportFreeUnlock"] if f["unlock"] else "")
    return f"<p>\n    {_w(text)}\n  </p>"


def support_unlock(f):
    if not f["unlock"]:
        return ""
    s = _s(f)
    return (f"<h3>{_w(s['supportUnlockAdsTitle'])}</h3>\n  <p>\n    {_w(s['supportUnlockAdsText'])}\n  </p>\n\n"
            f"  <h3>{_w(s['supportUnlockCancelTitle'])}</h3>\n  <p>\n    {_w(s['supportUnlockCancelText'])}\n  </p>")


def support_analytics(f):
    s = _s(f)
    if not f["analytics"]:
        # the privacy link is relative to the support page: ../privacy/ is the page's own language
        off = s["supportAnalyticsOffText"].replace('href="privacy/"', 'href="../privacy/"')
        return f"<h3>{_w(s['supportAnalyticsTitle'])}</h3>\n  <p>\n    {_w(off)}\n  </p>"
    body = s["supportAnalyticsYes"] + " " + s["supportAnalyticsOnText"]
    if f["analytics_switch"]:
        if f.get("lang", "en") != "en":
            # the label must be the app's own Settings label in that language; refuse rather than guess
            raise SystemExit(f"support-analytics: the {f['lang']} switch label is not wired yet (Story 18.4)")
        switch = site_i18n.fill(s["supportAnalyticsSwitchText"], switch=html.escape(SWITCH_LABEL))
        return f"<h3>{_w(s['supportAnalyticsSwitchTitle'])}</h3>\n  <p>\n    {_w(body)}\n    {switch}\n  </p>"
    return f"<h3>{_w(s['supportAnalyticsTitle'])}</h3>\n  <p>\n    {_w(body)}\n  </p>"


def press_facts(f):
    x = f["facts"]
    price = ("Free to play. Occasional ads between puzzles in Endless play only; "
             "the Daily never shows an ad. Ads are not personalised.")
    if f["unlock"]:
        price += " A purchase removes the ads and changes nothing else."
    rows = [
        ("Questions", f'{x["axes"]}'),
        ("Countries", f'{x["countries"]}: the 193 UN members and 2 observer states'),
        ("Data", f'One named primary source per value, with its year and a link. '
                 f'Data version {x["dataset_version"]}'),
        ("Languages", languages_text(x["languages"])),
        ("Price", price),
    ]
    return "\n      ".join(f"<tr><th>{k}</th><td>{v}</td></tr>" for k, v in rows)


def press_description(f):
    x = f["facts"]
    ads = ("Endless play is supported by occasional ads between games, never during a puzzle "
           "and never in the Daily. Ads are not personalised.")
    if f["unlock"]:
        ads += " You can remove them with a purchase."
    return f"""<p>
    Sorting Geography is a geography game for phones and tablets. Each round shows five
    countries and one question, such as coastline length, population or highest point.
    Drag them into order, confirm, and see how close you were.
  </p>
  <p>
    Confirm your order and the answer fills in on the same screen: the real values, where
    each country belongs, and your score. The score is honest and countable, and you choose
    how it is counted: Simple (countries in the right place) or Pairs (how many pairs you
    put the right way round). The first game walks you through both.
  </p>
  <p>
    There are {x["axes"]} questions across {x["countries"]} countries. Every value comes
    from one named primary source, such as the World Bank, the United Nations, FAO, Natural
    Earth or the CIA World Factbook archive, with its year. Where a source has no figure for
    a country, the country is left out of that question rather than given a guess.
  </p>
  <p>
    One new Daily puzzle a day: the same five countries and the same question for every
    player, shared without giving the answer away. The Daily never shows an ad. Players start
    with countries most people know and unlock the rest as they play, across five levels from
    Beginner to Expert: the game moves a new player from Beginner to Easy once, and after
    that they choose when to move up.
  </p>
  <p>
    No account and no sign-in. It plays offline: the countries, flags and numbers are all in
    the app. Abbreviations such as GDP are spelled out the first time a player meets them.
    Light and dark themes. {ads}
  </p>"""


def press_honesty(f):
    m = f["facts"]["pt_highest_point_m"]
    return f"""<p>
    Every value in the game names one primary source and the year it describes, and the
    player can see it. Countries are counted whole: Portugal's highest point, {m:,} m, is
    Mount Pico in the Azores, not on the mainland, so that is the number the game uses.
    Where a source has no figure for a country, the country is left out of that question
    rather than given a guess. A figure whose licence does not allow it to be used does
    not ship, even when that costs a good question.
  </p>"""


def terms_purchases(f):
    if not f["unlock"]:
        return ""
    return """<h2>Buying the unlock</h2>
  <p>
    A purchase removes the ads and changes nothing else. It is sold and paid for through
    Google Play or the App Store, under their terms, and refunds are handled by the store
    you bought it from. If a purchase is refunded or a subscription ends, the ads come
    back; your progress is never touched.
  </p>"""


def _link_or_todo(url: str | None, what: str) -> str:
    if url is None:
        return f'<span class="todo">{what}: link to come</span>'
    u = html.escape(url, quote=True)
    return f'<a href="{u}">{u}</a>'


def testers_why(f):
    # No tester count or "before it can go public" rule: whether Google's
    # 12-tester rule applies depends on the account type (team-lead 2026-11-20).
    return """<p>
    Before Sorting Geography goes public, we are testing it with real players. This test runs on
    Google Play, so it is for Android only.
  </p>"""


def testers_join(f):
    t = f["testers"]
    return f"""<ol>
    <li>Join the testers' group, signed in with your Google account:
      {_link_or_todo(t["group_url"], "testers' group")}.</li>
    <li>On your phone or tablet, open the test link and tap "Become a tester":
      {_link_or_todo(t["optin_url"], "Google Play test")}.</li>
    <li>From that page, install Sorting Geography from Google Play. Updates arrive through
      Google Play like any other app's.</li>
  </ol>"""


def testers_do(f):
    t = f["testers"]
    return f"""<ul>
    <li>Keep the game installed and stay in the test for at least {t["days"]} days in a row.</li>
    <li>Play a few games every day.</li>
    <li>After you have played for a while, a Daily appears at the bottom of the screen. From
      then on, play it once a day too.</li>
    <li>Tell us anything that seems wrong, however small.</li>
  </ul>"""


FRAGMENTS = {
    "testers-why": testers_why,
    "testers-join": testers_join,
    "testers-do": testers_do,
    "press-facts": press_facts,
    "press-description": press_description,
    "press-honesty": press_honesty,
    "terms-purchases": terms_purchases,
    "privacy-summary": privacy_summary,
    "privacy-connection": privacy_connection,
    "privacy-analytics": privacy_analytics,
    "privacy-unlock": privacy_unlock,
    "support-free": support_free,
    "support-unlock": support_unlock,
    "support-analytics": support_analytics,
}

# Words that may appear in a served page ONLY inside a generated region, and
# only while their feature is on. Outside a region they are a hand-typed claim.
CLAIMS = {
    # Ra'uf 2026-11-19: no streaks at launch ("only if customers request it").
    # The site makes no streak claim either way, so the word is banned on
    # every served page, generated or not: no region may produce it.
    "no-streaks": [r"\bstreaks?\b"],
    "analytics": [r"\bPostHog\b", r"\busage numbers\b", r"\bdiscard(?:ed|s)?\b[^.]{0,40}\bIP\b"],
    "analytics_switch": [re.escape(SWITCH_LABEL)],
    "unlock": [r"\bRestore purchases\b", r"\bsubscription\b", r"\bthe unlock\b",
               r"\bremoves? (?:the )?ads\b"],
    # Counts come from src/facts.json, checked against the game by --game.
    # credits.html is exempt: scripts/build_credits.py generates it from the
    # dataset itself.
    # Google's closed-test numbers come from src/testers.json.
    "testers": [r"\b\d+\s+days in a row\b", r"\b\d+\s+testers\b"],
    "facts": [r"\b\d{2,3}\s+(?:questions|axes)\b", r"\b\d{3}\s+countries\b",
              r"\bdata(?:set)? version\s+v?\d+"],
}
CLAIMS_EXEMPT = {"credits.html"}

REGION = re.compile(r"(<!-- feature:([a-z0-9-]+) -->)(.*?)(<!-- /feature:\2 -->)", re.S)


def served_pages(root: pathlib.Path) -> list[pathlib.Path]:
    ignored = {"docs", "src", "scripts", "node_modules", ".git", ".github", ".wrangler"}
    return sorted(p for p in root.rglob("*.html") if not (set(p.relative_to(root).parts) & ignored))


def render(text: str, flags: dict, where: str) -> str:
    if "facts" not in flags:
        raise SystemExit("render needs the context (flags + facts); use context()")
    def sub(m):
        name = m.group(2)
        if name not in FRAGMENTS:
            raise SystemExit(f"{where}: unknown feature region '{name}'")
        return m.group(1) + FRAGMENTS[name](page_flags) + m.group(4)
    lang = site_i18n.page_lang(text)       # 18.4: each page's regions in its own language
    page_flags = {**flags, "lang": lang, "s": site_i18n.strings(lang, flags.get("root", ROOT))}
    return REGION.sub(sub, text)


def check(root: pathlib.Path = ROOT, flags: dict | None = None) -> list[str]:
    flags = context(root, flags)
    bad = []
    served = testers_served(flags["testers"])
    if (TESTERS_IGNORE in ignored(root)) == served:
        bad.append(f"{ASSETSIGNORE}: the tester page is {'listed' if served else 'not listed'} but "
                   f"src/testers.json says it is {'' if served else 'not '}ready; run scripts/build_features.py")
    if not served:
        for p in served_pages(root):
            if is_served(p, root) and re.search(r'href="[^"]*testers/?(?:index\.html)?"', p.read_text(encoding="utf-8")):
                bad.append(f"{p.relative_to(root)}: links to /testers/, which is not served yet")
    seen = set()
    for p in served_pages(root):
        rel = p.relative_to(root)
        text = p.read_text(encoding="utf-8")
        if render(text, flags, str(rel)) != text:
            bad.append(f"{rel}: a feature region is stale or hand-edited; run scripts/build_features.py")
        seen.update(m.group(2) for m in REGION.finditer(text))
        for m in re.finditer(r"\bstreaks?\b", re.sub(r"<!--.*?-->", " ", text, flags=re.S), re.I):
            if REGION.search(text) and any(r.start() <= m.start() < r.end() for r in REGION.finditer(text)):
                bad.append(f"{rel}: '{m.group(0)}' inside a generated region (no streak claims, Ra'uf 2026-11-19)")
        rest = REGION.sub(" ", text)
        rest = re.sub(r"<!--.*?-->", " ", rest, flags=re.S)
        for feature, pats in CLAIMS.items():
            if str(rel) in CLAIMS_EXEMPT:
                break
            for pat in pats:
                for m in re.finditer(pat, rest, re.I):
                    bad.append(f"{rel}: '{m.group(0)}' outside a feature region "
                               f"(a {feature} claim must come from scripts/build_features.py)")
    fj = root / FACTS_JS
    if not fj.exists() or fj.read_text(encoding="utf-8") != facts_module(root):
        bad.append(f"{FACTS_JS} is stale or hand-edited; run scripts/build_features.py")
    missing = set(FRAGMENTS) - seen
    if missing:
        bad.append(f"feature regions missing from the pages: {', '.join(sorted(missing))}")
    return bad


# ---------------------------------------------------------------------------
# --game: what main actually has
# ---------------------------------------------------------------------------

def game_show(game: pathlib.Path, ref: str, path: str) -> str | None:
    r = subprocess.run(["git", "-C", str(game), "show", f"{ref}:{path}"], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


def game_features(game: pathlib.Path, ref: str = "origin/main") -> dict[str, bool]:
    seam = game_show(game, ref, "app/lib/shell/paid_unlock_seam.dart")
    if seam is None:
        raise SystemExit(f"{game}: cannot read app/lib/shell/paid_unlock_seam.dart at {ref}")
    m = re.search(r"\bkPaidUnlockEnabled\s*=\s*(true|false)\s*;", seam)
    if not m:
        raise SystemExit("paid_unlock_seam.dart: no `kPaidUnlockEnabled = true|false;` line")
    pubspecs = [game_show(game, ref, p) or "" for p in
                ("app/pubspec.yaml", "packages/sort_platform/pubspec.yaml", "packages/sort_core/pubspec.yaml")]
    if not pubspecs[0]:
        raise SystemExit(f"{game}: cannot read app/pubspec.yaml at {ref}")
    posthog = any(re.search(r"^\s+posthog_flutter\s*:", s, re.M) for s in pubspecs)
    r = subprocess.run(["git", "-C", str(game), "grep", "-l", "-F", SWITCH_LABEL, ref, "--",
                        "app/lib", "packages"], capture_output=True, text=True)
    if r.returncode not in (0, 1):
        raise SystemExit(f"git grep failed: {r.stderr.strip()}")
    return {"analytics": posthog, "analytics_switch": bool(r.stdout.strip()), "unlock": m.group(1) == "true"}


def game_facts(game: pathlib.Path, ref: str = "origin/main") -> dict:
    raw = game_show(game, ref, "app/assets/data/dataset_runtime.json")
    if raw is None:
        raise SystemExit(f"{game}: cannot read app/assets/data/dataset_runtime.json at {ref}")
    d = json.loads(raw)
    m = re.match(r"dataset-(v\d+)", d.get("version", ""))
    if not m:
        raise SystemExit(f"dataset_runtime.json: unreadable version {d.get('version')!r}")
    gen = game_show(game, ref, "packages/sort_platform/lib/src/l10n/shipped_locales.gen.dart")
    if gen is None:
        raise SystemExit(f"{game}: cannot read shipped_locales.gen.dart at {ref}")
    body = re.search(r"kShippedLocaleTags\s*=\s*<String>\[(.*?)\]", gen, re.S)
    if not body:
        raise SystemExit("shipped_locales.gen.dart: no kShippedLocaleTags list")
    langs = re.findall(r"'([^']+)'", body.group(1))
    pt = d["axes"].get("highest_point_m", {}).get("PT")
    return {"dataset_version": m.group(1), "axes": len(d["axes"]),
            "countries": len(d["facets"]["continent"]), "languages": langs,
            "pt_highest_point_m": int(pt) if isinstance(pt, (int, float)) and pt == int(pt) else pt}


def compare_package(game: pathlib.Path, ref: str = "origin/main") -> list[str]:
    """The tester page's Play link names PACKAGE; it must be the game's applicationId."""
    gradle = game_show(game, ref, "app/android/app/build.gradle.kts")
    if gradle is None:
        return [f"{game}: cannot read app/android/app/build.gradle.kts at {ref}"]
    m = re.search(r'\bapplicationId\s*=\s*"([^"]+)"', gradle)
    if not m:
        return ["build.gradle.kts: no applicationId line"]
    if m.group(1) != PACKAGE:
        return [f"the tester page's Play package is {PACKAGE}, but the game's main has {m.group(1)}"]
    return []


def compare_facts(facts: dict, real: dict) -> list[str]:
    return [f"src/facts.json {k} = {facts[k]!r}, but the game's main has {real[k]!r}"
            for k in FACT_KEYS if facts[k] != real[k]]


# A placeholder is refused in every form review-share found getting through
# (18.9b B2, B3): the class token `todo` in any quotes or next to any other
# class, and the placeholder words themselves in case the tags are stripped.
# HTML comments are skipped: the worker strips every comment before a page is
# sent (src/pages.js stripComments, 18.9b B5), so a comment never reaches a
# visitor (review-share + team-lead 2026-11-19).
TODO_CLASS = re.compile(
    r"""<[A-Za-z][^>]*?\bclass\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+)""", re.S | re.I)
TODO_TOKEN = re.compile(r"(?<![\w-])todo(?![\w-])", re.I)
TODO_WORDS = re.compile(r"to be confirmed|\[todo", re.I)


def todos(root: pathlib.Path = ROOT) -> list[str]:
    bad = []
    for p in served_pages(root):
        if not is_served(p, root):
            continue    # never uploaded, never seen (20.3c)
        text = re.sub(r"<!--.*?-->", lambda m: re.sub(r"[^\n]", " ", m.group(0)),
                      p.read_text(encoding="utf-8"), flags=re.S)
        rel = p.relative_to(root)
        for m in TODO_CLASS.finditer(text):
            attr = m.group(0)[m.group(0).lower().rindex("class"):]  # case-insensitive, like HTML
            if TODO_TOKEN.search(attr.split("=", 1)[1]):
                line = text.count("\n", 0, m.start()) + 1
                bad.append(f"{rel}:{line}: placeholder still open: {text[m.start():m.start() + 80]!r}")
        for m in TODO_WORDS.finditer(text):
            line = text.count("\n", 0, m.start()) + 1
            bad.append(f"{rel}:{line}: placeholder words still served: {m.group(0)!r}")
    return bad


def compare(flags: dict, real: dict) -> list[str]:
    bad = []
    what = {"analytics": "the PostHog sink (posthog_flutter dependency)",
            "analytics_switch": f"the Settings switch \"{SWITCH_LABEL}\"",
            "unlock": "the paid unlock (kPaidUnlockEnabled)"}
    for k in FEATURES:
        if flags[k] and not real[k]:
            bad.append(f"the pages claim {what[k]}, which the game's main does not have")
        elif real[k] and not flags[k]:
            bad.append(f"the game's main has {what[k]}, which the pages do not describe")
    return bad


# The worker cannot read src/facts.json at run time, so the welcome email
# (src/email.js) imports this generated copy; --check fails when it is stale.
FACTS_JS = "src/facts.gen.js"


def facts_module(root: pathlib.Path = ROOT) -> str:
    facts = load_facts(root)
    return ("// GENERATED by scripts/build_features.py from src/facts.json. Do not edit.\n"
            f"export const FACTS = {json.dumps(facts, sort_keys=True)};\n")


def build(root: pathlib.Path = ROOT) -> None:
    mod = facts_module(root)
    if not (root / FACTS_JS).exists() or (root / FACTS_JS).read_text(encoding="utf-8") != mod:
        (root / FACTS_JS).write_text(mod, encoding="utf-8")
        print(f"wrote {FACTS_JS}")
    flags = context(root)
    want = assetsignore_text(root, testers_served(flags["testers"]))
    f = root / ASSETSIGNORE
    if not f.exists() or f.read_text(encoding="utf-8") != want:
        f.write_text(want, encoding="utf-8")
        print(f"wrote {ASSETSIGNORE} (tester page {'served' if testers_served(flags['testers']) else 'NOT served'})")
    for p in served_pages(root):
        text = p.read_text(encoding="utf-8")
        new = render(text, flags, str(p.relative_to(root)))
        if new != text:
            p.write_text(new, encoding="utf-8")
            print(f"wrote {p.relative_to(root)}")


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--game" in args:
        i = args.index("--game")
        if i + 1 >= len(args):
            raise SystemExit("--game needs the game repo's path")
        game = pathlib.Path(args[i + 1])
        ref = args[args.index("--ref") + 1] if "--ref" in args else "origin/main"
        real = game_features(game, ref)
        problems = (compare(load_flags(), real) + compare_facts(load_facts(), game_facts(game, ref))
                    + compare_package(game, ref) + check() + todos())
        if problems:
            print(f"feature check FAILED against {ref}:")
            for b in problems:
                print("  " + b)
            sys.exit(1)
        print(f"ok   pages match the game at {ref}: {real}")
    elif "--check" in args:
        problems = check()
        if problems:
            print("feature check FAILED (Story 18.9 F3: the pages describe main as it is):")
            for b in problems:
                print("  " + b)
            sys.exit(1)
        print(f"ok   feature regions current: {load_flags()}")
    else:
        build()
