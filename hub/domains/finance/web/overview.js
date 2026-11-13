// Aperçu : la page d'entrée de l'espace Finance. Le patrimoine dans une carte (sa courbe sur un
// an), deux cartes résumé (reste à vivre, épargné ce mois), puis « À faire » et « À savoir » :
// les mêmes lignes que l'accueil du hub (home.js), sans le nom du domaine. Rien n'est calculé
// ici : tout vient de /api/finance.
import { row } from "../../accueil.js";
import { pendingCount, pendingPath } from "../../approvals.js";
import { base, units } from "../../format.js";
import { store } from "../../store.js";
import { esc, fill, ic, n0, nf, pf, sgn, skel } from "../../ui.js";
import { model } from "./bmodel.js";
import { budgetPath } from "./budget.js";
import { rows } from "./home.js";
import { STRATS } from "./strategies.js";
import { breaksPath } from "./wplace.js";

const kpisPath = () => `/finance/kpis?month=${store.today}`;
const flowsPath = () => `/finance/flows?month=${store.today}&period=m`;
const USES = ["/observations?domain=finance", "/collectors/connections", "/collectors", "/finance/accounts"];

// un an de valeur, un point par semaine
function yearPath(k) {
  const d = new Date(`${k.as_of}T00:00:00Z`);
  d.setUTCFullYear(d.getUTCFullYear() - 1);
  return `/finance/performance?from=${d.toISOString().slice(0, 10)}&step=week`;
}

// la courbe de la carte : une ligne et son aire, sans axe (le détail est dans Patrimoine)
function curve(vals, w = 320, h = 84) {
  if (vals.length < 2) return "";
  const mn = Math.min(...vals), mx = Math.max(...vals), d = mx - mn || 1;
  const pts = vals.map((v, i) => [(i / (vals.length - 1)) * w, 4 + (h - 8) * (1 - (v - mn) / d)]);
  const line = pts.map((p) => p.map((x) => x.toFixed(1)).join(",")).join("L");
  const [lx, ly] = pts[pts.length - 1];
  return `<svg class="ov-curve" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true"><path class="area" d="M0,${h}L${line}L${w},${h}Z"/><path class="line" d="M${line}"/><circle cx="${lx.toFixed(1)}" cy="${ly.toFixed(1)}" r="3.5"/></svg>`;
}

function hero(k, perf) {
  const sum = perf ? perf.owned || perf.summary : null;
  const vals = perf ? perf.items.map((i) => units(i.value)) : [];
  const gain = sum ? units(sum.gain) : null;
  const p = sum && sum.personal != null ? Number(sum.personal) : null;
  const net = units(k.net_worth);
  const stale = k.stale_accounts > 0 ? `<span class="ov-flag">${k.stale_accounts} à actualiser</span>` : "";
  const delta = gain == null ? "" : `<span class="delta ${Math.round(gain) === 0 ? "zero" : gain >= 0 ? "pos" : "neg"} num"><span class="money">${sgn(gain)}${n0(gain)}</span> ${base()}${p == null ? "" : ` · ${sgn(p)}${pf(Math.abs(p))} %`}</span> <span class="ov-per">sur 1 an</span>`;
  return `<button class="ov-hero" type="button" data-a="tab" data-v="patrimoine" aria-label="Patrimoine net ${n0(net)} ${base()}. Ouvrir le patrimoine">
      <span class="ov-top"><span>Patrimoine net</span>${stale}</span>
      <span class="ov-amt num"><span class="money">${nf(net)}</span><small>${base()}</small></span>
      <span class="ov-delta">${delta}</span>
      ${curve(vals)}
    </button>`;
}

function cards(b, f) {
  const m = b ? model(b) : null;
  let rest;
  if (!m) rest = `<span class="l">Reste à vivre</span>${skel("block")}`;
  else if (m.T == null) rest = `<span class="l">Dépensé ce mois${ic("chev")}</span><span class="v num"><span class="money">${n0(m.spent)}</span></span><span class="s">Pas encore de budget</span>`;
  else {
    rest = `<span class="l">Reste à vivre${ic("chev")}</span><span class="v num${m.rest < 0 ? " neg" : ""}"><span class="money">${nf(m.rest)}</span></span>
      <span class="pbar thin" data-css="--c:${m.state.color}"><i data-css="width:${Math.min(100, m.ratio * 100).toFixed(1)}%"></i>${m.expected != null ? `<span class="pace" data-css="left:${(m.expected * 100).toFixed(1)}%"></span>` : ""}</span>
      <span class="s">${m.daysLeft != null ? `${m.daysLeft} jour${m.daysLeft > 1 ? "s" : ""} restant${m.daysLeft > 1 ? "s" : ""}` : esc(m.state.short)}</span>`;
  }
  let saved = `<span class="l">Épargné ce mois</span>${skel("block")}`;
  if (f) {
    const I = units(f.income) || 0, S = units(f.groups.find((x) => x.group === "savings")?.total) || 0;
    saved = `<span class="l">Épargné ce mois${ic("chev")}</span><span class="v num"><span class="money">${n0(S)}</span></span><span class="s">${I > 0 ? `${pf(S / I, 0)} % des revenus` : "Aucun revenu reçu ce mois"}</span>`;
  }
  return `<div class="sumcards"><button class="sumcard" type="button" data-a="tab" data-v="budget">${rest}</button><button class="sumcard" type="button" data-a="tab" data-v="budget">${saved}</button></div>`;
}

function lists() {
  const all = rows();
  if (!all) return skel("block");
  const n = pendingCount();
  const acts = all.filter((x) => !x.info), infos = all.filter((x) => x.info);
  if (n > 0) acts.unshift({ ic: "faceid", c: "var(--accent)", t: `${n} proposition${n > 1 ? "s" : ""} à valider`, s: "Sur l'accueil du hub, en un Face ID", a: "hub" });
  return `<section class="flat" aria-labelledby="t-ov-todo"><h2 class="flat-title" id="t-ov-todo">À faire</h2>
      ${acts.length ? acts.map(row).join("") : `<div class="status good">${ic("check")}<span>Rien à faire, tout est à jour.</span></div>`}</section>
    ${infos.length ? `<section class="flat" aria-labelledby="t-ov-info"><h2 class="flat-title" id="t-ov-info">À savoir</h2>${infos.map(row).join("")}</section>` : ""}`;
}

export function render() {
  const box = document.getElementById("apercu-body");
  const ke = store.use(kpisPath());
  const k = ke.data;
  for (const p of [...USES, breaksPath, STRATS, pendingPath]) store.use(p);
  const be = store.use(budgetPath(store.today, "m"));
  const fe = store.use(flowsPath());
  if (ke.status === "error") {
    fill(box, `<div class="err-box" role="alert">Impossible de charger l'aperçu : ${esc(ke.error.message)}</div>`);
    return;
  }
  if (!k) {
    fill(box, skel());
    return;
  }
  const pe = store.use(yearPath(k));
  fill(box, `${hero(k, pe.data)}${cards(be.data, fe.data)}${lists()}<div class="endspace"></div>`);
}

export const actions = {};
