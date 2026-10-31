// Patrimoine : l'état de l'écran (filtres, période, mesure, séries affichées), les lignes (un actif
// dans un compte, une dette) et la page ouverte. Les lignes viennent de /finance/accounts,
// /finance/holdings et /finance/debts, valorisées au dernier point de /finance/networth/history.
import { CCY_NAME, FACETS, assetMark, facetMark, facetName, instMark, setInstitutions } from "./meta.js";
import { MOIS, MOIS_L, base } from "../../format.js";
import { pref, setPref } from "../../ui.js";
import { store } from "../../store.js";

export const paths = { accounts: "/finance/accounts", holdings: "/finance/holdings", history: "/finance/networth/history", fresh: "/finance/freshness", debts: "/finance/debts" };
export const KIND_LABEL = { cash: "Compte", securities: "Titres", pension: "Prévoyance", crypto: "Crypto", debt: "Dette" };

// périodes : dix au choix, six épinglées sous la courbe ; une plage libre en plus
export const PRESETS = [
  { k: "1S", label: "1 semaine", days: 7 }, { k: "1M", label: "1 mois", days: 30 }, { k: "3M", label: "3 mois", days: 91 },
  { k: "6M", label: "6 mois", days: 182 }, { k: "YTD", label: "Depuis le 1er janvier" }, { k: "1A", label: "1 an", days: 365 },
  { k: "2A", label: "2 ans", days: 730 }, { k: "3A", label: "3 ans", days: 1095 }, { k: "5A", label: "5 ans", days: 1826 },
  { k: "Max", label: "Depuis le début" },
];
const PINNED = ["1M", "3M", "YTD", "1A", "5A", "Max"];
// séries de la courbe cachées par défaut : la courbe est simple, le reste s'affiche à la demande
const HIDDEN = ["dep", "assets", "marks", "pru", "buys", "events", "goal"];

// Compte et Actif s'ajoutent aux critères d'avant ; leurs valeurs viennent des lignes
const ACC_F = { key: "acc", label: "Compte", values: [], names: {} };
const ASSET_F = { key: "asset", label: "Actif", values: [], names: {} };
export const FILTERS = [...FACETS, ACC_F, ASSET_F];
export const BY = ["cat", "liq", "goal", "inst", "acc", "asset"];
export const LOOK = [["region", "Région"], ["sector", "Secteur"], ["currency", "Devise"]];
export const SORTS = [{ k: "val", label: "Valeur" }, { k: "chg", label: "Gain" }, { k: "az", label: "Nom" }];
export const TABS = [["rend", "Rendement"], ["risk", "Risque"]];

const saved = pref("wealth", {});
const okBy = (k) => BY.includes(k) || LOOK.some(([x]) => x === k);
const okPins = (p) => Array.isArray(p) && p.length >= 2 && p.length <= 6 && p.every((k) => PRESETS.some((x) => x.k === k));
export const S = {
  filters: Object.fromEntries(FILTERS.map((f) => [f.key, new Set()])),
  by: okBy(saved.by) ? saved.by : "cat",
  period: PRESETS.some((p) => p.k === saved.period) ? saved.period : "1A",
  custom: null, // [du, au] en AAAA-MM-JJ
  pinned: okPins(saved.pinned) ? saved.pinned : PINNED,
  // Valeur ou Performance ; l'ancienne mesure « gain » devient Performance en francs
  mode: ["gain", "rend", "perf"].includes(saved.mode) ? "perf" : "val",
  unit: saved.unit === "pct" || saved.mode === "rend" || saved.mode === "perf" ? "pct" : "chf",
  cmp: typeof saved.cmp === "string" ? saved.cmp : null, // ISIN du repère
  hidden: new Set(Array.isArray(saved.hidden) ? saved.hidden : HIDDEN),
  tab: TABS.some(([k]) => k === saved.tab) ? saved.tab : "rend",
  view: saved.view === "asset" ? "asset" : "acc",
  sort: SORTS.some((s) => s.k === saved.sort) ? saved.sort : "val",
  gross: saved.gross === true, // Brut : les dettes sortent du total, de la courbe et de la répartition
  amode: "pos", // page d'un actif : ma position ou le cours
  where: "here", // page d'un actif ouverte depuis un compte : ce compte ou partout
  scrub: null,
  ruler: null,
  rulerOn: false,
  full: false,
};
export const FOLD = { alloc: false, perf: true, ...pref("fold", {}) };

