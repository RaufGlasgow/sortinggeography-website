// The release flip, with the clock set before, at and after the moment
// (Story 18.8). Runs in plain Node (`node --test scripts/test_launch.mjs`):
// the worker's page path and countdown.js are driven with fakes, no network,
// no Cloudflare account.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import vm from 'node:vm';

import { RELEASE_UTC_MS, launchState } from '../src/launch.js';
import { serveAsset, stampLaunch } from '../src/pages.js';

const BEFORE = RELEASE_UTC_MS - 1;
const AT = RELEASE_UTC_MS;
const AFTER = RELEASE_UTC_MS + 60_000;

test('the constant is 10 December 2026, 09:00 UTC', () => {
  assert.equal(new Date(RELEASE_UTC_MS).toISOString(), '2026-12-10T09:00:00.000Z');
});

test('launchState: pre before, out at and after', () => {
  assert.equal(launchState(BEFORE), 'pre');
  assert.equal(launchState(AT), 'out');
  assert.equal(launchState(AFTER), 'out');
});

// A fake HTMLRewriter that records what the worker would set on <html>.
function fakeRewriter(sink) {
  return class {
    on(selector, handler) { this.selector = selector; this.handler = handler; return this; }
    transform(response) {
      assert.equal(this.selector, 'html');
      const attrs = {};
      this.handler.element({ setAttribute: (k, v) => { attrs[k] = v; } });
      sink.attrs = attrs;
      return response;
    }
  };
}

function htmlResponse() {
  return new Response('<html><body>x</body></html>', {
    headers: { 'Content-Type': 'text/html; charset=utf-8', ETag: '"abc"', 'Last-Modified': 'x' },
  });
}

for (const [label, now, want] of [['before', BEFORE, 'pre'], ['at', AT, 'out'], ['after', AFTER, 'out']]) {
  test(`stampLaunch ${label} the moment marks the page ${want}`, () => {
    const sink = {};
    const res = stampLaunch(htmlResponse(), now, fakeRewriter(sink));
    assert.equal(sink.attrs['data-launch'], want);
    assert.equal(sink.attrs['data-now'], String(now));
    // No validators: a browser must never be told its pre-launch copy is current.
    assert.equal(res.headers.get('ETag'), null);
    assert.equal(res.headers.get('Last-Modified'), null);
    assert.equal(res.headers.get('Cache-Control'), 'no-cache');
  });
}

test('serveAsset drops conditional headers for pages and stamps them', async () => {
  const seen = {};
  globalThis.HTMLRewriter = fakeRewriter(seen);
  let asked;
  const env = { ASSETS: { fetch: async (req) => { asked = req; return htmlResponse(); } } };
  const req = new Request('https://sortinggeography.com/', {
    headers: { Accept: 'text/html', 'If-None-Match': '"abc"', 'If-Modified-Since': 'x' },
  });
  await serveAsset(req, env, AFTER);
  assert.equal(asked.headers.get('If-None-Match'), null);
  assert.equal(asked.headers.get('If-Modified-Since'), null);
  assert.equal(seen.attrs['data-launch'], 'out');
  delete globalThis.HTMLRewriter;
});

test('serveAsset passes images and styles straight through', async () => {
  const original = new Response('png', { headers: { 'Content-Type': 'image/png', ETag: '"p"' } });
  const env = { ASSETS: { fetch: async () => original } };
  const req = new Request('https://sortinggeography.com/images/google-play-badge.png',
    { headers: { Accept: 'image/*' } });
  const res = await serveAsset(req, env, AFTER);
  assert.equal(res, original);
});

// ---- 18.9b B5: no served page carries an HTML comment ---------------------
// Every page the site serves goes through the real serveAsset with a fake
// asset store holding the real file; what comes out is what a visitor gets.
const SITE = new URL('../', import.meta.url);
const NOT_SERVED = new Set(['docs', 'src', 'scripts', 'node_modules', '.git', '.github', '.wrangler']);
function servedPages(dir = '') {
  return readdirSync(new URL(dir || '.', SITE), { withFileTypes: true }).flatMap((e) => {
    const rel = dir + e.name;
    if (e.isDirectory()) return NOT_SERVED.has(e.name) ? [] : servedPages(rel + '/');
    return e.name.endsWith('.html') ? [rel] : [];
  });
}

test('the site has pages to check', () => {
  assert.ok(servedPages().length >= 6, servedPages().join(', '));
});

