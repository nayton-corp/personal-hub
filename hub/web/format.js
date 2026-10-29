// Mise en forme suisse : 12'345 CHF, 12,3 %. Les montants arrivent en {minor, currency, display}.

// Devise de base de l'instance, donnée par le profil (HUB_CURRENCY) ; CHF jusqu'à sa réponse.
let baseCcy = "CHF";
export const base = () => baseCcy;
export function setBase(code) {
  const changed = Boolean(code) && code !== baseCcy;
  if (changed) baseCcy = code;
  return changed;
}

const group = (s) => s.replace(/\B(?=(\d{3})+(?!\d))/g, "'");

export const units = (m) => (m == null ? null : m.minor / 100);

export function chf(value) {
  if (value == null || Number.isNaN(value)) return "—";
  const n = Math.round(Math.abs(value));
  return (value < 0 && n !== 0 ? "−" : "") + group(String(n));
}

export function chf2(value) {
  if (value == null || Number.isNaN(value)) return "—";
  const [int, dec] = Math.abs(value).toFixed(2).split(".");
  return (value < 0 ? "−" : "") + group(int) + "." + dec;
}

export const signed = (v) => (v == null ? "—" : (v > 0 ? "+" : v < 0 ? "−" : "") + chf(Math.abs(v)));

export function pct(x, digits = 0) {
  if (x == null || Number.isNaN(x)) return "—";
  return (x * 100).toFixed(digits).replace(".", ",") + " %";
}

export const spct = (x, d = 1) => (x == null ? "—" : (x > 0 ? "+" : x < 0 ? "−" : "") + pct(Math.abs(x), d));

// rapport du serveur (texte décimal) en nombre
export const ratio = (s) => (s == null ? null : Number(s));

export const MOIS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."];
export const MOIS_L = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"];
const JOURS = ["dimanche", "lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi"];

const utc = (iso) => new Date(`${iso.slice(0, 10)}T00:00:00Z`);

export function date(iso) {
  if (!iso) return "—";
  const d = utc(iso);
  return `${d.getUTCDate()} ${MOIS[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
}

export function dayName(iso) {
  const d = utc(iso);
  return `${JOURS[d.getUTCDay()]} ${d.getUTCDate()} ${MOIS[d.getUTCMonth()]}`;
}

export const monthName = (month) => `${MOIS_L[Number(month.slice(5, 7)) - 1]} ${month.slice(0, 4)}`;

export function daysSince(iso, now = new Date()) {
  if (!iso) return null;
  return Math.floor((now - utc(iso)) / 86_400_000);
}

export const initials = (s) =>
  (s || "?").split(/[\s·]+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join("").toUpperCase();

export function el(tag, cls, txt) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (txt != null) e.textContent = txt;
  return e;
}

// « il y a 2 h », « hier à 07:31 », « le 26 oct. »
export function ago(ms, now = Date.now()) {
  const min = Math.round((now - ms) / 60_000);
  if (min < 2) return "à l'instant";
  if (min < 60) return `il y a ${min} min`;
  if (min < 12 * 60) return `il y a ${Math.round(min / 60)} h`;
  const d = new Date(ms);
  const hm = d.toLocaleTimeString("fr-CH", { hour: "2-digit", minute: "2-digit" });
  const days = Math.floor((new Date(now).setHours(0, 0, 0, 0) - new Date(ms).setHours(0, 0, 0, 0)) / 86_400_000);
  if (days <= 0) return `aujourd'hui à ${hm}`;
  if (days === 1) return `hier à ${hm}`;
  return `le ${d.getDate()} ${MOIS[d.getMonth()]}`;
}

// Ligne sous les titres : la dernière donnée reçue par le hub (tous comptes visibles), ou, hors
// ligne, l'heure des chiffres affichés. 45 jours sans donnée sur un compte : en orange.
export const STALE_DAYS = 45;
export function freshLine(fr, offline, lastOk) {
  if (offline) return { text: lastOk ? `Hors ligne · chiffres ${ago(lastOk)}` : "Hors ligne", warn: true };
  if (!fr) return { text: "", warn: false };
  const items = fr.items.filter((f) => !f.hidden);
  const last = Math.max(0, ...items.map((f) => (f.last_import ? Date.parse(f.last_import) : 0)));
  const late = items.filter((f) => { const a = daysSince(f.last_data); return a == null || a > STALE_DAYS; }).length;
  if (!items.length) return { text: "Aucun compte pour l'instant", warn: false };
  const data = items.map((f) => f.last_data).filter(Boolean).sort().pop();
  const text = last ? `Mis à jour ${ago(last)}` : data ? `Données au ${date(data)}` : "Aucune donnée reçue";
  return { text: late ? `${text} · ${late} compte${late > 1 ? "s" : ""} en retard` : text, warn: (!last && !data) || late > 0 };
}
