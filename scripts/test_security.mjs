// Security headers and the report-only CSP (Story 18.10). Plain Node:
// `node --test scripts/test_security.mjs`. Drives the real worker with fakes.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';

import worker from '../src/worker.js';
import { SECURITY_HEADERS, CSP_REPORT_ONLY, CSP_REPORT_LOG_CHARS, REPORT_MAX_BYTES, stripQueries } from '../src/security.js';

const SITE = new URL('../', import.meta.url);
const ORIGIN = 'https://sortinggeography.com';
const NOT_SERVED = new Set(['docs', 'src', 'scripts', 'node_modules', '.git', '.github', '.wrangler', 'functions']);
const IGNORED = new Set(readFileSync(new URL('.assetsignore', SITE), 'utf8').split('\n')
  .map((l) => l.trim().replace(/^\/|\/$/g, '')).filter((l) => l && !l.startsWith('#')));

function served(ext, dir = '') {
  return readdirSync(new URL(dir || '.', SITE), { withFileTypes: true }).flatMap((e) => {
    const rel = dir + e.name;
    if (e.isDirectory()) {
      return NOT_SERVED.has(e.name) || IGNORED.has(e.name) || e.name.startsWith('.') ? [] : served(ext, rel + '/');
    }
    return rel.endsWith(ext) && !IGNORED.has(e.name) ? [rel] : [];
  });
}

const kv = () => { const m = new Map(); return { m, get: async (k) => m.get(k) ?? null, put: async (k, v) => m.set(k, v),
  delete: async (k) => m.delete(k), list: async () => ({ keys: [], list_complete: true }) }; };
function env(extra = {}) {
  return {
    LAUNCH_EMAILS: kv(), SUBSCRIBE_LIMIT: { limit: async () => ({ success: true }) },
    ASSETS: { fetch: async (req) => {
      const path = new URL(req.url).pathname;
      if (path.endsWith('.css')) return new Response('body{}', { headers: { 'Content-Type': 'text/css' } });
      if (path.endsWith('.png')) return new Response('png', { headers: { 'Content-Type': 'image/png' } });
      if (path === '/missing/') return new Response('not found', { status: 404, headers: { 'Content-Type': 'text/html' } });
      return new Response('<!doctype html><html><body><h1>x</h1></body></html>', { headers: { 'Content-Type': 'text/html' } });
    } },
    ...extra,
  };
}
const ctx = () => ({ waitUntil() {} });
globalThis.HTMLRewriter = class { onDocument() { return this; } on() { return this; } transform(r) { return r; } };

const ROUTES = [
  ['a page', 'GET', '/', { Accept: 'text/html' }],
  ['a stylesheet', 'GET', '/style.css', { Accept: 'text/css' }],
  ['an image', 'GET', '/images/google-play-badge.png', { Accept: 'image/*' }],
  ['a 404 page', 'GET', '/missing/', { Accept: 'text/html' }],
  ['the /index.html redirect', 'GET', '/index.html', {}],
  ['the /privacy.html redirect', 'GET', '/privacy.html', {}],
  ['a signup GET (405)', 'GET', '/api/subscribe', {}],
  ['an unsigned unsubscribe (403)', 'GET', '/api/unsubscribe?email=x%40example.com', {}],
  ['the backlog GET (405)', 'GET', '/api/send-welcome-backlog', {}],
  ['the export without a key (401)', 'GET', '/api/export-emails', {}],
  ['a CSP report (204)', 'POST', '/api/csp-report', { 'Content-Type': 'application/csp-report' }],
];

for (const [name, method, path, headers] of ROUTES) {
  test(`every header on ${name}`, async () => {
    const init = { method, headers };
    if (method === 'POST') init.body = '{"csp-report":{}}';
    const res = await worker.fetch(new Request(ORIGIN + path, init), env(), ctx());
    for (const [k, v] of Object.entries(SECURITY_HEADERS)) assert.equal(res.headers.get(k), v, `${path}: ${k}`);
  });
}

