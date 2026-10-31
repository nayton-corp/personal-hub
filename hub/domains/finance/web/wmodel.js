// Patrimoine : ce que trace la courbe de la page ouverte. Valeur et apports viennent de
// /finance/performance pour les lignes de la page ; gain et rendement, des seuls avoirs quand la
// sélection a une dette (une seconde lecture). Le cours d'un actif et le repère viennent de
// /finance/prices. Les événements (gros versements, retraits, revenus) sont des totaux du jour
// calculés par le serveur. Une date sans cours ou un compte resté sans relevé rend la courbe
// « estimée » à cet endroit.
import { S, activeCount, asOf, day, here, iso, lines, paths, perfPath, range, scopeLines, selIds } from "./wstate.js";
import { rate, units } from "./perf.js";
import { STALE_DAYS, base } from "../../format.js";
import { store } from "../../store.js";

const STEP = "day"; // le serveur garde au plus 400 points, la fin comprise

// courbe affichée : Valeur, Performance en francs ou en %, position ou cours d'un actif
export function kindFor(r = here()) {
  if (r.t === "asset") return S.amode === "price" ? "price" : "pos";
  return S.mode === "val" ? "val" : S.unit === "pct" ? "pct" : "gain";
}

const pricesPath = (isin, from, to) => `/finance/prices?isin=${encodeURIComponent(isin)}${from ? `&from=${from}` : ""}${to ? `&to=${to}` : ""}`;

// dernier cours connu à une date (cours triés par date)
function priceAt(items, d) {
  let lo = 0, hi = items.length - 1, k = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (items[mid].on_date <= d) { k = mid; lo = mid + 1; } else hi = mid - 1;
  }
  return k < 0 ? null : Number(items[k].price);
}

// indice du premier point à la date `d` ou après
function indexOf(pts, d) {
  let lo = 0, hi = pts.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (pts[mid].d < d) lo = mid + 1; else hi = mid;
  }
  return lo;
}

export const granLabel = (pts) => {
  if (pts.length < 2) return "";
  const s = Math.round((day(pts[pts.length - 1].d) - day(pts[0].d)) / 864e5 / (pts.length - 1));
  return s <= 1 ? "par jour" : s === 7 ? "par semaine" : `tous les ${s} jours`;
};

// plages estimées : points sans cours ni change, et fin de courbe d'un compte resté sans relevé
function uncertain(pts, sel) {
  const out = [];
  let k0 = null;
  pts.forEach((p, k) => {
    if (!p.ok && k0 == null) k0 = Math.max(0, k - 1);
    if ((p.ok || k === pts.length - 1) && k0 != null) {
      out.push({ k0, k1: k, why: "Cours ou change manquant : valeur estimée" });
      k0 = null;
    }
  });
  const fresh = store.data(paths.fresh);
  if (fresh && pts.length > 1) {
    const end = day(asOf());
    for (const f of fresh.items) {
      const mine = sel.filter((l) => l.acc === f.account_id);
      if (!f.last_data || !mine.length) continue;
      // un compte vide ne rend rien incertain ; un compte que sa connexion a alimenté
      // récemment n'est pas sans nouvelles, même sans écriture (Revolut n'a pas de solde
      // de clôture : un compte qui ne bouge pas garde une vieille dernière donnée)
      if (Math.abs(mine.reduce((t, l) => t + l.value, 0)) < 0.5) continue;
      const seen = f.last_import && f.last_import.slice(0, 10) > f.last_data ? f.last_import.slice(0, 10) : f.last_data;
      if (Math.round((end - day(seen)) / 864e5) <= STALE_DAYS) continue;
      const age = Math.round((end - day(f.last_data)) / 864e5);
      if (age <= STALE_DAYS || f.last_data >= pts[pts.length - 1].d) continue;
      const k = Math.max(0, indexOf(pts, f.last_data) - 1);
      if (k < pts.length - 1) out.push({ k0: k, k1: pts.length - 1, stale: true, acc: f.account_id, age, why: `${f.name} : aucun relevé depuis le ${f.last_data.split("-").reverse().join(".")}, valeur reprise telle quelle` });
    }
  }
  return out;
}

