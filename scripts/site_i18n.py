#!/usr/bin/env python3
"""Site languages (Story 18.4): the strings, the language of a page, CLDR text.

Every word of the home page and of the launch regions is a key in
src/i18n/site_<lang>.arb (ARB, the format the game's translation pipeline
reads; English is the source). Dates, times and country names come from CLDR
through Node (scripts/cldr.mjs), never from a translator.

A language's pages are built only when it is listed in src/site_languages.json
"published" (empty until the game ships a language) and its ARB has every key.
The folder is the locale tag lowercased (de, pt-pt): what the game's 8.16
readiness gate looks for.
"""
from __future__ import annotations

import functools
import json
import pathlib
import re
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent
I18N = "src/i18n"
LANGS_FILE = "src/site_languages.json"


def arb_path(lang: str, root: pathlib.Path = ROOT) -> pathlib.Path:
    return root / I18N / f"site_{lang.replace('-', '_')}.arb"


@functools.lru_cache(maxsize=None)
def _load(path: str) -> dict:
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))


def strings(lang: str, root: pathlib.Path = ROOT) -> dict[str, str]:
    """The ARB's messages (no @-metadata). Every English key must be present."""
    en = {k: v for k, v in _load(str(arb_path("en", root))).items() if not k.startswith("@")}
    if lang == "en":
        return en
    p = arb_path(lang, root)
    if not p.exists():
        raise SystemExit(f"{p.relative_to(root)}: missing (language {lang} is published)")
    got = {k: v for k, v in _load(str(p)).items() if not k.startswith("@")}
    missing = sorted(set(en) - set(got))
    extra = sorted(set(got) - set(en))
    if missing or extra:
        raise SystemExit(f"{p.relative_to(root)}: missing {missing}, unknown {extra}")
    return got


def published(root: pathlib.Path = ROOT) -> list[str]:
    f = root / LANGS_FILE
    langs = json.loads(f.read_text(encoding="utf-8")).get("published", []) if f.exists() else []
    for lang in langs:
        if not re.fullmatch(r"[a-z]{2,3}(?:-[A-Za-z0-9]{2,4})?", lang) or lang == "en":
            raise SystemExit(f"{LANGS_FILE}: bad language tag {lang!r}")
    return langs


def folder(lang: str) -> str:
    return "" if lang == "en" else lang.lower() + "/"


def page_lang(text: str) -> str:
    m = re.search(r'<html\b[^>]*\blang="([^"]+)"', text)
    return m.group(1) if m else "en"


@functools.lru_cache(maxsize=None)
def cldr(lang: str, ms: int, isos: tuple[str, ...] = ()) -> dict:
    out = subprocess.run(["node", str(ROOT / "scripts" / "cldr.mjs"), lang, str(ms), *isos],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def fill(template: str, **values: str) -> str:
    """ICU-style {name} placeholders, all of which must be supplied."""
    def sub(m):
        if m.group(1) not in values:
            raise SystemExit(f"string {template!r}: no value for {{{m.group(1)}}}")
        return values[m.group(1)]
    return re.sub(r"\{([A-Za-z]+)\}", sub, template)
