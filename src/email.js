// The welcome email (Story 18.5), one template per language.
//
// Ready for the Resend key: nothing is sent until RESEND_API_KEY exists
// (src/worker.js). English only today; a language is added here, with the
// game's translation pipeline, in the release that ships it (18.4), and a
// signup in a language with no template gets English.
//
// The question count comes from src/facts.gen.js, which
// scripts/build_features.py writes from src/facts.json (checked against the
// game by --game), so the email cannot drift from the press page.
// Palette: the app's (forest green, ocean blue). No gold, no orange: CI's
// palette check scans src/*.js. scripts/test_email.mjs checks every template.

import { FACTS } from './facts.gen.js';

export const SITE = 'https://sortinggeography.com';
export const FROM = 'Sorting Geography <hello@sortinggeography.com>';

// The token (src/token.js) proves the link came from a real email of ours.
export function unsubscribeUrl(email, token) {
  return `${SITE}/api/unsubscribe?email=${encodeURIComponent(email)}&t=${encodeURIComponent(token)}`;
}

// Every word a translation supplies goes through esc(), so a '<' or '&' in a
// translated sentence can never break the layout.
export const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
  .replace(/>/g, '&gt;').replace(/"/g, '&quot;');

// Each language: the words only. Paragraphs are plain text; the layout below
// is shared, so a translation can never break the HTML.
const TEXT = {
  en: (f) => ({
    subject: 'You are on the list',
    heading: 'You are on the list',
    paragraphs: [
      'Thank you for signing up for Sorting Geography.',
      `It is a daily geography game: five countries, one question, put them in order. Tallest mountain, longest coastline, most rainfall: ${f.axes} ways to sort the world, all of it from named public sources, listed on our data sources page.`,
      // Ra'uf's own sentence, word for word, from the Sorting History welcome
      // email (sortinghistory-website-deploy/src/worker.js:266, his commit
      // 9dade19, 2026-02-11). Never reworded: it is his voice about his family.
      "I developed this game for my wife and family, and I hope you'll enjoy it as much as we do.",
      'We will write when it ships, and when new ways to sort arrive. Nothing else.',
    ],
    unsubscribe: 'Unsubscribe',
    unsubscribeNote: 'the address is deleted, not kept.',
  }),
};

export const LANGS = Object.keys(TEXT);

export function pickLang(requested) {
  return LANGS.includes(requested) ? requested : 'en';
}

export function welcomeEmail(email, lang, token) {
  if (!token) throw new Error('welcomeEmail needs the unsubscribe token');
  const code = pickLang(lang);
  const t = TEXT[code](FACTS);
  const unsub = unsubscribeUrl(email, token);
  const html = `<!doctype html>
<html lang="${code}"><head><meta charset="utf-8"></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',system-ui,sans-serif;background:#f5f1e6;color:#16150f;margin:0;padding:2rem;">
  <div style="max-width:32rem;margin:0 auto;background:#fffdf7;border:1px solid #d9d2bf;border-radius:20px;padding:2rem;">
    <h1 style="color:#103A22;font-size:1.35rem;margin-top:0;">${esc(t.heading)}</h1>
${t.paragraphs.map((p) => `    <p style="line-height:1.6;">${esc(p)}</p>`).join('\n')}
    <hr style="border:none;border-top:1px solid #d9d2bf;margin:1.5rem 0;">
    <p style="font-size:.85rem;color:#4a473c;"><a href="${esc(unsub)}" style="color:#1c4f6b;">${esc(t.unsubscribe)}</a> &mdash; ${esc(t.unsubscribeNote)}</p>
  </div>
</body></html>`;
  const text = [t.heading, '', ...t.paragraphs.flatMap((p) => [p, '']),
    `${t.unsubscribe} (${t.unsubscribeNote}): ${unsub}`, ''].join('\n');
  return {
    lang: code,
    message: {
      from: FROM,
      to: [email],
      subject: t.subject,
      html,
      text,
      // One-click unsubscribe (RFC 8058): mail clients show their own
      // unsubscribe button and POST to this URL; src/worker.js accepts it.
      headers: {
        'List-Unsubscribe': `<${unsub}>`,
        'List-Unsubscribe-Post': 'List-Unsubscribe=One-Click',
      },
    },
  };
}
