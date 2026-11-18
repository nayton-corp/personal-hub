// Budget, le corps du mois (refonte du budget, lot B) : les dépenses du quotidien (ce qui reste
// d'abord), les catégories hors budget en net, les charges fixes du mois (une par catégorie, payées
// ou attendues, /finance/budget/upcoming) et les provisions de l'année. Tout vient du serveur.
import { MOIS, base, units } from "../../format.js";
import { esc, ic, m0, money, n0 } from "../../ui.js";
import { catMark } from "./meta.js";
import { rank } from "./bmodel.js";
import { UNCAT, dayMonth } from "./bhero.js";
import { store } from "../../store.js";

const u = (m) => (m ? units(m) : 0);
const iso = () => new Date().toISOString().slice(0, 10);
const isOff = (l) => (l.group === "variable" || l.group === "mixed") && l.t == null && !l.yearly && l.category !== UNCAT;

// la barre d'une catégorie : toute la largeur vaut sa cible ; au-delà, la part en trop en rouge
function bar(ratio, pace) {
  if (ratio > 1) {
    const k = 1 / ratio;
    return `<span class="pbar thin pc split"><i data-css="width:${(k * 100).toFixed(1)}%"></i><b class="ov" data-css="width:${((1 - k) * 100).toFixed(1)}%"></b></span>`;
  }
  const mark = pace != null && pace > 0 && pace < 1 ? `<span class="pace" data-css="left:${(pace * 100).toFixed(1)}%"></span>` : "";
  return `<span class="pbar thin pc"><i data-css="width:${(Math.max(0, ratio) * 100).toFixed(1)}%"></i>${mark}</span>`;
}

function row(c, pace) {
  const rest = c.t - c.s, over = rest < 0;
  const st = over ? `${m0(c.s)} sur ${m0(c.t)} · ${m0(-rest)} de trop` : `${m0(c.s)} sur ${m0(c.t)}${c.state === "likely_over" ? " · au-dessus du rythme" : ""}`;
  return `<button class="crow" type="button" data-a="cat" data-v="${esc(c.category)}" aria-label="${esc(c.name)} : ${over ? "dépassé" : "reste"} ${n0(Math.abs(rest))} ${base()}">
    ${catMark(c.category, c.group)}<span><span class="crow-top"><b>${esc(c.name)}</b>
    <span class="brest num${over ? " neg" : ""}"><small>${over ? "dépassé" : "reste"}</small>${over ? "−" : ""}${m0(Math.abs(rest))}</span></span>
    ${bar(c.t ? c.s / c.t : 0, pace)}<span class="crow-st ok">${st}</span></span></button>`;
}

const spentRow = (c) => `<button class="crow" type="button" data-a="cat" data-v="${esc(c.category)}">${catMark(c.category, c.group)}<span><span class="crow-top"><b>${esc(c.name)}</b>
  <span class="brest num"><small>dépensé</small>${m0(c.s)}</span></span><span class="crow-st ok">${c.count} écriture${c.count > 1 ? "s" : ""} · sans cible</span></span></button>`;

// B : { offOpen } (« Hors cible » déplié)
export function daily(m, B) {
  const vars = m.lines.filter((l) => (l.group === "variable" || l.group === "mixed") && l.t != null && !l.yearly)
    .sort((x, y) => rank(y) - rank(x) || y.s / y.t - x.s / x.t);
  const cats = (store.data("/finance/categories") || { items: [] }).items;
  const free = (l) => ((cats.find((c) => c.id === l.category) || { mode: "target" }).mode === "target" ? 0 : 1);
  // d'abord celles qui pourraient avoir une cible, puis les suivies sans cible
  const off = m.lines.filter(isOff).sort((x, y) => free(x) - free(y) || y.s - x.s);
  if (!vars.length && !off.length) return "";
  const pace = m.current ? m.expected : null;
  const vs = vars.reduce((t, c) => t + c.s, 0), vt = vars.reduce((t, c) => t + c.t, 0), os = off.reduce((t, c) => t + c.s, 0);
  const could = off.filter((l) => !free(l)).length;
  const offRow = off.length ? `<button class="crow" type="button" data-a="boff" aria-expanded="${B.offOpen}">${catMark("divers", "variable")}<span><span class="crow-top"><b>Hors cible</b>
      <span class="brest num"><small>dépensé</small>${m0(os)}</span></span><span class="crow-st ok">${off.map((c) => esc(c.name)).join(", ")} · compté dans le reste</span></span></button>
    ${B.offOpen ? `<div class="crow-sub">${off.map(spentRow).join("")}</div>` : ""}
    ${could ? `<div class="bfix-cta">${ic("plus")}<span>${could} catégorie${could > 1 ? "s" : ""} sans cible.</span><button type="button" data-a="plan">Fixer des cibles</button></div>` : ""}` : "";
  return `<section class="card bflat" id="budCats" aria-labelledby="t-daily">
    <div class="section-head"><h2 class="section-title" id="t-daily">Dépenses du quotidien</h2><span class="hint num">${money(vs + os)}${vt ? ` / ${money(vt)}` : ""}</span></div>
    ${vars.map((c) => row(c, pace)).join("")}${offRow}
  </section>`;
}

