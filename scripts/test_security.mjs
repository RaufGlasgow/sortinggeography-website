// Security headers and the report-only CSP (Story 18.10). Plain Node:
// `node --test scripts/test_security.mjs`. Drives the real worker with fakes.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';

import worker from '../src/worker.js';
import { SECURITY_HEADERS, CSP_REPORT_ONLY, CSP_REPORT_LOG_CHARS } from '../src/security.js';

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
    const res = await worker.fetch(new Request(`${ORIGIN}/api/csp-report`, { method: 'POST', body: 'x'.repeat(5000),
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
