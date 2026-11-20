// Unsubscribe tokens (18.5 review E2): an HMAC-SHA256 of the address, keyed
// by UNSUBSCRIBE_SECRET, so only the person holding a real email from us can
// remove that address. No secret, no token: the caller must refuse.

const enc = new TextEncoder();

async function key(secret) {
  return crypto.subtle.importKey('raw', enc.encode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
}

function b64url(buf) {
  let s = '';
  for (const b of new Uint8Array(buf)) s += String.fromCharCode(b);
  return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

export async function unsubscribeToken(email, secret) {
  if (!secret) throw new Error('UNSUBSCRIBE_SECRET is not set');
  return b64url(await crypto.subtle.sign('HMAC', await key(secret), enc.encode(email)));
}

export async function tokenValid(email, token, secret) {
  if (!secret || !email || typeof token !== 'string' || token.length === 0) return false;
  const want = await unsubscribeToken(email, secret);
  if (want.length !== token.length) return false;
  let diff = 0; // constant time over equal lengths
  for (let i = 0; i < want.length; i += 1) diff |= want.charCodeAt(i) ^ token.charCodeAt(i);
  return diff === 0;
}