// catégories hors budget : ni dans le dépensé ni dans le reste, montrées en net
export function outside(b) {
  const xs = b.off_budget || [];
  if (!xs.length) return "";
  return `<section class="card bflat" aria-labelledby="t-out">
    <div class="section-head"><h2 class="section-title" id="t-out">Hors budget</h2><span class="hint">ne compte pas dans le reste</span></div>
    ${xs.map((x) => {
      const net = u(x.net);
      return `<button class="crow" type="button" data-a="cat" data-v="${esc(x.category)}">${catMark(x.category, "variable")}<span><span class="crow-top"><b>${esc(x.name)}</b>
        <span class="brest num"><small>net</small>${net > 0 ? "−" : "+"}${m0(Math.abs(net))}</span></span>
        <span class="crow-st ok">${x.count} écriture${x.count > 1 ? "s" : ""} · ${net > 0 ? "plus envoyé que reçu" : "plus reçu qu'envoyé"}</span></span></button>`;
    }).join("")}
  </section>`;
}

// --- à venir : les charges fixes du mois, par date ---------------------------------------------

const dateBox = (d, done) => `<span class="up-date${done ? " done" : ""}"><b>${Number(d.slice(8, 10))}</b><span>${MOIS[Number(d.slice(5, 7)) - 1]}</span></span>`;

function when(d) {
  const days = Math.round((Date.parse(d) - Date.parse(iso())) / 864e5);
  return days < 0 ? "" : days === 0 ? "aujourd'hui" : days === 1 ? "demain" : `dans ${days} jours`;
}

// une charge fixe : sa catégorie ; « via » les abonnements repérés qui la datent
function upRow(x) {
  const paid = x.status === "paid", via = x.via ? ` · ${esc(x.via)}` : "";
  const st = paid ? `${ic("check")}payé le ${dayMonth(x.on)}${via}` : x.status === "late" ? `<span class="pill warn">${ic("clock")}pas encore vu</span>${via}` : `${when(x.on) || "ce mois"}${via}`;
  const tip = x.suggested_target ? ` · cible proposée ${m0(u(x.suggested_target))}` : "";
  return `<button class="up-row${paid ? " paid" : ""}" type="button" data-a="cat" data-v="${esc(x.category)}">${dateBox(x.on, paid)}<span class="up-main"><b>${esc(x.name)}</b><span>${st}${tip}</span></span>
    <span class="num up-v">${m0(u(x.amount))}</span></button>`;
}

// up : /finance/budget/upcoming ; B : { paidOpen }
export function upcoming(up, b, B) {
  if (!up || !up.items.length) return "";
  const next = up.items.filter((x) => x.status !== "paid"), paid = up.items.filter((x) => x.status === "paid");
  const tn = u(up.due_total), tp = paid.reduce((t, x) => t + u(x.amount), 0);
  const title = b.current ? "Charges fixes du mois" : "Charges fixes";
  return `<section class="card bflat" id="upcoming" aria-labelledby="t-up">
    <div class="section-head"><h2 class="section-title" id="t-up">${title}</h2><span class="hint">${paid.length} sur ${up.items.length} payé${paid.length > 1 ? "s" : ""}</span></div>
    <div class="up-sum"><span><b class="num">${m0(tp)}</b> payés</span><span class="up-bar"><i data-css="width:${tp + tn ? ((tp / (tp + tn)) * 100).toFixed(1) : 0}%"></i></span>
      <span><b class="num">${m0(tn)}</b> ${b.current ? "à venir" : "pas vus"}</span></div>
    ${next.length ? next.map(upRow).join("") : '<div class="empty">Plus rien d\'attendu d\'ici la fin du mois.</div>'}
    ${paid.length ? `<button class="grp grp-btn" type="button" data-a="bpaid" aria-expanded="${B.paidOpen}"><span>Déjà payé · <span class="num">${m0(tp)}</span></span>
      <span class="grp-st">${paid.length} ligne${paid.length > 1 ? "s" : ""}${ic("down", B.paidOpen ? "up" : "")}</span></button>${B.paidOpen ? paid.map(upRow).join("") : ""}` : ""}
  </section>`;
}

// --- provisions de l'année : les catégories suivies à l'année, au rythme de l'année -------------

export function provisions(m) {
  const ys = m.lines.filter((l) => l.yearly && l.yearly.target);
  if (!ys.length) return "";
  return `<section class="card bflat" aria-labelledby="t-prov">
    <div class="section-head"><h2 class="section-title" id="t-prov">Provisions de l'année</h2><span class="hint">hors reste du mois</span></div>
    ${ys.map((c) => {
      const y = c.yearly, done = u(y.spent), goal = u(y.target), r = goal - done;
      const aside = y.set_aside ? u(y.set_aside) : null, pace = y.pace != null ? Number(y.pace) : null;
      const left = r <= 0 ? " · enveloppe épuisée" : aside != null ? ` · ${m0(aside)} par mois d'ici décembre` : "";
      const st = `${m0(done)} sur ${m0(goal)} depuis janvier${c.s ? ` · ${m0(c.s)} ce mois` : ""}${left}${c.state === "likely_over" ? " · au-dessus du rythme" : ""}`;
      return `<button class="crow" type="button" data-a="cat" data-v="${esc(c.category)}">${catMark(c.category, c.group)}<span><span class="crow-top"><b>${esc(c.name)}</b>
        <span class="brest num${r < 0 ? " neg" : ""}"><small>${r < 0 ? "dépassé" : "reste"}</small>${r < 0 ? "−" : ""}${m0(Math.abs(r))}</span></span>
        ${bar(goal ? done / goal : 0, pace)}<span class="crow-st ok">${st}</span></span></button>`;
    }).join("")}
  </section>`;
}
