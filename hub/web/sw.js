// Service worker minimal : met en cache la coquille de l'app, jamais les réponses de l'API.
const CACHE = "hub-shell-v31";
// la coquille seule : les modules des domaines (/d/<domaine>/…) se gardent au premier chargement
const SHELL = ["/", "/index.html", "/app.js", "/shell.js", "/accueil.js", "/approvals.js", "/sources.js", "/store.js", "/ui.js",
  "/format.js", "/webauthn.js", "/styles.css", "/fonts/ibm-plex-sans-latin-400-normal.woff2",
  "/fonts/ibm-plex-sans-latin-500-normal.woff2", "/fonts/ibm-plex-sans-latin-600-normal.woff2",
  "/fonts/ibm-plex-sans-latin-700-normal.woff2", "/fonts/ibm-plex-mono-latin-500-normal.woff2",
  "/manifest.webmanifest", "/icons/icon-192.png"];

self.addEventListener("install", (event) => {
  // « reload » : la copie hors ligne vient du serveur, jamais du cache HTTP du navigateur
  const fresh = SHELL.map((u) => new Request(u, { cache: "reload" }));
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(fresh)).then(() => self.skipWaiting()));
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
