// Patrimoine : le haut de l'écran. La barre de contexte dit toujours ce que l'écran montre (tout
// le patrimoine, la sélection filtrée, un compte, un actif) ; le chemin et le retour mènent d'une
// page à l'autre. Le grand chiffre et le petit sélecteur à sa droite (Net/Brut, ou compte/Partout
// pour un actif) suivent ; sous la courbe, la légende, la règle et les périodes. Le plein écran
// reprend la même courbe en paysage, avec une info-bulle complète.
import { FILTERS, S, accName as ACC_NAME, accOf, activeCount, assetOf as ASSET_OF, fName, here, longDate, sum, trail } from "./wstate.js";
import { chartSVG, legendHTML, pct, px, rulerHTML, sgnMoney, tipHTML } from "./wchart.js";
import { esc, fill, ic, n0, nf } from "../../ui.js";
import { assetMark, instMark } from "./meta.js";
import { base } from "../../format.js";
import { kindFor } from "./wmodel.js";

const $ = (id) => document.getElementById(id);
const yearly = (r, days) => (r != null && days >= 365 ? (1 + r) ** (365 / days) - 1 : null);
const tone = (v) => (v == null || Math.abs(v) < 1e-9 ? "zero" : v > 0 ? "pos" : "neg");
const seg = (label, a, items) => `<div class="seg tiny" role="group" aria-label="${label}">${items.map(([v, l, on]) => `<button type="button" data-a="${a}" data-v="${v}" aria-pressed="${on}">${esc(l)}</button>`).join("")}</div>`;

// --- barre du haut : chemin et contexte ---------------------------------------------------------

const crumbName = (x) => (x.t === "acc" ? ACC_NAME(x.id) : ASSET_OF(x.id) ? ASSET_OF(x.id).name : x.id);

export function drawTop(all) {
  const t = trail(), r = here();
  $("pat-top").classList.toggle("paged", t.length > 0);
  const crumbs = $("patCrumbs");
  crumbs.hidden = !t.length;
  if (t.length) {
    const path = [`<button type="button" data-a="w-crumb" data-v="0">Patrimoine</button>`, ...t.slice(0, -1).map((x, k) => `<button type="button" data-a="w-crumb" data-v="${k + 1}">${esc(crumbName(x))}</button>`)];
    fill(crumbs, `<button class="back-btn" type="button" data-a="back" aria-label="Retour">${ic("back")}</button>
      <span class="crumb-path">${path.join('<span class="sep">›</span>')}<span class="sep">›</span><span class="here">${r.t === "acc" ? "Compte" : "Actif"}</span></span>
      <h1 class="sr">${esc(crumbName(r))}</h1>`);
  }
  fill($("filterbar"), ctxHTML(all, r));
}

function ctxHTML(all, r) {
  if (r.t === "home") {
    const n = activeCount();
    let h = `<button class="scope" type="button" data-a="w-switch" aria-haspopup="dialog" aria-label="${n ? "Patrimoine filtré" : "Tout le patrimoine"}, changer de compte"><span class="ibox tint sm" data-css="--c:var(--accent)" aria-hidden="true">${ic("layers")}</span><span class="t">${n ? "Patrimoine filtré" : "Tout le patrimoine"}</span>${ic("down", "chev")}</button>`;
    h += `<button class="fbtn${n ? " active" : ""}" type="button" data-a="filters" aria-haspopup="dialog">${ic("filter")}Filtres${n ? `<span class="count" aria-label="${n} actifs">${n}</span>` : ""}</button>`;
    for (const f of FILTERS) for (const v of S.filters[f.key]) {
      h += `<button class="chip" type="button" data-a="w-opt" data-v="${f.key}|${esc(v)}" aria-label="Retirer le filtre ${esc(fName(f.key, v))}">${esc(fName(f.key, v))}${ic("close")}</button>`;
    }
    if (n > 1) h += '<button class="clear-link" type="button" data-a="w-clear">Tout effacer</button>';
    return h;
  }
  if (r.t === "acc") {
    const l = accOf(r.id);
    return `<button class="scope on" type="button" data-a="w-switch" aria-haspopup="dialog" aria-label="Filtré sur ${esc(ACC_NAME(r.id))}, changer de compte">${l ? instMark(l.inst, "sm") : ""}<span class="t">${esc(ACC_NAME(r.id))}</span>${ic("down", "chev")}</button>
      <button class="scope-x" type="button" data-a="w-home" aria-label="Revenir à tout le patrimoine">${ic("close")}</button>
      ${activeCount() ? `<span class="chip-hint">Filtres du patrimoine gardés pour le retour (${activeCount()})</span>` : ""}`;
  }
  const a = ASSET_OF(r.id), held = new Set(all.filter((l) => l.asset === r.id).map((l) => l.acc)).size;
  return `<span class="scope on">${a ? assetMark(a, "sm") : ""}<span class="t">${esc(a ? a.name : r.id)}</span></span>
    <button class="scope-x" type="button" data-a="w-home" aria-label="Revenir à tout le patrimoine">${ic("close")}</button>
    ${held > 1 && !(r.from && S.where === "here") ? `<span class="chip-hint">dans ${held} comptes</span>` : ""}`;
}

