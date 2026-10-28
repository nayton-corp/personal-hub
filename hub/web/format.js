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
