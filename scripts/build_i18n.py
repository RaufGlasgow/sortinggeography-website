#!/usr/bin/env python3
"""Build the home page in every published site language (Story 18.4).

src/templates/index.html.tmpl + src/i18n/site_<lang>.arb -> index.html (en) and
<lang lowercased>/index.html for each language in src/site_languages.json
"published". Markers in the template:

    {{key}}            the ARB message (HTML-escaped, except the inline tags the
                       English value itself carries: <em>, <a href="...">)
    {{@lang}}          the language tag (de, pt-PT)
    {{@root}}          "" on the English page, "../" on a language page
    {{@country:XX}}    the CLDR name of country XX in that language
    {{@alternates}}    hreflang links for every published language + x-default
                       (empty while English is the only language)

Launch regions (<!-- launch:NAME -->) stay empty here; scripts/build_launch.py
fills them in each page's language.

    python3 scripts/build_i18n.py           # write the pages
    python3 scripts/build_i18n.py --check   # CI: pages current, every gate green

Gates (--check): a published language has every key and no unknown one; no
value is left identical to English unless src/i18n/allow_identical.json lists
it for that language; each value keeps exactly the English inline tags; every
page is what the template builds (outside its launch regions).
"""
from __future__ import annotations

import html
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import build_launch  # noqa: E402
import site_i18n  # noqa: E402

ROOT = site_i18n.ROOT
TEMPLATE = "src/templates/index.html.tmpl"
ALLOW = "src/i18n/allow_identical.json"
SITE = "https://sortinggeography.com/"
INLINE_TAG = re.compile(r"</?(?:em|a)\b[^>]*>")
MARKER = re.compile(r"\{\{(@?[A-Za-z][A-Za-z0-9]*)(?::([A-Z]{2}))?\}\}")
REGION = build_launch.REGION


def tags(value: str) -> list[str]:
    return sorted(INLINE_TAG.findall(value))


def placeholders(value: str) -> list[str]:
    return sorted(re.findall(r"\{([A-Za-z]+)\}", value))


def safe(value: str, root_prefix: str) -> str:
    """Escape everything except the inline tags; relative links gain the root."""
    parts = re.split(f"({INLINE_TAG.pattern})", value)
    out = []
    for part in parts:
        if INLINE_TAG.fullmatch(part or ""):
            out.append(re.sub(r'href="(?![a-z]+:|/|#)', f'href="{root_prefix}', part))
        else:
            out.append(html.escape(part, quote=False))
    return "".join(out)


def alternates(langs: list[str]) -> str:
    if not langs:
        return ""
    links = [f'<link rel="alternate" hreflang="{lg}" href="{SITE}{site_i18n.folder(lg)}">' for lg in ["en", *langs]]
    links.append(f'<link rel="alternate" hreflang="x-default" href="{SITE}">')
    return "\n" + "\n".join(links)


def render(lang: str, root: pathlib.Path = ROOT) -> str:
    tpl = (root / TEMPLATE).read_text(encoding="utf-8")
    s = site_i18n.strings(lang, root)
    rp = "../" if lang != "en" else ""
    isos = tuple(sorted(set(re.findall(r"\{\{@country:([A-Z]{2})\}\}", tpl))))
    c = site_i18n.cldr(lang, build_launch.release_ms(root), isos)
    langs = site_i18n.served(root)          # hreflang only to pages a visitor can open

    def sub(m):
        name, arg = m.group(1), m.group(2)
        if name == "@lang":
            return lang
        if name == "@root":
            return rp
        if name == "@country":
            return html.escape(c["countries"][arg])
        if name == "@alternates":
            return alternates(langs)
        if name.startswith("@"):
            raise SystemExit(f"{TEMPLATE}: unknown marker {m.group(0)}")
        if name not in s:
            raise SystemExit(f"{TEMPLATE}: {{{{{name}}}}} is not in site_en.arb")
        return safe(s[name], rp)
    return MARKER.sub(sub, tpl)


def page_path(lang: str) -> str:
    return f"{site_i18n.folder(lang)}index.html"


def empty_regions(text: str) -> str:
    return REGION.sub(lambda m: m.group(1) + m.group(4), text)


