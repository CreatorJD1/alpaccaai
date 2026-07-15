const JSON_HEADERS = {
  "Content-Type": "application/json; charset=utf-8",
  "Cache-Control": "no-store",
};

function json(body, status) {
  return new Response(JSON.stringify(body), { status, headers: JSON_HEADERS });
}

function route(pathname, env) {
  if (pathname === "/lease" || pathname.startsWith("/lease/")) {
    return { binding: env.LEASE_SERVICE, prefix: "/lease" };
  }
  if (pathname === "/vault" || pathname.startsWith("/vault/")) {
    return { binding: env.VAULT_SERVICE, prefix: "/vault" };
  }
  return null;
}

export async function onRequest(context) {
  const url = new URL(context.request.url);
  if (url.pathname === "/healthz") {
    return json(
      { service: "alpecca-continuity-gateway", version: 1, state: "ready" },
      200,
    );
  }

  const target = route(url.pathname, context.env);
  if (!target) {
    return json({ detail: "not found" }, 404);
  }
  if (!target.binding || typeof target.binding.fetch !== "function") {
    return json({ detail: "service unavailable" }, 503);
  }

  url.pathname = url.pathname.slice(target.prefix.length) || "/";
  try {
    return await target.binding.fetch(new Request(url.toString(), context.request));
  } catch (_error) {
    return json({ detail: "service unavailable" }, 503);
  }
}
