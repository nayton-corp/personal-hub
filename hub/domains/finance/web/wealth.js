// Patrimoine : la sélection (filtres par catégorie, disponibilité, objectif, institution, compte,
// actif) pilote l'écran : total et courbe, répartition, performance, puis la liste des comptes
// ou des actifs. Toucher un compte ou un actif ouvre sa page (wpages.js), avec retour et chemin ;
// la barre de contexte dit toujours ce que l'écran montre. État et lignes : wstate.js ; courbe :
// wmodel.js et wchart.js ; haut de l'écran : whero.js ; panneaux : wsheets.js.
import { BY, FILTERS, FOLD, LOOK, PRESETS, S, SORTS, TABS, accLabel, activeCount, fName, here, lines, match, paths, range, remember, scopeLines, sum, trail } from "./wstate.js";
import { amount, announce, closeSheet, cv, esc, fill, ic, money, n0, openSheet, setPref, share, skel, toast } from "../../ui.js";
import { accountPage, assetPage } from "./wpages.js";
import { chartSVG, flagHTML, gutter, legendHTML, nearest, rulerHTML } from "./wchart.js";
import { cmpBtn, drawLand, drawTop, heroHTML, periodsHTML, toolbarHTML } from "./whero.js";
import { facetColor, facetMark, assetMark, lookMark } from "./meta.js";
import { gainSpan, perfSection, perfSummary, rate, signedMoney, units } from "./perf.js";
import { kindFor, model } from "./wmodel.js";
import { DEBT_KIND, debtMark } from "./debts.js";
import { byLabel } from "./wsheets.js";
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
    <div class="hero" id="evo"><div id="hero"></div><div id="wtools"></div><div id="wcmp"></div>
      <div class="chart-wrap" data-chart="main" id="cw"></div><div class="legend" id="legend"></div><div id="wrul"></div><div id="wper"></div></div>
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
  fill($("hero"), heroHTML(M, all, r));
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
    for (const id of ["wtools", "wcmp", "cw", "legend", "wrul", "wper", "wsecs"]) fill($(id), "");
    return;
  }
  const r = here(), kind = kindFor(r);
  M = model(r);
  if (S.scrub != null && S.scrub >= M.pts.length) S.scrub = null;
  fill($("wtools"), toolbarHTML(M, r, false));
  fill($("wcmp"), kind === "pct" ? `<div class="toolbar">${cmpBtn(M)}</div>` : "");
  updateChart();
  fill($("legend"), M.pts.length > 1 ? legendHTML(M, kind) : "");
  fill($("wper"), periodsHTML());
  fill($("wsecs"), r.t === "acc" ? accountPage(M, r) : r.t === "asset" ? assetPage(M, all, r) : homeSections(all));
  fill($("miniTotal"), `${r.t === "home" && activeCount() ? "Sélection · " : ""}${money(sum(M.sel))} ${base()}`);
  const dh = $("detailHead");
  if (dh) requestAnimationFrame(() => dh.style.setProperty("--topbar-h", `${$("pat-top").offsetHeight}px`));
}

// --- patrimoine : répartition, performance, comptes et actifs --------------------------------

const look = () => LOOK.some(([k]) => k === S.by);
function allocRows(sel, all) {
  if (!look()) {
    const g = {};
    for (const l of sel) if (l[S.by] != null) g[l[S.by]] = (g[l[S.by]] || 0) + l.value;
    const rank = Object.keys(g);
    return { rows: Object.entries(g).filter(([, v]) => Math.abs(v) >= 0.5).sort((a, b) => b[1] - a[1]).map(([k, v], i) => ({ k, v, name: fName(S.by, k), c: S.by === "acc" || S.by === "asset" ? cv(i) : facetColor(S.by, k), rank })) };
  }
  const e = store.use(`/finance/lookthrough?dimension=${S.by}`);
  if (e.status === "error") return { error: e.error.message };
  if (!e.data) return { loading: true };
  const items = e.data.items.map((x) => ({ k: x.bucket, v: units(x.value) }));
  if (S.by === "currency") {
    for (const l of all) {
      if (!l.asset.startsWith("ccy:") || l.kind === "debt" || l.value <= 0) continue;
      const it = items.find((x) => x.k === l.unit) || items[items.push({ k: l.unit, v: 0 }) - 1];
      it.v += l.value;
    }
  }
  return { rows: items.filter((x) => x.v >= 0.5).sort((a, b) => b.v - a.v).map((x, i) => ({ ...x, name: x.k, c: cv(i) })), fund: true };
}

function layout(rows, x, y, w, h, out = []) {
  if (!rows.length) return out;
  if (rows.length === 1) { out.push({ r: rows[0], x, y, w, h }); return out; }
  const tot = rows.reduce((t, r) => t + r.v, 0);
  let acc = 0, k = 0;
  while (k < rows.length - 1 && acc + rows[k].v <= tot / 2) acc += rows[k++].v;
  if (!k) { acc = rows[0].v; k = 1; }
  const f = acc / tot;
  if (w >= h) { layout(rows.slice(0, k), x, y, w * f, h, out); layout(rows.slice(k), x + w * f, y, w * (1 - f), h, out); }
  else { layout(rows.slice(0, k), x, y, w, h * f, out); layout(rows.slice(k), x, y + h * f, w, h * (1 - f), out); }
  return out;
}

