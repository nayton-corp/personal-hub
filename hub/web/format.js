// @ts-check
// Mise en forme des nombres : 12'345 CHF, 12,3 %. Le séparateur des milliers vient de la locale
// du profil (fr-CH : apostrophe) ; la décimale reste le point pour les montants et la virgule
// pour les pourcentages. Les montants arrivent en {minor, currency, display}.
/** @typedef {import("./api").MoneyOut} MoneyOut */
/** @typedef {import("./api").FreshnessListOut} FreshnessListOut */

// Devise de base de l'instance et son exposant (centimes : 2), donnés par le profil
// (HUB_CURRENCY), lu avant le premier rendu ; 2 décimales sans lui. Le front ne divise jamais
// par 100 lui-même (audit m9) : `units` et `toMinor` passent par l'exposant.
let baseCcy = "";
let baseExp = 2;
export const base = () => baseCcy;
export const decimals = () => baseExp;

// Locale de l'instance (profil, HUB_LOCALE) : séparateur des milliers, heures et dates longues.
// L'apostrophe typographique de fr-CH (U+2019) devient l'apostrophe droite, lisible partout.
let loc = "fr";
let sep = "\u202f";
export const locale = () => loc;
/** @param {string} l */
function groupSeparator(l) {
  try {
    const part = new Intl.NumberFormat(l).formatToParts(1234567).find((x) => x.type === "group");
    return part ? part.value.replace("\u2019", "'") : "'";
  } catch {
    return "'";
  }
}
/** @param {string | null | undefined} l */
export function setLocale(l) {
  const changed = Boolean(l) && l !== loc;
  if (l && changed) {
    loc = l;
    sep = groupSeparator(l);
  }
  return changed;
}
sep = groupSeparator(loc);
/** @param {string | null | undefined} code @param {number} [exponent] */
export function setBase(code, exponent = baseExp) {
  const changed = (Boolean(code) && code !== baseCcy) || (Number.isInteger(exponent) && exponent !== baseExp);
  if (code) baseCcy = code;
  if (Number.isInteger(exponent) && exponent >= 0) baseExp = exponent;
  return changed;
}

/** @param {string} s */
const group = (s) => s.replace(/\B(?=(\d{3})+(?!\d))/g, sep);

// un montant {minor, currency} en unités (12345 → 123.45) ; null reste null
/** @param {MoneyOut | null | undefined} m @returns {number | null} */
export const units = (m) => (m == null ? null : m.minor / 10 ** baseExp);
// une saisie en unités vers les centimes de la devise de base (123.45 → 12345)
/** @param {string | number} value */
export const toMinor = (value) => Math.round(Number(value) * 10 ** baseExp);

/** @param {number | null | undefined} value */
export function chf(value) {
  if (value == null || Number.isNaN(value)) return "—";
  const n = Math.round(Math.abs(value));
  return (value < 0 && n !== 0 ? "−" : "") + group(String(n));
}

// aux décimales de la devise de base (12'345.50)
/** @param {number | null | undefined} value */
export function chf2(value) {
  if (value == null || Number.isNaN(value)) return "—";
  if (baseExp === 0) return chf(value);
  const [int, dec] = Math.abs(value).toFixed(baseExp).split(".");
  return (value < 0 ? "−" : "") + group(int) + "." + dec;
}

/** @param {number | null | undefined} v */
export const signed = (v) => (v == null ? "—" : (v > 0 ? "+" : v < 0 ? "−" : "") + chf(Math.abs(v)));

/** @param {number | null | undefined} x @param {number} [digits] */
export function pct(x, digits = 0) {
  if (x == null || Number.isNaN(x)) return "—";
  return (x * 100).toFixed(digits).replace(".", ",") + " %";
}

/** @param {number | null | undefined} x @param {number} [d] */
export const spct = (x, d = 1) => (x == null ? "—" : (x > 0 ? "+" : x < 0 ? "−" : "") + pct(Math.abs(x), d));

