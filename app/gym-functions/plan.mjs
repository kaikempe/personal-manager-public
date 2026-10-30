// The plan and exercise history the phone app shows. The Mac (scripts/gym_pull.py) PUTs them whenever they change;
// the app GETs them on open. PUT and the history need the Bearer token (same as /api/session); the plan alone is
// public so the app works even before the key is entered (exercise names, weights and the gym dates, nothing else).
import { getStore } from "@netlify/blobs";
import { timingSafeEqual } from "node:crypto";

const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", "cache-control": "no-store" } });

function authorised(req) {
  const token = Netlify.env.get("GYM_TOKEN");
  if (!token) return false;
  const got = Buffer.from(req.headers.get("authorization") || "");
  const want = Buffer.from(`Bearer ${token}`);
  return got.length === want.length && timingSafeEqual(got, want);
}

export default async (req) => {
  const store = getStore("gym-data");
  if (req.method === "GET") {
    const d = (await store.get("current", { type: "json" })) || {};
    return json(authorised(req) ? d : { plan: d.plan });
  }
  if (!authorised(req)) return json({ error: "unauthorised" }, 401);
  if (req.method === "PUT") {
    const text = await req.text();
    if (text.length > 500_000) return json({ error: "too large" }, 413);
    let d;
    try { d = JSON.parse(text); } catch { return json({ error: "not JSON" }, 400); }
    if (!d || typeof d.plan !== "object" || !d.plan.days) return json({ error: "bad plan" }, 400);
    await store.setJSON("current", { plan: d.plan, history: d.history || {} });
    return json({ ok: true });
  }
  return json({ error: "method not allowed" }, 405);
};

export const config = { path: "/api/plan" };
