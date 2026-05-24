/**
 * Cloudflare Pages middleware — gates the WHOLE site (dashboard + /api/*)
 * behind one shared ID + password (HTTP Basic Auth).
 *
 * The browser shows a native username/password prompt and remembers it for the
 * session, so the team just needs the one ID/password you share with them.
 *
 * Set these as environment variables on the Pages project (Settings → Variables):
 *   AUTH_USER  - the shared username
 *   AUTH_PASS  - the shared password
 * (mark them as encrypted/secret). Keep them ASCII.
 */

function timingSafeEqual(a, b) {
  if (a.length !== b.length) return false;
  let out = 0;
  for (let i = 0; i < a.length; i++) out |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return out === 0;
}

export async function onRequest(context) {
  const { request, env, next } = context;

  // If creds aren't configured yet, fail safe (locked) with a clear message.
  if (!env.AUTH_USER || !env.AUTH_PASS) {
    return new Response(
      "Login not configured. Set AUTH_USER and AUTH_PASS env vars on this Pages project.",
      { status: 503 }
    );
  }

  const header = request.headers.get("Authorization") || "";
  if (header.startsWith("Basic ")) {
    let decoded = "";
    try { decoded = atob(header.slice(6)); } catch (e) { decoded = ""; }
    const i = decoded.indexOf(":");
    const user = i >= 0 ? decoded.slice(0, i) : "";
    const pass = i >= 0 ? decoded.slice(i + 1) : "";
    if (timingSafeEqual(user, env.AUTH_USER) && timingSafeEqual(pass, env.AUTH_PASS)) {
      return next(); // authenticated — serve the page / run the API
    }
  }

  return new Response("Authentication required.", {
    status: 401,
    headers: {
      "WWW-Authenticate": 'Basic realm="The Garage — Fleet Papers", charset="UTF-8"',
      "Content-Type": "text/plain; charset=utf-8",
    },
  });
}