// --- grand chiffre ------------------------------------------------------------------------------

function whereSeg(all, r) {
  const held = new Set(all.filter((l) => l.asset === r.id).map((l) => l.acc));
  if (!r.from || held.size < 2) return "";
  const l = accOf(r.from);
  return `<span class="netgross">${seg("Périmètre du chiffre", "w-where", [["here", l ? l.inst : "Ce compte", S.where === "here"], ["all", "Partout", S.where === "all"]])}</span>`;
}

export function heroHTML(m, all, r = here()) {
  const pts = m.pts;
  const anyDebt = r.t === "home" && all.some((l) => l.kind === "debt");
  const ng = anyDebt ? `<span class="netgross">${seg("Dettes dans le total", "w-gross", [["net", "Net", !S.gross], ["gross", "Brut", S.gross]])}</span>` : "";
  const right = r.t === "asset" ? whereSeg(all, r) : ng;
  const what = r.t === "acc" ? (m.onlyDebt ? "Reste à rembourser" : "Valeur du compte") : activeCount() ? "Sélection filtrée" : S.gross ? "Patrimoine brut, sans les dettes" : "Patrimoine net";
  if (pts.length < 2) {
    const v = sum(m.sel || []);
    return `<div class="hero-top"><span class="hero-label">${what}</span>${right}</div><div class="hero-amount num"><span class="money">${nf(v)}</span><small>${base()}</small></div>`;
  }
  const k = S.scrub == null ? pts.length - 1 : Math.min(S.scrub, pts.length - 1), p = pts[k], p0 = pts[0];
  const scrub = S.scrub != null;
  const days = Math.round((Date.parse(p.d) - Date.parse(p0.d)) / 864e5);
  const since = scrub ? `du ${p0.d.split("-").reverse().join(".")} au ${p.d.split("-").reverse().join(".")}` : m.label;
  const kind = kindFor(r);
  const at = (s) => (scrub ? `<b>${longDate(p.d)}</b>` : s);
  let label, big, sub = "";
  if (kind === "price") {
    label = at(`Cours · ${m.label}`);
    big = `<span class="money">${px(p.price)}</span><small>${esc(m.priceCcy || "")}</small>`;
    const ch = p.price / p0.price - 1;
    sub = `<div class="hero-delta"><span class="delta ${tone(ch)}">${pct(ch)}</span><span class="period-link">${since}</span></div>${m.pru ? `<div class="hero-sub">Prix de revient moyen <span class="money">${px(m.pru)}</span> ${base()} · ${pct(p.price / m.pru - 1)} sur ton prix</div>` : ""}`;
  } else if (kind === "pos") {
    const held = new Set(m.sel.map((l) => l.acc)).size;
    const where = r.from && S.where === "here" ? `dans ${accOf(r.from) ? accOf(r.from).inst : ""}` : held > 1 ? `partout (${held} comptes)` : `dans ${m.sel[0].inst}`;
    label = at(`Ma position · ${where}`);
    big = `<span class="money">${n0(p.v)}</span><small>${base()}</small>`;
    const lat = m.cost != null && !scrub ? p.v - m.cost : null;
    sub = `<div class="hero-delta"><span class="delta ${tone(p.g)}"><span class="money">${sgnMoney(p.g)}</span> ${base()} · ${pct(p.r)}</span><span class="period-link">${since}</span></div>${lat != null ? `<div class="hero-sub">Gain latent depuis l'achat <span class="money">${sgnMoney(lat)}</span> ${base()} (${pct(m.cost ? lat / m.cost : 0)})</div>` : ""}`;
  } else if (kind === "val") {
    label = at(what);
    big = `<span class="money">${nf(p.v)}</span><small>${base()}</small>`;
    if (m.onlyDebt) sub = `<div class="hero-delta"><span class="delta ${tone(p.v - p0.v)}"><span class="money">${sgnMoney(p.v - p0.v)}</span> ${base()}</span><span class="period-link">remboursés ${since}</span></div><div class="hero-sub">Intérêts <span class="money">${sgnMoney(p.g)}</span> ${base()}</div>`;
    else sub = `<div class="hero-delta"><span class="delta ${tone(p.g)}"><span class="money">${sgnMoney(p.g)}</span> ${base()}${p.r == null ? "" : ` · ${pct(p.r)}`}</span><span class="period-link">de gain ${since}</span></div><div class="hero-sub">${r.t === "home" && !activeCount() ? "Épargne" : "Apports nets"} <span class="money">${sgnMoney(p.f)}</span> · variation totale <span class="money">${sgnMoney(p.v - p0.v)}</span></div>`;
  } else {
    const yr = yearly(p.r, days);
    label = at(`Performance ${m.label}`);
    big = kind === "gain" ? `<span class="${tone(p.g)}"><span class="money">${sgnMoney(p.g)}</span></span><small>${base()}</small>` : `<span class="${tone(p.r)}">${pct(p.r)}</span>`;
    const other = kind === "gain" ? `<b class="${tone(p.r)}">${pct(p.r)}</b> pondéré dans le temps` : `<b class="${tone(p.g)}"><span class="money">${sgnMoney(p.g)}</span> ${base()}</b> de gain`;
    sub = `<div class="hero-delta"><span>soit ${other}</span></div><div class="hero-sub">${yr != null ? `${pct(yr)} par an · ` : ""}${m.cmp && p.b != null ? `repère ${esc(m.cmp.name)} ${pct(p.b)}` : "versements exclus"}</div>`;
  }
  const late = (m.unc || []).find((u) => u.k1 >= pts.length - 1);
  if (late && !scrub) sub += `<button class="warnline" type="button" data-a="w-why" data-v="${esc(late.why)}">${ic("info")}<span>Fin de courbe estimée : ${late.stale ? `${esc(ACC_NAME(late.acc))}, aucun relevé depuis ${late.age} jours` : "cours ou change manquant"}</span></button>`;
  return `<div class="hero-top"><span class="hero-label">${label}</span>${right}</div><div class="hero-amount num">${big}</div>${sub}`;
}

