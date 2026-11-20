// Security headers on EVERY response the worker sends (Story 18.10), from this
// one list, never per page. Same shape as the Sorting History site
// (SortingHistory-mkt/src/index.js, SECURITY_HEADERS + withSecurityHeaders()).
// wrangler.toml run_worker_first = true sends every request through the
// worker, files included, so no separate _headers file is needed.
//
// The CSP is REPORT-ONLY first: browsers POST what it would have blocked to
// /api/csp-report (logged, 2000 characters at most, stored nowhere, 204). It
// is enforced only after about a week of reports from the live site.
// frame-ancestors is enforced from the start (report-only cannot enforce it).
//
// Trimmed to what the site actually loads (checked 2026-11-20): our own
// scripts, stylesheet and images, and fetch('/api/subscribe'). No fonts,
// frames, analytics or third-party scripts. 'unsafe-inline' for styles only:
// the worker's unsubscribe page carries an inline <style>, the home page one
// style="" attribute. Scripts are 'self' only: no served page may carry an
// inline <script> (scripts/test_security.mjs checks every page).

export const CSP_REPORT_ONLY = [
  "default-src 'self'",
  "script-src 'self'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self'",
  "font-src 'self'",
  "connect-src 'self'",
  "frame-src 'none'",
  "frame-ancestors 'self'",
  "base-uri 'self'",
  "form-action 'self'",
  "object-src 'none'",
  'report-uri /api/csp-report',
].join('; ');

export const SECURITY_HEADERS = {
  'Strict-Transport-Security': 'max-age=31536000',
  'Referrer-Policy': 'strict-origin-when-cross-origin',
  'X-Content-Type-Options': 'nosniff',
  'X-Frame-Options': 'SAMEORIGIN',
  'Content-Security-Policy': "frame-ancestors 'self'",
  'Content-Security-Policy-Report-Only': CSP_REPORT_ONLY,
};

export function withSecurityHeaders(response) {
  const out = new Response(response.body, response);
  for (const [k, v] of Object.entries(SECURITY_HEADERS)) out.headers.set(k, v);
  return out;
}

// Browsers report CSP violations here. Logged (Cloudflare's worker logs, at
// most 2000 characters), stored nowhere, answered 204.
//  - The body is read from the stream up to REPORT_MAX_BYTES and refused (413)
//    past it, whatever Content-Length says or omits (review H1: a chunked POST
//    had no length and was read whole).
//  - Every URL in it loses its query string and fragment before logging
//    (review H2): a report from the unsubscribe page carries ?email=…&t=…,
//    which must never reach a log, even if Workers Logs is turned on later.
export const CSP_REPORT_LOG_CHARS = 2000;
export const REPORT_MAX_BYTES = 8192;

async function readCapped(request, max) {
  if (!request.body) return '';
  const reader = request.body.getReader();
  const chunks = [];
  let size = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > max) {
      await reader.cancel();
      return null;
    }
    chunks.push(value);
  }
  const all = new Uint8Array(size);
  let at = 0;
  for (const c of chunks) { all.set(c, at); at += c.byteLength; }
  return new TextDecoder().decode(all);
}

// Any URL keeps its scheme, host and path only. The scheme is bounded (at
// most 32 characters) so the scan stays linear: an unbounded one is retried
// from every position of a long run of letters, which grows with the square
// of the body and could exhaust the worker's CPU on one report.
export function stripQueries(text) {
  return text.replace(/([a-z][a-z0-9+.-]{0,31}:\/\/[^\s"'?#]*)[?#][^\s"']*/gi, '$1');
}

export async function handleCspReport(request) {
  if (Number(request.headers.get('Content-Length') || 0) > REPORT_MAX_BYTES) {
    return new Response(null, { status: 413 });
  }
  const body = await readCapped(request, REPORT_MAX_BYTES);
  if (body === null) return new Response(null, { status: 413 });
  console.log('csp-report', stripQueries(body).slice(0, CSP_REPORT_LOG_CHARS));
  return new Response(null, { status: 204 });
}