export function remember() {
  const { by, period, pinned, mode, unit, cmp, view, sort, tab, gross } = S;
  setPref("wealth", { ...pref("wealth", {}), by, period, pinned, mode, unit, cmp, view, sort, tab, gross, hidden: [...S.hidden] });
}

// --- page ouverte : [] le patrimoine ; [{t:"acc", id}] un compte ; {t:"asset", id, from} un actif

export const trail = () => (Array.isArray(store.params.page) ? store.params.page : []);
export const here = () => trail()[trail().length - 1] || { t: "home" };

// --- lignes : un actif dans un compte -------------------------------------------------------------

function lastValues() {
  const h = store.data(paths.history);
  const last = h && h.items.length ? h.items[h.items.length - 1] : null;
  return last ? last.by_account : null;
}

let cache = { key: null, lines: [] };
export function lines() {
  const acc = store.data(paths.accounts), hold = store.data(paths.holdings), byAcc = lastValues(), owed = store.data(paths.debts);
  if (!acc || !hold || !byAcc || !owed) return null;
  const key = [acc, hold, byAcc, owed];
  if (cache.key && cache.key.every((x, i) => x === key[i])) return cache.lines;
  setInstitutions(acc.items.map((a) => a.institution));
  const out = [];
  for (const a of acc.items) {
    if (a.hidden) continue;
    const total = byAcc[a.id] ? byAcc[a.id].minor / 100 : 0;
    const own = hold.items.filter((p) => p.account_id === a.id);
    const meta = { acc: a.id, accName: a.name, inst: a.institution, liq: a.availability, goal: a.goal, kind: a.kind, target: a.target ? a.target.minor / 100 : null };
    let held = 0;
    for (const p of own) {
      const v = p.value.minor / 100;
      held += v;
      const crypto = p.kind === "crypto";
      out.push({ ...meta, asset: `isin:${p.isin}`, isin: p.isin, name: p.name, symbol: crypto ? p.isin : null, cat: a.category || (crypto ? "crypto" : "funds"), qty: p.quantity, unit: crypto ? p.isin : "parts", value: v, price: p.price, priceCcy: p.price_currency, priceDate: p.price_date, cost: p.cost ? p.cost.minor / 100 : null });
    }
    const rest = total - held;
    if (!own.length || Math.abs(rest) >= 1) {
      // sans positions : le solde, dans la devise du compte ; avec : le reste, déjà converti
      const ccy = own.length ? base() : a.balance.currency;
      const q = own.length ? rest : a.balance.minor / 100;
      out.push({ ...meta, asset: `ccy:${ccy}`, name: CCY_NAME[ccy] || ccy, symbol: ccy, cat: a.category || (a.kind === "crypto" && !own.length ? "crypto" : "cash"), qty: q, unit: ccy, value: own.length ? rest : total });
    }
  }
  // une dette : sa valeur (négative) du dernier point ; ni disponibilité ni objectif
  for (const d of owed.items) {
    const v = byAcc[d.key];
    if (!v || !v.minor) continue;
    out.push({ acc: d.key, debt: d.id, accName: d.name, inst: d.lender, liq: null, goal: null, kind: "debt", debtKind: d.kind, asset: `debt:${d.id}`, name: d.name, symbol: null, cat: "debt", qty: v.minor / 100, unit: base(), value: v.minor / 100 });
  }
  // critères Compte et Actif : ce que les lignes contiennent
  ACC_F.values = [...new Set(out.map((l) => l.acc))];
  ACC_F.names = Object.fromEntries(out.map((l) => [l.acc, accLabel(l)]));
  ACC_F.lines = Object.fromEntries(out.map((l) => [l.acc, l]));
  const assets = out.filter((l) => l.kind !== "debt");
  ASSET_F.values = [...new Set(assets.map((l) => l.asset))];
  ASSET_F.names = Object.fromEntries(assets.map((l) => [l.asset, l.name]));
  ASSET_F.lines = Object.fromEntries(assets.map((l) => [l.asset, l]));
  cache = { key, lines: out };
  return out;
}