def gates(root: pathlib.Path = ROOT) -> list[str]:
    bad = []
    en = site_i18n.strings("en", root)
    allow = json.loads((root / ALLOW).read_text(encoding="utf-8")) if (root / ALLOW).exists() else {}
    for lang in site_i18n.published(root):
        try:
            s = site_i18n.strings(lang, root)
        except SystemExit as e:
            bad.append(str(e))
            continue
        ok_same = set(allow.get(lang, []))
        for k, v in s.items():
            if v == en[k] and k not in ok_same:
                bad.append(f"site_{lang}.arb {k}: still the English text ({v[:60]!r}); translate it or list it "
                           f"in {ALLOW} for {lang}")
            if tags(v) != tags(en[k]):
                bad.append(f"site_{lang}.arb {k}: inline tags {tags(v)} differ from English {tags(en[k])}")
            if placeholders(v) != placeholders(en[k]):
                bad.append(f"site_{lang}.arb {k}: placeholders {placeholders(v)} differ from English "
                           f"{placeholders(en[k])} (a date or platform would go missing)")
        for k in sorted(ok_same - set(en)):
            bad.append(f"{ALLOW} {lang}: {k} is not a key")
    for lang in ["en", *site_i18n.published(root)]:
        p = root / page_path(lang)
        if not p.exists():
            bad.append(f"{page_path(lang)} is missing; run scripts/build_i18n.py")
            continue
        if empty_regions(p.read_text(encoding="utf-8")) != render(lang, root):
            bad.append(f"{page_path(lang)} is stale or hand-edited; run scripts/build_i18n.py")
    # pm-release 2026-11-20: the hold is a gate. A built language page the game has not shipped must be in
    # .assetsignore (never uploaded, a 404); a served one must not be.
    try:
        want_ai = assetsignore_text(root)
    except SystemExit as e:
        want_ai = None
        bad.append(str(e))
    if want_ai is not None and (root / ASSETSIGNORE).read_text(encoding="utf-8") != want_ai:
        bad.append(f"{ASSETSIGNORE} does not hold exactly the unshipped language pages {held(root)}; "
                   "run scripts/build_i18n.py")
    if (root / "sitemap.xml").read_text(encoding="utf-8") != sitemap_text(root):
        bad.append("sitemap.xml does not list exactly the published language pages; run scripts/build_i18n.py")
    known = {page_path(lg) for lg in ["en", *site_i18n.published(root)]}
    for p in root.glob("*/index.html"):
        rel = str(p.relative_to(root))
        lang_dir = re.fullmatch(r"([a-z]{2,3}(?:-[a-z0-9]{2,4})?)/index\.html", rel)
        if lang_dir and rel not in known and site_i18n.page_lang(p.read_text(encoding="utf-8")) != "en":
            bad.append(f"{rel}: a language page whose language is not published")
    return bad


def sitemap_text(root: pathlib.Path = ROOT) -> str:
    """The sitemap with exactly one <url> per published language page (crawlable, 18.4)."""
    f = root / "sitemap.xml"
    t = f.read_text(encoding="utf-8")
    t = re.sub(r"  <url><loc>" + re.escape(SITE) + r"[a-z]{2,3}(?:-[a-z0-9]{2,4})?/</loc></url>\n", "", t)
    add = "".join(f"  <url><loc>{SITE}{site_i18n.folder(lg)}</loc></url>\n" for lg in site_i18n.served(root))
    return t.replace("</urlset>", add + "</urlset>", 1)


ASSETSIGNORE = ".assetsignore"


def held(root: pathlib.Path = ROOT) -> list[str]:
    """Built language folders that are not served yet: each must be in .assetsignore."""
    s = set(site_i18n.served(root))
    return [site_i18n.folder(lg).rstrip("/") for lg in site_i18n.published(root) if lg not in s]


def assetsignore_text(root: pathlib.Path = ROOT) -> str:
    """.assetsignore with exactly the held language folders; every other line kept as it is."""
    f = root / ASSETSIGNORE
    managed = {site_i18n.folder(lg).rstrip("/") for lg in site_i18n.GAME_LOCALES}
    lines = [ln for ln in (f.read_text(encoding="utf-8").splitlines() if f.exists() else [])
             if ln.strip().strip("/") not in managed]
    return "\n".join(lines + held(root)) + "\n"


