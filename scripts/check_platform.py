#!/usr/bin/env python3
"""No platform bias on any public surface (Ra'uf 2026-11-18).

    "the design of the website assumes ios and the game is in both ios and
     android, so should not be so biased in the presenation."

The rule, as the release plan (5.9) states it: name both platforms together,
never one store alone, never Apple first; "Android and iOS"; badges Google Play
then App Store; devices are "phone" and "tablet", never "iPhone" or "iPad".

This check fails a served page or text file when, inside one block of text
(a paragraph, list item, heading, cell, badge row ...):

  1. "iPhone" or "iPad" appears at all (say phone or tablet);
  2. an Apple-side name (iOS, App Store, Apple, iCloud) appears with no
     Google-side name (Android, Google Play, Google) beside it;
  3. an Android-side name (Android, Google Play) appears with no Apple-side
     name (iOS, App Store, Apple) beside it;
  4. both sides appear but the Apple side comes first.

The text of a block includes its alt, title, aria-label and meta content
attributes, so a badge or an Open Graph line cannot slip past. Scripts and
styles are skipped ("-apple-system" is a font name, not a platform claim);
HTML comments are skipped (they describe the rule, they do not show it).

Same idea as Sally's check_platform_parity() (ux/website/refresh-2026-11-19/
_build.py, 217ef0b6), extended with the ordering rule, the device names and the
reverse direction for every pair. scripts/test_checks.py breaks it on purpose.

    python3 scripts/check_platform.py           # whole site
    python3 scripts/check_platform.py FILE ...  # just these files
"""
from __future__ import annotations

import html
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
IGNORED_DIRS = {"docs", "src", "scripts", "node_modules", ".git", ".github", ".wrangler", "_preview-short"}

DEVICE = re.compile(r"\biP(?:hone|ad)s?\b", re.I)
APPLE = re.compile(r"\b(?:iOS|iPadOS|App\s+Store|Apple|iCloud)\b")
GOOGLE = re.compile(r"\b(?:Android|Google\s+Play|Google)\b")
ANDROID = re.compile(r"\b(?:Android|Google\s+Play)\b")

BLOCK = re.compile(
    r"</?(?:p|li|div|h[1-6]|td|th|dt|dd|figcaption|blockquote|section|button|header|footer|"
    r"nav|figure|ul|ol|summary|details|label|form|main|aside|table|tr|dl|br|hr|body|head|title)\b[^>]*>",
    re.I)
ATTR = re.compile(r'\b(?:alt|title|aria-label|content|placeholder)\s*=\s*"([^"]*)"', re.I)


def blocks_html(page: str) -> list[str]:
    page = re.sub(r"<!--.*?-->", " ", page, flags=re.S)
    page = re.sub(r"<(script|style)\b.*?</\1>", " ", page, flags=re.S | re.I)
    page = re.sub(r'\sstyle\s*=\s*"[^"]*"', " ", page, flags=re.I)
    out = []
    for block in BLOCK.split(page):
        # Each meta tag is its own block: one description must not borrow the
        # other platform from the next tag.
        for meta in re.findall(r"<meta\b[^>]*>", block, flags=re.I):
            out.append(" ".join(ATTR.findall(meta)))
        block = re.sub(r"<meta\b[^>]*>", " ", block, flags=re.I)
        attrs = " ".join(ATTR.findall(block))
        text = re.sub(r"<[^>]+>", " ", block) + " " + attrs
        out.append(text)
    return out


def blocks_text(text: str) -> list[str]:
    # Plain text and Markdown: a block is a paragraph (blank-line separated),
    # and each list line or table row is its own block.
    out = []
    for para in re.split(r"\n\s*\n", text):
        lines = para.splitlines()
        if any(re.match(r"\s*(?:[-*|]|\d+\.)\s", ln) for ln in lines):
            out.extend(lines)
        else:
            out.append(" ".join(lines))
    return out


# The ONE page allowed to name Android alone: the Google Play closed-test page
# (Story 20.3b). Joining a Google Play test is an Android procedure, so its
# steps cannot honestly name iOS. The exemption covers only rule 3, only this
# path, and only while the page says why in so many words; the other rules
# (device names, Apple first, Apple alone) still apply to it.
ANDROID_ONLY = {"testers/index.html": "This test runs on Google Play, so it is for Android only."}


def problems_in(name: str, content: str, is_html: bool) -> list[str]:
    bad = []
    why = ANDROID_ONLY.get(name.replace("\\", "/"))
    android_alone_ok = bool(why) and why in re.sub(r"\s+", " ", html.unescape(content))
    for raw in (blocks_html(content) if is_html else blocks_text(content)):
        text = re.sub(r"\s+", " ", html.unescape(raw)).strip()
        if not text:
            continue
        short = text[:110]
        if DEVICE.search(text):
            bad.append(f"{name}: says {DEVICE.search(text).group(0)!r} (say phone or tablet): {short}")
        a, g, an = APPLE.search(text), GOOGLE.search(text), ANDROID.search(text)
        if a and not g:
            bad.append(f"{name}: {a.group(0)!r} with no Android or Google beside it: {short}")
        if an and not a and not android_alone_ok:
            bad.append(f"{name}: {an.group(0)!r} with no iOS or App Store beside it: {short}")
        if a and g and a.start() < g.start():
            bad.append(f"{name}: {a.group(0)!r} comes before {g.group(0)!r} (Android side first): {short}")
    return bad


def targets(root: pathlib.Path = ROOT) -> list[pathlib.Path]:
    files = []
    for pattern in ("*.html", "*.txt", "*.xml", "*.md"):
        files += [p for p in root.rglob(pattern)
                  if not (set(p.relative_to(root).parts) & IGNORED_DIRS)]
    return sorted(set(files))


def check(paths: list[pathlib.Path], root: pathlib.Path = ROOT) -> list[str]:
    bad = []
    for p in paths:
        try:
            name = str(p.relative_to(root))
        except ValueError:
            name = str(p)
        bad += problems_in(name, p.read_text(encoding="utf-8"), p.suffix in (".html", ".xml"))
    return bad


if __name__ == "__main__":
    args = [pathlib.Path(a) for a in sys.argv[1:]]
    paths = args or targets()
    problems = check(paths)
    if problems:
        print("platform check FAILED (Ra'uf 2026-11-18: Android and iOS together, never Apple first):")
        for b in problems:
            print("  " + b)
        sys.exit(1)
    print(f"ok   platform-neutral: {len(paths)} files")
