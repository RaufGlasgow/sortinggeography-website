// The welcome email (Story 18.5), ready for the Resend key. Plain Node:
// `node --test scripts/test_email.mjs`. The real worker is driven with a fake
// KV store, a fake rate limiter and a fake Resend (global fetch); nothing is
// sent anywhere.
import { test, beforeEach, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import worker from '../src/worker.js';
import { sendWelcomeEmail, BACKLOG_BATCH, MAX_FAILURES } from '../src/mail.js';
import { welcomeEmail, LANGS, pickLang, unsubscribeUrl, esc } from '../src/email.js';
import { unsubscribeToken, tokenValid } from '../src/token.js';

const FACTS = JSON.parse(readFileSync(new URL('../src/facts.json', import.meta.url), 'utf8'));
const SITE = 'https://sortinggeography.com';
const SECRET = 'test-secret';

function fakeKV(seed = {}) {
  const m = new Map(Object.entries(seed).map(([k, v]) => [k, JSON.stringify(v)]));
  return {
    m,
    async get(k) { return m.has(k) ? m.get(k) : null; },
    async put(k, v) { m.set(k, v); },
    async delete(k) { m.delete(k); },
    async list() { return { keys: [...m.keys()].map((name) => ({ name })), list_complete: true }; },
  };
}

function fakeLimit(max = 1000) {
  const seen = new Map();
  return { seen, async limit({ key }) { const n = (seen.get(key) || 0) + 1; seen.set(key, n); return { success: n <= max }; } };
}

function envWith(extra = {}) {
  return { LAUNCH_EMAILS: fakeKV(), SUBSCRIBE_LIMIT: fakeLimit(), UNSUBSCRIBE_SECRET: SECRET, ...extra };
}

let sent;
let resendStatus;
const realFetch = globalThis.fetch;
beforeEach(() => {
  sent = [];
  resendStatus = 200;
  globalThis.fetch = async (url, init) => {
    assert.equal(url, 'https://api.resend.com/emails');
    const body = JSON.parse(init.body);
    sent.push(body);
    return new Response('{}', { status: typeof resendStatus === 'function' ? resendStatus(body) : resendStatus });
  };
});
afterEach(() => { globalThis.fetch = realFetch; });

function ctx() {
  const jobs = [];
  return { jobs, waitUntil: (p) => jobs.push(p) };
}

async function subscribe(env, fields, headers = {}) {
  const body = new FormData();
  for (const [k, v] of Object.entries(fields)) body.set(k, v);
  const c = ctx();
  const res = await worker.fetch(new Request(`${SITE}/api/subscribe`, { method: 'POST', body, headers }), env, c);
  await Promise.all(c.jobs);
  return res;
}

// ---- the template -------------------------------------------------------------
for (const lang of LANGS) {
  test(`template ${lang}: subject, both parts, signed unsubscribe link and header`, async () => {
    const email = 'a+b@example.com';
    const token = await unsubscribeToken(email, SECRET);
    const { message } = welcomeEmail(email, lang, token);
    const unsub = unsubscribeUrl(email, token);
    assert.ok(unsub.includes('a%2Bb%40example.com') && unsub.includes(`&t=${encodeURIComponent(token)}`));
    assert.ok(message.subject.length > 0);
    assert.deepEqual(message.to, [email]);
    assert.ok(message.html.includes(`href="${esc(unsub)}"`), 'html carries the unsubscribe link');
    assert.ok(message.text.includes(unsub), 'text part carries the unsubscribe link');
    assert.equal(message.headers['List-Unsubscribe'], `<${unsub}>`);
    assert.equal(message.headers['List-Unsubscribe-Post'], 'List-Unsubscribe=One-Click');
    assert.match(message.html, new RegExp(`<html lang="${lang}">`));
  });

  test(`template ${lang}: question count from facts.json, no streak, no comment, no device names`, () => {
    const { message } = welcomeEmail('x@example.com', lang, 'tok');
    for (const part of [message.html, message.text]) {
      assert.ok(part.includes(String(FACTS.axes)), `count ${FACTS.axes} from facts.json`);
      assert.doesNotMatch(part, /\bstreaks?\b/i, 'no streak claims (Ra\'uf 2026-11-19)');
      assert.doesNotMatch(part, /nearly two hundred|hundreds of/i, 'a count in words cannot be checked');
      assert.doesNotMatch(part, /iPhone|iPad/, 'phone and tablet, never the device names');
      assert.doesNotMatch(part, /one click/i, 'unsubscribing is a link and a button now');
    }
    assert.equal(message.html.includes('<!--'), false);
  });
}

test("the English template carries Ra'uf's own sentence, word for word", () => {
  // sortinghistory-website-deploy/src/worker.js:266 (his commit 9dade19).
  const { message } = welcomeEmail('x@example.com', 'en', 'tok');
  assert.ok(message.text.includes("I developed this game for my wife and family, and I hope you'll enjoy it as much as we do."));
});

test('a welcome cannot be built without a token', () => {
  assert.throws(() => welcomeEmail('x@example.com', 'en'));
});

test('pickLang: a language with no template gets English', () => {
  assert.equal(pickLang('en'), 'en');
  assert.equal(pickLang('de'), LANGS.includes('de') ? 'de' : 'en');
  assert.equal(pickLang('xx'), 'en');
  assert.equal(pickLang(undefined), 'en');
});

test('the address cannot inject html: it only appears URL-encoded', () => {
  const { message } = welcomeEmail('"><script>@example.com', 'en', 'tok');
  assert.equal(message.html.includes('<script>'), false);
});

test('esc() makes translated words safe in the html', () => {
  assert.equal(esc('Fish & <chips> "x"'), 'Fish &amp; &lt;chips&gt; &quot;x&quot;');
});

test('tokens: right address and secret only', async () => {
  const t = await unsubscribeToken('x@example.com', SECRET);
  assert.equal(await tokenValid('x@example.com', t, SECRET), true);
  assert.equal(await tokenValid('y@example.com', t, SECRET), false);
  assert.equal(await tokenValid('x@example.com', t, 'other'), false);
  assert.equal(await tokenValid('x@example.com', t.slice(0, -1) + (t.endsWith('A') ? 'B' : 'A'), SECRET), false);
  assert.equal(await tokenValid('x@example.com', '', SECRET), false);
  assert.equal(await tokenValid('x@example.com', t, undefined), false);
});

// ---- the signup (E1, E3) ----------------------------------------------------------
test('signup without a key: stored with its language, nothing sent, no user agent kept', async () => {
  const env = envWith();
  const res = await subscribe(env, { email: 'One@Example.com', lang: 'de' }, { 'User-Agent': 'UA/1' });
  assert.equal(res.status, 200);
  const rec = JSON.parse(env.LAUNCH_EMAILS.m.get('one@example.com'));
  assert.deepEqual(Object.keys(rec).sort(), ['email', 'lang', 'source', 'timestamp'], 'exactly what the privacy page says');
  assert.equal(rec.lang, 'de');
  assert.equal(sent.length, 0);
});

test('a junk lang field is stored as en', async () => {
  const env = envWith();
  await subscribe(env, { email: 'x@example.com', lang: '<b>' });
  assert.equal(JSON.parse(env.LAUNCH_EMAILS.m.get('x@example.com')).lang, 'en');
});

test('the same address five times: one record, one welcome (E1)', async () => {
  const env = envWith({ RESEND_API_KEY: 'k' });
  for (let i = 0; i < 5; i += 1) assert.equal((await subscribe(env, { email: 'victim@example.com' })).status, 200);
  assert.equal(sent.length, 1);
});

test('a repeat signup keeps the first record untouched', async () => {
  const env = envWith();
  await subscribe(env, { email: 'x@example.com', lang: 'en' });
  const first = env.LAUNCH_EMAILS.m.get('x@example.com');
  await subscribe(env, { email: 'x@example.com', lang: 'de' });
  assert.equal(env.LAUNCH_EMAILS.m.get('x@example.com'), first);
});

test('a cross-site Origin is refused; our own origins pass (E1)', async () => {
  const env = envWith({ RESEND_API_KEY: 'k' });
  assert.equal((await subscribe(env, { email: 'a@example.com' }, { Origin: 'https://evil.example' })).status, 403);
  assert.equal(env.LAUNCH_EMAILS.m.size, 0);
  assert.equal((await subscribe(env, { email: 'b@example.com' }, { Origin: 'https://sortinggeography.com' })).status, 200);
  assert.equal((await subscribe(env, { email: 'c@example.com' }, { Origin: 'https://www.sortinggeography.com' })).status, 200);
});

test('the rate limit stops a burst from one IP, per IP (E1)', async () => {
  const env = envWith({ RESEND_API_KEY: 'k', SUBSCRIBE_LIMIT: fakeLimit(5) });
  const codes = [];
  for (let i = 0; i < 7; i += 1) {
    codes.push((await subscribe(env, { email: `p${i}@example.com` }, { 'CF-Connecting-IP': '1.2.3.4' })).status);
  }
  assert.deepEqual(codes, [200, 200, 200, 200, 200, 429, 429]);
  assert.equal(sent.length, 5);
  assert.equal((await subscribe(env, { email: 'q@example.com' }, { 'CF-Connecting-IP': '5.6.7.8' })).status, 200);
});

test('no rate-limit binding: signups are refused, not run unguarded', async () => {
  const env = envWith({ SUBSCRIBE_LIMIT: undefined, RESEND_API_KEY: 'k' });
  assert.equal((await subscribe(env, { email: 'x@example.com' })).status, 503);
  assert.equal(env.LAUNCH_EMAILS.m.size, 0);
  assert.equal(sent.length, 0);
});

test('the signup answer carries no open CORS header', async () => {
  const res = await subscribe(envWith(), { email: 'x@example.com' });
  assert.equal(res.headers.get('Access-Control-Allow-Origin'), null);
});

// ---- sending --------------------------------------------------------------------
test('signup with a key: welcome sent and the signup marked welcomed', async () => {
  const env = envWith({ RESEND_API_KEY: 'k' });
  await subscribe(env, { email: 'x@example.com', lang: 'en' });
  assert.equal(sent.length, 1);
  assert.deepEqual(sent[0].to, ['x@example.com']);
  assert.ok(sent[0].text && sent[0].html && sent[0].headers['List-Unsubscribe']);
  assert.ok(JSON.parse(env.LAUNCH_EMAILS.m.get('x@example.com')).welcomedAt);
});

test('no UNSUBSCRIBE_SECRET: nothing is sent (no honest unsubscribe link)', async () => {
  const env = envWith({ RESEND_API_KEY: 'k', UNSUBSCRIBE_SECRET: undefined });
  await subscribe(env, { email: 'x@example.com' });
  assert.equal(sent.length, 0);
});

test('Resend refuses: the signup stays, not welcomed, the failure counted', async () => {
  resendStatus = 403;
  const env = envWith({ RESEND_API_KEY: 'k' });
  const res = await subscribe(env, { email: 'x@example.com' });
  assert.equal(res.status, 200);
  const rec = JSON.parse(env.LAUNCH_EMAILS.m.get('x@example.com'));
  assert.equal(rec.welcomedAt, undefined);
  assert.equal(rec.failures, 1);
  assert.ok(rec.lastFailedAt);
});

test('unsubscribed while the welcome was in flight: the address is not brought back', async () => {
  const env = envWith({ RESEND_API_KEY: 'k' });
  globalThis.fetch = async () => { env.LAUNCH_EMAILS.m.delete('x@example.com'); return new Response('{}'); };
  assert.equal(await sendWelcomeEmail('x@example.com', 'en', env), true);
  assert.equal(env.LAUNCH_EMAILS.m.has('x@example.com'), false);
});

// ---- unsubscribe (E2) -------------------------------------------------------------
async function unsub(env, email, token, method) {
  const url = `${SITE}/api/unsubscribe?email=${encodeURIComponent(email)}${token === null ? '' : `&t=${encodeURIComponent(token)}`}`;
  const init = method === 'POST'
    ? { method, body: 'List-Unsubscribe=One-Click', headers: { 'Content-Type': 'application/x-www-form-urlencoded' } }
    : {};
  return worker.fetch(new Request(url, init), env, ctx());
}

function onList(email) {
  return envWith({ LAUNCH_EMAILS: fakeKV({ [email]: { email } }) });
}

test('GET with a valid token only shows the confirm button; nothing is deleted', async () => {
  const env = onList('x@example.com');
  const res = await unsub(env, 'x@example.com', await unsubscribeToken('x@example.com', SECRET), 'GET');
  assert.equal(res.status, 200);
  const page = await res.text();
  assert.match(page, /<form method="post" action="\/api\/unsubscribe\?email=x%40example\.com&amp;t=/);
  assert.equal(env.LAUNCH_EMAILS.m.has('x@example.com'), true, 'a link scanner opening the URL deletes nothing');
});

test('POST with a valid token deletes (the button, and the one-click)', async () => {
  const env = onList('x@example.com');
  const res = await unsub(env, 'x@example.com', await unsubscribeToken('x@example.com', SECRET), 'POST');
  assert.equal(res.status, 200);
  assert.equal(env.LAUNCH_EMAILS.m.has('x@example.com'), false);
});

for (const [name, token] of [['no token', null], ['an empty token', ''], ['a wrong token', 'abc'],
  ["another address's token", 'OTHER']]) {
  test(`POST with ${name} is refused and deletes nothing (anyone could unsubscribe anyone)`, async () => {
    const env = onList('x@example.com');
    const t = token === 'OTHER' ? await unsubscribeToken('y@example.com', SECRET) : token;
    const res = await unsub(env, 'x@example.com', t, 'POST');
    assert.equal(res.status, 403);
    assert.equal(env.LAUNCH_EMAILS.m.has('x@example.com'), true);
    assert.match(await res.text(), /support@sortinggeography\.com/);
  });
}

test('no UNSUBSCRIBE_SECRET on the server: every unsubscribe is refused, none deletes', async () => {
  const env = { ...onList('x@example.com'), UNSUBSCRIBE_SECRET: undefined };
  const res = await unsub(env, 'x@example.com', await unsubscribeToken('x@example.com', SECRET), 'POST');
  assert.equal(res.status, 403);
  assert.equal(env.LAUNCH_EMAILS.m.has('x@example.com'), true);
});

// ---- the backlog (E4) -------------------------------------------------------------
async function backlog(env, fields) {
  const body = new FormData();
  for (const [k, v] of Object.entries(fields)) body.set(k, v);
  return worker.fetch(new Request(`${SITE}/api/send-welcome-backlog`, { method: 'POST', body }), env, ctx());
}

function seeded(n, welcomed = 0, extra = () => ({})) {
  const seed = {};
  for (let i = 0; i < n; i += 1) {
    seed[`p${i}@example.com`] = { email: `p${i}@example.com`, lang: 'en', ...(i < welcomed ? { welcomedAt: 'x' } : {}), ...extra(i) };
  }
  return fakeKV(seed);
}

test('backlog refuses without the secret, with a wrong one, and when the secret is unset', async () => {
  const env = envWith({ LAUNCH_EMAILS: seeded(2), EXPORT_SECRET: 's', RESEND_API_KEY: 'k' });
  assert.equal((await backlog(env, {})).status, 401);
  assert.equal((await backlog(env, { key: 'wrong' })).status, 401);
  assert.equal((await backlog({ ...env, EXPORT_SECRET: undefined }, { key: '' })).status, 401);
  assert.equal((await worker.fetch(new Request(`${SITE}/api/send-welcome-backlog?key=s`), env, ctx())).status, 405,
    'GET (key in the URL, into logs) is refused');
  assert.equal(sent.length, 0);
});

test('backlog dry run counts who is waiting and sends nothing', async () => {
  const env = envWith({ LAUNCH_EMAILS: seeded(5, 2), EXPORT_SECRET: 's', RESEND_API_KEY: 'k' });
  assert.deepEqual(await (await backlog(env, { key: 's' })).json(), { dryRun: true, waiting: 3, givenUp: 0 });
  assert.equal(sent.length, 0);
});

test('backlog send without a Resend key or the unsubscribe secret is refused', async () => {
  assert.equal((await backlog(envWith({ LAUNCH_EMAILS: seeded(2), EXPORT_SECRET: 's' }), { key: 's', send: '1' })).status, 409);
  assert.equal((await backlog(envWith({ LAUNCH_EMAILS: seeded(2), EXPORT_SECRET: 's', RESEND_API_KEY: 'k', UNSUBSCRIBE_SECRET: undefined }),
    { key: 's', send: '1' })).status, 409);
});

test('backlog sends once to each waiting signup, in batches, never twice', async () => {
  const env = envWith({ LAUNCH_EMAILS: seeded(BACKLOG_BATCH + 5, 3), EXPORT_SECRET: 's', RESEND_API_KEY: 'k' });
  const first = await (await backlog(env, { key: 's', send: '1' })).json();
  assert.equal(first.sent, BACKLOG_BATCH);
  assert.equal(first.remaining, 2);
  const second = await (await backlog(env, { key: 's', send: '1' })).json();
  assert.equal(second.sent, 2);
  assert.equal(second.remaining, 0);
  assert.equal((await (await backlog(env, { key: 's', send: '1' })).json()).sent, 0);
  const to = sent.map((m) => m.to[0]);
  assert.equal(new Set(to).size, to.length, 'nobody got it twice');
  assert.equal(to.length, BACKLOG_BATCH + 2);
  assert.ok(!to.includes('p0@example.com'), 'already-welcomed signups are skipped');
});

test('backlog: refused addresses go last and are given up after MAX_FAILURES (E4)', async () => {
  // 45 addresses Resend always refuses, listed first, plus one good one.
  const kv = seeded(45);
  kv.m.set('good@example.com', JSON.stringify({ email: 'good@example.com', lang: 'en' }));
  resendStatus = (body) => (body.to[0] === 'good@example.com' ? 200 : 422);
  const env = envWith({ LAUNCH_EMAILS: kv, EXPORT_SECRET: 's', RESEND_API_KEY: 'k' });
  const outs = [];
  for (let i = 0; i < 2 * MAX_FAILURES + 2; i += 1) {
    outs.push(await (await backlog(env, { key: 's', send: '1' })).json());
    if (i === 1) {
      assert.ok(JSON.parse(kv.m.get('good@example.com')).welcomedAt,
        'by the second call the never-tried address goes ahead of the 40 that were refused');
    }
  }
  const last = outs.at(-1);
  assert.deepEqual([last.sent, last.failed, last.remaining, last.givenUp], [0, 0, 0, 45]);
  for (const [k, v] of kv.m) if (k !== 'good@example.com') assert.equal(JSON.parse(v).failures, MAX_FAILURES);
});

test('src/worker.js exports only its handler (workerd treats named exports as entrypoints)', () => {
  const src = readFileSync(new URL('../src/worker.js', import.meta.url), 'utf8');
  assert.deepEqual(src.match(/^export\b.*$/gm), ['export default {']);
});

test('the template words carry no number typed by hand (counts come from facts)', () => {
  const src = readFileSync(new URL('../src/email.js', import.meta.url), 'utf8');
  const words = src.slice(src.indexOf('const TEXT = {'), src.indexOf('export const LANGS'));
  assert.ok(words.length > 100, 'found the TEXT block');
  assert.doesNotMatch(words.replace(/\/\/.*$/gm, ''), /\b\d{2,}\b/, 'a count in the words must be ${f.<fact>}');
});