// rapport du serveur (texte décimal) en nombre
/** @param {string | null | undefined} s @returns {number | null} */
export const ratio = (s) => (s == null ? null : Number(s));

export const MOIS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."];
export const MOIS_L = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"];
const JOURS = ["dimanche", "lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi"];

/** @param {string} iso */
const utc = (iso) => new Date(`${iso.slice(0, 10)}T00:00:00Z`);

/** @param {string | null | undefined} iso */
export function date(iso) {
  if (!iso) return "—";
  const d = utc(iso);
  return `${d.getUTCDate()} ${MOIS[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
}

/** @param {string} iso */
export function dayName(iso) {
  const d = utc(iso);
  return `${JOURS[d.getUTCDay()]} ${d.getUTCDate()} ${MOIS[d.getUTCMonth()]}`;
}

/** @param {string} month */
export const monthName = (month) => `${MOIS_L[Number(month.slice(5, 7)) - 1]} ${month.slice(0, 4)}`;

/** @param {string | null | undefined} iso @param {Date} [now] @returns {number | null} */
export function daysSince(iso, now = new Date()) {
  if (!iso) return null;
  return Math.floor((now.getTime() - utc(iso).getTime()) / 86_400_000);
}

/** @param {string | null | undefined} s */
export const initials = (s) =>
  (s || "?").split(/[\s·]+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join("").toUpperCase();

/** @param {string} tag @param {string} [cls] @param {string | null} [txt] */
export function el(tag, cls, txt) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (txt != null) e.textContent = txt;
  return e;
}

// « il y a 2 h », « hier à 07:31 », « le 26 oct. »
/** @param {number} ms @param {number} [now] */
export function ago(ms, now = Date.now()) {
  const min = Math.round((now - ms) / 60_000);
  if (min < 2) return "à l'instant";
  if (min < 60) return `il y a ${min} min`;
  if (min < 12 * 60) return `il y a ${Math.round(min / 60)} h`;
  const d = new Date(ms);
  const hm = d.toLocaleTimeString(loc, { hour: "2-digit", minute: "2-digit" });
  const days = Math.floor((new Date(now).setHours(0, 0, 0, 0) - new Date(ms).setHours(0, 0, 0, 0)) / 86_400_000);
  if (days <= 0) return `aujourd'hui à ${hm}`;
  if (days === 1) return `hier à ${hm}`;
  return `le ${d.getDate()} ${MOIS[d.getMonth()]}`;
}

// Ligne sous les titres : la dernière donnée reçue par le hub (tous comptes visibles), ou, hors
// ligne, l'heure des chiffres affichés. 45 jours sans donnée sur un compte : en orange.
// jours sans donnée au-delà desquels un compte est à rafraîchir (réglage `stale_account_days`,
// lu dans /finance/settings)
let stale = 45;
export const staleDays = () => stale;
/** @param {number | null | undefined} n */
export function setStaleDays(n) {
  if (typeof n === "number" && Number.isInteger(n) && n > 0) stale = n;
}
/** @param {FreshnessListOut | null | undefined} fr @param {boolean} offline @param {number | null} [lastOk] */
export function freshLine(fr, offline, lastOk) {
  if (offline) return { text: lastOk ? `Hors ligne · chiffres ${ago(lastOk)}` : "Hors ligne", warn: true };
  if (!fr) return { text: "", warn: false };
  const items = fr.items.filter((f) => !f.hidden);
  const last = Math.max(0, ...items.map((f) => (f.last_import ? Date.parse(f.last_import) : 0)));
  const late = items.filter((f) => { const a = daysSince(f.last_data); return a == null || a > stale; }).length;
  if (!items.length) return { text: "Aucun compte pour l'instant", warn: false };
  const data = items.map((f) => f.last_data).filter(Boolean).sort().pop();
  const text = last ? `Mis à jour ${ago(last)}` : data ? `Données au ${date(data)}` : "Aucune donnée reçue";
  return { text: late ? `${text} · ${late} compte${late > 1 ? "s" : ""} en retard` : text, warn: (!last && !data) || late > 0 };
}