def build(root: pathlib.Path = ROOT) -> None:
    ai = root / ASSETSIGNORE
    want_ai = assetsignore_text(root)
    if not ai.exists() or ai.read_text(encoding="utf-8") != want_ai:
        ai.write_text(want_ai, encoding="utf-8")
        print(f"wrote {ASSETSIGNORE} (held: {held(root) or 'none'})")
    sm = root / "sitemap.xml"
    want = sitemap_text(root)
    if sm.read_text(encoding="utf-8") != want:
        sm.write_text(want, encoding="utf-8")
        print("wrote sitemap.xml")
    for lang in ["en", *site_i18n.published(root)]:
        p = root / page_path(lang)
        new = render(lang, root)
        old = p.read_text(encoding="utf-8") if p.exists() else ""
        if empty_regions(old) != new:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(new, encoding="utf-8")
            print(f"wrote {page_path(lang)}")
    build_launch.build(root)


# ---------------------------------------------------------------------------
# Pull-and-hold (pm-release 2026-11-20): the verified site strings live on the
# game's main (pipeline/translation/site/site_<x>.arb, Story 8.33). --pull copies
# them here and records which languages are built and which are served; --game
# (a deploy step) fails if anything here differs from the game's main.
# ---------------------------------------------------------------------------
import subprocess  # noqa: E402

GAME_SITE = "pipeline/translation/site"
GAME_LOCALES_JSON = "pipeline/translation/locales.json"


class GameError(Exception):
    pass


def _git(game: pathlib.Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(game), *args], capture_output=True, text=True)


def game_show(game: pathlib.Path, ref: str, path: str) -> str | None:
    r = _git(game, "show", f"{ref}:{path}")
    return r.stdout if r.returncode == 0 else None


def game_state(game: pathlib.Path, ref: str) -> dict:
    """What the game's main says, or GameError: any git problem fails, never reads as 'nothing yet'."""
    if _git(game, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}").returncode != 0:
        raise GameError(f"{game}: not a git repo with a commit at {ref!r}")
    en = game_show(game, ref, f"{GAME_SITE}/site_en.arb")
    if en is None:
        raise GameError(f"{game}: no {GAME_SITE}/site_en.arb at {ref} (Story 18.4a not on the game's main?)")
    loc = game_show(game, ref, GAME_LOCALES_JSON)
    if loc is None:
        raise GameError(f"{game}: no {GAME_LOCALES_JSON} at {ref}")
    locales = json.loads(loc)
    arbs = {}
    for lg in site_i18n.GAME_LOCALES:
        text = game_show(game, ref, f"{GAME_SITE}/{site_i18n.arb_name(lg)}")
        if text is not None:
            arbs[lg] = text
    shipped = [lg for lg in site_i18n.GAME_LOCALES if locales.get(lg, {}).get("status") == "shipped"]
    # 18.4a review M2: only a site file the game's CI gate passed may be read: its sha256 must be in
    # pipeline/translation/site/gates.json (python -m translation site-gates).
    rec_text = game_show(game, ref, f"{GAME_SITE}/gates.json")
    if rec_text is None:
        raise GameError(f"{game}: no {GAME_SITE}/gates.json at {ref} (the site gate record, Story 18.4a)")
    record = json.loads(rec_text)
    return {"en": en, "arbs": arbs, "shipped": shipped, "record": record}


def passed(state: dict, lang: str) -> bool:
    import hashlib
    text = state["arbs"].get(lang)
    if text is None:
        return False
    sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return state["record"].get(lang, {}).get("sha256") == sha


def _complete(text: str, en_keys: set[str]) -> bool:
    got = {k for k in json.loads(text) if not k.startswith("@")}
    return en_keys <= got


def plan(state: dict, root: pathlib.Path = ROOT) -> tuple[list[str], list[str]]:
    en_keys = set(site_i18n.strings("en", root))
    published = [lg for lg in site_i18n.GAME_LOCALES
                 if lg in state["arbs"] and _complete(state["arbs"][lg], en_keys) and passed(state, lg)]
    served = [lg for lg in published if lg in state["shipped"]]
    return published, served


