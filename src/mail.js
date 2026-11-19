// Sending the welcome email (Story 18.5): one message on signup, and the
// backlog for signups made before the Resend key. The words are src/email.js.
// Imported by src/worker.js; tested by scripts/test_email.mjs.

import { welcomeEmail } from './email.js';

// Resend, same as the Sorting History site; the template is src/email.js.
// Returns true only when Resend accepted the message (2xx), and only then is
// the signup marked welcomedAt, so a send that failed (domain not yet
// verified, bad key, outage) is picked up by the backlog send later.
export async function sendWelcomeEmail(email, lang, env) {
  if (!env.RESEND_API_KEY) return false; // not configured yet - store the signup, send nothing
  const { message } = welcomeEmail(email, lang);
  try {
    const res = await fetch('https://api.resend.com/emails', {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${env.RESEND_API_KEY}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(message),
    });
    if (!res.ok) return false;
    const stored = await env.LAUNCH_EMAILS.get(email);
    if (!stored) return true; // unsubscribed meanwhile: do not bring the address back
    const record = JSON.parse(stored);
    record.welcomedAt = new Date().toISOString();
    await env.LAUNCH_EMAILS.put(email, JSON.stringify(record));
    return true;
  } catch (e) {
    return false; // fire-and-forget: never fail a stored subscription because mail failed
  }
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
  if (send && !env.RESEND_API_KEY) {
    return Response.json({ error: 'RESEND_API_KEY is not set; nothing can be sent' }, { status: 409 });
  }
  const waiting = [];
  let cursor = null;
  do {
    const list = await env.LAUNCH_EMAILS.list(cursor ? { cursor } : {});
    for (const entry of list.keys) {
      const value = await env.LAUNCH_EMAILS.get(entry.name);
      if (!value) continue;
      let record;
      try { record = JSON.parse(value); } catch { continue; }
      if (!record.welcomedAt) waiting.push(record);
    }
    cursor = list.list_complete ? null : list.cursor;
  } while (cursor);

  if (!send) return Response.json({ dryRun: true, waiting: waiting.length });

  let sent = 0;
  let failed = 0;
  for (const record of waiting.slice(0, BACKLOG_BATCH)) {
    if (await sendWelcomeEmail(record.email, record.lang || 'en', env)) sent += 1;
    else failed += 1;
  }
  return Response.json({ dryRun: false, sent, failed, remaining: waiting.length - sent });
}

