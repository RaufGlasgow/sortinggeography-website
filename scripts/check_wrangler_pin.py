#!/usr/bin/env python3
"""One wrangler version for test and deploy (Story 18.9c, team-lead 2026-11-19).

CI's real-worker test (ci.yml, WRANGLER: npx --yes wrangler@X) and the deploy
command in docs/DEPLOY-RUNBOOK.md Step 4 (npx --yes wrangler@X deploy) must name
the same exact version, so what is tested is what deploys.
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
    # Every deploy COMMAND line in Step 4 (not the prose about it) must be the pinned one.
    for line in re.findall(r"^[ \t]*(?:npx[ \t]+\S+[ \t]+)?wrangler\S*[ \t]+deploy\b.*$", step4, re.M):
        if not re.fullmatch(r"npx --yes wrangler@" + EXACT + r" deploy\s*", line.strip() + " "):
            bad.append(f"DEPLOY-RUNBOOK.md Step 4: unpinned deploy command: {line.strip()!r}")
    if tested and deployed and set(deployed) != {tested[0]}:
        bad.append(f"CI tests wrangler {tested[0]} but Step 4 deploys {sorted(set(deployed))}")
    return bad


if __name__ == "__main__":
    problems = check()
    if problems:
        print("wrangler pin check FAILED (tested must be what deploys):")
        for b in problems:
            print("  " + b)
        sys.exit(1)
    print("ok   wrangler pinned: CI and the deploy step use the same version")