function allocSection(sel, all) {
  const a = allocRows(sel, all);
  const head = `<div class="section-head"><h2 class="section-title" id="t-alloc">Répartition</h2><button class="by-btn" type="button" data-a="w-byopen" aria-haspopup="dialog">par ${esc(byLabel(S.by).toLowerCase())}${ic("down")}</button></div>`;
  if (a.error || a.loading) return `<section class="section" aria-labelledby="t-alloc">${head}${a.error ? `<div class="err-box" role="alert">Composition indisponible : ${esc(a.error)}</div>` : skel("block")}</section>`;
  const rows = a.rows.filter((r) => r.v > 0), owed = a.rows.filter((r) => r.v < 0).reduce((t, r) => t + r.v, 0);
  const total = rows.reduce((t, r) => t + r.v, 0);
  if (!rows.length || total <= 0) return `<section class="section" aria-labelledby="t-alloc">${head}<div class="empty">${a.fund ? "Aucune composition de fonds connue pour l'instant." : "Rien à répartir avec ces filtres."}</div></section>`;
  const mark = (r) => (a.fund ? lookMark(S.by, r.k, r.c) : S.by === "asset" ? assetMark((lines() || []).find((l) => l.asset === r.k) || { name: r.name, cat: "funds" }, "sm") : S.by === "acc" ? facetMark("inst", ((lines() || []).find((l) => l.acc === r.k) || {}).inst || r.name) : facetMark(S.by, r.k));
  const act = (r) => (a.fund ? `data-a="w-bucket" data-v="${esc(r.k)}"` : `data-a="w-alloc" data-v="${esc(r.k)}"`);
  const on = (r) => !a.fund && S.filters[S.by].has(r.k);
  const tm = layout(rows, 0, 0, 340, 170).map(({ r, x, y, w, h }) => {
    const big = w > 70 && h > 38, mid = w > 38 && h > 20;
    return `<g class="tm-cell${on(r) ? " on" : ""}" ${act(r)}><rect x="${(x + 1.5).toFixed(1)}" y="${(y + 1.5).toFixed(1)}" width="${Math.max(0, w - 3).toFixed(1)}" height="${Math.max(0, h - 3).toFixed(1)}" rx="6" data-css="--c:${r.c}"/>
      ${big ? `<text class="tm-n" x="${(x + 9).toFixed(1)}" y="${(y + 19).toFixed(1)}">${esc(r.name.length > w / 7.5 ? `${r.name.slice(0, Math.max(3, Math.floor(w / 7.5) - 1))}…` : r.name)}</text><text class="tm-v" x="${(x + 9).toFixed(1)}" y="${(y + 35).toFixed(1)}">${Math.round((r.v / total) * 100)} %</text>`
        : mid ? `<text class="tm-v" x="${(x + 6).toFixed(1)}" y="${(y + h / 2 + 4).toFixed(1)}">${Math.round((r.v / total) * 100)} %</text>` : ""}</g>`;
  }).join("");
  const hint = a.fund ? `Ce que contiennent tes fonds${S.by === "currency" ? ", plus tes liquidités" : ""}, sur tous tes placements : lecture seule, les filtres ne s'y appliquent pas. Toucher un bloc montre les actifs qui y contribuent.`
    : `${activeCount() ? "De la sélection filtrée." : "De tout le patrimoine."} Toucher un bloc ou une ligne filtre l'écran.`;
  return `<section class="section" aria-labelledby="t-alloc">${head}<p class="hint">${hint}</p>
    <svg class="chart tm" viewBox="0 0 340 170" aria-hidden="true">${tm}</svg>
    <div class="alloc-list">${rows.map((r) => `<button class="alloc-row" type="button" ${act(r)} ${a.fund ? 'aria-haspopup="dialog"' : `aria-pressed="${on(r)}"`} aria-label="${esc(r.name)}, ${share(r.v / total)}, ${a.fund ? "voir les actifs" : on(r) ? "retirer ce filtre" : "filtrer l'écran sur cette valeur"}">
      ${mark(r)}<span class="alloc-name">${esc(r.name)}</span><span class="alloc-pct num">${share(r.v / total)}</span><span class="alloc-val">${amount(r.v)}</span><span class="fic">${ic(a.fund ? "chev" : on(r) ? "close" : "filter")}</span></button>`).join("")}
    ${owed < 0 ? `<div class="alloc-row static">${facetMark("cat", "debt")}<span class="alloc-name">Dettes, retranchées</span><span class="alloc-pct"></span><span class="alloc-val">${amount(owed)}</span><span></span></div>` : ""}</div></section>`;
}

