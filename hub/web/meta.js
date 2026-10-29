// Libellés, pictogrammes et teintes des catégories, des facettes du patrimoine et des actifs.
import { cv, esc, ibox, ic, monogram } from "./ui.js";

// catégories du registre (base, packs) : pictogramme et teinte ; les autres prennent ceux de
// leur groupe
const CAT_LOOK = {
  logement: ["home", 0], assurances: ["shield", 1], impots: ["landmark", 5], telecom: ["wifi", 3],
  abonnements: ["repeat", 4], transports: ["train", 6], "voiture-credit": ["car", 5], "voiture-frais": ["car", 6], alimentation: ["cart", 1], restaurants: ["utensils", 2],
  sante: ["heart", 4], loisirs: ["ticket", 3], shopping: ["bag", 4], voyages: ["plane", 6], divers: ["dots", 5],
  retraits: ["banknote", 5], "twint-particuliers": ["swap", 6], salaire: ["briefcase", 1], remboursements: ["arrowin", 6],
  "autres-revenus": ["arrowin", 1], rendement: ["trend", 1], "epargne-3a": ["piggy", 0], investissements: ["trend", 0],
  crypto: ["coin", 2], "transfer-own": ["swap", -1], "transfer-titres": ["swap", -1], "frais-placement": ["landmark", 5],
  "a-categoriser": ["help", -2], autres: ["dots", -1],
};
const GROUP_LOOK = { income: ["arrowin", 1], fixed: ["home", 5], variable: ["cart", 2], savings: ["piggy", 0], transfer: ["swap", -1] };
export const GROUP_LABEL = { income: "Revenus", fixed: "Fixes", variable: "Variables", savings: "Épargne", transfer: "Transferts", mixed: "Autres" };

function look(id, groupName) {
  const [icon, c] = CAT_LOOK[id] || GROUP_LOOK[groupName] || ["dots", 5];
  return { icon, color: c === -1 ? "var(--faint)" : c === -2 ? "var(--accent)" : cv(c) };
}
export const catLook = look;
export function catMark(id, groupName, size = "sm") {
  if (!id) return ibox(ic("help"), "var(--accent)", size);
  const l = look(id, groupName);
  return ibox(ic(l.icon), l.color, size);
}
export function catIc(id, groupName) {
  const l = look(id, groupName);
  return `<span class="tint-ic" data-css="color:${l.color};display:inline-flex">${ic(l.icon)}</span>`;
}

// --- patrimoine : facettes ------------------------------------------------------------------
export const FACETS = [
  { key: "cat", label: "Catégorie", values: ["cash", "funds", "crypto"], names: { cash: "Liquidités", funds: "Actions & fonds", crypto: "Crypto" }, icons: { cash: "banknote", funds: "trend", crypto: "coin" } },
  { key: "liq", label: "Disponibilité", values: ["immediate", "days", "locked"], names: { immediate: "Immédiate", days: "Sous quelques jours", locked: "Bloquée" }, icons: { immediate: "bolt", days: "clock", locked: "lockc" } },
  { key: "goal", label: "Objectif", values: ["current", "safety", "projects", "long_term", "retirement"], names: { current: "Courant", safety: "Réserve de sécurité", projects: "Projets", long_term: "Long terme", retirement: "Retraite" }, icons: { current: "wallet", safety: "shield", projects: "plane", long_term: "trend", retirement: "piggy" } },
  { key: "inst", label: "Institution", values: [], names: {} }, // rempli depuis les comptes
];
export const FACET = Object.fromEntries(FACETS.map((f) => [f.key, f]));

export function setInstitutions(names) {
  const f = FACET.inst;
  f.values = [...new Set(names)].sort((a, b) => a.localeCompare(b, "fr"));
  f.names = Object.fromEntries(f.values.map((v) => [v, v]));
}
export const facetName = (key, v) => FACET[key].names[v] ?? v;
export const facetColor = (key, v) => cv(Math.max(0, FACET[key].values.indexOf(v)));
export function facetMark(key, v, size = "sm") {
  const f = FACET[key];
  const inner = f.icons ? ic(f.icons[v]) : `<span>${esc(monogram(v))}</span>`;
  return ibox(inner, facetColor(key, v), size);
}
export function facetIc(key, v) {
  const f = FACET[key];
  return f.icons ? `<span data-css="--c:${facetColor(key, v)};display:inline-flex">${ic(f.icons[v])}</span>` : `<i data-css="--c:${facetColor(key, v)}"></i>`;
}

// --- actifs ---------------------------------------------------------------------------------
export const CCY_NAME = { CHF: "Franc suisse", EUR: "Euro", USD: "Dollar US", GBP: "Livre sterling", JPY: "Yen" };
const GLYPH = { CHF: "Fr.", EUR: "€", USD: "$", GBP: "£", JPY: "¥", BTC: "₿", ETH: "Ξ", USDT: "₮", USDC: "$", SOL: "◎", LTC: "Ł", XRP: "✕", ADA: "₳", DOT: "●" };
const CRYPTO_TINT = { BTC: "var(--s3)", ETH: "var(--s4)", USDT: "var(--s2)", USDC: "var(--s7)", SOL: "var(--s5)" };

export function assetMark(a, size = "") {
  const g = GLYPH[a.symbol] || monogram(a.name);
  const color = CRYPTO_TINT[a.symbol] || facetColor("cat", a.cat);
  return ibox(`<span class="${g.length === 1 ? "glyph" : ""}">${esc(g)}</span>`, color, size);
}
