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

const SITE = new URL('../', import.meta.url);
const NOT_SERVED = new Set(['docs', 'src', 'scripts', 'node_modules', '.git', '.github', '.wrangler', 'functions']);
function servedPages(dir = '') {
  return readdirSync(new URL(dir || '.', SITE), { withFileTypes: true }).flatMap((e) => {
    const rel = dir + e.name;
    if (e.isDirectory()) return NOT_SERVED.has(e.name) || e.name.startsWith('.') ? [] : servedPages(rel + '/');
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
    { cwd: fileURLToPath(SITE), env: { ...process.env, WRANGLER_SEND_METRICS: 'false', CI: '1' }, stdio: ['ignore', 'pipe', 'pipe'] });
  dev.stdout.on('data', (d) => { log += d; });
  dev.stderr.on('data', (d) => { log += d; });
  const deadline = Date.now() + 90_000;
  for (;;) {
    if (dev.exitCode !== null) throw new Error(`wrangler dev exited ${dev.exitCode}:\n${log}`);
    try { const r = await fetch(base + '/robots.txt'); await r.text(); if (r.ok) break; } catch {}
    if (Date.now() > deadline) throw new Error(`wrangler dev did not start in 90 s:\n${log}`);
    await new Promise((r) => setTimeout(r, 500));
  }
});

after(() => { dev?.kill('SIGTERM'); });

test('the site has pages to check', () => {
  assert.ok(servedPages().length >= 6, servedPages().join(', '));
});

for (const page of servedPages()) {
  test(`${page} as the real worker sends it: no comment, nothing else changed`, async () => {
    const source = readFileSync(new URL(page, SITE), 'utf8');
    // The asset layer serves /x/index.html at /x/ and /x.html at /x (it
    // redirects the .html name), so fetch the URL a visitor ends up on.
    const path = '/' + page.replace(/index\.html$/, '').replace(/\.html$/, '');
    const res = await fetch(base + path, { headers: { Accept: 'text/html' }, redirect: 'manual' });
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