export const accOf = (id) => ACC_F.lines?.[id] || null;
export const assetOf = (id) => ASSET_F.lines?.[id] || null;
export const accName = (id) => ACC_F.names[id] ?? id;
export const accLabel = (l) => (l.inst === l.accName ? l.accName : `${l.inst} · ${l.accName}`);
export const fName = (key, v) => (key === "acc" ? ACC_F.names[v] ?? v : key === "asset" ? ASSET_F.names[v] ?? v : facetName(key, v));
export function fMark(key, v, size = "sm") {
  if (key === "acc") return instMark(ACC_F.lines[v] ? ACC_F.lines[v].inst : v, size);
  if (key === "asset") return ASSET_F.lines[v] ? assetMark(ASSET_F.lines[v], size) : facetMark("cat", "funds", size);
  return facetMark(key, v, size);
}

export const activeCount = () => FILTERS.reduce((n, f) => n + S.filters[f.key].size, 0);
export function match(l, except) {
  for (const f of FILTERS) {
    if (f.key === except) continue;
    const s = S.filters[f.key];
    if (s.size && !s.has(l[f.key])) return false;
  }
  return true;
}
export const sum = (ls) => ls.reduce((t, l) => t + l.value, 0);

// les lignes que montre une page : la sélection filtrée, un compte, un actif (dans un compte)
export function scopeLines(all, r = here()) {
  if (r.t === "acc") return all.filter((l) => l.acc === r.id);
  if (r.t === "asset") return all.filter((l) => l.asset === r.id && (!r.from || S.where === "all" || l.acc === r.from));
  return all.filter((l) => match(l) && !(S.gross && l.kind === "debt"));
}

// identifiant d'une ligne pour /finance/performance : « compte|ISIN », « compte|cash », « debt:… »
export const lineId = (l) => (l.kind === "debt" ? l.asset : l.asset.startsWith("isin:") ? `${l.acc}|${l.asset.slice(5)}` : `${l.acc}|cash`);

export const perfPath = (from, to, step, ids) =>
  `/finance/performance?${from ? `from=${from}&` : ""}${to ? `to=${to}&` : ""}step=${step}${ids ? ids.map((i) => `&line=${encodeURIComponent(i)}`).join("") : ""}`;

// lignes demandées : aucune pour tout le patrimoine (le serveur prend celles de l'app), sinon la
// sélection ; « compte|cash » porte aussi les revenus et frais d'un compte à positions
export function selIds(sel, all = false) {
  if (all) return null;
  const ids = new Set(sel.map(lineId));
  for (const l of sel) if (l.kind !== "debt") ids.add(`${l.acc}|cash`);
  return [...ids].sort();
}

// --- période --------------------------------------------------------------------------------

export const iso = (d) => d.toISOString().slice(0, 10);
export const day = (s) => new Date(`${s}T00:00:00Z`);
export const asOf = () => {
  const h = store.data(paths.history);
  return h ? h.as_of || (h.items.length ? h.items[h.items.length - 1].on_date : iso(new Date())) : iso(new Date());
};
export const firstDay = () => {
  const h = store.data(paths.history);
  return h && h.items.length ? h.items[0].on_date : null;
};
export const preset = () => PRESETS.find((p) => p.k === S.period);
export const shortDate = (s) => {
  const d = day(s);
  return `${d.getUTCDate()} ${MOIS[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
};
export const longDate = (s) => {
  const d = day(s);
  return `${d.getUTCDate()} ${MOIS_L[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
};

// { from, to, label } : `to` vide jusqu'à aujourd'hui
export function range() {
  if (S.custom) return { from: S.custom[0], to: S.custom[1], label: `du ${shortDate(S.custom[0])} au ${shortDate(S.custom[1])}` };
  const p = preset(), end = day(asOf());
  let from;
  if (p.k === "YTD") from = `${end.getUTCFullYear() - 1}-12-31`;
  else if (p.k === "Max") from = firstDay();
  else {
    const d = new Date(end);
    d.setUTCDate(d.getUTCDate() - p.days);
    from = iso(d);
  }
  const label = p.k === "YTD" ? "depuis le 1er janvier" : p.k === "Max" ? "depuis le début" : `sur ${p.label}`;
  return { from, to: null, label };
}
