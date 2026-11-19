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

--game reads the game repo's origin/main (git show, nothing checked out) and
fails when features.json says a feature is on that main does not have, or off
when main has it: either way the privacy page would be false. It cannot run in
this public repo's CI (the game repo is private), so it is a deploy step
(docs/DEPLOY-RUNBOOK.md), never skipped: no path, no deploy.
"""
from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys

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


def support_free(f):
    s = ("<p>\n    Yes. Every question, every country and the Daily are free. The Daily never shows\n"
         "    an ad. Endless play shows an occasional ad between puzzles.")
    if f["unlock"]:
        s += " A purchase removes the ads and changes nothing else."
    return s + "\n  </p>"


def support_unlock(f):
    if not f["unlock"]:
        return ""
    return """<h3>I bought the unlock, but I still see ads</h3>
  <p>
    Open the app while connected to the internet: it checks with the store when it
    starts. If that does not help, use Restore purchases in Settings, signed in to the
    same Google Play or App Store account you bought it with. If it still shows ads,
    write to us.
  </p>

  <h3>How do I cancel the yearly subscription?</h3>
  <p>
    Through the store you bought it from. On Android, open Google Play, then Payments
    and subscriptions, then Subscriptions. On iOS, open Settings, tap your name, then
    Subscriptions. A one-time purchase has nothing to cancel.
  </p>"""


def support_analytics(f):
    if not f["analytics"]:
        return ("<h3>Does the app send usage numbers?</h3>\n  <p>\n    No. It sends no usage "
                "statistics of its own. The <a href=\"../privacy/\">privacy page</a>\n    says what "
                "Google's ad service receives.\n  </p>")
    body = ("The app sends anonymous usage numbers so we can see which questions are too\n    "
            f"hard. Your IP address is {IP_LINE}; no advertising ID, nothing that identifies you.")
    if f["analytics_switch"]:
        return ("<h3>Can I stop the app sending usage numbers?</h3>\n  <p>\n    Yes. " + body +
                f"\n    To stop them, open Settings and turn off <strong>{SWITCH_LABEL}</strong>.\n  </p>")
    return "<h3>Does the app send usage numbers?</h3>\n  <p>\n    Yes. " + body + "\n  </p>"


FRAGMENTS = {
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
}

REGION = re.compile(r"(<!-- feature:([a-z0-9-]+) -->)(.*?)(<!-- /feature:\2 -->)", re.S)


def served_pages(root: pathlib.Path) -> list[pathlib.Path]:
    ignored = {"docs", "src", "scripts", "node_modules", ".git", ".github", ".wrangler"}
    return sorted(p for p in root.rglob("*.html") if not (set(p.relative_to(root).parts) & ignored))


def render(text: str, flags: dict, where: str) -> str:
    def sub(m):
        name = m.group(2)
        if name not in FRAGMENTS:
            raise SystemExit(f"{where}: unknown feature region '{name}'")
        return m.group(1) + FRAGMENTS[name](flags) + m.group(4)
    return REGION.sub(sub, text)


def check(root: pathlib.Path = ROOT, flags: dict | None = None) -> list[str]:
    flags = load_flags(root) if flags is None else flags
    bad = []
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
            for pat in pats:
                for m in re.finditer(pat, rest, re.I):
                    bad.append(f"{rel}: '{m.group(0)}' outside a feature region "
                               f"(a {feature} claim must come from scripts/build_features.py)")
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


def build(root: pathlib.Path = ROOT) -> None:
    flags = load_flags(root)
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
        problems = compare(load_flags(), real) + check()
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
