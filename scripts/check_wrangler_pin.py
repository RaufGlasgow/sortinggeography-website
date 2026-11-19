#!/usr/bin/env python3
"""One wrangler version for test and deploy (Story 18.9c, team-lead 2026-11-19).

CI's real-worker test (ci.yml, WRANGLER: npx --yes wrangler@X) and the deploy
command in docs/DEPLOY-RUNBOOK.md Step 4 (npx --yes wrangler@X deploy) must name
the same exact version, so what is tested is what deploys. Every other mention
of a wrangler deploy in README.md or docs/ must be that same pinned command.
"""
from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
EXACT = r"(\d+\.\d+\.\d+)"


def check(root: pathlib.Path = ROOT) -> list[str]:
    bad = []
    ci = (root / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    book = (root / "docs/DEPLOY-RUNBOOK.md").read_text(encoding="utf-8")
    tested = re.findall(r"WRANGLER:\s*npx --yes wrangler@" + EXACT + r"\s*$", ci, re.M)
    step4 = book.split("## Step 4", 1)[1].split("\n## ", 1)[0] if "## Step 4" in book else ""
    deployed = re.findall(r"^npx --yes wrangler@" + EXACT + r" deploy\s*$", step4, re.M)
    if len(tested) != 1:
        bad.append(f"ci.yml: expected one `WRANGLER: npx --yes wrangler@<x.y.z>`, found {tested}")
    if not deployed:
        bad.append("DEPLOY-RUNBOOK.md Step 4: no `npx --yes wrangler@<x.y.z> deploy` command")
    # Every `wrangler ... deploy` in any instructions (README.md, docs/*.md), in
    # any form and anywhere on a line (`npx wrangler deploy`, `cd x && wrangler
    # deploy`, prose in backticks), must be exactly the pinned command
    # (review-share R4-W1, R4-W2).
    for doc in [root / "README.md", *sorted((root / "docs").rglob("*.md"))]:
        if not doc.exists():
            continue
        for n, line in enumerate(doc.read_text(encoding="utf-8").splitlines(), 1):
            for m in re.finditer(r"(\S+[ \t]+)?(\S+[ \t]+)?\bwrangler(@\S+)?[ \t]+deploy\b", line):
                pinned = re.search(r"(?:^|[\s`])npx --yes wrangler@" + EXACT + r"[ \t]+deploy\b", " " + m.group(0))
                if not pinned or (tested and pinned.group(1) != tested[0]):
                    bad.append(f"{doc.relative_to(root)}:{n}: not the pinned deploy: {line.strip()[:90]!r}")
    # (Step 4's version against CI's is covered by the docs-wide rule above.)
    return bad


if __name__ == "__main__":
    problems = check()
    if problems:
        print("wrangler pin check FAILED (tested must be what deploys):")
        for b in problems:
            print("  " + b)
        sys.exit(1)
    print("ok   wrangler pinned: CI and the deploy step use the same version")
