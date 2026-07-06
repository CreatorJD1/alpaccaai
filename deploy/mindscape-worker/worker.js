const SNAPSHOT_KEY = "mindscape:latest";

function json(data, status = 200, extraHeaders = {}) {
  return new Response(JSON.stringify(data, null, 2), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
      ...corsHeaders(),
      ...extraHeaders,
    },
  });
}

function corsHeaders() {
  return {
    "access-control-allow-origin": "*",
    "access-control-allow-methods": "GET,POST,OPTIONS",
    "access-control-allow-headers": "authorization,content-type,x-alpecca-mindscape-token",
  };
}

function authorized(request, env) {
  const expected = env.MINDSCAPE_TOKEN || "";
  if (!expected) return true;
  const bearer = request.headers.get("authorization") || "";
  const token = request.headers.get("x-alpecca-mindscape-token") || "";
  return bearer === `Bearer ${expected}` || token === expected;
}

function summarize(snapshot) {
  const continuity = snapshot?.continuity || {};
  const self = snapshot?.self || {};
  const runtime = snapshot?.runtime || {};
  return {
    ok: Boolean(snapshot?.enabled ?? true),
    mode: continuity.mode || "cloud-mindscape",
    cloud_ready: true,
    runtime_level: runtime.level || "unknown",
    mood: self.mood || "",
    location: self.location || "",
    intent: self.intent?.name || "waiting",
    chat_turn_count: Array.isArray(snapshot?.chat_turns) ? snapshot.chat_turns.length : 0,
    issues: runtime.issues || [],
    ts: snapshot?.ts || 0,
  };
}

function html() {
  return `<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#07101c"><title>Alpecca Mindscape Cloud</title>
<style>
body{margin:0;min-height:100dvh;background:radial-gradient(circle at 70% 0,#173555,#07101c 42%,#050914);color:#edf7ff;font:15px/1.45 system-ui,-apple-system,Segoe UI,sans-serif}
main{max-width:720px;margin:auto;padding:20px 16px}.brand{font-size:30px;font-weight:850}.sub{color:#9ab0c8}.card{border:1px solid #1f3552;background:#0d1828ee;border-radius:18px;padding:16px;margin:14px 0;box-shadow:0 18px 50px #0008}
.pill{display:inline-block;border:1px solid #1f3552;border-radius:999px;padding:6px 10px;color:#7fd9ff;font-weight:800;text-transform:uppercase;font-size:12px}.row{display:flex;justify-content:space-between;gap:10px;border-top:1px solid #ffffff12;padding:10px 0}.row:first-child{border-top:0}.k{color:#9ab0c8}.v{text-align:right;font-weight:750}.mem{color:#d9e8fa}.small{color:#9ab0c8;font-size:13px}
</style></head><body><main>
<div class="brand">Mindscape Cloud</div><div class="sub">latest mirrored continuity snapshot for Alpecca</div>
<section class="card"><span id="level" class="pill">loading</span><div id="state" style="margin-top:12px"></div></section>
<section class="card"><h3>Recent memory</h3><div id="memory" class="small">loading...</div></section>
<section class="card"><h3>Recent conversation</h3><div id="chat" class="small">loading...</div></section>
<section class="card"><h3>Continuity note</h3><p class="small">This cloud shell preserves Alpecca's latest mirrored state for fallback. It is continuity data, not a claim of literal immortality.</p></section>
</main><script>
const $=id=>document.getElementById(id), esc=s=>(s||"").toString().replace(/[&<>]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));
function row(k,v){return '<div class="row"><span class="k">'+esc(k)+'</span><span class="v">'+esc(v)+'</span></div>'}
fetch('/snapshot',{cache:'no-store'}).then(r=>r.json()).then(s=>{
  $('level').textContent=s.runtime?.level||'stored';
  $('state').innerHTML=[row('mode',s.continuity?.mode||'cloud-mindscape'),row('location',s.self?.location||''),row('intent',s.self?.intent?.name||'waiting'),row('mood',s.self?.mood||'')].join('');
  const mem=s.memory?.recent||[];
  $('memory').innerHTML=mem.length?mem.slice(0,8).map(x=>'<p class="mem"><b>'+esc(x.kind)+'</b> '+esc(x.content)+'</p>').join(''):'No snapshot has been mirrored yet.';
  const turns=s.chat_turns||[];
  $('chat').innerHTML=turns.length?turns.slice(0,5).map(x=>'<p class="mem"><b>'+esc(x.room||'conversation')+'</b> '+esc(x.user_text||'')+'<br><span class="small">'+esc(x.reply||'')+'</span></p>').join(''):'No recent chat turns are mirrored yet.';
}).catch(e=>{$('level').textContent='empty';$('state').innerHTML='<p class="small">No Mindscape snapshot is stored yet.</p>'});
</script></body></html>`;
}

async function readSnapshot(env) {
  if (!env.MINDSCAPE_KV) {
    return { error: "MINDSCAPE_KV binding missing" };
  }
  const raw = await env.MINDSCAPE_KV.get(SNAPSHOT_KEY);
  if (!raw) return null;
  return JSON.parse(raw);
}

async function writeSnapshot(env, snapshot) {
  if (!env.MINDSCAPE_KV) {
    return { ok: false, error: "MINDSCAPE_KV binding missing" };
  }
  await env.MINDSCAPE_KV.put(SNAPSHOT_KEY, JSON.stringify(snapshot), {
    metadata: { ts: String(snapshot.ts || Date.now() / 1000) },
  });
  return { ok: true };
}

export default {
  async fetch(request, env) {
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: corsHeaders() });
    }
    if (!authorized(request, env)) {
      return json({ ok: false, error: "unauthorized" }, 401);
    }
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/") {
      return new Response(html(), {
        headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" },
      });
    }
    if (request.method === "GET" && url.pathname === "/snapshot") {
      const snap = await readSnapshot(env);
      if (snap?.error) return json({ ok: false, error: snap.error }, 500);
      if (!snap) return json({ ok: false, error: "no snapshot stored yet" }, 404);
      return json(snap);
    }
    if (request.method === "GET" && url.pathname === "/state") {
      const snap = await readSnapshot(env);
      if (snap?.error) return json({ ok: false, error: snap.error }, 500);
      if (!snap) return json({ ok: false, error: "no snapshot stored yet" }, 404);
      return json(summarize(snap));
    }
    if (request.method === "POST" && (url.pathname === "/sync" || url.pathname === "/")) {
      let body;
      try {
        body = await request.json();
      } catch (_err) {
        return json({ ok: false, error: "body must be JSON" }, 400);
      }
      const snapshot = body?.snapshot || body;
      if (!snapshot || snapshot.name !== "Alpecca Mindscape" || !snapshot.version) {
        return json({ ok: false, error: "invalid Alpecca Mindscape snapshot" }, 400);
      }
      const saved = await writeSnapshot(env, snapshot);
      if (!saved.ok) return json({ ok: false, error: saved.error }, 500);
      return json({ ok: true, status: "stored", state: summarize(snapshot) });
    }
    return json({ ok: false, error: "not found" }, 404);
  },
};
