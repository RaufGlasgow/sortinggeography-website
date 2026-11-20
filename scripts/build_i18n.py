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
    langs = site_i18n.published(root)

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
    add = "".join(f"  <url><loc>{SITE}{site_i18n.folder(lg)}</loc></url>\n" for lg in site_i18n.published(root))
    return t.replace("</urlset>", add + "</urlset>", 1)


def build(root: pathlib.Path = ROOT) -> None:
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


if __name__ == "__main__":
    if "--check" in sys.argv[1:]:
        problems = gates()
        if problems:
            print("site language check FAILED (Story 18.4):")
            for b in problems:
                print("  " + b)
            sys.exit(1)
        print(f"ok   site languages: en + {site_i18n.published() or 'none published'}; pages current")
    else:
        build()