// { status, error, pts, events, unc, label, sel, perf, net, hasDebt, onlyDebt, target, pru, cmp }
export function model(r = here()) {
  const all = lines();
  if (!all) return { status: "loading", pts: [], sel: [] };
  const sel = scopeLines(all, r);
  const rg = range();
  const base0 = { sel, label: rg.label, rg, pts: [], events: [], unc: [] };
  if (!sel.length) return { ...base0, status: "ok", empty: true };
  if (!rg.from) return { ...base0, status: "ok" };
  const owned = sel.filter((l) => l.kind !== "debt");
  const hasDebt = owned.length < sel.length && owned.length > 0;
  const plain = r.t === "home" && !activeCount() && !S.gross;
  const e = store.use(perfPath(rg.from, rg.to, STEP, selIds(sel, plain)));
  const a = hasDebt ? store.use(perfPath(rg.from, rg.to, STEP, selIds(owned))) : e;
  const out = { ...base0, status: e.status === "ok" ? a.status : e.status, error: e.error || a.error, net: e.data, perf: a.data, hasDebt, onlyDebt: !owned.length };
  if (!e.data) return out;
  const own = a.data && a !== e ? new Map(a.data.items.map((it) => [it.on_date, it])) : null;
  const items = e.data.items;
  const v0 = items.length ? units(items[0].value) : 0;
  out.pts = items.map((it) => {
    const o = own ? own.get(it.on_date) || it : it;
    const f = units(it.net_flows);
    return { d: it.on_date, v: units(it.value), f, dep: v0 + f, g: units(o.gain), r: rate(o.twr), dd: rate(o.drawdown), ok: it.complete, a: own ? units(o.value) : units(it.value) };
  });
  const pts = out.pts;
  if (pts.length > 1) {
    const evs = (a.data || e.data).events || [];
    out.events = evs.map((x) => ({ d: x.on_date, kind: x.kind, v: units(x.amount), k: indexOf(pts, x.on_date) }));
    out.unc = uncertain(pts, sel);
  }
  if (r.t === "acc" && sel[0].target) out.target = sel[0].target;
  if (r.t === "asset") assetCurve(out, sel, rg);
  else if (S.cmp && kindFor(r) === "pct" && pts.length > 1) bench(out, rg);
  return out;
}

// repère : le cours d'un fonds que tu détiens, ramené à 0 au début de la période
function bench(out, rg) {
  const pe = store.use(pricesPath(S.cmp, null, rg.to));
  if (!pe.data || !pe.data.items.length) return;
  const items = pe.data.items;
  const p0 = priceAt(items, out.pts[0].d) ?? Number(items[0].price);
  out.cmp = { name: pe.data.name || S.cmp };
  for (const p of out.pts) {
    const x = priceAt(items, p.d);
    p.b = x == null || !p0 ? null : x / p0 - 1;
  }
}

// page d'un actif : prix de revient (francs, si coté en francs), cours, achats et ventes
function assetCurve(out, sel, rg) {
  const f = sel.find((l) => l.isin);
  const q = sel.reduce((t, l) => t + Number(l.qty), 0);
  const cost = sel.every((l) => l.cost != null) ? sel.reduce((t, l) => t + l.cost, 0) : null;
  out.qty = q;
  out.cost = cost;
  if (!f || S.amode !== "price") return;
  const pe = store.use(pricesPath(f.isin, rg.from, rg.to));
  if (pe.status === "error") { out.status = "error"; out.error = pe.error; return; }
  if (!pe.data) { out.status = "loading"; out.pts = []; return; }
  out.priceCcy = pe.data.currency || f.priceCcy;
  const pts = pe.data.items.map((x) => ({ d: x.on_date, price: Number(x.price), ok: true }));
  out.pru = cost != null && q > 0 && out.priceCcy === base() ? cost / q : null;
  out.buys = out.events.filter((x) => x.kind !== "income").map((x) => ({ ...x, k: indexOf(pts, x.d) }));
  out.pts = pts;
  out.events = [];
  out.unc = [];
}

// apports nets des douze derniers mois d'un compte (page du compte) : totaux par mois
export function monthly(sel) {
  const d = day(asOf());
  d.setUTCFullYear(d.getUTCFullYear() - 1);
  d.setUTCDate(1);
  d.setUTCMonth(d.getUTCMonth() + 1);
  const e = store.use(perfPath(iso(d), null, "month", selIds(sel)));
  return e.data ? e.data.by_month.map((m) => ({ m: m.period, v: units(m.net_flows) })) : null;
}
