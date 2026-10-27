// Données de l'app (L2-03) : remplace le runtime dash.* du prototype. Chaque vue demande les
// routes dont elle a besoin avec use(path) ; la première demande lance la requête, la réponse
// redessine. Les paramètres (mois, période, filtres) vivent ici, jamais dans les données.

export class ApiError extends Error {
  constructor(message, status, type) {
    super(message);
    this.status = status;
    this.type = type;
  }
}

export async function api(path, body) {
  const res = await fetch(`/api${path}`, {
    method: body === undefined ? "GET" : "POST",
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    credentials: "same-origin",
  });
  if (res.status === 204) return null;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(data.title || `Erreur ${res.status}`, res.status, data.type);
  return data;
}

// Mois civil à Zurich : le serveur ne déduit jamais « ce mois » des données.
export function currentMonth(now = new Date()) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Europe/Zurich", year: "numeric", month: "2-digit",
  }).formatToParts(now);
  const get = (t) => parts.find((p) => p.type === t).value;
  return `${get("year")}-${get("month")}`;
}

export function shiftMonth(month, delta) {
  const [y, m] = month.split("-").map(Number);
  const i = y * 12 + (m - 1) + delta;
  return `${Math.floor(i / 12)}-${String((i % 12) + 1).padStart(2, "0")}`;
}

const DEFAULTS = { tab: "accueil", range: "12", mode: "chf", env: "all", period: "m", tx: "all", q: "", look: "region" };

function remembered() {
  try {
    return JSON.parse(localStorage.getItem("hub.params") || "{}");
  } catch {
    return {};
  }
}

class Store {
  constructor() {
    this.cache = new Map();
    this.listeners = new Set();
    const saved = remembered();
    this.params = { ...DEFAULTS, ...saved, month: currentMonth() };
    this.today = currentMonth();
    this.pending = false;
  }

  // { status: "loading" | "ok" | "error", data, error }
  use(path) {
    let entry = this.cache.get(path);
    if (!entry) {
      entry = { status: "loading", data: null, error: null };
      this.cache.set(path, entry);
      api(path)
        .then((data) => Object.assign(entry, { status: "ok", data }))
        .catch((error) => {
          Object.assign(entry, { status: "error", error });
          // session expirée : l'app revient à l'écran de connexion
          if (error.status === 401) window.dispatchEvent(new Event("hub:auth"));
        })
        .finally(() => this.notify());
    }
    return entry;
  }

  // une valeur prête, ou null
  data(path) {
    const e = this.use(path);
    return e.status === "ok" ? e.data : null;
  }

  set(changes) {
    Object.assign(this.params, changes);
    try {
      const { range, mode, env, period, tab } = this.params;
      localStorage.setItem("hub.params", JSON.stringify({ range, mode, env, period, tab }));
    } catch {
      /* navigation privée : rien à retenir */
    }
    this.notify();
  }

  invalidate() {
    this.cache.clear();
    this.today = currentMonth();
    this.notify();
  }

  on(fn) {
    this.listeners.add(fn);
  }

  // regroupe les réponses arrivées dans la même trame
  notify() {
    if (this.pending) return;
    this.pending = true;
    requestAnimationFrame(() => {
      this.pending = false;
      for (const fn of this.listeners) fn();
    });
  }
}

export const store = new Store();
