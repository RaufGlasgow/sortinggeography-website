// Sending the welcome email (Story 18.5): one message on signup, and the
// backlog for signups made before the Resend key. The words are src/email.js.
// Imported by src/worker.js; tested by scripts/test_email.mjs.

import { welcomeEmail } from './email.js';
import { unsubscribeToken } from './token.js';

// After this many refused sends an address is given up (18.5 review E4), so a
// few dead addresses can never block the backlog for everyone else.
export const MAX_FAILURES = 3;

// Resend, same as the Sorting History site; the template is src/email.js.
// Returns true only when Resend accepted the message (2xx), and only then is
// the signup marked welcomedAt, so a send that failed (domain not yet
// verified, bad key, outage) is picked up by the backlog send later.
export async function sendWelcomeEmail(email, lang, env) {
  // Not configured yet: store the signup, send nothing. Without the
  // unsubscribe secret there is no honest unsubscribe link, so no mail either.
  if (!env.RESEND_API_KEY || !env.UNSUBSCRIBE_SECRET) return false;
  const { message } = welcomeEmail(email, lang, await unsubscribeToken(email, env.UNSUBSCRIBE_SECRET));
  let ok = false;
  try {
    const res = await fetch('https://api.resend.com/emails', {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${env.RESEND_API_KEY}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(message),
    });
    ok = res.ok;
  } catch (e) {
    ok = false; // fire-and-forget: never fail a stored subscription because mail failed
  }
  try {
    const stored = await env.LAUNCH_EMAILS.get(email);
    if (!stored) return ok; // unsubscribed meanwhile: do not bring the address back
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
  return ok;
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
  if (!send) return Response.json({ dryRun: true, waiting: waiting.length, givenUp });

  let sent = 0;
  let failed = 0;
  for (const record of waiting.slice(0, BACKLOG_BATCH)) {
    if (await sendWelcomeEmail(record.email, record.lang || 'en', env)) sent += 1;
    else failed += 1;
  }
  return Response.json({ dryRun: false, sent, failed, remaining: waiting.length - sent, givenUp });
}

