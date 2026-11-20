// Every page as the REAL worker sends it (Story 18.9c). Starts `wrangler dev`
// (workerd, the same runtime and HTMLRewriter as Cloudflare; local only, no
// account, nothing deployed), fetches each served page as a browser would, and
// checks:
//   - no '<!--' and no '-->' is left anywhere in what is sent;
//   - the page equals its source minus its comments, built here WITHOUT any
//     regex (split on '<!--', cut at '-->'), plus only the two attributes the
//     worker stamps on <html>. scripts/check_comments.py guarantees that
//     method is right: no '<!--' or '-->' inside a script, style or attribute;
//   - the <h1> and </main> survive.
// Run: node --test scripts/test_served.mjs   (needs `wrangler` on PATH, or
// WRANGLER="npx --yes wrangler@4.74.0").
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { spawn } from 'node:child_process';
import { createServer } from 'node:net';
import { fileURLToPath } from 'node:url';
import { SECURITY_HEADERS } from '../src/security.js';

const SITE = new URL('../', import.meta.url);
const NOT_SERVED = new Set(['docs', 'src', 'scripts', 'node_modules', '.git', '.github', '.wrangler', 'functions']);
// Story 20.3c: what .assetsignore lists is never uploaded, so it must 404.
const IGNORED = new Set(readFileSync(new URL('.assetsignore', SITE), 'utf8').split('\n')
  .map((l) => l.trim().replace(/^\/|\/$/g, '')).filter((l) => l && !l.startsWith('#')));
function servedPages(dir = '') {
  return readdirSync(new URL(dir || '.', SITE), { withFileTypes: true }).flatMap((e) => {
    const rel = dir + e.name;
    if (e.isDirectory()) return NOT_SERVED.has(e.name) || IGNORED.has(e.name) || e.name.startsWith('.') ? [] : servedPages(rel + '/');
    return e.name.endsWith('.html') ? [rel] : [];
  });
}

async function freePort() {
  return new Promise((resolve) => {
    const s = createServer().listen(0, '127.0.0.1', () => { const { port } = s.address(); s.close(() => resolve(port)); });
  });
}

let dev;
let base;
let log = '';

before(async () => {
  const port = await freePort();
  base = `http://127.0.0.1:${port}`;
  const cmd = (process.env.WRANGLER || 'wrangler').split(' ');
  dev = spawn(cmd[0], [...cmd.slice(1), 'dev', '--ip', '127.0.0.1', '--port', String(port), '--log-level', 'warn'],
    // detached: wrangler gets its own process group, so after() can stop
    // npx, wrangler AND workerd together. Killing only npx left workerd
    // holding the pipes open on GitHub's runner and the job never ended.
    { cwd: fileURLToPath(SITE), env: { ...process.env, WRANGLER_SEND_METRICS: 'false', CI: '1' },
      stdio: ['ignore', 'pipe', 'pipe'], detached: true });
  dev.stdout.on('data', (d) => { log += d; });
  dev.stderr.on('data', (d) => { log += d; });
  const deadline = Date.now() + 90_000;
  for (;;) {
    if (dev.exitCode !== null) throw new Error(`wrangler dev exited ${dev.exitCode}:\n${log}`);
    try {
      const r = await fetch(base + '/robots.txt', { signal: AbortSignal.timeout(3000) });
      await r.text();
      if (r.ok) break;
    } catch {}
    if (Date.now() > deadline) throw new Error(`wrangler dev did not start in 90 s:\n${log}`);
    await new Promise((r) => setTimeout(r, 500));
  }
});

// Stop the whole group, force it after 5 s, and let go of the pipes, so the
// test process always exits.
after(async () => {
  if (!dev) return;
  const group = (sig) => { try { process.kill(-dev.pid, sig); } catch {} };
  const gone = new Promise((r) => (dev.exitCode !== null || dev.signalCode !== null ? r() : dev.once('exit', r)));
  group('SIGTERM');
  const forced = setTimeout(() => group('SIGKILL'), 5000);
  await Promise.race([gone, new Promise((r) => setTimeout(r, 8000))]);
  clearTimeout(forced);
  group('SIGKILL');
  dev.stdout.destroy();
  dev.stderr.destroy();
  dev.unref();
});

test('the site has pages to check', () => {
  assert.ok(servedPages().length >= 6, servedPages().join(', '));
});