test('a signup POST (the JSON answer) carries every header', async () => {
  const body = new FormData();
  body.set('email', 'x@example.com');
  const res = await worker.fetch(new Request(`${ORIGIN}/api/subscribe`, { method: 'POST', body }), env(), ctx());
  assert.equal(res.status, 200);
  for (const [k, v] of Object.entries(SECURITY_HEADERS)) assert.equal(res.headers.get(k), v, k);
});

test('the headers are exactly the agreed values', () => {
  assert.deepEqual(Object.keys(SECURITY_HEADERS).sort(), ['Content-Security-Policy', 'Content-Security-Policy-Report-Only',
    'Referrer-Policy', 'Strict-Transport-Security', 'X-Content-Type-Options', 'X-Frame-Options']);
  assert.equal(SECURITY_HEADERS['Strict-Transport-Security'], 'max-age=31536000', 'no includeSubDomains yet');
  assert.equal(SECURITY_HEADERS['Referrer-Policy'], 'strict-origin-when-cross-origin');
  assert.equal(SECURITY_HEADERS['X-Content-Type-Options'], 'nosniff');
  assert.equal(SECURITY_HEADERS['X-Frame-Options'], 'SAMEORIGIN');
  assert.equal(SECURITY_HEADERS['Content-Security-Policy'], "frame-ancestors 'self'", 'only frame-ancestors is enforced yet');
});

function directives() {
  return Object.fromEntries(CSP_REPORT_ONLY.split(';').map((d) => d.trim().split(/\s+/)).map(([k, ...v]) => [k, v]));
}

