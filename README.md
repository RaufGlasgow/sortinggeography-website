# sortinggeography.com

The marketing website for **Sorting Geography** — a geography game for Android
and iOS. Static HTML, no build step, no framework.

**This repo is PUBLIC on purpose.** Public repositories get unlimited free GitHub
Actions minutes; private ones bill against a monthly allowance. Keeping the website
here and the game private means the site's CI costs nothing to run.

Nothing in this repo comes from the game repo except one generated file — see below.

## Layout

| Path | What |
| --- | --- |
| `index.html` | Landing page |
| `privacy/index.html` | Privacy policy, at `/privacy/` (the URL both store listings name). `/privacy.html` 301s here, because the app links to that name. Two sections are marked `if:unlock` / `if:analytics`: check them against the release build |
| `src/features.json` | Feature switches for `/privacy/`, `/support/`, `/terms/` and `/press/` (`analytics`, `analytics_switch`, `unlock`, `age_screen`, `reminders` — off until Story 12.7 ships); checked against the game repo by `scripts/build_features.py --game` |
| `support/index.html` | Support page, at `/support/` (the store listings' Support URL). Contact: support@sortinggeography.com, which needs Cloudflare Email Routing turned on for the domain |
| `terms/index.html`, `press/index.html` | Terms of use and the press kit. Counts, data version, languages and the Portugal example come from `src/facts.json` (checked against the game by `build_features.py --game`); the developer's legal name and the governing law are `<span class="todo">` placeholders, and `--game` refuses a deploy while any remains |
| `app-ads.txt` | The AdMob publisher line (the same account as Sorting History) |
| `scripts/check_store_pages.py` | CI: the support and privacy pages, app-ads.txt, robots.txt and sitemap are in place. `scripts/check_live.py` is the after-deploy half: each URL answers 200 and the support address can receive mail |
| `credits.html` | **Generated.** Data-source attribution for every measure in the game |
| `src/launch.js` | **The release moment, the one constant** (Story 18.8). Change it here, then run `python3 scripts/build_launch.py` |
| `scripts/build_launch.py` | Writes every launch date and "comes to / out now" line into the pages' `<!-- launch:... -->` regions; `--check` fails CI on a stale region or a hand-typed date or launch phrase anywhere else |
| `countdown.js` | The timer (decoration; the date is real text). Flips an open page at the moment |
| `src/pages.js` | Stamps `<html data-launch="pre|out">` on every page from the constant, so the same URL shows "Out now" at the moment with no redeploy |
| `scripts/check_platform.py` | Fails any page that names one platform alone, names the two in the wrong order, or names a device instead of saying phone or tablet (Ra'uf 2026-11-18). `scripts/test_checks.py` mutation-tests both guards |
| `style.css` | The whole stylesheet. App palette: forest green primary, ocean blue secondary, violet for rewards only |
| `scripts/build_credits.py` | Regenerates `credits.html` from the game's dataset |
| `src/worker.js` | The Cloudflare Worker: serves the pages, plus the launch-email API |
| `wrangler.toml` | Worker + static-assets + KV config |
| `.assetsignore` | What Cloudflare must NOT serve as a public file (source, config, scripts) |

## Regenerating the credits page

`credits.html` is built from the game's own dataset, so it can never drift from what
the app actually ships:

```sh
python3 scripts/build_credits.py ../Sorting-Geography/pipeline/content/dataset.json
```

Re-run it whenever the dataset version moves. This page is not decoration: World Bank
WDI, Our World in Data and GeoNames all ship under CC BY, which **requires**
attribution, so shipping the app without it is a licence breach.

## Hosting — Cloudflare Worker with static assets

Same shape as the Sorting History site, deliberately: one pattern in the family, not two.
The site is a Worker (`src/worker.js`) with `[assets]` pointing at the repo root, so the
HTML is served straight from here and the Worker only handles the few dynamic paths.

| Path | What |
| --- | --- |
| `/api/subscribe` | POST an email to the launch list (KV `LAUNCH_EMAILS`), and send the confirmation through Resend |
| `/api/unsubscribe?email=` | GET; **deletes** the address rather than flagging it |
| `/api/export-emails?key=` | GET the list as CSV; requires `EXPORT_SECRET` |
| `/index.html` | 301 to `/`, so Google never sees two URLs for one page |

The welcome email goes through **Resend**, the same provider the Sorting History site
uses — `api.resend.com`, an `RESEND_API_KEY` secret, sent fire-and-forget inside
`ctx.waitUntil` so a mail failure can never fail a signup that was already stored. If the
key is unset the address is stored and no mail is attempted.

Two deliberate differences from the Sorting History worker, each because the thing behind
it does not exist here:

- **No language auto-redirect.** That site ships `/de /pt /nl /es`; this one is
  English-only, and redirecting into directories that do not exist would 404 real
  visitors. Add it *with* the translated pages, never before them.
- **This app's palette in the mail and the unsubscribe page.** The Sorting History
  versions head and link in `#e07850`, an orange; the identity bans it outside the
  in-game reward burst, and this repo's palette check would fail on it, correctly.

### Deploying

Needs Ra'uf's Cloudflare account — `wrangler login` is an interactive browser flow and
cannot be scripted:

```sh
wrangler login                                   # once, interactive
wrangler kv namespace create LAUNCH_EMAILS       # copy the id into wrangler.toml
wrangler kv namespace create LAUNCH_EMAILS --preview
wrangler secret put EXPORT_SECRET                # any long random string
wrangler secret put UNSUBSCRIBE_SECRET           # another long random string (signs unsubscribe links)
wrangler secret put RESEND_API_KEY               # from resend.com, same account as Sorting History
npx --yes wrangler@4.74.0 deploy                 # pinned; run docs/DEPLOY-RUNBOOK.md Step 4's checks first
```

Then bind the domain. `sortinggeography.com` is already delegated to Cloudflare (same
nameservers as sortinghistory.com) but has **no A record**, so nothing is served yet.
Adding it as a Custom Domain on the Worker creates the DNS records automatically —
do `sortinggeography.com` and `www.sortinggeography.com`.

**One more account step for the mail:** the sender is `hello@sortinggeography.com`, so
`sortinggeography.com` must be added and verified as a domain in Resend (it publishes DKIM
and SPF records to add in Cloudflare DNS). Until that is done Resend will reject the send —
the signup is still stored, and the visitor is still told they are on the list, so verify
the domain before announcing the site anywhere.

## House rules

- **No gold, no orange, anywhere.** The app's identity reserves gold for a single
  in-game reward moment and bans it everywhere else. CI enforces this.
- Every page must parse and every local link must resolve. CI enforces both.
- `src/worker.js` must parse (`node --check`). CI enforces it.
- The palette check scans `src/*.js` as well as `.css` and `.html` — the worker builds a
  page's CSS inside a template literal, which would otherwise escape it. **Its hex half
  had never been able to fire** (a `\b` before `#` can only match after a word character,
  so `color: #ffd700;` was always missed); fixed and mutation-proven 2026-09-12.
- No trackers, no external fonts, no CDN.