function perfBlock(all) {
  const ctx = {
    S, n: activeCount(), per: { label: range().label }, perf: M.perf, src: { status: M.status, error: M.error }, all, sel: M.sel, pts: M.pts,
    fmtDate: (d) => d.split("-").reverse().join("."),
  };
  return `<section class="section${FOLD.perf ? " folded" : ""}" id="perf" aria-labelledby="t-perf">
    <div class="section-head"><button class="fold-btn" type="button" data-a="w-fold" data-v="perf" aria-expanded="${!FOLD.perf}" aria-controls="perf-body"><h2 class="section-title" id="t-perf">Performance</h2>${ic("down", "fold-chev")}</button><span class="sec-note">${esc(range().label)}</span></div>
    <button class="sec-sum" type="button" data-a="w-fold" data-v="perf" aria-label="Déplier la performance">${perfSummary(M.perf, range().label)}</button>
    <div class="sec-body" id="perf-body">${FOLD.perf ? "" : `<div class="scroll-x"><div class="seg small" id="tabSeg" role="group" aria-label="Thème">${TABS.map(([k, l]) => `<button type="button" data-a="w-tab" data-v="${k}" aria-pressed="${S.tab === k}">${l}</button>`).join("")}</div></div>${perfSection(ctx)}`}</div></section>`;
}

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
  const delta = (r) => {
    if (!r.c || M.pts.length < 2) return "";
    const g = units(r.c.gain);
    if (r.debt) return `<span class="faint num">intérêts ${signedMoney(g)}</span>`;
    if (r.cash) return `<span class="faint num">apports ${signedMoney(units(r.c.net_flows))}</span>`;
    return gainSpan(g, rate(r.c.twr)).replace(` ${base()}`, "");
  };
  return `<section class="section" aria-labelledby="t-detail"><div class="detail-head" id="detailHead">
      <div class="seg" role="group" aria-label="Comptes ou actifs">${[["acc", "Comptes"], ["asset", "Actifs"]].map(([k, l]) => `<button type="button" data-a="w-view" data-v="${k}" aria-pressed="${S.view === k}">${l}</button>`).join("")}</div>
      <div class="detail-meta"><span>${rows.length} ${S.view === "acc" ? "compte" : "actif"}${rows.length > 1 ? "s" : ""}</span><button class="sort-btn" type="button" data-a="w-sort" aria-label="Trier par ${so.label}, toucher pour changer">Trier : ${so.label}${ic("sort")}</button></div></div>
    <h2 class="sr" id="t-detail">Comptes et actifs</h2>
    <div class="list">${rows.length ? rows.map((r) => `<button class="row row2 go-row" type="button" data-a="w-open" data-v="${esc(r.key)}">${r.mark}
      <span class="row-main"><span class="row-title">${esc(r.title)}</span><span class="row-sub">${r.sub}</span></span>
      <span class="row-num"><span class="row-val num">${amount(r.value)}</span><span class="row-delta">${delta(r)}</span></span><span class="go">${ic("chev")}</span></button>`).join("")
      : '<div class="empty">Aucun élément ne correspond à ces filtres.<br><button type="button" data-a="w-clear">Effacer les filtres</button></div>'}</div>
    <p class="hint">Toucher une ligne ouvre sa page : la courbe et les chiffres se limitent à ce ${S.view === "acc" ? "compte" : "actif"}.</p></section>`;
}

function homeSections(all) {
  const sel = scopeLines(all, { t: "home" });
  return allocSection(sel, all) + perfBlock(all) + listSection(sel);
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
  filters: () => openSheet("filters"),
  "w-opt": (v) => { const i = v.indexOf("|"); toggle(v.slice(0, i), v.slice(i + 1)); store.notify(); announceSel(); },
  "w-clear": () => { for (const f of FILTERS) S.filters[f.key].clear(); store.notify(); announceSel(); },
  "w-byopen": () => openSheet("by"),
  "w-by": (v) => { closeSheet(); set({ by: v }); },
  "w-alloc": (v) => {
    const prev = { filters: Object.fromEntries(FILTERS.map((f) => [f.key, new Set(S.filters[f.key])])), by: S.by };
    const adding = !S.filters[S.by].has(v), name = fName(S.by, v);
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
  "w-ruler": () => { Object.assign(S, { rulerOn: !(S.rulerOn || S.ruler), ruler: null, scrub: null }); render(); },
  "w-ruler-clear": () => { Object.assign(S, { rulerOn: false, ruler: null }); render(); },
  "w-full": (v) => {
    Object.assign(S, { full: v === "1", scrub: null });
    render();
    if (S.full) { const l = $("lcw"); if (l) l.querySelector("svg").focus({ preventScroll: true }); }
    else $("cw").querySelector("svg")?.focus({ preventScroll: true });
  },
  "w-why": (v) => toast(v),
  "w-bucket": (k) => openSheet("bucket", k),
  "w-fold": (k) => { FOLD[k] = !FOLD[k]; setPref("fold", FOLD); store.notify(); },
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