for (const page of servedPages()) {
  test(`${page} is served with no HTML comment and its content intact`, async () => {
    const source = readFileSync(new URL(page, SITE), 'utf8');
    globalThis.HTMLRewriter = fakeRewriter({});
    const env = { ASSETS: { fetch: async () => new Response(source, {
      headers: { 'Content-Type': 'text/html; charset=utf-8', 'Content-Length': String(source.length) } }) } };
    const path = '/' + page.replace(/index\.html$/, '');
    const res = await serveAsset(new Request('https://sortinggeography.com' + path,
      { headers: { Accept: 'text/html' } }), env, AFTER);
    delete globalThis.HTMLRewriter;
    const sent = await res.text();
    assert.equal(sent.includes('<!--'), false, `${page}: a comment is served: ${sent.slice(sent.indexOf('<!--'), sent.indexOf('<!--') + 80)}`);
    // The expected page, built WITHOUT the worker's regex (18.9b B6): split on
    // every '<!--', drop each piece up to its own '-->'. A strip that eats more
    // than one comment (greedy) or less (only the first) cannot equal this.
    const [head, ...rest] = source.split('<!--');
    const expected = head + rest.map((piece) => {
      const end = piece.indexOf('-->');
      assert.notEqual(end, -1, `${page}: a '<!--' is never closed`);
      return piece.slice(end + 3);
    }).join('');
    assert.equal(sent, expected, `${page}: the served page is not the source minus its comments`);
    assert.ok(sent.includes('<h1'), `${page}: no <h1> left`);
    assert.ok(sent.includes('</body>') && sent.includes('</html>'), `${page}: page cut short`);
    assert.equal(res.headers.get('Content-Length'), null);
  });
}

// ---- countdown.js, in a fake page -----------------------------------------
function runCountdown({ clientNow, serverNow, stamped }) {
  const rootAttrs = { 'data-launch': stamped };
  if (serverNow !== undefined) rootAttrs['data-now'] = String(serverNow);
  const cells = ['d', 'h', 'm', 's'].map((u) => ({ getAttribute: () => u, textContent: '0' }));
  const cd = {
    hidden: true,
    getAttribute: (k) => (k === 'data-release' ? String(RELEASE_UTC_MS) : null),
    querySelectorAll: () => cells,
  };
  const root = {
    getAttribute: (k) => (k in rootAttrs ? rootAttrs[k] : null),
    setAttribute: (k, v) => { rootAttrs[k] = v; },
  };
  const intervals = [];
  const context = {
    document: { documentElement: root, querySelector: () => cd },
    Date: { now: () => clientNow },
    Number, Math, String, isFinite,
    setInterval: (fn) => { intervals.push(fn); return 1; },
    clearInterval: () => {},
  };
  vm.runInNewContext(readFileSync(new URL('../countdown.js', import.meta.url), 'utf8'), context);
  return { rootAttrs, cd, cells, intervals };
}

test('countdown before the moment shows the timer and stays pre', () => {
  const t = runCountdown({ clientNow: RELEASE_UTC_MS - (2 * 86400 + 3 * 3600 + 4 * 60 + 5) * 1000, stamped: 'pre' });
  assert.equal(t.rootAttrs['data-launch'], 'pre');
  assert.equal(t.cd.hidden, false);
  assert.deepEqual(t.cells.map((c) => c.textContent), ['2', '03', '04', '05']);
  assert.equal(t.intervals.length, 1);
});

test('countdown at the moment flips the page to out', () => {
  const t = runCountdown({ clientNow: AT, stamped: 'pre' });
  assert.equal(t.rootAttrs['data-launch'], 'out');
});

test('countdown after the moment flips to out', () => {
  const t = runCountdown({ clientNow: AFTER, stamped: 'pre' });
  assert.equal(t.rootAttrs['data-launch'], 'out');
});

test('a visitor clock a day fast is not told "out" early: the server clock wins', () => {
  const t = runCountdown({ clientNow: AFTER + 86400_000, serverNow: BEFORE - 3600_000, stamped: 'pre' });
  // countdown.js read data-now and Date.now() at the same instant, so the
  // offset puts it back an hour before the moment.
  assert.equal(t.rootAttrs['data-launch'], 'pre');
  assert.deepEqual(t.cells.map((c) => c.textContent), ['0', '01', '00', '00']);
});
