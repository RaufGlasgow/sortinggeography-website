// How the worker serves pages (Story 18.8): stamps the launch state from the
// one constant in src/launch.js. Kept apart from worker.js so a test can drive
// it with a fake asset store and a fake HTMLRewriter (scripts/test_launch.mjs).

import { launchState } from './launch.js';

// Pages: stamp the launch state. Everything else passes straight through.
//
// Conditional headers are dropped for pages and the validators removed from the
// answer: otherwise a browser holding the pre-launch copy sends If-None-Match,
// the asset layer answers 304 (the FILE has not changed), and the visitor keeps
// seeing the countdown after the moment. Pages are a few kilobytes; always
// sending them whole is the honest trade.
export async function serveAsset(request, env, nowMs) {
  const accept = request.headers.get('Accept') || '';
  const looksLikePage = request.method === 'GET' &&
    (accept.includes('text/html') || !/\.[a-z0-9]+$/i.test(new URL(request.url).pathname) ||
     new URL(request.url).pathname.endsWith('.html'));
  if (!looksLikePage) return env.ASSETS.fetch(request);

  const headers = new Headers(request.headers);
  headers.delete('If-None-Match');
  headers.delete('If-Modified-Since');
  const response = await env.ASSETS.fetch(new Request(request, { headers }));
  if (!(response.headers.get('Content-Type') || '').includes('text/html')) return response;
  return stampLaunch(response, nowMs);
}

export function stampLaunch(response, nowMs, Rewriter = globalThis.HTMLRewriter) {
  const out = new Response(response.body, response);
  out.headers.delete('ETag');
  out.headers.delete('Last-Modified');
  out.headers.set('Cache-Control', 'no-cache');
  // The body changes length (attributes added, comments removed).
  out.headers.delete('Content-Length');
  const state = launchState(nowMs);
  return new Rewriter()
    // No served page carries an HTML comment (18.9b B5, 18.9c). The source
    // pages keep theirs: build markers (`<!-- launch:NAME -->`,
    // `<!-- feature:NAME -->`) and notes for whoever edits the page, none of
    // it for a visitor. HTMLRewriter's own parser finds the comments, so a
    // '<!--' inside a script or an attribute is never mistaken for one.
    // scripts/check_comments.py refuses such text in the source anyway, and
    // scripts/test_served.mjs fetches every page from the real worker.
    .onDocument({
      comments(comment) {
        comment.remove();
      },
    })
    .on('html', {
      element(el) {
        el.setAttribute('data-launch', state);
        // The server's clock, so the page's own countdown is not fooled by a
        // visitor whose clock is wrong.
        el.setAttribute('data-now', String(nowMs));
      },
    })
    .transform(out);
}