// --- outils, périodes -------------------------------------------------------------------------

export const cmpBtn = (m) => `<button class="cmp${S.cmp ? " on" : ""}" type="button" data-a="w-cmp" aria-haspopup="dialog">Repère : ${S.cmp ? esc(m.cmp ? m.cmp.name : "…") : "aucun"}${ic("down")}</button>`;

export function toolbarHTML(m, r, land) {
  let h = "";
  if (r.t === "asset") {
    if (m.sel.some((l) => l.isin)) h += seg("Courbe", "w-amode", [["pos", "Ma position", S.amode === "pos"], ["price", "Cours", S.amode === "price"]]);
  } else if (!m.onlyDebt) {
    h += seg("Mesure", "w-mode", [["val", "Valeur", S.mode === "val"], ["perf", "Performance", S.mode === "perf"]]);
    if (S.mode === "perf") h += seg("Unité", "w-unit", [["chf", base(), S.unit === "chf"], ["pct", "%", S.unit === "pct"]]);
  }
  h += '<span class="grow"></span>';
  if (land && kindFor(r) === "pct") h += cmpBtn(m);
  h += `<button class="tool" type="button" data-a="w-ruler" aria-pressed="${S.rulerOn || !!S.ruler}" aria-label="Mesurer entre deux dates" title="Mesurer entre deux dates">${ic("ruler")}</button>`;
  h += land ? `<button class="tool" type="button" data-a="w-full" data-v="0" aria-label="Quitter le plein écran">${ic("close")}</button>`
    : `<button class="tool" type="button" data-a="w-full" data-v="1" aria-label="Courbe en plein écran" title="Plein écran">${ic("expand")}</button>`;
  return `<div class="toolbar">${h}</div>`;
}

