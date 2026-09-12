# Deploy runbook — sortinggeography.com

**Written 2026-09-12. Every command was checked against the wrangler actually installed on
Ra'uf's machine (4.74.0) using its own `--help`, and every dashboard/DNS step against the
current Cloudflare and Resend documentation on that date. Nothing here is from memory.**

## Where this came from, and what was stale in it

Ra'uf asked whether there was a saved process from Sorting History. **There is** —
`sortinghistory-website/docs/tech-spec-email-capture.md` plus three stories under
`docs/stories/MKT-001.*`. What carries over unchanged, and what does not:

| from the saved spec | status |
|---|---|
| KV namespace named `LAUNCH_EMAILS`, key = email, value = JSON metadata | **carried over** |
| `/api/subscribe` validates, stores, returns JSON; duplicates are idempotent 200s | **carried over** |
| `/api/export-emails?key=` behind a secret, returns CSV | **carried over** |
| Free-tier headroom: KV 1,000 writes/day, 100,000 reads/day, 1 GB; Workers 100,000 req/day | **carried over** — a pre-launch list will never approach it |
| Rollback: revert the form to a mailto link | **carried over** |
| **Cloudflare PAGES Functions, `wrangler pages dev`, "bind KV to Pages project"** | **STALE.** The Sorting History site has since migrated to a **Worker with static assets** (`main = "src/worker.js"` + `[assets]`), which is what this repo mirrors. Following the saved spec literally would build the previous architecture. |
| **Hash the IP for duplicate detection** | **NOT carried over, deliberately.** The shipped Sorting History worker stores no IP at all, and neither does this one — the email is the KV key, so duplicates need no second signal. Less data is the better answer. |
| The domain, the certificate and the Resend setup | **ABSENT from the saved spec.** That is the part below, and the part Ra'uf was missing. |

## Before you start

- `wrangler` is already installed: **4.74.0** (`/opt/homebrew/bin/wrangler`). 4.131.1 exists;
  every command below is verified against 4.74.0, so upgrading is optional. If you do upgrade
  (`brew upgrade wrangler` [UNVERIFIED — not run]), re-check `wrangler kv namespace --help`,
  because that command's spelling has changed across major versions before.
- `sortinggeography.com` is **already bought and already delegated to Cloudflare** — its
  nameservers are `magdalena.ns.cloudflare.com` and `ram.ns.cloudflare.com`, the same pair as
  `sortinghistory.com`, so it is in the same account. It currently has **no A record**: nothing
  is served. Verified with `dig` on 2026-09-12.
- `wrangler deploy --dry-run` already passes in this repo: config valid, both bindings resolve,
  8.10 KiB upload. So only the account steps remain.

---

## Step 1 — Log in (only Ra'uf can do this)

```sh
wrangler login
```

Opens a browser for Cloudflare OAuth. It cannot be scripted, which is why it is step one and
why it is his.

Check it took:

```sh
wrangler whoami
```

## Step 2 — Create the two KV namespaces

`--binding` plus `--update-config` writes the returned id straight into `wrangler.toml`, which
is why the file ships with `PLACEHOLDER_FILL_ON_FIRST_DEPLOY` rather than a hand-copied id.

```sh
wrangler kv namespace create LAUNCH_EMAILS --binding LAUNCH_EMAILS --update-config
wrangler kv namespace create LAUNCH_EMAILS --binding LAUNCH_EMAILS --update-config --preview
```

Then **read `wrangler.toml` and confirm both `id` and `preview_id` are real ids**, not the
placeholder. If `--update-config` did not write them (it is newer than some wrangler builds),
paste them in by hand — the command prints them.

## Step 3 — Set the two secrets

```sh
wrangler secret put EXPORT_SECRET      # paste a long random string; this guards the CSV export
wrangler secret put RESEND_API_KEY     # from resend.com — the same account Sorting History uses
```

Each prompts for the value on stdin and stores it encrypted; neither is ever written to the repo.

`EXPORT_SECRET` is load-bearing: the worker refuses the export outright when it is unset
(`if (!env.EXPORT_SECRET || ...)`), so a missing secret cannot be matched by a missing key and
publish the list.

## Step 4 — Deploy

```sh
wrangler deploy
```

`wrangler.toml` already carries both custom domains:

