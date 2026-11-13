// Patrimoine : la sélection (filtres par catégorie, disponibilité, objectif, institution, compte,
// actif) pilote l'écran : total et courbe, répartition, performance, puis la liste des comptes
// ou des actifs. Toucher un compte ou un actif ouvre sa page (wpages.js), avec retour et chemin ;
// la barre de contexte dit toujours ce que l'écran montre. État et lignes : wstate.js ; courbe :
// wmodel.js et wchart.js ; haut de l'écran : whero.js ; panneaux : wsheets.js.
import { BY, FILTERS, FOLD, PRESETS, S, SORTS, TABS, accLabel, activeCount, fName, here, lines, match, paths, range, remember, scopeLines, sum, trail } from "./wstate.js";
import { SH, SHEETS, amount, announce, closeSheet, esc, fill, ic, money, n0, openSheet, skel, toast } from "../../ui.js";
import { accountPage, assetPage } from "./wpages.js";
import { allocBrief, allocDetail } from "./walloc.js";
import { chartSVG, flagHTML, gutter, legendHTML, nearest, rulerHTML } from "./wchart.js";
import { displayBody, drawLand, drawTop, heroHTML, periodsHTML } from "./whero.js";
import { facetMark, assetMark } from "./meta.js";
import { gainSpan, perfSection, rate, ratePct, signedMoney, units } from "./perf.js";
import { kindFor, model } from "./wmodel.js";
import { moneyRate } from "./wcurve.js";
import { DEBT_KIND, debtMark } from "./debts.js";
import { byLabel } from "./wsheets.js";
import { stratBrief, stratSection } from "./strategies.js";
import * as place from "./wplace.js";
import { base } from "../../format.js";
import { go } from "../../shell.js";
import { linkTo } from "./journal.js";
import { store } from "../../store.js";

const $ = (id) => document.getElementById(id);
const H = 210;
let M = { pts: [], sel: [] }; // modèle de la page affichée
let shown = null; // page affichée au dernier rendu

export function init() {
  fill($("patBody"), `
    <div class="hero" id="evo"><div id="hero"></div><div id="wper"></div>
      <div class="chart-wrap" data-chart="main" id="cw"></div><div class="legend" id="legend"></div><div id="wrul"></div></div>
    <div id="wsecs"></div><div class="endspace"></div>`);
  document.addEventListener("pointerdown", (e) => pointer(e, "down"));
  document.addEventListener("pointermove", (e) => pointer(e, "move"));
  document.addEventListener("pointerup", (e) => pointer(e, "up"));
  document.addEventListener("keydown", keys);
  window.addEventListener("resize", () => { if (store.params.tab === "patrimoine") render(); });
  window.addEventListener("scroll", () => {
    if (store.params.tab === "patrimoine") $("pat-top").classList.toggle("compact", window.scrollY > 110);
  }, { passive: true });
}

// --- doigt : lire une date, mesurer entre deux dates ------------------------------------------

let dragging = false, release = null;
function ptIndex(e, wrap) {
  const svg = wrap.querySelector("svg"), box = svg.getBoundingClientRect();
  const land = wrap.dataset.chart === "land", rotated = land && wrap.closest(".rot");
  const vw = svg.viewBox.baseVal.width || box.width, frac = (vw - gutter(land)) / vw;
  const t = (rotated ? (e.clientY - box.top) / box.height : (e.clientX - box.left) / box.width) / frac;
  return nearest(M, Math.max(0, Math.min(1, t)));
}
function pointer(e, phase) {
  if (store.params.tab !== "patrimoine" || M.pts.length < 2) return;
  const wrap = e.target.closest ? e.target.closest("[data-chart]") : null;
  if (phase === "down") {
    if (!wrap) return;
    clearTimeout(release);
    const k = ptIndex(e, wrap);
    if (S.rulerOn) { S.ruler = [k, k]; dragging = wrap; }
    else S.scrub = k;
    return updateChart();
  }
  if (phase === "move") {
    const w = wrap || dragging;
    if (!w) {
      if (S.scrub != null && e.pointerType === "mouse") { S.scrub = null; updateChart(); }
      return;
    }
    const k = ptIndex(e, w);
    if (dragging) { S.ruler[1] = k; updateChart(); }
    else if (!S.rulerOn && (e.pointerType === "mouse" || e.buttons) && k !== S.scrub) { S.scrub = k; updateChart(); }
    return;
  }
  if (dragging) {
    dragging = false;
    if (S.ruler && S.ruler[0] === S.ruler[1]) S.ruler = null;
    else S.rulerOn = false;
    return render();
  }
  if (e.pointerType !== "mouse" && S.scrub != null && wrap) release = setTimeout(() => { S.scrub = null; updateChart(); }, 1600);
}
function keys(e) {
  if (store.params.tab !== "patrimoine") return;
  if (e.key === "Escape" && S.full) { S.full = false; return render(); }
  const svg = e.target.closest && e.target.closest("[data-chart] svg");
  if (!svg || !["ArrowLeft", "ArrowRight", "Home", "End", "Escape"].includes(e.key) || M.pts.length < 2) return;
  e.preventDefault();
  const n = M.pts.length, cur = S.scrub == null ? n - 1 : S.scrub;
  S.scrub = e.key === "Escape" ? null : e.key === "Home" ? 0 : e.key === "End" ? n - 1 : Math.max(0, Math.min(n - 1, cur + (e.key === "ArrowLeft" ? -1 : 1)));
  updateChart();
  announce($("hero").innerText.replace(/\s+/g, " "));
}