for (const page of servedPages()) {
  test(`${page} as the real worker sends it: no comment, nothing else changed`, async () => {
    const source = readFileSync(new URL(page, SITE), 'utf8');
    // The asset layer serves /x/index.html at /x/ and /x.html at /x (it
    // redirects the .html name), so fetch the URL a visitor ends up on.
    const path = '/' + page.replace(/index\.html$/, '').replace(/\.html$/, '');
    const res = await fetch(base + path, { headers: { Accept: 'text/html' }, redirect: 'manual',
      signal: AbortSignal.timeout(15000) });
    assert.equal(res.status, 200, `${path}: HTTP ${res.status}`);
    const sent = await res.text();
    for (const mark of ['<!--', '-->']) {
      const i = sent.indexOf(mark);
      assert.equal(i, -1, `${path}: '${mark}' is served: ${JSON.stringify(sent.slice(Math.max(0, i - 40), i + 60))}`);
    }
    const [head, ...rest] = source.split('<!--');
    const expected = head + rest.map((piece) => {
      const end = piece.indexOf('-->');
      assert.notEqual(end, -1, `${page}: a '<!--' is never closed`);
      return piece.slice(end + 3);
    }).join('');
    const stamped = /^(<!doctype html>\s*<html\b[^>]*?) data-launch="(?:pre|out)" data-now="\d+"(>)/i;
    assert.match(sent, stamped, `${path}: <html> not stamped by the worker`);
    assert.equal(sent.replace(stamped, '$1$2'), expected, `${path}: the served page is not the source minus its comments`);
    assert.ok(sent.includes('<h1'), `${path}: no <h1> left`);
    assert.ok(sent.includes('</main>') && sent.includes('</html>'), `${path}: page cut short`);
  });
}

// Story 20.3c: a page dir in .assetsignore (the tester page until both of its
// links exist) is not served by the real worker: 404, not the page.
const UNSERVED_PAGES = readdirSync(SITE, { withFileTypes: true })
  .filter((e) => e.isDirectory() && IGNORED.has(e.name) && !NOT_SERVED.has(e.name))
  .map((e) => e.name);
for (const dir of UNSERVED_PAGES) {
  test(`/${dir}/ is listed in .assetsignore, so the real worker does not serve it`, async () => {
    for (const path of [`/${dir}/`, `/${dir}/index.html`, `/${dir}`]) {
      const res = await fetch(base + path, { headers: { Accept: 'text/html' }, redirect: 'manual', signal: AbortSignal.timeout(15000) });
      const body = await res.text();
      assert.notEqual(res.status, 200, `${path}: HTTP ${res.status}`);
      assert.equal(body.includes('Become a tester'), false, `${path}: the page itself came back`);
    }
  });
}

// Story 18.5: the signup guards in the real runtime (local KV and the real
// rate-limit binding; no RESEND_API_KEY or UNSUBSCRIBE_SECRET here, so
// nothing is sent and no unsubscribe can verify).
async function post(path, body, headers = {}) {
  return fetch(base + path, { method: 'POST', body, headers, signal: AbortSignal.timeout(15000) });
}
function form(fields) {
  const f = new FormData();
  for (const [k, v] of Object.entries(fields)) f.set(k, v);
  return f;
}

test('signup: stored by the real worker; cross-site refused; the rate limit bites; unsigned unsubscribe refused', async () => {
  const first = await post('/api/subscribe', form({ email: 'served-test@example.com', lang: 'en' }));
  assert.equal(first.status, 200);
  assert.equal((await first.json()).success, true);
  assert.equal(first.headers.get('Access-Control-Allow-Origin'), null);
  assert.equal((await post('/api/subscribe', form({ email: 'x@example.com' }), { Origin: 'https://evil.example' })).status, 403);
  const un = await post('/api/unsubscribe?email=served-test%40example.com', 'List-Unsubscribe=One-Click',
    { 'Content-Type': 'application/x-www-form-urlencoded' });
  assert.equal(un.status, 403, 'no valid token: nothing deleted');
  const codes = [];
  for (let i = 0; i < 8; i += 1) codes.push((await post('/api/subscribe', form({ email: `burst${i}@example.com` }))).status);
  assert.ok(codes.includes(429), `the SUBSCRIBE_LIMIT binding refuses a burst: ${codes}`);
  assert.equal((await post('/api/send-welcome-backlog', new FormData())).status, 401, 'no EXPORT_SECRET in dev');
});

// Story 18.10: the security headers in the real runtime, on a page, a file,
// an API answer and a redirect.
test('the real worker sends every security header on pages, files, APIs and redirects', async () => {
  for (const [path, init] of [['/', {}], ['/style.css', {}], ['/api/subscribe', {}], ['/index.html', { redirect: 'manual' }],
    ['/api/csp-report', { method: 'POST', body: '{}', headers: { 'Content-Type': 'application/csp-report' } }]]) {
    const res = await fetch(base + path, { ...init, signal: AbortSignal.timeout(15000) });
    await res.arrayBuffer();
    for (const [k, v] of Object.entries(SECURITY_HEADERS)) assert.equal(res.headers.get(k), v, `${path}: ${k}`);
  }
});

// 18.10 review H1 in the real runtime: a streamed report with no length is
// refused. Just over the limit (two 5 KB chunks, no Content-Length), so the
// client has finished uploading before the worker answers and the 413 is not
// racing a half-sent body (a 1 MB upload could be cut short and surface as a
// reset or a 503 from the local proxy instead). The 1 MB case is in
// scripts/test_security.mjs, where nothing races.
test('the real worker refuses a CSP report over 8 KB sent with no Content-Length', async () => {
  const chunk = new TextEncoder().encode('x'.repeat(5000));
  const body = new ReadableStream({ start(c) { c.enqueue(chunk); c.enqueue(chunk); c.close(); } });
  const res = await fetch(base + '/api/csp-report', { method: 'POST', body, duplex: 'half', signal: AbortSignal.timeout(15000) });
  await res.arrayBuffer();
  assert.equal(res.status, 413);
});
