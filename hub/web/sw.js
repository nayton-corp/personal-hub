// Service worker minimal : met en cache la coquille de l'app, jamais les réponses de l'API.
const CACHE = "hub-shell-v8";
const SHELL = ["/", "/index.html", "/app.js", "/store.js", "/finance.js", "/proposals.js", "/charts.js",
  "/format.js", "/webauthn.js", "/styles.css", "/vendor/d3.v7.9.0.min.js",
  "/manifest.webmanifest", "/icons/icon-192.png"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin || url.pathname.startsWith("/api/")) return;
  if (event.request.method !== "GET") return;
  // réseau d'abord : l'app reste à jour, le cache ne sert qu'hors connexion
  event.respondWith(
    fetch(event.request)
      .then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(event.request, copy));
        return res;
      })
      .catch(() => caches.match(event.request).then((r) => r || caches.match("/index.html"))),
  );
});
