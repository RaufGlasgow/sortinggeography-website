// Sending the welcome email (Story 18.5): one message on signup, and the
// backlog for signups made before the Resend key. The words are src/email.js.
// Imported by src/worker.js; tested by scripts/test_email.mjs.

import { welcomeEmail } from './email.js';
import { unsubscribeToken } from './token.js';

// After this many refused sends an address is given up (18.5 review E4), so a
// few dead addresses can never block the backlog for everyone else.
export const MAX_FAILURES = 3;

// THE daily cap on everything this site sends through Resend (18.5 review E6;
// team-lead 2026-11-20). Resend's free plan is "limited to 100 emails per day"
// and 3,000 a month (resend.com/pricing, read by team-lead 19 Nov 2026), and
// the page does not say what happens past 100. So every send, welcome,
// backlog and any later launch-day mailing, goes through sendViaResend()
// below, which counts them all against ONE per-UTC-day total and stops at
// DAILY_SEND_CAP (wrangler.toml [vars], 90: 10 under the limit for the KV
// counter's small overshoot under a burst; 90 x 31 = 2,790, under the month).
// What is not sent today is not a failure: it waits, and the backlog (or the
// launch send) carries on the next day where it stopped.
// scripts/test_email.mjs fails if any other file in src/ calls Resend, or if
// the cap in wrangler.toml goes above 90. Missing or not a positive whole
// number means DEFAULT_DAILY_SEND_CAP, never "no cap".
export const DEFAULT_DAILY_SEND_CAP = 90;
const SENDS_KEY = (now) => `sends:${now.toISOString().slice(0, 10)}`;

export function dailyCap(env) {
  const n = Number(env.DAILY_SEND_CAP);
  return Number.isInteger(n) && n > 0 ? n : DEFAULT_DAILY_SEND_CAP;
}

// The counter's key has no "@", so it can never be a signup's key; the export
// and the backlog skip every key without one.
export const isSignupKey = (name) => name.includes('@');

export async function sentToday(env, now = new Date()) {
  return Number((await env.LAUNCH_EMAILS.get(SENDS_KEY(now))) || 0);
}

// The one door to Resend. 'sent' (2xx, counted), 'capped' (today's total is
// reached, or Resend itself answers 429: nothing is a failure, try tomorrow),
// or 'failed' (refused or unreachable).
export async function sendViaResend(env, message) {
  const now = new Date();
  if ((await sentToday(env, now)) >= dailyCap(env)) return 'capped';
  let res;
  try {
    res = await fetch('https://api.resend.com/emails', {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${env.RESEND_API_KEY}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(message),
    });
  } catch (e) {
    return 'failed';
  }
  if (res.status === 429) return 'capped';
  if (!res.ok) return 'failed';
  try {
    // KV is eventually consistent, so the count can run a little over under
    // a burst (the per-IP limit keeps that small). Kept two days, then gone.
    await env.LAUNCH_EMAILS.put(SENDS_KEY(now), String((await sentToday(env, now)) + 1),
      { expirationTtl: 2 * 86400 });
  } catch (e) {
    /* the send happened; a missed count only errs one high */
  }
  return 'sent';
}

// The welcome (signup and backlog): 'sent', 'capped', 'failed', or 'off'
// (not configured). Only 'sent' marks the signup welcomedAt; 'failed' counts a
// failure (E4); 'capped' changes nothing and simply waits.
export async function sendWelcomeEmail(email, lang, env) {
  // Not configured yet: store the signup, send nothing. Without the
  // unsubscribe secret there is no honest unsubscribe link, so no mail either.
  if (!env.RESEND_API_KEY || !env.UNSUBSCRIBE_SECRET) return 'off';
  const { message } = welcomeEmail(email, lang, await unsubscribeToken(email, env.UNSUBSCRIBE_SECRET));
  const result = await sendViaResend(env, message);
  if (result === 'capped') return result; // waits for the backlog
  const ok = result === 'sent';
  try {
    const stored = await env.LAUNCH_EMAILS.get(email);
    if (!stored) return result; // unsubscribed meanwhile: do not bring the address back
    const record = JSON.parse(stored);
    if (ok) {
      record.welcomedAt = new Date().toISOString();
    } else {
      record.failures = (record.failures || 0) + 1;
      record.lastFailedAt = new Date().toISOString();
    }
    await env.LAUNCH_EMAILS.put(email, JSON.stringify(record));
  } catch (e) {
    /* the record could not be updated; the send result still stands */
  }
  return result;
}

// Everyone who signed up before the key existed, or whose welcome failed,
// gets it once (plan v3.7: "until then signups are kept and sent the welcome
// once it works"). POST, guarded by EXPORT_SECRET like the export. Dry run
// unless the body says send=1; at most BACKLOG_BATCH sends per call (Workers
// cap subrequests per request), so call it again until remaining is 0.
export const BACKLOG_BATCH = 40;

export async function handleWelcomeBacklog(request, env) {
  const form = await request.formData().catch(() => null);
  const key = form?.get('key');
  if (!env.EXPORT_SECRET || !key || key !== env.EXPORT_SECRET) {
    return new Response('Unauthorized', { status: 401 });
  }
  const send = form.get('send') === '1';
  if (send && (!env.RESEND_API_KEY || !env.UNSUBSCRIBE_SECRET)) {
    return Response.json({ error: 'RESEND_API_KEY or UNSUBSCRIBE_SECRET is not set; nothing can be sent' },
      { status: 409 });
  }
  const waiting = [];
  let givenUp = 0;
  let cursor = null;
  do {
    const list = await env.LAUNCH_EMAILS.list(cursor ? { cursor } : {});
    for (const entry of list.keys) {
      if (!isSignupKey(entry.name)) continue;
      const value = await env.LAUNCH_EMAILS.get(entry.name);
      if (!value) continue;
      let record;
      try { record = JSON.parse(value); } catch { continue; }
      if (record.welcomedAt) continue;
      if ((record.failures || 0) >= MAX_FAILURES) givenUp += 1;
      else waiting.push(record);
    }
    cursor = list.list_complete ? null : list.cursor;
  } while (cursor);

  // Never-failed first, then the least-failed: refused addresses go last.
  waiting.sort((a, b) => (a.failures || 0) - (b.failures || 0));
  if (!send) return Response.json({ dryRun: true, waiting: waiting.length, givenUp, dailyCap: dailyCap(env) });

  // Never past today's cap (E6): what is left waits for tomorrow's call.
  const room = Math.max(0, dailyCap(env) - (await sentToday(env, new Date())));
  let sent = 0;
  let failed = 0;
  let capped = false;
  for (const record of waiting.slice(0, Math.min(BACKLOG_BATCH, room))) {
    const result = await sendWelcomeEmail(record.email, record.lang || 'en', env);
    if (result === 'sent') sent += 1;
    else if (result === 'capped') { capped = true; break; } // today is done; carry on tomorrow
    else failed += 1;
  }
  return Response.json({ dryRun: false, sent, failed, remaining: waiting.length - sent, givenUp,
    capReached: capped || (room <= BACKLOG_BATCH && waiting.length > room) });
}

