/**
 * Cloudflare Pages Function — the document locker API.
 * Already gated by _middleware.js (shared ID/password), so any request that
 * reaches here is from an authenticated team member.
 *
 * Requires a KV namespace bound as `DOCS` (Settings → Functions → KV bindings).
 *
 *   GET  /api/files                  -> { ok, files:{ "vehicleId|DocType": {url,name,uploadedAt} } }
 *   GET  /api/files?get=<key>        -> streams the stored file (inline)
 *   POST /api/files  {action:'upload', vehicle_id, doc_type, filename, mimeType, dataBase64}
 *   POST /api/files  {action:'delete', vehicle_id, doc_type}
 *
 * Files are stored in KV as  doc:<key> = {name, mime, data(base64)}  and a single
 * __index__ entry holds the lightweight map the dashboard lists from.
 */

const INDEX_KEY = "__index__";
const MAX_BYTES = 12 * 1024 * 1024; // ~12 MB per file (KV value cap is 25 MiB)

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8" },
  });
}

async function getIndex(env) {
  return (await env.DOCS.get(INDEX_KEY, { type: "json" })) || {};
}

export async function onRequestGet({ request, env }) {
  if (!env.DOCS) return json({ ok: false, error: "KV namespace 'DOCS' not bound" }, 500);
  const url = new URL(request.url);
  const key = url.searchParams.get("get");

  if (key) {
    const doc = await env.DOCS.get("doc:" + key, { type: "json" });
    if (!doc) return new Response("Not found", { status: 404 });
    const bin = atob(doc.data);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    return new Response(bytes, {
      headers: {
        "Content-Type": doc.mime || "application/octet-stream",
        "Content-Disposition": `inline; filename="${(doc.name || "document").replace(/"/g, "")}"`,
        "Cache-Control": "private, no-store",
      },
    });
  }

  const index = await getIndex(env);
  const files = {};
  for (const [k, m] of Object.entries(index)) {
    files[k] = { url: "/api/files?get=" + encodeURIComponent(k), name: m.name, uploadedAt: m.uploadedAt };
  }
  return json({ ok: true, files });
}

export async function onRequestPost({ request, env }) {
  if (!env.DOCS) return json({ ok: false, error: "KV namespace 'DOCS' not bound" }, 500);

  let body;
  try { body = JSON.parse(await request.text()); }
  catch (e) { return json({ ok: false, error: "invalid JSON body" }, 400); }

  const vehicleId = String(body.vehicle_id || "").trim();
  const docType = String(body.doc_type || "").trim();
  if (!vehicleId || !docType) return json({ ok: false, error: "missing vehicle_id or doc_type" }, 400);
  const key = vehicleId + "|" + docType;

  if (body.action === "delete") {
    await env.DOCS.delete("doc:" + key);
    const index = await getIndex(env);
    delete index[key];
    await env.DOCS.put(INDEX_KEY, JSON.stringify(index));
    return json({ ok: true, removed: true });
  }

  // upload
  if (!body.dataBase64) return json({ ok: false, error: "no file data" }, 400);
  // base64 length * 3/4 ≈ byte size
  if (body.dataBase64.length * 0.75 > MAX_BYTES) {
    return json({ ok: false, error: "file too large (max ~12 MB)" }, 413);
  }

  await env.DOCS.put("doc:" + key, JSON.stringify({
    name: body.filename || docType,
    mime: body.mimeType || "application/octet-stream",
    data: body.dataBase64,
  }));

  const index = await getIndex(env);
  index[key] = {
    name: body.filename || docType,
    uploadedAt: new Date().toISOString(),
    size: Math.round(body.dataBase64.length * 0.75),
  };
  await env.DOCS.put(INDEX_KEY, JSON.stringify(index));

  return json({ ok: true, url: "/api/files?get=" + encodeURIComponent(key), name: body.filename || docType });
}
