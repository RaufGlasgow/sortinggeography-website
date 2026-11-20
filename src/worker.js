// Sorting Geography's marketing site.
//
// A Cloudflare Worker serving the static pages plus a launch-email signup, the
// same shape as the Sorting History site (src/worker.js there) so the family has
// ONE pattern. Three deliberate differences, each because the thing behind it
// does not exist here:
//
//   • NO language auto-redirect. Sorting History ships /de /pt /nl /es pages;
//     this site is English-only today, and redirecting to directories that do
//     not exist would 404 real visitors. Add it WITH the translated pages, not
//     before them.
//   • The welcome email goes through RESEND, the same provider the Sorting
//     History site uses (api.resend.com, RESEND_API_KEY, fire-and-forget in
//     ctx.waitUntil so a mail failure never fails the signup). An earlier draft
//     of this file claimed no provider was wired in the family and left it out;
//     that was simply wrong - Ra'uf: "Sortinghistory does all the time!" - and
//     it was wrong because I had not read that site's sendWelcomeEmail.
//   • The unsubscribe page uses the APP's palette — forest green, ocean blue,
//     violet for rewards only. NO GOLD AND NO ORANGE anywhere: the identity
//     reserves gold for one in-game reward moment, and this repo's CI enforces
//     the ban (Sorting History's equivalent page uses an orange link; copying
//     it verbatim would fail the build, correctly).
//
// The release countdown (Story 18.8): every HTML page carries both launch
// states; the worker stamps <html data-launch="pre|out"> from the one constant
// in src/launch.js, so at the moment the SAME URL shows "Out now" with no
// redeploy and with JavaScript off. wrangler.toml sets run_worker_first so the
// worker sees page requests at all (otherwise static assets bypass it).

import { serveAsset } from './pages.js';
// Mail (welcome, backlog) lives in src/mail.js: workerd treats every named
// export of this main module as an entrypoint, so this file exports only the
// handler (scripts/test_served.mjs caught a constant export breaking start-up).
import { sendWelcomeEmail, handleWelcomeBacklog, isSignupKey } from './mail.js';
import { tokenValid } from './token.js';
import { withSecurityHeaders, handleCspReport } from './security.js';

export default {
  // Every response, page, file, API answer, redirect or error, leaves through
  // withSecurityHeaders (Story 18.10, src/security.js).
  async fetch(request, env, ctx) {
    return withSecurityHeaders(await route(request, env, ctx));
  },
};

async function route(request, env, ctx) {
    const url = new URL(request.url);

    if (url.pathname === '/api/csp-report') {
      if (request.method === 'POST') return handleCspReport(request);
      return new Response('Method not allowed', { status: 405 });
    }

    if (url.pathname === '/api/subscribe') {
      if (request.method === 'POST') return handleSubscribe(request, env, ctx);
      return new Response('Method not allowed', { status: 405 });
    }

    if (url.pathname === '/api/unsubscribe') {
      // GET only shows a confirm button: link scanners that open every URL in
      // a message must not unsubscribe anyone (18.5 review E2). POST deletes:
      // the button, and the mail client's own one-click (RFC 8058, the
      // List-Unsubscribe-Post header in src/email.js). Both need the token.
      if (request.method === 'GET') return handleUnsubscribe(request, env, false);
      if (request.method === 'POST') return handleUnsubscribe(request, env, true);
      return new Response('Method not allowed', { status: 405 });
    }

    if (url.pathname === '/api/send-welcome-backlog') {
      if (request.method === 'POST') return handleWelcomeBacklog(request, env);
      return new Response('Method not allowed', { status: 405 });
    }

    if (url.pathname === '/api/export-emails') {
      if (request.method === 'GET') return handleExport(request, env);
      return new Response('Method not allowed', { status: 405 });
    }

    // 301 /index.html -> / so Google never sees two URLs for one page.
    if (url.pathname === '/index.html') {
      return Response.redirect(`${url.origin}/`, 301);
    }

    // 301 /privacy.html -> /privacy/ (Story 18.9). The page moved to the URL
    // the store listings name; the app's kPrivacyUrl and any old link still
    // point at the .html name and must keep working.
    if (url.pathname === '/privacy.html') {
      return Response.redirect(`${url.origin}/privacy/`, 301);
    }

    return serveAsset(request, env, Date.now());
}