const width = () => Math.max(280, Math.min(720, ($("cw") && $("cw").clientWidth) || 340));
function updateChart() {
  const all = lines() || [], r = here(), kind = kindFor(r), w = width();
  fill($("hero"), heroHTML(M, all, r) + (S.scrub == null && r.t !== "asset" ? place.breaksLine(M.sel) : ""));
  fill($("cw"), chartSVG(M, kind, w, H, { interactive: true, empty: emptyText() }) + flagHTML(M, w));
  fill($("wrul"), rulerHTML(M, kind));
  drawLand(M, all);
}
const emptyText = () => (M.status === "error" ? `Courbe indisponible : ${M.error.message}` : M.status === "loading" ? "Chargement…" : M.empty ? "Aucune donnée pour cette sélection" : "Pas assez de points sur cette période");

// --- rendu ------------------------------------------------------------------------------------

export function render() {
  const ae = store.use(paths.accounts), he = store.use(paths.holdings), hi = store.use(paths.history), de = store.use(paths.debts);
  store.use(paths.fresh);
  const err = [ae, he, hi, de].find((e) => e.status === "error");
  const all = lines();
  const key = JSON.stringify(trail());
  if (key !== shown) {
    shown = key;
    Object.assign(S, { scrub: null, ruler: null, rulerOn: false, where: "here" });
    if (here().t !== "asset") S.amode = "pos";
  }
  drawTop(all || []);
  if (err || !all) {
    fill($("hero"), err ? `<div class="err-box" role="alert">Impossible de charger le patrimoine : ${esc(err.error.message)}</div>` : skel());
    for (const id of ["cw", "legend", "wrul", "wper", "wsecs"]) fill($(id), "");
    return;
  }
  const r = here(), kind = kindFor(r);
  M = model(r);
  if (S.scrub != null && S.scrub >= M.pts.length) S.scrub = null;
  updateChart();
  fill($("legend"), M.pts.length > 1 ? legendHTML(M, kind, "line") : "");
  fill($("wper"), periodsHTML());
  fill($("wsecs"), r.t === "acc" ? accountPage(M, r) : r.t === "asset" ? assetPage(M, all, r) : homeSections(all));
  fill($("miniTotal"), `${r.t === "home" && activeCount() ? "Sélection · " : ""}${money(sum(M.sel))} ${base()}`);
  const dh = $("detailHead");
  if (dh) requestAnimationFrame(() => dh.style.setProperty("--topbar-h", `${$("pat-top").offsetHeight}px`));
}

// --- patrimoine : répartition, performance, comptes et actifs --------------------------------

const perfCtx = (all) => ({
  S, n: activeCount(), per: { label: range().label }, perf: M.perf, src: { status: M.status, error: M.error }, all, sel: M.sel, pts: M.pts,
  fmtDate: (d) => d.split("-").reverse().join("."),
});

