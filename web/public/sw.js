const STATIC_CACHE = "lifeos-static-v2";
const SHARE_CACHE = "lifeos-share-inbox-v1";
const SHARE_KEY = "/__lifeos_pending_share__";
const SHARE_TTL_MS = 15 * 60 * 1000;
let lastFocusedClientId = null;
const APP_SHELL = [
  "/",
  "/capture",
  "/manifest.webmanifest",
  "/favicon.svg",
  "/icons/pwa-192.png",
  "/icons/pwa-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(STATIC_CACHE);
    await cache.addAll(APP_SHELL);
    const response = await fetch("/");
    const html = await response.text();
    const assets = Array.from(html.matchAll(/(?:src|href)="(\/assets\/[^"]+)"/g), (match) => match[1]);
    if (assets.length) await cache.addAll(assets);
  })());
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((key) => key.startsWith("lifeos-static-") && key !== STATIC_CACHE)
            .map((key) => caches.delete(key)),
        ),
      )
      .then(() => self.clients.claim()),
  );
});

async function staticAsset(request) {
  const url = new URL(request.url);
  return (
    url.origin === self.location.origin &&
    request.method === "GET" &&
    (url.pathname.startsWith("/assets/") || url.pathname.startsWith("/icons/") || url.pathname === "/manifest.webmanifest" || url.pathname === "/favicon.svg")
  );
}

self.addEventListener("fetch", async (event) => {
  const request = event.request;
  const url = new URL(request.url);

  if (request.method === "POST" && url.origin === self.location.origin && url.pathname === "/share-target") {
    event.respondWith(receiveShare(request));
    return;
  }

  if (await staticAsset(request)) {
    event.respondWith(
      caches.open(STATIC_CACHE).then((cache) =>
        cache.match(request.url).then((cached) => {
          if (cached) return cached;
          return fetch(request).then((response) => {
            if (response.ok) cache.put(request, response.clone());
            return response;
          });
        }),
      ),
    );
    return;
  }

  if (request.method === "GET" && request.mode === "navigate" && url.origin === self.location.origin) {
    event.respondWith(
      fetch(request)
        .then((response) => response)
        .catch(() => caches.match(url.href).then((cached) => cached || caches.match("/"))),
    );
  }
});

function cleanPart(value, limit) {
  return typeof value === "string" ? value.trim().slice(0, limit) : "";
}

async function receiveShare(request) {
  const form = await request.formData();
  const shared = {
    title: cleanPart(form.get("title"), 200),
    text: cleanPart(form.get("text"), 20000),
    url: cleanPart(form.get("url"), 2000),
    receivedAt: new Date().toISOString(),
    expiresAt: Date.now() + SHARE_TTL_MS,
  };
  const cache = await caches.open(SHARE_CACHE);
  await cache.put(SHARE_KEY, new Response(JSON.stringify(shared), { headers: { "Content-Type": "application/json" } }));
  const clients = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
  if (clients.length) {
    let client = lastFocusedClientId ? await self.clients.get(lastFocusedClientId).catch(() => null) : null;
    if (!client) client = clients.find((item) => item.focused) || clients[0];
    const navigated = await client.navigate("/capture?shared=1").catch(() => null);
    if (!navigated) {
      await Promise.all(clients.map((item) => item.postMessage({ type: "lifeos-share", payload: shared })));
    }
    return new Response(null, { status: 204 });
  }
  return Response.redirect(new URL("/capture?shared=1", self.location.origin).href, 303);
}

self.addEventListener("message", (event) => {
  if (event.data?.type === "lifeos-focus" && event.source?.id) lastFocusedClientId = event.source.id;
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = event.notification.data && event.notification.data.url ? event.notification.data.url : "/";
  event.waitUntil((async () => {
    const clients = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    const client = clients.find((item) => item.focused) || clients[0];
    if (client) {
      await client.focus();
      await client.navigate(target);
      return;
    }
    await self.clients.openWindow(target);
  })());
});
