#!/usr/bin/env python3
"""After a deploy: the URLs the stores and AdMob read answer 200 (Story 18.9).

    python3 scripts/check_live.py                       # https://sortinggeography.com
    python3 scripts/check_live.py https://example.dev   # a preview

Fails when:
  - /support/, /privacy/ or /app-ads.txt answers anything but 200 (redirects
    are NOT followed for these: a store or AdMob crawler must get the page
    itself at the URL in the listing);
  - /app-ads.txt does not carry the publisher line, or is served as HTML;
  - /privacy.html does not 301 to /privacy/ (the app's own link);
  - the support address's domain has no MX record, so mail to it would bounce.
    Fix: Cloudflare dashboard, sortinggeography.com, Email > Email Routing,
    add support@ (the same way sortinghistory.com is set up).

Not run in CI: it needs the deployed site and the network.
"""
from __future__ import annotations

import http.client
import pathlib
import subprocess
import sys
import json
import urllib.parse

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from check_store_pages import APP_ADS_LINE, SUPPORT_EMAIL  # noqa: E402

UA = "sortinggeography-site-check/1.0"


def get(base: str, path: str) -> tuple[int, dict, str]:
    u = urllib.parse.urlsplit(base)
    conn = (http.client.HTTPSConnection if u.scheme == "https" else http.client.HTTPConnection)(u.netloc, timeout=20)
    conn.request("GET", path, headers={"User-Agent": UA, "Accept": "*/*"})
    r = conn.getresponse()
    body = r.read().decode("utf-8", "replace")
    headers = {k.lower(): v for k, v in r.getheaders()}
    conn.close()
    return r.status, headers, body


def main(base: str) -> int:
    bad = []
    for path in ("/support/", "/privacy/", "/app-ads.txt"):
        try:
            status, headers, body = get(base, path)
        except OSError as e:
            bad.append(f"{path}: no answer ({e})")
            continue
        if status != 200:
            bad.append(f"{path}: HTTP {status}, expected 200")
            continue
        if path == "/app-ads.txt":
            if "text/html" in headers.get("content-type", ""):
                bad.append("/app-ads.txt is served as HTML")
            if APP_ADS_LINE not in body:
                bad.append("/app-ads.txt does not carry the publisher line")
        print(f"ok   {path} 200")
    try:
        status, headers, _ = get(base, "/privacy.html")
        loc = headers.get("location", "")
        if status != 301 or not loc.endswith("/privacy/"):
            bad.append(f"/privacy.html: HTTP {status} to {loc!r}, expected 301 to /privacy/")
        else:
            print("ok   /privacy.html 301 -> /privacy/")
    except OSError as e:
        bad.append(f"/privacy.html: no answer ({e})")

    # 18.9b B5: the worker strips every HTML comment, so a live page never
    # carries the internal notes the source pages hold.
    # 20.3c: /testers/ is live only once both of its links exist; until then
    # it must be a 404 (it is in .assetsignore).
    tj = json.loads((pathlib.Path(__file__).resolve().parent.parent / "src/testers.json").read_text())
    testers_live = tj.get("group_url") is not None and tj.get("optin_url") is not None
    if not testers_live:
        try:
            status, _, _ = get(base, "/testers/")
            if status != 404:
                bad.append(f"/testers/: HTTP {status}, expected 404 until both tester links exist")
            else:
                print("ok   /testers/ 404 (not served until its links exist)")
        except OSError as e:
            bad.append(f"/testers/: no answer ({e})")
    # 18.4: a served language page answers 200; a built one the game has not shipped is a 404.
    sl = json.loads((pathlib.Path(__file__).resolve().parent.parent / "src/site_languages.json").read_text())
    for lang in sl.get("published", []):
        path = "/" + lang.lower() + "/"
        want = 200 if lang in sl.get("served", []) else 404
        try:
            status, _, _ = get(base, path)
        except OSError as e:
            bad.append(f"{path}: no answer ({e})")
            continue
        if status != want:
            bad.append(f"{path}: HTTP {status}, expected {want} ({'served' if want == 200 else 'held until the game ships it'})")
        else:
            print(f"ok   {path} {status} ({'served' if want == 200 else 'held'})")
    for path in ("/", "/privacy/", "/support/", "/terms/", "/press/") + (("/testers/",) if testers_live else ()):
        try:
            status, _, body = get(base, path)
        except OSError as e:
            bad.append(f"{path}: no answer ({e})")
            continue
        if "<!--" in body:
            bad.append(f"{path}: serves an HTML comment: {body[body.index('<!--'):][:80]!r}")
        elif "<h1" not in body or "</main>" not in body:
            bad.append(f"{path}: page served without its <h1> or </main>: too much stripped?")
        else:
            print(f"ok   {path} carries no HTML comment")

    # 18.10: the live headers are exactly what src/security.js builds (the one
    # list, read through node so there is no second copy here).
    expected = json.loads(subprocess.run(
        ["node", "--input-type=module", "-e",
         "import('" + (pathlib.Path(__file__).resolve().parent.parent / "src/security.js").as_uri()
         + "').then(m => console.log(JSON.stringify(m.SECURITY_HEADERS)))"],
        capture_output=True, text=True, check=True).stdout)
    for path in ("/", "/style.css", "/privacy/", "/api/subscribe", "/index.html"):
        try:
            status, headers, _ = get(base, path)
        except OSError as e:
            bad.append(f"{path}: no answer ({e})")
            continue
        wrong = [k for k, v in expected.items() if headers.get(k.lower()) != v]
        if wrong:
            bad.append(f"{path} (HTTP {status}): security headers differ from src/security.js: {', '.join(wrong)}")
        else:
            print(f"ok   {path} security headers match src/security.js")

    # Story 6.17 release gate (pm-release): once the age screen is described, the live /privacy/ must say so.
    feats = json.loads((pathlib.Path(__file__).resolve().parent.parent / "src/features.json").read_text())
    if feats.get("age_screen"):
        try:
            status, _, body = get(base, "/privacy/")
            if "date of birth" not in body:
                bad.append("/privacy/ does not yet describe the age question (6.17 must not reach a store before it does)")
            else:
                print("ok   /privacy/ describes the age question (6.17)")
        except OSError as e:
            bad.append(f"/privacy/: no answer ({e})")

    domain = SUPPORT_EMAIL.split("@", 1)[1]
    mx = subprocess.run(["dig", "+short", "MX", domain], capture_output=True, text=True).stdout.strip()
    if not mx:
        bad.append(f"{domain} has no MX record: mail to {SUPPORT_EMAIL} would bounce (turn on Email Routing)")
    else:
        print(f"ok   {domain} MX: {mx.splitlines()[0]}")

    if bad:
        print("live check FAILED (Story 18.9):")
        for b in bad:
            print("  " + b)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "https://sortinggeography.com"))
