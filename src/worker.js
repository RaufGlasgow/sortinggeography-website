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
//   • NO welcome email. Sorting History sends one on signup through its mail
//     provider; no provider is wired here, so a signup is stored and nothing is
//     claimed to the visitor that does not happen.
//   • The unsubscribe page uses the APP's palette — forest green, ocean blue,
//     violet for rewards only. NO GOLD AND NO ORANGE anywhere: the identity
//     reserves gold for one in-game reward moment, and this repo's CI enforces
//     the ban (Sorting History's equivalent page uses an orange link; copying
//     it verbatim would fail the build, correctly).

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    if (url.pathname === '/api/subscribe') {
      if (request.method === 'OPTIONS') return handleCORS();
      if (request.method === 'POST') return handleSubscribe(request, env);
      return new Response('Method not allowed', { status: 405 });
    }

    if (url.pathname === '/api/unsubscribe') {
      if (request.method === 'GET') return handleUnsubscribe(request, env);
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

    return env.ASSETS.fetch(request);
  },
};

function handleCORS() {
  return new Response(null, {
    headers: {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'POST, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type',
    },
  });
}

async function handleSubscribe(request, env) {
  const headers = {
    'Content-Type': 'application/json',
    'Access-Control-Allow-Origin': '*',
  };

  try {
    const formData = await request.formData();
    const email = formData.get('email')?.toLowerCase().trim();

    if (!email || !isValidEmail(email)) {
      return new Response(
        JSON.stringify({ success: false, error: 'That does not look like an email address.' }),
        { status: 400, headers },
      );
    }

    await env.LAUNCH_EMAILS.put(
      email,
      JSON.stringify({
        email,
        timestamp: new Date().toISOString(),
        source: request.headers.get('Referer') || 'direct',
        userAgent: request.headers.get('User-Agent') || 'unknown',
      }),
    );

    // Says only what actually happens: the address is stored, and it is used
    // once. No welcome email is sent, so none is promised.
    return new Response(
      JSON.stringify({ success: true, message: 'Thank you. We will write once, when it ships.' }),
      { status: 200, headers },
    );
  } catch (error) {
    return new Response(
      JSON.stringify({ success: false, error: 'Something went wrong. Please try again.' }),
      { status: 500, headers },
    );
  }
}

async function handleUnsubscribe(request, env) {
  const url = new URL(request.url);
  const email = url.searchParams.get('email')?.toLowerCase().trim();

  if (!email) {
    return new Response(unsubscribePage('No email address was given.', false), {
      status: 400,
      headers: { 'Content-Type': 'text/html' },
    });
  }

  try {
    await env.LAUNCH_EMAILS.delete(email);
    return new Response(
      unsubscribePage('You are unsubscribed. We will not write to you again.', true),
      { status: 200, headers: { 'Content-Type': 'text/html' } },
    );
  } catch (error) {
    return new Response(unsubscribePage('Something went wrong. Please try again later.', false), {
      status: 500,
      headers: { 'Content-Type': 'text/html' },
    });
  }
}

// The app palette, light and dark, and nothing else: forest green, ocean blue,
// parchment, violet. No gold, no orange (CI enforces it).
function unsubscribePage(message, success) {
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
</style>
</head><body>
<div class="card">
  <h1>${success ? 'Unsubscribed' : 'Not done'}</h1>
  <p>${message}</p>
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
