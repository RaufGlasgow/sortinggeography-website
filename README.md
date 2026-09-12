# sortinggeography.com

The marketing website for **Sorting Geography** — a daily geography game for iPhone
and Android. Static HTML, no build step, no framework.

**This repo is PUBLIC on purpose.** Public repositories get unlimited free GitHub
Actions minutes; private ones bill against a monthly allowance. Keeping the website
here and the game private means the site's CI costs nothing to run.

Nothing in this repo comes from the game repo except one generated file — see below.

## Layout

| Path | What |
| --- | --- |
| `index.html` | Landing page |
| `privacy.html` | Privacy policy (**draft** — must be finalised against the shipping build before store submission) |
| `credits.html` | **Generated.** Data-source attribution for every measure in the game |
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
wrangler secret put RESEND_API_KEY               # from resend.com, same account as Sorting History
wrangler deploy
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
