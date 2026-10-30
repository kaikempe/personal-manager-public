// Inbox for finished workouts. The phone POSTs a session; the Mac (scripts/gym_pull.py) lists and then deletes it.
// Every call needs "Authorization: Bearer $GYM_TOKEN" (Netlify env var). Sessions are validated again by gym_ingest.py.
import { getStore } from "@netlify/blobs";
import { timingSafeEqual } from "node:crypto";

const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
const ID = /^[\w.-]{4,80}$/;

function authorised(req) {
  const token = Netlify.env.get("GYM_TOKEN");
  if (!token) return false;
  const got = Buffer.from(req.headers.get("authorization") || "");
  const want = Buffer.from(`Bearer ${token}`);
  return got.length === want.length && timingSafeEqual(got, want);
}

export default async (req) => {
  if (!authorised(req)) return json({ error: "unauthorised" }, 401);
  const store = getStore("gym-sessions");

  if (req.method === "POST") {
    const text = await req.text();
    if (text.length > 100_000) return json({ error: "too large" }, 413);
    let s;
    try { s = JSON.parse(text); } catch { return json({ error: "not JSON" }, 400); }
    if (!s || typeof s.id !== "string" || !ID.test(s.id)) return json({ error: "bad id" }, 400);
    await store.setJSON(s.id, s);
    return json({ ok: true, id: s.id });
  }
  if (req.method === "GET") {
    const { blobs } = await store.list();
    const sessions = [];
    for (const b of blobs) {
      const s = await store.get(b.key, { type: "json" });
      if (s) sessions.push(s);
    }
    return json({ sessions });
  }
  if (req.method === "DELETE") {
    const id = new URL(req.url).searchParams.get("id") || "";
    if (!ID.test(id)) return json({ error: "bad id" }, 400);
    await store.delete(id);
    return json({ ok: true });
  }
  return json({ error: "method not allowed" }, 405);
};

export const config = { path: "/api/session" };