export function periodsHTML() {
  let h = S.pinned.map((k) => `<button class="pchip" type="button" data-a="w-period" data-v="${k}" aria-pressed="${!S.custom && S.period === k}">${k}</button>`).join("");
  if (S.custom) h += `<button class="pchip custom" type="button" data-a="w-periods" aria-pressed="true">${S.custom[0].split("-").reverse().join(".")} → ${S.custom[1] ? S.custom[1].split("-").reverse().join(".") : "auj."}</button>`;
  h += `<button class="pchip more" type="button" data-a="w-periods" aria-haspopup="dialog" aria-label="Toutes les périodes et plage personnalisée">${ic("dots")}</button>`;
  return `<div class="periods" role="group" aria-label="Période">${h}</div>`;
}

// --- plein écran --------------------------------------------------------------------------------

export function drawLand(m, all) {
  let host = $("wland");
  if (!S.full) {
    if (host) host.remove();
    document.body.classList.remove("land-open");
    return;
  }
  if (!host) {
    host = document.createElement("div");
    host.id = "wland";
    document.body.append(host);
  }
  document.body.classList.add("land-open");
  const r = here(), kind = kindFor(r);
  const portrait = innerWidth <= 900 && innerHeight > innerWidth;
  const fw = portrait ? innerHeight : innerWidth, fh = portrait ? innerWidth : innerHeight;
  const W = Math.min(fw - 40, 1100), H = Math.max(160, fh - 150);
  const pts = m.pts, p = pts.length ? pts[S.scrub == null ? pts.length - 1 : Math.min(S.scrub, pts.length - 1)] : null;
  const title = r.t === "home" ? (activeCount() ? "Sélection filtrée" : S.gross ? "Patrimoine brut" : "Patrimoine net") : r.t === "acc" ? ACC_NAME(r.id) : `${ASSET_OF(r.id) ? ASSET_OF(r.id).name : ""}`;
  const bigV = !p ? "" : kind === "price" ? `${px(p.price)} ${esc(m.priceCcy || "")}` : kind === "pct" ? pct(p.r) : kind === "gain" ? `${sgnMoney(p.g)} ${base()}` : `${nf(p.v)} ${base()}`;
  fill(host, `<div class="land${portrait ? " rot" : ""}" role="dialog" aria-modal="true" aria-label="Courbe en plein écran"><div class="land-frame" data-css="width:${fw}px;height:${fh}px">
    <div class="land-head"><div class="ttl"><span>${esc(m.label)}</span><b>${esc(title)}</b></div>${toolbarHTML(m, r, true)}<div class="big num"><span class="money">${bigV}</span></div></div>
    <div class="chart-wrap" data-chart="land" id="lcw">${chartSVG(m, kind, W, H, { interactive: true, big: true })}${tipHTML(m, kind, W)}</div>
    <div id="lrul">${rulerHTML(m, kind)}</div>
    <div class="land-foot">${periodsHTML()}<div class="legend">${legendHTML(m, kind)}</div></div>
  </div></div>`);
  return { W, H };
}