test('the report-only CSP: scripts self only, no wildcards, reports to /api/csp-report', () => {
  const d = directives();
  assert.deepEqual(d['script-src'], ["'self'"], 'no unsafe-inline or unsafe-eval for scripts');
  assert.deepEqual(d['default-src'], ["'self'"]);
  assert.deepEqual(d['object-src'], ["'none'"]);
  assert.deepEqual(d['frame-ancestors'], ["'self'"]);
  assert.deepEqual(d['report-uri'], ['/api/csp-report']);
  for (const [k, v] of Object.entries(d)) {
    for (const s of v) assert.doesNotMatch(s, /^\*|^https?:$|^data:$|^https:\/\//, `${k} ${s}: the site loads nothing from elsewhere`);
  }
});

// ---- what the site actually loads must be what the CSP allows -----------------
const SAME = (u) => !/^[a-z][a-z0-9+.-]*:/i.test(u) && !u.startsWith('//') || u.startsWith(ORIGIN + '/');

for (const page of served('.html')) {
  test(`${page}: no inline <script>, and every resource it loads is our own`, () => {
    const t = readFileSync(new URL(page, SITE), 'utf8').replace(/<!--[\s\S]*?-->/g, '');
    for (const m of t.matchAll(/<script\b([^>]*)>/gi)) {
      const attrs = m[1];
      const type = (attrs.match(/\btype\s*=\s*["']?([^"'\s>]+)/i) || [])[1];
      const data = type && !/javascript|module/i.test(type);           // JSON-LD etc. never runs
      assert.ok(/\bsrc\s*=/.test(attrs) || data, `${page}: inline <script${attrs}> would need 'unsafe-inline'`);
    }
    assert.doesNotMatch(t, /\son[a-z]+\s*=/i, `${page}: an inline on…= handler would need 'unsafe-inline'`);
    assert.doesNotMatch(t, /href\s*=\s*["']\s*javascript:/i, `${page}: a javascript: URL`);
    const loads = [
      ...[...t.matchAll(/<(?:script|img|iframe|source|embed|audio|video|track)\b[^>]*\bsrc\s*=\s*["']([^"']+)/gi)].map((m) => m[1]),
      ...[...t.matchAll(/<link\b[^>]*\brel\s*=\s*["'][^"']*(?:stylesheet|preload|icon|manifest)[^"']*["'][^>]*\bhref\s*=\s*["']([^"']+)/gi)].map((m) => m[1]),
      ...[...t.matchAll(/<form\b[^>]*\baction\s*=\s*["']([^"']+)/gi)].map((m) => m[1]),
      ...[...t.matchAll(/url\(\s*["']?([^"')]+)/gi)].map((m) => m[1]),
    ];
    for (const u of loads) assert.ok(SAME(u), `${page} loads ${u}, which the CSP does not allow`);
    assert.doesNotMatch(t, /<(?:iframe|object|embed)\b/i, `${page}: frames and objects are 'none'`);
  });
}

for (const file of [...served('.js'), ...served('.css')]) {
  test(`${file}: fetches and url()s are our own`, () => {
    const t = readFileSync(new URL(file, SITE), 'utf8');
    for (const m of t.matchAll(/(?:fetch|import|importScripts)\(\s*["'`]([^"'`]+)/g)) assert.ok(SAME(m[1]), `${file}: ${m[1]}`);
    for (const m of t.matchAll(/url\(\s*["']?([^"')]+)/g)) assert.ok(SAME(m[1]), `${file}: ${m[1]} (img-src and font-src are 'self' only)`);
    assert.doesNotMatch(t, /\beval\(|new Function\(/, `${file}: eval would need 'unsafe-eval'`);
  });
}

// ---- the report endpoint -------------------------------------------------------
test('a CSP report is logged (at most 2000 characters), stored nowhere, answered 204', async () => {
  const e = env();
  const logs = [];
  const real = console.log;
  console.log = (...a) => logs.push(a.join(' '));
  try {
    const res = await worker.fetch(new Request(`${ORIGIN}/api/csp-report`, { method: 'POST', body: 'x'.repeat(5000).slice(0, REPORT_MAX_BYTES - 10),
      headers: { 'Content-Type': 'application/csp-report' } }), e, ctx());
    assert.equal(res.status, 204);
  } finally { console.log = real; }
  assert.equal(logs.length, 1);
  assert.ok(logs[0].length <= CSP_REPORT_LOG_CHARS + 20, `logged ${logs[0].length} characters`);
  assert.equal(e.LAUNCH_EMAILS.m.size, 0, 'nothing stored');
});

test('a CSP report over 8 KB is refused unread; GET is 405', async () => {
  const big = await worker.fetch(new Request(`${ORIGIN}/api/csp-report`, { method: 'POST', body: 'x',
    headers: { 'Content-Length': '9000' } }), env(), ctx());
  assert.equal(big.status, 413);
  assert.equal((await worker.fetch(new Request(`${ORIGIN}/api/csp-report`), env(), ctx())).status, 405);
});

// ---- review H1 / H2 ---------------------------------------------------------------
function logged(fn) {
  const logs = [];
  const real = console.log;
  console.log = (...a) => logs.push(a.join(' '));
  return fn().finally(() => { console.log = real; }).then((r) => [r, logs]);
}

test('a report over 8 KB with NO Content-Length (streamed) is refused, and nothing is logged (H1)', async () => {
  const big = new ReadableStream({
    start(c) { for (let i = 0; i < 64; i += 1) c.enqueue(new TextEncoder().encode('x'.repeat(16384))); c.close(); },
  });
  const [res, logs] = await logged(() => worker.fetch(new Request(`${ORIGIN}/api/csp-report`,
    { method: 'POST', body: big, duplex: 'half' }), env(), ctx()));
  assert.equal(res.headers.get('Content-Length'), null);
  assert.equal(res.status, 413);
  assert.equal(logs.length, 0);
});

test('a report exactly at the limit is accepted', async () => {
  const [res] = await logged(() => worker.fetch(new Request(`${ORIGIN}/api/csp-report`,
    { method: 'POST', body: 'x'.repeat(REPORT_MAX_BYTES) }), env(), ctx()));
  assert.equal(res.status, 204);
});

test('a report from the unsubscribe page never logs the address or the token (H2)', async () => {
  const report = JSON.stringify({ 'csp-report': {
    'document-uri': `${ORIGIN}/api/unsubscribe?email=a%40example.com&t=SECRETTOKEN#frag`,
    referrer: `${ORIGIN}/api/unsubscribe?email=b%40example.com&t=TOKEN2`,
    'blocked-uri': 'https://evil.example/x.js?email=c@example.com',
    'source-file': 'chrome-extension://abc/inject.js?q=1',
  } });
  const [res, logs] = await logged(() => worker.fetch(new Request(`${ORIGIN}/api/csp-report`,
    { method: 'POST', body: report, headers: { 'Content-Type': 'application/csp-report' } }), env(), ctx()));
  assert.equal(res.status, 204);
  assert.equal(logs.length, 1);
  for (const leak of ['email', 'example.com&', '%40', 'SECRETTOKEN', 'TOKEN2', '@example.com', 'frag', '?q=1']) {
    assert.equal(logs[0].includes(leak), false, `logged "${leak}": ${logs[0]}`);
  }
  assert.ok(logs[0].includes(`${ORIGIN}/api/unsubscribe`), 'the path is kept');
});

test('stripQueries keeps scheme, host and path of every URL, in any report format', () => {
  assert.equal(stripQueries('"documentURL":"https://sortinggeography.com/api/unsubscribe?email=x&t=y"'),
    '"documentURL":"https://sortinggeography.com/api/unsubscribe"');
  assert.equal(stripQueries('a http://h/p#x b https://h2/?q c'), 'a http://h/p b https://h2/ c');
});

test('stripping stays fast on a worst-case body (no regex blow-up)', () => {
  // 32 KB: big enough that a quadratic regex takes seconds, small enough that it
  // still finishes and FAILS here instead of hanging the run.
  for (const body of ['a'.repeat(REPORT_MAX_BYTES), 'a'.repeat(32768)]) {
    const t0 = performance.now();
    stripQueries(body);
    const ms = performance.now() - t0;
    assert.ok(ms < 200, `${body.length} letters took ${ms.toFixed(1)} ms`);
  }
});


// ---- fonts are our own (team-lead 2026-11-20, Story 18.3) ----------------------
// The CSP allows fonts and styles from 'self' only. A design that loads Google
// Fonts would break once the CSP is enforced, and send every visitor's address
// to Google. Fonts live under /fonts/<family>/, each family with its OFL text.
const THIRD_PARTY_FONTS = /fonts\.googleapis\.com|fonts\.gstatic\.com|use\.typekit\.net|fonts\.bunny\.net/i;

for (const file of [...served('.html'), ...served('.css'), ...served('.js')]) {
  test(`${file}: no third-party font service`, () => {
    const t = readFileSync(new URL(file, SITE), 'utf8');
    assert.doesNotMatch(t, THIRD_PARTY_FONTS, `${file} loads fonts from a third party`);
  });
}

test('every font file we serve sits beside its family\'s OFL licence', () => {
  let dirs = [];
  try { dirs = readdirSync(new URL('fonts/', SITE), { withFileTypes: true }).filter((e) => e.isDirectory()); } catch { dirs = []; }
  for (const d of dirs) {
    const files = readdirSync(new URL(`fonts/${d.name}/`, SITE));
    if (files.some((f) => /\.(woff2?|ttf|otf)$/i.test(f))) {
      assert.ok(files.includes('OFL.txt'), `fonts/${d.name}/ has font files but no OFL.txt`);
      const lic = readFileSync(new URL(`fonts/${d.name}/OFL.txt`, SITE), 'utf8');
      assert.match(lic, /SIL Open Font License, Version 1\.1/, `fonts/${d.name}/OFL.txt is not the OFL`);
    }
  }
});
