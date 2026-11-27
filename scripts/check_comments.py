#!/usr/bin/env python3
"""No '<!--' or '-->' outside a real HTML comment on any served page (Story 18.9c).

The worker removes every comment with HTMLRewriter (src/pages.js), which parses
HTML properly. scripts/test_served.mjs checks each page as the real worker
sends it against "source minus its comments", built by plain splitting on
'<!--' and '-->'. That split is only right if the marks appear nowhere but in
real comments, so this check refuses them:
  - inside a <script> or <style> (their text is not parsed for comments);
  - inside any tag, e.g. an attribute value like title="a-->b";
  - in page text (a stray '-->');
  - a comment that is never closed (the parser hands it back as text, so
    the text rule catches it), or that opens another '<!--' inside it.
"""
from __future__ import annotations

import pathlib
import sys
from html.parser import HTMLParser

ROOT = pathlib.Path(__file__).resolve().parent.parent
MARKS = ("<!--", "-->")


def served_pages(root: pathlib.Path) -> list[pathlib.Path]:
    ignored = {"docs", "src", "scripts", "node_modules", ".git", ".github", ".wrangler", "functions"}
    return sorted(p for p in root.rglob("*.html") if not (set(p.relative_to(root).parts) & ignored))


class Scan(HTMLParser):
    def __init__(self, rel: str):
        super().__init__(convert_charrefs=False)
        self.rel, self.bad, self.open = rel, [], []

    def where(self) -> str:
        return f"{self.rel}:{self.getpos()[0]}"

    def handle_starttag(self, tag, attrs):
        self.open.append(tag)
        raw = self.get_starttag_text() or ""
        for m in MARKS:
            if m in raw:
                self.bad.append(f"{self.where()}: '{m}' inside the <{tag}> tag: {raw[:80]!r}")

    handle_startendtag = handle_starttag

    def handle_endtag(self, tag):
        if tag in self.open:
            while self.open and self.open.pop() != tag:
                pass

    def handle_data(self, data):
        inside = next((t for t in reversed(self.open) if t in ("script", "style")), None)
        for m in MARKS:
            if m in data:
                what = f"inside <{inside}>" if inside else "in page text"
                self.bad.append(f"{self.where()}: '{m}' {what}: {data.strip()[:80]!r}")

    def handle_comment(self, data):
        if "<!--" in data:
            self.bad.append(f"{self.where()}: a comment opens another '<!--' inside it")


def check(root: pathlib.Path = ROOT) -> list[str]:
    bad = []
    for p in served_pages(root):
        rel = str(p.relative_to(root))
        text = p.read_text(encoding="utf-8")
        s = Scan(rel)
        s.feed(text)
        s.close()
        bad += s.bad
    return bad


if __name__ == "__main__":
    problems = check()
    if problems:
        print("comment check FAILED (Story 18.9c: '<!--' and '-->' only in real comments):")
        for b in problems:
            print("  " + b)
        sys.exit(1)
    print(f"ok   comments: '<!--' and '-->' only in real comments on {len(served_pages(ROOT))} pages")
