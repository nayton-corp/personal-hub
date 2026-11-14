// Service worker minimal : met en cache la coquille de l'app, jamais les réponses de l'API.
const CACHE = "hub-shell-v38";
// la coquille seule : les modules des domaines (/d/<domaine>/…) se gardent au premier chargement
const SHELL = ["/", "/index.html", "/app.js", "/shell.js", "/accueil.js", "/approvals.js", "/picks.js", "/assistant.js", "/orb.js", "/orb-shaders.js", "/assistant.css", "/sources.js", "/upkeep.js", "/store.js", "/ui.js",
  "/format.js", "/webauthn.js", "/theme.css", "/styles.css", "/fonts/ibm-plex-sans-latin-400-normal.woff2",
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
  // logos des domaines (/d/<domaine>/logos/…) : le cache d'abord, relu en fond. Recréés à chaque
  // rendu, ils clignotaient le temps d'un aller-retour au serveur, et disparaissaient quand il
  // ratait ; un logo changé par une mise à jour s'affiche au chargement suivant.
  if (/^\/d\/[^/]+\/logos\//.test(url.pathname)) {
    event.respondWith(logo(event));
    return;
  }
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

// un logo est relu au serveur une fois par vie du service worker, pas à chaque rendu ; seule une
// image est gardée (un fichier absent répond par la page de l'app)
const relu = new Set();
function logo(event) {
  return caches.open(CACHE).then((c) =>
    c.match(event.request).then((hit) => {
      if (hit && relu.has(event.request.url)) return hit;
      relu.add(event.request.url);
      const fresh = fetch(event.request).then((res) => {
        if (res.ok && (res.headers.get("content-type") || "").startsWith("image/")) c.put(event.request, res.clone());
        return res;
      });
      if (!hit) return fresh;
      event.waitUntil(fresh.catch(() => relu.delete(event.request.url)));
      return hit;
    }),
  );
}