// The signup (18.5 review E1). Before the Resend key goes in, the route must
// not let anyone use hello@ to mail an inbox over and over:
//   - a cross-site Origin is refused (our form posts from our own pages);
//   - SUBSCRIBE_LIMIT (wrangler.toml [[ratelimits]]) caps signups per IP;
//     without the binding the route refuses, rather than running unguarded;
//   - an address already on the list keeps its record and is sent nothing.
// The answer is the same whether the address was new or not.
const OWN_ORIGINS = new Set(['https://sortinggeography.com', 'https://www.sortinggeography.com']);
const JSON_HEADERS = { 'Content-Type': 'application/json' };
const ON_LIST = JSON.stringify({ success: true, message: 'You are on the list. Check your email.' });

async function handleSubscribe(request, env, ctx) {
  const origin = request.headers.get('Origin');
  if (origin && !OWN_ORIGINS.has(origin)) {
    return new Response(JSON.stringify({ success: false, error: 'Not allowed.' }), { status: 403, headers: JSON_HEADERS });
  }
  if (!env.SUBSCRIBE_LIMIT) {
    return new Response(JSON.stringify({ success: false, error: 'Signups are not open right now.' }),
      { status: 503, headers: JSON_HEADERS });
  }
  const ip = request.headers.get('CF-Connecting-IP') || 'unknown';
  const { success: allowed } = await env.SUBSCRIBE_LIMIT.limit({ key: ip });
  if (!allowed) {
    return new Response(JSON.stringify({ success: false, error: 'Too many tries. Please wait a minute.' }),
      { status: 429, headers: JSON_HEADERS });
  }

  try {
    const formData = await request.formData();
    const email = formData.get('email')?.toLowerCase().trim();

    if (!email || !isValidEmail(email)) {
      return new Response(
        JSON.stringify({ success: false, error: 'That does not look like an email address.' }),
        { status: 400, headers: JSON_HEADERS },
      );
    }
    // The page's language (a hidden field; /de/ pages will send "de"). Kept as
    // given, so a signup made before its language's email template exists is
    // still known; src/email.js falls back to English until then.
    const rawLang = String(formData.get('lang') || 'en');
    const lang = /^[a-z]{2}(?:-[A-Za-z0-9]{2,4})?$/.test(rawLang) ? rawLang : 'en';

    if (await env.LAUNCH_EMAILS.get(email)) {
      return new Response(ON_LIST, { status: 200, headers: JSON_HEADERS });
    }

    // Exactly what privacy/index.html says is kept (18.5 review E3); the
    // welcome's date or failed tries are added by src/mail.js.
    await env.LAUNCH_EMAILS.put(
      email,
      JSON.stringify({
        email,
        lang,
        timestamp: new Date().toISOString(),
        source: request.headers.get('Referer') || 'direct',
      }),
    );

    // Fire-and-forget: a mail failure must never fail a signup that was stored.
    ctx.waitUntil(sendWelcomeEmail(email, lang, env));

    return new Response(ON_LIST, { status: 200, headers: JSON_HEADERS });
  } catch (error) {
    return new Response(
      JSON.stringify({ success: false, error: 'Something went wrong. Please try again.' }),
      { status: 500, headers: JSON_HEADERS },
    );
  }
}

const HTML = { 'Content-Type': 'text/html; charset=utf-8' };
const NOT_VALID = 'This link is not valid. To be removed, email support@sortinggeography.com.';

async function handleUnsubscribe(request, env, remove) {
  const url = new URL(request.url);
  const email = url.searchParams.get('email')?.toLowerCase().trim();
  const token = url.searchParams.get('t') || '';
  if (!(await tokenValid(email, token, env.UNSUBSCRIBE_SECRET))) {
    return new Response(unsubscribePage(NOT_VALID, false), { status: 403, headers: HTML });
  }
  if (!remove) {
    return new Response(unsubscribePage('Remove this address from the list?', false, url.pathname + url.search),
      { status: 200, headers: HTML });
  }
  try {
    await env.LAUNCH_EMAILS.delete(email);
    return new Response(unsubscribePage('You are unsubscribed. We will not write to you again.', true),
      { status: 200, headers: HTML });
  } catch (error) {
    return new Response(unsubscribePage('Something went wrong. Please try again later.', false),
      { status: 500, headers: HTML });
  }
}

