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

// GET sans corps, POST avec ; `method` pour PATCH, PUT et DELETE (connexions, G5)
export async function api(path, body, method) {
  const res = await fetch(`/api${path}`, {
    method: method || (body === undefined ? "GET" : "POST"),
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    credentials: "same-origin",
  });
  if (res.status === 204) return null;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(data.title || `Erreur ${res.status}`, res.status, data.type);
  return data;
}

// Fuseau de l'instance, donné par le profil (HUB_TZ) ; Zurich jusqu'à sa réponse.
let zone = "Europe/Zurich";
export const timeZone = () => zone;
export function setTimeZone(tz) {
  const changed = Boolean(tz) && tz !== zone;
  if (changed) zone = tz;
  return changed;
}

// Jour où commence le mois budgétaire (réglage du hub, 1 par défaut) : après le 15, le mois
// porte le nom de sa fin, comme period.py côté serveur.
let startDay = 1;
export const monthStartDay = () => startDay;

// Mois budgétaire en cours, dans le fuseau de l'instance : le serveur ne le déduit jamais des
// données.
export function currentMonth(now = new Date(), day = startDay) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: zone, year: "numeric", month: "2-digit", day: "2-digit",
  }).formatToParts(now);
  const get = (t) => Number(parts.find((p) => p.type === t).value);
  let month = `${get("year")}-${String(get("month")).padStart(2, "0")}`;
  if (get("day") < day) month = shiftMonth(month, -1);
  return day > 15 ? shiftMonth(month, 1) : month;
}

// Bornes d'un mois budgétaire, dates comprises (period.bounds côté serveur, fin exclue).
export function monthSpan(month, day = startDay) {
  const first = day > 15 ? shiftMonth(month, -1) : month;
  const d = String(day).padStart(2, "0");
  const end = new Date(Date.parse(`${shiftMonth(first, 1)}-${d}T00:00:00Z`) - 864e5);
  return [`${first}-${d}`, end.toISOString().slice(0, 10)];
}

export function shiftMonth(month, delta) {
  const [y, m] = month.split("-").map(Number);
  const i = y * 12 + (m - 1) + delta;
  return `${Math.floor(i / 12)}-${String((i % 12) + 1).padStart(2, "0")}`;
}

// tx : all, todo, in, out ; txcat : { id, month } quand le journal suit une catégorie du budget ;
// jf : filtres du journal (compte, catégorie, from, to, min, max en unités, tri)
const DEFAULTS = { tab: "accueil", period: "m", tx: "all", q: "", txcat: null, jf: {} };

function remembered() {
  try {
    return JSON.parse(localStorage.getItem("hub.params") || "{}");
  } catch {
    return {};
  }
}

// Hors ligne : une réponse qui ne vient pas (réseau coupé, hub arrêté) laisse à l'écran les
// derniers chiffres reçus pendant la session ; rien n'est gardé sur l'appareil.
const unreachable = (e) => !(e instanceof ApiError) || e.status >= 500;

class Store {
  constructor() {
    this.cache = new Map();
    this.offline = false;
    this.lastOk = null; // heure de la dernière réponse du hub (ms)
    this.listeners = new Set();
    const { period, tab } = remembered();
    this.params = { ...DEFAULTS, ...(period ? { period } : {}), ...(tab ? { tab } : {}), month: currentMonth() };
    this.today = currentMonth();
    this.pending = false;
  }

  // { status: "loading" | "ok" | "error", data, error } ; une valeur périmée (invalidate) reste
  // affichée pendant qu'elle se relit, et après un échec du réseau
  use(path) {
    let entry = this.cache.get(path);
    if (!entry) {
      entry = { status: "loading", data: null, error: null, stale: false, busy: false };
      this.cache.set(path, entry);
    }
    if (entry.busy || (entry.status !== "loading" && !entry.stale)) return entry;
    entry.busy = true;
    api(path)
      .then((data) => {
        Object.assign(entry, { status: "ok", data, error: null, stale: false });
        this.offline = false;
        this.lastOk = Date.now();
      })
      .catch((error) => {
        // session expirée : l'app revient à l'écran de connexion
        if (error.status === 401) window.dispatchEvent(new Event("hub:auth"));
        if (entry.data != null && unreachable(error)) {
          entry.stale = false; // pas de nouvel essai à chaque rendu : au prochain retour dans l'app
          this.offline = true;
        } else Object.assign(entry, { status: "error", error, stale: false });
        if (entry.data == null && unreachable(error)) this.offline = true;
      })
      .finally(() => {
        entry.busy = false;
        this.notify();
      });
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
      const { period, tab } = this.params;
      localStorage.setItem("hub.params", JSON.stringify({ period, tab }));
    } catch {
      /* navigation privée : rien à retenir */
    }
    this.notify();
  }

  // tout se relit ; les chiffres déjà là restent affichés d'ici la réponse (pas de saut)
  invalidate() {
    for (const [path, e] of this.cache) {
      if (e.status === "ok") e.stale = true;
      else if (!e.busy) this.cache.delete(path);
    }
    this.today = currentMonth();
    this.notify();
  }

  // nouveau jour de début : le mois en cours et le mois affiché suivent
  setMonthStart(day) {
    if (!day || day === startDay) return;
    const wasToday = this.params.month === this.today;
    startDay = day;
    this.today = currentMonth();
    if (wasToday || this.params.month > this.today) this.params.month = this.today;
    this.invalidate();
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
