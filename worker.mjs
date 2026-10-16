const LIVE_HOST = "pol.neilennis.com";

async function assetJson(env, url, path) {
  const response = await env.ASSETS.fetch(new URL(path, url));
  if (!response.ok) throw new Error(`Missing site data: ${path}`);
  return response.json();
}

function redirect(destination, requestUrl, status = 301) {
  const target = new URL(destination, requestUrl);
  // Same-site aliases should remain on the preview host while it is reviewed.
  if (target.hostname === LIVE_HOST && requestUrl.hostname !== LIVE_HOST) {
    target.hostname = requestUrl.hostname;
  }
  return Response.redirect(target, status);
}

function previewHeader(response, url) {
  if (!url.hostname.endsWith(".workers.dev")) return response;
  const result = new Response(response.body, response);
  result.headers.set("X-Robots-Tag", "noindex, nofollow");
  return result;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.hostname === `www.${LIVE_HOST}`) {
      url.hostname = LIVE_HOST;
      return Response.redirect(url, 301);
    }

    let response;
    const oldId = url.pathname === "/"
      ? (url.searchParams.get("p") || url.searchParams.get("page_id"))
      : /^\/p\/(\d+)\/?$/.exec(url.pathname)?.[1];
    if (oldId && /^\d+$/.test(oldId)) {
      try {
        const map = await assetJson(env, url, "/postmap.json");
        if (map[oldId]) response = redirect(map[oldId], url);
      } catch {
        response = new Response("Shortlink map unavailable", { status: 503 });
      }
    }

    if (!response && url.pathname === "/feed/") response = redirect("/feed.xml", url);
    if (!response && url.pathname === "/wp-sitemap.xml") response = redirect("/sitemap.xml", url);
    if (!response && url.pathname.startsWith("/index.php/")) {
      response = redirect(url.pathname.slice("/index.php".length) + url.search, url);
    }
    if (!response) {
      try {
        const map = await assetJson(env, url, "/redirects.json");
        if (map[url.pathname]) response = redirect(map[url.pathname], url);
      } catch {
        response = new Response("Redirect map unavailable", { status: 503 });
      }
    }
    if (!response) response = await env.ASSETS.fetch(request);
    return previewHeader(response, url);
  },
};