def pull(game: pathlib.Path, ref: str, root: pathlib.Path = ROOT) -> None:
    state = game_state(game, ref)
    if state["en"] != (root / site_i18n.I18N / "site_en.arb").read_text(encoding="utf-8"):
        raise GameError("the game's site_en.arb differs from src/i18n/site_en.arb: copy the website's English "
                        "into the game (pipeline/translation/site/site_en.arb) first; the website is its author")
    published, served_ = plan(state, root)
    for lg in published:
        p = site_i18n.arb_path(lg, root)
        if not p.exists() or p.read_text(encoding="utf-8") != state["arbs"][lg]:
            p.write_text(state["arbs"][lg], encoding="utf-8")
            print(f"pulled {p.relative_to(root)}")
    f = root / site_i18n.LANGS_FILE
    data = json.loads(f.read_text(encoding="utf-8"))
    data["published"], data["served"] = published, served_
    f.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    site_i18n._load.cache_clear()
    build(root)


def check_game(game: pathlib.Path, ref: str, root: pathlib.Path = ROOT) -> list[str]:
    try:
        state = game_state(game, ref)
    except GameError as e:
        return [str(e)]
    bad = []
    if state["en"] != (root / site_i18n.I18N / "site_en.arb").read_text(encoding="utf-8"):
        bad.append("src/i18n/site_en.arb is not byte-identical to the game's pipeline/translation/site/site_en.arb")
    published, served_ = plan(state, root)
    if site_i18n.published(root) != published:
        bad.append(f"built languages {site_i18n.published(root)} != the game's complete site ARBs {published}; "
                   "run scripts/build_i18n.py --pull")
    if site_i18n.served(root) != served_:
        bad.append(f"served languages {site_i18n.served(root)} != built and shipped on the game's main {served_}; "
                   "run scripts/build_i18n.py --pull")
    for lg in published:
        p = site_i18n.arb_path(lg, root)
        if not p.exists() or p.read_text(encoding="utf-8") != state["arbs"][lg]:
            bad.append(f"{p.relative_to(root)} differs from the game's {GAME_SITE}/{site_i18n.arb_name(lg)}")
    for lg in state["arbs"]:
        if not passed(state, lg):
            bad.append(f"the game's {GAME_SITE}/{site_i18n.arb_name(lg)} has no passing record in gates.json "
                       "(run `python -m translation site-gates` on the game side); the website will not read it")
    for lg in state["shipped"]:
        if lg not in published:
            bad.append(f"the game ships {lg} but has no complete site strings for it: /{site_i18n.folder(lg)} cannot be built")
    return bad + gates(root)


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--pull" in args or "--game" in args:
        flag = "--pull" if "--pull" in args else "--game"
        i = args.index(flag)
        if i + 1 >= len(args):
            raise SystemExit(f"{flag} needs the game repo's path")
        game = pathlib.Path(args[i + 1])
        ref = args[args.index("--ref") + 1] if "--ref" in args else "origin/main"
        if flag == "--pull":
            try:
                pull(game, ref)
            except GameError as e:
                raise SystemExit(f"pull FAILED: {e}")
            sys.exit(0)
        problems = check_game(game, ref)
        if problems:
            print(f"site language check FAILED against the game at {ref}:")
            for b in problems:
                print("  " + b)
            sys.exit(1)
        s = site_i18n.served()
        held_ = [lg for lg in site_i18n.published() if lg not in s]
        print(f"ok   site languages match the game at {ref}. Serving: "
              f"{', '.join('/' + site_i18n.folder(lg) for lg in s) or 'English only'}"
              f"{'; held until shipped: ' + ', '.join('/' + site_i18n.folder(lg) for lg in held_) if held_ else ''}")
        sys.exit(0)

    if "--check" in args:
        problems = gates()
        if problems:
            print("site language check FAILED (Story 18.4):")
            for b in problems:
                print("  " + b)
            sys.exit(1)
        print(f"ok   site languages: en + {site_i18n.published() or 'none published'}; pages current")
    else:
        build()