// trois cartes résumé : leur détail s'ouvre dans un grand panneau ; Stratégies se déplie sur place
function cards(sel) {
  const a = allocBrief(sel), p = M.perf && M.perf.summary, st = stratBrief();
  const card = (a2, v, l, val, sub, cls = "") => `<button class="sumcard${cls}" type="button" data-a="${a2}"${v ? ` data-v="${v}"` : ""} aria-haspopup="dialog"><span class="l">${l}</span><span class="v">${val}</span><span class="s">${sub}</span></button>`;
  let second;
  if (S.mode === "perf") {
    const k = M.perf && M.perf.risk, dd = k ? rate(k.max_drawdown) : null, vol = k ? rate(k.volatility) : null;
    second = card("w-card", "risk", "Risque", dd == null ? "—" : dd < 0 ? `<span class="neg">${ratePct(dd)}</span>` : "Aucune baisse", vol == null ? "pas assez de recul" : `volatilité ${ratePct(vol).replace("+", "")} par an`);
  } else {
    const g = p ? units(p.gain) : null, r = p ? rate(p.mwr) ?? rate(p.twr) : null;
    second = card("w-card", "rend", "Rendement", g == null ? "—" : `<span class="${g >= 0 ? "pos" : "neg"}">${signedMoney(g)} ${base()}</span>`, `${r == null ? "" : `${ratePct(r)} · `}${esc(range().label)}`);
  }
  return `<div class="sumcards wcards">${card("w-card", "alloc", "Répartition", a.v, a.s)}${second}
    ${FOLD.strat ? `<button class="sumcard wide" type="button" data-a="w-fold" data-v="strat" aria-expanded="false"><span class="l">Stratégies</span><span class="v">${st.v}${st.hot ? ' <span class="pill info">à voir</span>' : ""}</span><span class="s">${st.s}</span></button>` : ""}</div>${FOLD.strat ? "" : stratSection()}`;
}

SHEETS.walloc = () => ({ title: "Répartition", tall: true, body: allocDetail(scopeLines(lines() || [], { t: "home" })) });
SHEETS.wperf = () => ({
  title: "Performance", tall: true,
  body: `<div class="seg small" id="tabSeg" role="group" aria-label="Thème">${TABS.map(([k, l]) => `<button type="button" data-a="w-tab" data-v="${k}" aria-pressed="${S.tab === k}">${l}</button>`).join("")}</div><p class="hint">${esc(range().label)}</p>${perfSection(perfCtx(lines() || []))}`,
});
SHEETS.wdisplay = () => ({ title: "Affichage", body: displayBody(M, lines() || []) });

function listSection(sel) {
  const groups = Object.groupBy(sel, (l) => (S.view === "acc" ? `a:${l.acc}` : `s:${l.asset}`));
  const perf = M.perf, net = M.net;
  let rows = Object.entries(groups).map(([key, ls]) => {
    const f = ls[0];
    const c = f.kind === "debt" ? net && net.by_account[f.acc] : perf && (S.view === "acc" ? perf.by_account[f.acc] : perf.by_asset[f.asset]);
    if (f.kind === "debt") return { key, title: f.name, sub: `${esc(f.inst)} · ${DEBT_KIND[f.debtKind] || "Dette"}`, mark: debtMark({ kind: f.debtKind }, ""), value: sum(ls), c, debt: true };
    if (S.view === "acc") return { key, title: f.accName, sub: `${esc(f.inst)} · ${{ cash: "Compte", securities: "Titres", pension: "Prévoyance", crypto: "Crypto" }[f.kind] || ""}`, mark: facetMark("inst", f.inst, ""), value: sum(ls), c, cash: f.kind === "cash" };
    const q = ls.reduce((t, l) => t + Number(l.qty), 0), nAcc = new Set(ls.map((l) => l.acc)).size;
    return { key, title: f.name, sub: `<span class="money">${n0(q) === "0" ? q : n0(q)}</span> ${esc(f.unit)} · ${nAcc > 1 ? `${nAcc} comptes` : esc(accLabel(f))}`, mark: assetMark(f), value: sum(ls), c, cash: f.asset.startsWith("ccy:") };
  });
  const gainOf = (r) => (r.c ? units(r.c.gain) : -Infinity);
  rows.sort(S.sort === "val" ? (a, b) => b.value - a.value : S.sort === "chg" ? (a, b) => gainOf(b) - gainOf(a) : (a, b) => a.title.localeCompare(b.title, "fr"));
  rows = rows.filter((r) => Math.abs(r.value) >= 0.5 || S.view === "acc");
  const so = SORTS.find((s) => s.k === S.sort);
  const days = M.pts.length > 1 ? Math.round((Date.parse(M.pts[M.pts.length - 1].d) - Date.parse(M.pts[0].d)) / 864e5) : 0;
  const delta = (r) => {
    if (!r.c || M.pts.length < 2) return "";
    const g = units(r.c.gain);
    if (r.debt) return `<span class="faint num">intérêts ${signedMoney(g)}</span>`;
    if (r.cash) return `<span class="faint num">apports ${signedMoney(units(r.c.net_flows))}</span>`;
    const x = moneyRate(rate(r.c.personal), days);
    return gainSpan(g, x ? x.v : null).replace(` ${base()}`, "");
  };
  return `<section class="section" aria-labelledby="t-detail"><div class="detail-head" id="detailHead">
      <div class="seg" role="group" aria-label="Comptes ou actifs">${[["acc", "Comptes"], ["asset", "Actifs"]].map(([k, l]) => `<button type="button" data-a="w-view" data-v="${k}" aria-pressed="${S.view === k}">${l}</button>`).join("")}</div>
      <div class="detail-meta"><span>${rows.length} ${S.view === "acc" ? "compte" : "actif"}${rows.length > 1 ? "s" : ""}</span><button class="sort-btn" type="button" data-a="w-sort" aria-label="Trier par ${so.label}, toucher pour changer">Trier : ${so.label}${ic("sort")}</button></div></div>
    <h2 class="sr" id="t-detail">Comptes et actifs</h2>
    <div class="list">${rows.length ? rows.map((r) => `<button class="row row2 go-row" type="button" data-a="w-open" data-v="${esc(r.key)}">${r.mark}
      <span class="row-main"><span class="row-title">${esc(r.title)}</span><span class="row-sub">${r.sub}</span></span>
      <span class="row-num"><span class="row-val num">${amount(r.value)}</span><span class="row-delta">${delta(r)}</span></span><span class="go">${ic("chev")}</span></button>`).join("")
      : '<div class="empty">Aucun élément ne correspond à ces filtres.<br><button type="button" data-a="w-clear">Effacer les filtres</button></div>'}</div>
</section>`;
}