// The app palette, light and dark, and nothing else: forest green, ocean blue,
// parchment, violet. No gold, no orange (CI enforces it).
function unsubscribePage(message, success, confirmAction = null) {
  return `<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Unsubscribe &mdash; Sorting Geography</title>
<style>
  :root { --green:#103A22; --ocean:#1c4f6b; --violet:#4c3a75; --parchment:#f5f1e6;
          --card:#fffdf7; --ink:#16150f; --rule:#d9d2bf; }
  @media (prefers-color-scheme: dark) {
    :root { --green:#18552F; --ocean:#2b6c8e; --violet:#6a52a3; --parchment:#000000;
            --card:#131310; --ink:#f3efe2; --rule:#2e2c24; }
  }
  body { font: 16px/1.6 -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
         background: var(--parchment); color: var(--ink); margin: 0;
         display: flex; align-items: center; justify-content: center; min-height: 100vh; }
  .card { background: var(--card); border: 1px solid var(--rule); border-radius: 20px;
          padding: 2rem; max-width: 26rem; text-align: center; }
  h1 { font-size: 1.25rem; margin: 0 0 1rem; color: ${success ? 'var(--green)' : 'var(--ocean)'}; }
  p { margin: 0 0 .75rem; }
  a { color: var(--ocean); }
  button { font: inherit; padding: .6rem 1.4rem; border: 0; border-radius: 999px;
           background: var(--green); color: #fff; cursor: pointer; margin: 0 0 .75rem; }
</style>
</head><body>
<div class="card">
  <h1>${success ? 'Unsubscribed' : confirmAction ? 'Unsubscribe' : 'Not done'}</h1>
  <p>${message}</p>
  ${confirmAction ? `<form method="post" action="${confirmAction.replace(/&/g, '&amp;').replace(/"/g, '&quot;')}"><button type="submit">Unsubscribe</button></form>` : ''}
  <p><a href="/">Back to Sorting Geography</a></p>
</div>
</body></html>`;
}

async function handleExport(request, env) {
  const url = new URL(request.url);
  const key = url.searchParams.get('key');

  // A missing secret must FAIL, never wave the request through — an unset
  // EXPORT_SECRET would otherwise match a missing key and publish the list.
  if (!env.EXPORT_SECRET || !key || key !== env.EXPORT_SECRET) {
    return new Response('Unauthorized', { status: 401 });
  }

  try {
    const rows = [];
    let cursor = null;

    do {
      const list = await env.LAUNCH_EMAILS.list(cursor ? { cursor } : {});
      for (const entry of list.keys) {
        if (!isSignupKey(entry.name)) continue; // the daily send counter (src/mail.js)
        const value = await env.LAUNCH_EMAILS.get(entry.name);
        if (!value) continue;
        try {
          const parsed = JSON.parse(value);
          rows.push([
            escapeCSV(parsed.email),
            escapeCSV(parsed.timestamp),
            escapeCSV(parsed.source),
          ].join(','));
        } catch {
          /* skip unparseable */
        }
      }
      cursor = list.list_complete ? null : list.cursor;
    } while (cursor);

    const csv = [['email', 'timestamp', 'source'].join(','), ...rows].join('\n');
    return new Response(csv, {
      status: 200,
      headers: {
        'Content-Type': 'text/csv',
        'Content-Disposition': 'attachment; filename="launch-emails.csv"',
      },
    });
  } catch (error) {
    return new Response('Export failed: ' + error.message, { status: 500 });
  }
}

function escapeCSV(value) {
  if (value == null) return '';
  const str = String(value);
  return /[",\n]/.test(str) ? '"' + str.replace(/"/g, '""') + '"' : str;
}

function isValidEmail(email) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
}
