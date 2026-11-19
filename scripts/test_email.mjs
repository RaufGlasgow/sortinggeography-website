// The welcome email (Story 18.5), ready for the Resend key. Plain Node:
// `node --test scripts/test_email.mjs`. The real worker is driven with a fake
// KV store and a fake Resend (global fetch); nothing is sent anywhere.
import { test, beforeEach, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import worker from '../src/worker.js';
import { sendWelcomeEmail, BACKLOG_BATCH } from '../src/mail.js';
import { welcomeEmail, LANGS, pickLang, unsubscribeUrl, esc } from '../src/email.js';

const FACTS = JSON.parse(readFileSync(new URL('../src/facts.json', import.meta.url), 'utf8'));
const SITE = 'https://sortinggeography.com';

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

let sent;
let resendStatus;
const realFetch = globalThis.fetch;
beforeEach(() => {
  sent = [];
  resendStatus = 200;
  globalThis.fetch = async (url, init) => {
    assert.equal(url, 'https://api.resend.com/emails');
    sent.push(JSON.parse(init.body));
    return new Response('{}', { status: resendStatus });
  };
});
afterEach(() => { globalThis.fetch = realFetch; });

function ctx() {
  const jobs = [];
  return { jobs, waitUntil: (p) => jobs.push(p) };
}

async function subscribe(env, fields) {
  const body = new FormData();
  for (const [k, v] of Object.entries(fields)) body.set(k, v);
  const c = ctx();
  const res = await worker.fetch(new Request(`${SITE}/api/subscribe`, { method: 'POST', body }), env, c);
  await Promise.all(c.jobs);
  return res;
}

// ---- the template -------------------------------------------------------------
for (const lang of LANGS) {
  test(`template ${lang}: subject, both parts, unsubscribe link and header`, () => {
    const email = 'a+b@example.com';
    const { message } = welcomeEmail(email, lang);
    const unsub = unsubscribeUrl(email);
    assert.ok(unsub.includes('a%2Bb%40example.com'), 'address is URL-encoded');
    assert.ok(message.subject.length > 0);
    assert.deepEqual(message.to, [email]);
    assert.ok(message.html.includes(`href="${unsub}"`), 'html carries the unsubscribe link');
    assert.ok(message.text.includes(unsub), 'text part carries the unsubscribe link');
    assert.equal(message.headers['List-Unsubscribe'], `<${unsub}>`);
    assert.equal(message.headers['List-Unsubscribe-Post'], 'List-Unsubscribe=One-Click');
    assert.match(message.html, new RegExp(`<html lang="${lang}">`));
  });

  test(`template ${lang}: question count from facts.json, no streak, no comment, no hand-typed count`, () => {
    const { message } = welcomeEmail('x@example.com', lang);
    for (const part of [message.html, message.text]) {
      assert.ok(part.includes(String(FACTS.axes)), `count ${FACTS.axes} from facts.json`);
      assert.doesNotMatch(part, /\bstreaks?\b/i, 'no streak claims (Ra\'uf 2026-11-19)');
      assert.doesNotMatch(part, /nearly two hundred|hundreds of/i, 'a count in words cannot be checked');
      assert.doesNotMatch(part, /iPhone|iPad/, 'phone and tablet, never the device names');
    }
    assert.equal(message.html.includes('<!--'), false);
  });
}

test('pickLang: a language with no template gets English', () => {
  assert.equal(pickLang('en'), 'en');
  assert.equal(pickLang('de'), LANGS.includes('de') ? 'de' : 'en');
  assert.equal(pickLang('xx'), 'en');
  assert.equal(pickLang(undefined), 'en');
});

test('the address cannot inject html: it only appears URL-encoded', () => {
  const { message } = welcomeEmail('"><script>@example.com');
  assert.equal(message.html.includes('<script>'), false);
});

test('esc() makes translated words safe in the html', () => {
  assert.equal(esc('Fish & <chips> "x"'), 'Fish &amp; &lt;chips&gt; &quot;x&quot;');
});

// ---- the worker -----------------------------------------------------------------
test('signup without a key: stored with its language, nothing sent, not welcomed', async () => {
  const env = { LAUNCH_EMAILS: fakeKV() };
  const res = await subscribe(env, { email: 'One@Example.com', lang: 'de' });
  assert.equal(res.status, 200);
  const rec = JSON.parse(env.LAUNCH_EMAILS.m.get('one@example.com'));
  assert.equal(rec.lang, 'de');
  assert.equal(rec.welcomedAt, undefined);
  assert.equal(sent.length, 0);
});

test('a junk lang field is stored as en', async () => {
  const env = { LAUNCH_EMAILS: fakeKV() };
  await subscribe(env, { email: 'x@example.com', lang: '<b>' });
  assert.equal(JSON.parse(env.LAUNCH_EMAILS.m.get('x@example.com')).lang, 'en');
});

test('signup with a key: welcome sent through Resend and the signup marked welcomed', async () => {
  const env = { LAUNCH_EMAILS: fakeKV(), RESEND_API_KEY: 'k' };
  await subscribe(env, { email: 'x@example.com', lang: 'en' });
  assert.equal(sent.length, 1);
  assert.deepEqual(sent[0].to, ['x@example.com']);
  assert.ok(sent[0].text && sent[0].html && sent[0].headers['List-Unsubscribe']);
  assert.ok(JSON.parse(env.LAUNCH_EMAILS.m.get('x@example.com')).welcomedAt);
});

test('Resend refuses (domain not verified): the signup stays, NOT marked welcomed', async () => {
  resendStatus = 403;
  const env = { LAUNCH_EMAILS: fakeKV(), RESEND_API_KEY: 'k' };
  const res = await subscribe(env, { email: 'x@example.com' });
  assert.equal(res.status, 200);
  assert.equal(JSON.parse(env.LAUNCH_EMAILS.m.get('x@example.com')).welcomedAt, undefined);
});

test('unsubscribed while the welcome was in flight: the address is not brought back', async () => {
  const env = { LAUNCH_EMAILS: fakeKV(), RESEND_API_KEY: 'k' };
  globalThis.fetch = async () => { env.LAUNCH_EMAILS.m.delete('x@example.com'); return new Response('{}'); };
  assert.equal(await sendWelcomeEmail('x@example.com', 'en', env), true);
  assert.equal(env.LAUNCH_EMAILS.m.has('x@example.com'), false);
});

test('one-click unsubscribe (POST) deletes the address', async () => {
  const env = { LAUNCH_EMAILS: fakeKV({ 'x@example.com': { email: 'x@example.com' } }) };
  const res = await worker.fetch(new Request(unsubscribeUrl('x@example.com'), {
    method: 'POST', body: 'List-Unsubscribe=One-Click',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' } }), env, ctx());
  assert.equal(res.status, 200);
  assert.equal(env.LAUNCH_EMAILS.m.has('x@example.com'), false);
});

test('the unsubscribe link (GET) still deletes the address', async () => {
  const env = { LAUNCH_EMAILS: fakeKV({ 'x@example.com': { email: 'x@example.com' } }) };
  const res = await worker.fetch(new Request(unsubscribeUrl('x@example.com')), env, ctx());
  assert.equal(res.status, 200);
  assert.equal(env.LAUNCH_EMAILS.m.has('x@example.com'), false);
});

// ---- the backlog ----------------------------------------------------------------
async function backlog(env, fields) {
  const body = new FormData();
  for (const [k, v] of Object.entries(fields)) body.set(k, v);
  return worker.fetch(new Request(`${SITE}/api/send-welcome-backlog`, { method: 'POST', body }), env, ctx());
}

function seeded(n, welcomed = 0) {
  const seed = {};
  for (let i = 0; i < n; i += 1) {
    seed[`p${i}@example.com`] = { email: `p${i}@example.com`, lang: 'en', ...(i < welcomed ? { welcomedAt: 'x' } : {}) };
  }
  return fakeKV(seed);
}

test('backlog refuses without the secret, with a wrong one, and when the secret is unset', async () => {
  const env = { LAUNCH_EMAILS: seeded(2), EXPORT_SECRET: 's', RESEND_API_KEY: 'k' };
  assert.equal((await backlog(env, {})).status, 401);
  assert.equal((await backlog(env, { key: 'wrong' })).status, 401);
  assert.equal((await backlog({ ...env, EXPORT_SECRET: undefined }, { key: '' })).status, 401);
  assert.equal((await worker.fetch(new Request(`${SITE}/api/send-welcome-backlog?key=s`), env, ctx())).status, 405,
    'GET (key in the URL, into logs) is refused');
  assert.equal(sent.length, 0);
});

test('backlog dry run counts who is waiting and sends nothing', async () => {
  const env = { LAUNCH_EMAILS: seeded(5, 2), EXPORT_SECRET: 's', RESEND_API_KEY: 'k' };
  const out = await (await backlog(env, { key: 's' })).json();
  assert.deepEqual(out, { dryRun: true, waiting: 3 });
  assert.equal(sent.length, 0);
});

test('backlog send without a Resend key is refused', async () => {
  const env = { LAUNCH_EMAILS: seeded(2), EXPORT_SECRET: 's' };
  assert.equal((await backlog(env, { key: 's', send: '1' })).status, 409);
});

test('backlog sends once to each waiting signup, in batches, never twice', async () => {
  const env = { LAUNCH_EMAILS: seeded(BACKLOG_BATCH + 5, 3), EXPORT_SECRET: 's', RESEND_API_KEY: 'k' };
  const first = await (await backlog(env, { key: 's', send: '1' })).json();
  assert.equal(first.sent, BACKLOG_BATCH);
  assert.equal(first.remaining, 2);
  const second = await (await backlog(env, { key: 's', send: '1' })).json();
  assert.equal(second.sent, 2);
  assert.equal(second.remaining, 0);
  const third = await (await backlog(env, { key: 's', send: '1' })).json();
  assert.equal(third.sent, 0);
  const to = sent.map((m) => m.to[0]);
  assert.equal(new Set(to).size, to.length, 'nobody got it twice');
  assert.equal(to.length, BACKLOG_BATCH + 2);
  assert.ok(!to.includes('p0@example.com'), 'already-welcomed signups are skipped');
});

test('backlog: a refused send is counted failed and stays waiting', async () => {
  resendStatus = 500;
  const env = { LAUNCH_EMAILS: seeded(2), EXPORT_SECRET: 's', RESEND_API_KEY: 'k' };
  const out = await (await backlog(env, { key: 's', send: '1' })).json();
  assert.deepEqual([out.sent, out.failed, out.remaining], [0, 2, 2]);
});

test('src/worker.js exports only its handler (workerd treats named exports as entrypoints)', () => {
  const src = readFileSync(new URL('../src/worker.js', import.meta.url), 'utf8');
  assert.deepEqual(src.match(/^export\b.*$/gm), ['export default {']);
});

test('the template words carry no number typed by hand (counts come from facts)', () => {
  const src = readFileSync(new URL('../src/email.js', import.meta.url), 'utf8');
  const words = src.slice(src.indexOf('const TEXT = {'), src.indexOf('export const LANGS'));
  assert.ok(words.length > 100, 'found the TEXT block');
  assert.doesNotMatch(words, /\b\d{2,}\b/, 'a count in the words must be ${f.<fact>}');
});