function homeSections(all) {
  const sel = scopeLines(all, { t: "home" });
  return cards(sel) + listSection(sel);
}

// --- actions ----------------------------------------------------------------------------------

function toggle(key, v) {
  const s = S.filters[key];
  if (s.has(v)) s.delete(v);
  else s.add(v);
  S.scrub = null;
}
// la répartition filtrée sur une seule valeur passe à l'axe suivant qui a encore plusieurs valeurs
function autoBy() {
  const sel = (lines() || []).filter((l) => match(l));
  if (new Set(sel.map((l) => l[S.by])).size > 1) return null;
  const k = BY.find((x) => x !== S.by && new Set(sel.map((l) => l[x])).size > 1);
  if (k) S.by = k;
  return k || null;
}
const announceSel = () => announce(`Sélection : ${n0(sum((lines() || []).filter((l) => match(l))))} ${base()}`);
const set = (patch) => { Object.assign(S, patch); remember(); store.notify(); };
const openPage = (page) => go("patrimoine", { page: page.slice(-4) });

export function only(key, v) {
  for (const f of FILTERS) S.filters[f.key].clear();
  S.filters[key].add(v);
  S.scrub = null;
  if (S.by === key) autoBy();
}

export const actions = {
  ...place.actions,
  filters: () => openSheet("filters"),
  "w-opt": (v) => { const i = v.indexOf("|"); toggle(v.slice(0, i), v.slice(i + 1)); store.notify(); announceSel(); },
  "w-clear": () => { for (const f of FILTERS) S.filters[f.key].clear(); store.notify(); announceSel(); },
  "w-byopen": () => openSheet("by"),
  "w-by": (v) => { if (SH.kind === "by") closeSheet(); set({ by: v }); },
  "w-card": (v) => { if (v !== "alloc") S.tab = v; openSheet(v === "alloc" ? "walloc" : "wperf"); },
  "w-display": () => openSheet("wdisplay"),
  "w-alloc": (v) => {
    const prev = { filters: Object.fromEntries(FILTERS.map((f) => [f.key, new Set(S.filters[f.key])])), by: S.by };
    const adding = !S.filters[S.by].has(v), name = fName(S.by, v);
    closeSheet();
    toggle(S.by, v);
    const nb = adding ? autoBy() : null;
    remember();
    store.notify();
    announceSel();
    const undo = () => Object.assign(S, prev);
    if (adding) toast(nb ? `Filtré sur « ${name} ». Répartition par ${byLabel(nb).toLowerCase()}.` : `Filtré sur « ${name} ».`, { undo });
  },
  "w-mode": (v) => set({ mode: v, scrub: null, ruler: null }),
  "w-unit": (v) => set({ unit: v, scrub: null }),
  "w-cmp": () => openSheet("cmp"),
  "w-cmp-set": (v) => { closeSheet(); set({ cmp: v || null }); },
  "w-tab": (v) => set({ tab: v }),
  "w-only": (v) => {
    const i = v.indexOf("|");
    only(v.slice(0, i), v.slice(i + 1));
    remember();
    if (store.params.tab !== "patrimoine" || trail().length) go("patrimoine", { top: true });
    else window.scrollTo({ top: 0 });
    store.notify();
    announceSel();
  },
  "w-period": (v) => { closeSheet(); set({ period: v, custom: null, scrub: null, ruler: null }); },
  "w-periods": () => openSheet("periods"),
  "w-pin": (v) => {
    if (S.pinned.includes(v)) {
      if (S.pinned.length <= 2) return toast("Garde au moins 2 périodes dans la barre");
      S.pinned = S.pinned.filter((x) => x !== v);
    } else {
      if (S.pinned.length >= 6) return toast("6 périodes au plus dans la barre");
      S.pinned = PRESETS.map((p) => p.k).filter((k) => k === v || S.pinned.includes(k));
    }
    set({});
  },
  "w-custom": () => {
    const a = $("w-d0").value, b = $("w-d1").value;
    if (!a || !b || b <= a) return toast("La fin doit suivre le début");
    closeSheet();
    set({ custom: [a, b], scrub: null, ruler: null });
  },
  "w-view": (v) => set({ view: v }),
  "w-sort": () => set({ sort: SORTS[(SORTS.findIndex((s) => s.k === S.sort) + 1) % SORTS.length].k }),
  // un compte (a:<id>) ou un actif (s:<actif>) : sa page, ajoutée au chemin
  "w-open": (v) => {
    closeSheet(true);
    const t = trail(), r = here();
    if (v.startsWith("a:")) {
      const id = v.slice(2);
      if (r.t === "acc" && r.id === id) return;
      openPage([...t, { t: "acc", id }]);
    } else openPage([...t, { t: "asset", id: v.slice(2), from: r.t === "acc" ? r.id : null }]);
  },
  "w-jump": (v) => actions["w-open"](v),
  "w-crumb": (v) => openPage(trail().slice(0, Number(v))),
  "w-home": () => { closeSheet(true); go("patrimoine", { page: null }); },
  "w-switch": () => openSheet("switch"),
  "w-switch-acc": (v) => { closeSheet(true); openPage([{ t: "acc", id: v }]); },
  "w-gross": (v) => { set({ gross: v === "gross", scrub: null, ruler: null }); announce(S.gross ? "Brut : dettes exclues" : "Net : dettes comprises"); },
  "w-where": (v) => { S.where = v; S.ruler = null; store.notify(); },
  "w-amode": (v) => { S.amode = v; S.ruler = null; S.scrub = null; store.notify(); },
  "w-series": (v) => {
    if (S.hidden.has(v)) S.hidden.delete(v);
    else S.hidden.add(v);
    set({});
  },
  "w-ruler": () => { closeSheet(); Object.assign(S, { rulerOn: !(S.rulerOn || S.ruler), ruler: null, scrub: null }); render(); },
  "w-ruler-clear": () => { Object.assign(S, { rulerOn: false, ruler: null }); render(); },
  "w-full": (v) => {
    closeSheet();
    Object.assign(S, { full: v === "1", scrub: null });
    render();
    if (S.full) { const l = $("lcw"); if (l) l.querySelector("svg").focus({ preventScroll: true }); }
    else $("cw").querySelector("svg")?.focus({ preventScroll: true });
  },
  "w-why": (v) => toast(v),
  "w-bucket": (k) => openSheet("bucket", k),
  "w-fold": (k) => { FOLD[k] = !FOLD[k]; store.notify(); },
  // le journal filtré sur ce compte, cet actif ou les paiements de cette dette ; le retour revient ici
  "w-journal": (key) => {
    const ls = (lines() || []).filter((l) => (key.startsWith("a:") ? `a:${l.acc}` : `s:${l.asset}`) === key);
    const f = ls[0];
    if (!f) return;
    let spec;
    if (f.kind === "debt") {
      const d = (store.data(paths.debts) || { items: [] }).items.find((x) => x.id === f.debt) || {};
      spec = { kind: "debt", id: f.debt, label: `Dette : ${f.name}`, jf: { ...(d.category_id ? { category: d.category_id } : {}), ...(d.account_id ? { account: d.account_id } : {}) } };
    } else if (key.startsWith("s:") && f.isin) {
      const r = here(), accs = [...new Set(ls.map((l) => l.acc))];
      const acc = r.t === "asset" && r.from && S.where === "here" ? r.from : accs.length === 1 ? accs[0] : null;
      spec = { kind: "asset", id: f.asset, label: `Actif : ${f.name}`, asset: { isin: f.isin, account: acc } };
    } else spec = { kind: "acc", id: f.acc, label: `Compte : ${accLabel(f)}`, jf: { account: f.acc } };
    go("journal", { link: linkTo(spec), top: true });
  },
};