```toml
[[routes]]
pattern = "sortinggeography.com"
custom_domain = true

[[routes]]
pattern = "www.sortinggeography.com"
custom_domain = true
```

With `custom_domain = true` **Cloudflare creates the DNS records and issues the certificates
itself** — there is no dashboard step. `www` is listed separately on purpose: Cloudflare matches
a custom domain exactly, so a Worker attached to `sortinggeography.com` does **not** receive
`www.sortinggeography.com`.

The dashboard equivalent, if it is ever needed:
**Workers & Pages → the Worker → Settings → Domains & Routes → Add → Custom Domain.**

Then check it:

```sh
dig +short sortinggeography.com A          # should now return Cloudflare addresses
curl -sI https://sortinggeography.com/ | head -1
curl -sI https://sortinggeography.com/index.html | head -1   # expect 301 to /
```

The certificate can take a few minutes on a brand-new hostname.

## Step 5 — Verify the sending domain in Resend

**Do this before the site is announced anywhere.** Until it is done Resend rejects the send
while the visitor is still told they are on the list — the signup is stored, so nothing is
lost, but the confirmation never arrives.

The sender is `hello@sortinggeography.com`, matching `hello@sortinghistory.com`.

1. **resend.com → Domains → Add Domain →** `sortinggeography.com`.
2. Resend shows three records. Add them in **Cloudflare → sortinggeography.com → DNS**:

| Type | Name | Value | Notes |
|---|---|---|---|
| `MX` | `send` | the mail server Resend shows | Priority `10`, TTL Auto |
| `TXT` | `send` | Resend's SPF value | TTL Auto |
| `TXT` | `resend._domainkey` | Resend's DKIM value | TTL Auto, **Proxy status: DNS only** |

3. **Two gotchas, both from Resend's own Cloudflare guide:**
   - **Strip the domain from the record name.** Resend displays `send.sortinggeography.com`;
     paste only **`send`**. Cloudflare appends the zone itself, and pasting the full name
     creates `send.sortinggeography.com.sortinggeography.com`.
   - **DKIM must be DNS-only (grey cloud), not proxied**, or Cloudflare returns error
     **code 1004**.
4. Back in Resend, click **Verify DNS Records**. Usually minutes; Resend allows up to 72 hours.

Resend recommends a subdomain sender (`updates.example.com`) to isolate sending reputation.
**Not adopted**, to match Sorting History — noted so the choice is visible rather than assumed.

## Step 6 — Prove the whole path end to end

```sh
# a real signup
curl -s -X POST https://sortinggeography.com/api/subscribe \
  -F 'email=rauf+launchtest@example.com' | python3 -m json.tool

# it is stored
wrangler kv key list --binding LAUNCH_EMAILS | head

# the export refuses a wrong key, and works with the right one
curl -sI 'https://sortinggeography.com/api/export-emails?key=wrong' | head -1   # expect 401
curl -s  "https://sortinggeography.com/api/export-emails?key=$EXPORT_SECRET" | head -3

# unsubscribing DELETES the address rather than flagging it
curl -s 'https://sortinggeography.com/api/unsubscribe?email=rauf+launchtest@example.com' \
  | grep -o 'Unsubscribed'
wrangler kv key list --binding LAUNCH_EMAILS | grep -c launchtest   # expect 0
```

Check the confirmation email actually arrived at a real address — a 200 from `/api/subscribe`
proves only that the address was **stored**. The send is fire-and-forget inside `ctx.waitUntil`
precisely so a mail failure never fails a stored signup, which means a broken Resend setup is
**silent on the response**. This is the one step that cannot be checked from a status code.

## Step 7 — Regenerate the credits page at the current dataset

Required, not decoration: World Bank WDI, Our World in Data and GeoNames all ship under CC BY,
which obliges attribution.

```sh
python3 scripts/build_credits.py ../Sorting-Geography/pipeline/content/dataset.json
```

## Still owed on this site, separately from deploying it

- `privacy.html` is a **draft** and must be finalised against the shipping build before store
  submission. It now discloses the signup, the storage, that Resend sees the address, and that
  unsubscribing deletes it.
- No app screenshots yet. Sorting History has `docs/stories/MKT-002.1.story.app-screenshots-for-website.md`
  and `scripts/capture-screenshots.sh` for exactly this — reuse it rather than inventing one,
  and remember no simulator may be touched without Ra'uf's say-so.
