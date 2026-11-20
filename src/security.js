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
// most 2000 characters), stored nowhere, answered 204. A body over 8 KB is
// refused unread.
export const CSP_REPORT_LOG_CHARS = 2000;

export async function handleCspReport(request) {
  const length = Number(request.headers.get('Content-Length') || 0);
  if (length > 8192) return new Response(null, { status: 413 });
  const body = (await request.text()).slice(0, CSP_REPORT_LOG_CHARS);
  console.log('csp-report', body);
  return new Response(null, { status: 204 });
}
