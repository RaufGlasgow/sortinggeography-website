#!/usr/bin/env python3
"""The game never links to a country sheet the site does not have (Story 20.9).

The app links a country to https://sortinggeography.com/countries/<iso>/ (en)
or /<lang>/countries/<iso>/, but only for the languages in one constant on the
game's main, agreed with dev-sheet 2026-11-20, written exactly so:

    app/lib/play/country_sheet_url.dart
        const Set<String> kCountrySheetLanguages = <String>{'en', 'de'};

Tags are single-quoted, lowercased locale tags (de, pt-pt, es-419 ...). It
starts EMPTY (no sheet link) until the English sheets are live. iso is each key
of pipeline/roster/countries.json → "countries", lowercased: 195 of them.

For every tag, every one of the 195 sheets must exist here
(countries/<iso>/index.html for en, <lang>/countries/<iso>/index.html
otherwise), or this fails. A file on main whose constant does not parse fails
too: a check that cannot read the set must not wave it through. No file on
main means the app links nowhere yet, which is the one passing absence, and only when no other file in the app names a
sortinggeography.com/countries link (a renamed file cannot slip past).

It reads the game repo's origin/main (git show, nothing checked out), so it
cannot run in this public repo's CI; it is a deploy step next to
build_features.py --game (docs/DEPLOY-RUNBOOK.md Step 4).

    python3 scripts/check_sheet_links.py --game ../Sorting-Geography [--ref origin/main]
"""
from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SHEET_URL_DART = "app/lib/play/country_sheet_url.dart"
ROSTER = "pipeline/roster/countries.json"
CONST = re.compile(r"^\s*const\s+Set<String>\s+kCountrySheetLanguages\s*=\s*<String>\{([^}]*)\}\s*;", re.M)
TAG = re.compile(r"[a-z]{2,3}(?:-[a-z0-9]{2,4})?")


def game_show(game: pathlib.Path, ref: str, path: str) -> str | None:
    r = subprocess.run(["git", "-C", str(game), "show", f"{ref}:{path}"], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


def sheet_languages(dart: str) -> list[str] | None:
    """The tags, or None when the constant is missing or malformed."""
    found = CONST.findall(dart)
    if len(found) != 1:
        return None
    body = found[0].strip()
    if not body:
        return []
    parts = [p.strip() for p in body.rstrip(",").split(",")]
    tags = []
    for p in parts:
        m = re.fullmatch(r"'([^']*)'", p)
        if not m or not TAG.fullmatch(m.group(1)) or m.group(1) in tags:
            return None
        tags.append(m.group(1))
    return tags


def sheet_path(lang: str, iso: str) -> str:
    return f"countries/{iso}/index.html" if lang == "en" else f"{lang}/countries/{iso}/index.html"


class GitFailed(Exception):
    pass


def require_ref(game: pathlib.Path, ref: str) -> None:
    """The game repo and the ref must be real, or nothing below can be trusted (review S1)."""
    r = subprocess.run(["git", "-C", str(game), "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise GitFailed(f"{game}: not a git repo with a commit at {ref!r}")


def sheet_link_files(game: pathlib.Path, ref: str) -> list[str]:
    """Every file in the app at ref with sortinggeography.com and countries on one line,
    in any order and any form: a literal, an interpolated '$lang/countries/$iso/', or
    Uri.https('sortinggeography.com', '/countries/...') (review S2)."""
    r = subprocess.run(["git", "-C", str(game), "grep", "-l", "-i", "-E",
                        r"sortinggeography\.com.*countries|countries.*sortinggeography\.com",
                        ref, "--", "app/lib", "packages"], capture_output=True, text=True)
    if r.returncode not in (0, 1):      # 1 = no match; anything else is git failing
        raise GitFailed(f"git grep failed at {ref}: {r.stderr.strip()[:200]}")
    return sorted(line.split(":", 1)[1] for line in r.stdout.splitlines() if ":" in line)


def check(game: pathlib.Path, ref: str = "origin/main", root: pathlib.Path = ROOT) -> list[str]:
    try:
        return _check(game, ref, root)
    except GitFailed as e:
        return [str(e)]


def _check(game: pathlib.Path, ref: str, root: pathlib.Path) -> list[str]:
    require_ref(game, ref)
    if game_show(game, ref, ROSTER) is None:
        return [f"{game}: no {ROSTER} at {ref}; this is not the game repo"]
    elsewhere = [f for f in sheet_link_files(game, ref) if f != SHEET_URL_DART]
    if elsewhere:
        # A link built anywhere else escapes the constant this check reads.
        return [f"{f} at {ref} names a /countries/ link; only {SHEET_URL_DART} may" for f in elsewhere]
    dart = game_show(game, ref, SHEET_URL_DART)
    if dart is None:
        print(f"note {SHEET_URL_DART} is not on {ref} and nothing else links a sheet: no sheet link yet")
        return []
    langs = sheet_languages(dart)
    if langs is None:
        return [f"{SHEET_URL_DART} at {ref}: no single `const Set<String> kCountrySheetLanguages = "
                "<String>{'en', ...};` with single-quoted lowercase tags"]
    roster = game_show(game, ref, ROSTER)
    if roster is None:
        return [f"{game}: cannot read {ROSTER} at {ref}"]
    isos = sorted(k.lower() for k in json.loads(roster)["countries"])
    bad = []
    for lang in langs:
        missing = [iso for iso in isos if not (root / sheet_path(lang, iso)).is_file()]
        if missing:
            bad.append(f"the game links {lang} sheets, but {len(missing)} of {len(isos)} are not on the "
                       f"site (first: /{sheet_path(lang, missing[0]).removesuffix('index.html')})")
    if not bad:
        print(f"ok   sheet links: {langs or 'none'} x {len(isos)} countries all on the site")
    return bad


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--game" not in args or args.index("--game") + 1 >= len(args):
        raise SystemExit("usage: check_sheet_links.py --game PATH [--ref REF]")
    game = pathlib.Path(args[args.index("--game") + 1])
    ref = args[args.index("--ref") + 1] if "--ref" in args else "origin/main"
    problems = check(game, ref)
    if problems:
        print(f"sheet link check FAILED against {ref}:")
        for b in problems:
            print("  " + b)
        sys.exit(1)
