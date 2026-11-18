// Budget, « Mon budget » : un seul bloc où chaque catégorie suivie a une place, rangée d'après son
// réglage. Charges fixes (une liste dans l'ordre du mois, coupée par « Aujourd'hui » : payée avec
// sa date et une coche, à venir avec la date attendue, sans date habituelle à la fin), Chaque
// mois (barre, reste), Par an (cumul depuis janvier), puis Sans cible (suivies sans cible et hors
// budget). Le diagramme de flux se montre à la place de la liste. Les autres catégories se
// règlent dans « Régler ». Montants, états et dates viennent de /finance/budget et /upcoming.
import { MOIS, base, units } from "../../format.js";
import { esc, ic, m0, n0, pref, setPref } from "../../ui.js";
import { catMark } from "./meta.js";
import { rank } from "./bmodel.js";
import { UNCAT, dayMonth } from "./bhero.js";
import { store } from "../../store.js";

const u = (m) => (m ? units(m) : 0);
const todayIso = () => { const t = new Date(); return `${t.getFullYear()}-${String(t.getMonth() + 1).padStart(2, "0")}-${String(t.getDate()).padStart(2, "0")}`; };
const grp = (title, sum) => `<div class="grp"><span>${title}</span><span class="num">${sum}</span></div>`;

// la barre d'une catégorie : toute la largeur vaut sa cible ; au-delà, la part en trop en rouge
function bar(ratio, pace) {
  if (ratio > 1) {
    const k = 1 / ratio;
    return `<span class="pbar thin pc split"><i data-css="width:${(k * 100).toFixed(1)}%"></i><b class="ov" data-css="width:${((1 - k) * 100).toFixed(1)}%"></b></span>`;
  }
  const mark = pace != null && pace > 0 && pace < 1 ? `<span class="pace" data-css="left:${(pace * 100).toFixed(1)}%"></span>` : "";
  return `<span class="pbar thin pc"><i data-css="width:${(Math.max(0, ratio) * 100).toFixed(1)}%"></i>${mark}</span>`;
}

const rest = (r) => `<span class="brest num${r < 0 ? " neg" : ""}"><small>${r < 0 ? "dépassé" : "reste"}</small>${r < 0 ? "−" : ""}${m0(Math.abs(r))}</span>`;
const row = (c, right, st, extra = "", label = "") => `<button class="crow" type="button" data-a="cat" data-v="${esc(c.category)}"${label ? ` aria-label="${esc(label)}"` : ""}>${catMark(c.category, c.group)}<span><span class="crow-top"><b>${esc(c.name)}</b>${right}</span>${extra}<span class="crow-st ok">${st}</span></span></button>`;

// --- charges fixes ----------------------------------------------------------------------------

function soon(d) {
  const k = Math.round((Date.parse(d) - Date.parse(todayIso())) / 864e5);
  return k <= 0 ? "aujourd'hui" : k === 1 ? "demain" : `dans ${k} jours`;
}
const dbox = (d, kind) => d
  ? `<span class="fx-date ${kind}"><b>${Number(d.slice(8, 10))}</b><span>${MOIS[Number(d.slice(5, 7)) - 1]}</span>${kind === "paid" ? `<i>${ic("check")}</i>` : ""}</span>`
  : '<span class="fx-date nodate"><b>?</b></span>';
const fxRow = (c, date, kind, st, v, label) => `<button class="fx-row ${kind}" type="button" data-a="cat" data-v="${esc(c.category)}" aria-label="${esc(label)}">${dbox(date, kind)}<span class="up-main"><b>${esc(c.name)}</b><span>${st}</span></span><span class="num up-v">${m0(v)}</span></button>`;

function fixedItem(c, up) {
  const x = up ? up.items.find((i) => i.category === c.category) : null;
  const via = x && x.via ? ` · ${esc(x.via)}` : "";
  const above = c.t != null && c.s - c.t >= 1 ? c.s - c.t : 0;
  if ((x && x.status === "paid") || (!x && c.s > 0.5)) {
    const on = (x ? x.on : c.paid_on) || "", v = c.s || u(x && x.amount);
    const st = `${ic("check")}payé${above ? ` · <span class="neg">${m0(above)} au-dessus de la cible</span>` : via}`;
    return { paid: true, v, on, html: fxRow(c, on || null, "paid", st, v, `${c.name} : payé${on ? ` le ${dayMonth(on)}` : ""}, ${n0(v)} ${base()}`) };
  }
  const v = c.t != null ? c.t : x ? u(x.amount) : 0;
  if (x && x.status === "late") {
    return { paid: false, v, on: x.on, html: fxRow(c, x.on, "late", `<span class="warnt">${ic("alert")}pas encore vu, attendu le ${dayMonth(x.on)}</span>${via}`, v, `${c.name} : pas encore vu, attendu le ${dayMonth(x.on)}, ${n0(v)} ${base()}`) };
  }
  if (x) return { paid: false, v, on: x.on, html: fxRow(c, x.on, "due", `à payer ${soon(x.on)}${via}`, v, `${c.name} : à payer ${soon(x.on)}, ${n0(v)} ${base()}`) };
  return { paid: false, v, on: "", html: fxRow(c, null, "nodate", "à payer · pas de date habituelle", v, `${c.name} : à payer, pas de date habituelle, ${n0(v)} ${base()}`) };
}

function fixedPart(fixed, up, current) {
  const items = fixed.map((c) => fixedItem(c, up));
  if (!items.length) return "";
  const today = todayIso();
  const dated = items.filter((i) => i.on).sort((a, z) => a.on.localeCompare(z.on) || Number(z.paid) - Number(a.paid));
  const undated = items.filter((i) => !i.on);
  const k = dated.findIndex((i) => i.on > today);
  const cut = k < 0 ? dated.length : k;
  // le trait « Aujourd'hui » n'a de sens que dans le mois en cours
  const mark = current ? `<div class="fx-today" aria-hidden="true"><span>Aujourd'hui · ${dayMonth(today)}</span></div>` : "";
  const html = (xs) => xs.map((i) => i.html).join("");
  const paid = items.filter((i) => i.paid), paidV = paid.reduce((t, i) => t + i.v, 0);
  const left = items.filter((i) => !i.paid).reduce((t, i) => t + i.v, 0);
  const steps = [...paid, ...items.filter((i) => !i.paid)].map((i) => `<i class="${i.paid ? "on" : ""}"></i>`).join("");
  return `${grp("Charges fixes", `${n0(paidV)} / ${n0(paidV + left)}`)}
    <div class="fx-steps" role="img" aria-label="${paid.length} charges payées sur ${items.length}">${steps}</div>
    <p class="fx-sum"><b>${paid.length} sur ${items.length}</b> payées${left > 0.5 ? ` · reste <span class="num">${m0(left)}</span> à payer` : " · tout est payé"}</p>
    <div class="fx-list">${html(dated.slice(0, cut))}${mark}${html(dated.slice(cut))}${html(undated)}</div>`;
}

// --- chaque mois, par an, sans cible ----------------------------------------------------------

function monthRow(c, pace) {
  const r = c.t - c.s;
  return row(c, rest(r), `${m0(c.s)} sur ${m0(c.t)}${c.state === "likely_over" ? " · au-dessus du rythme" : ""}`, bar(c.t ? c.s / c.t : 0, pace),
    `${c.name} : ${r < 0 ? "dépassé" : "reste"} ${n0(Math.abs(r))} ${base()}`);
}

function yearRow(c) {
  const y = c.yearly, done = u(y.spent), goal = u(y.target), r = goal - done;
  const aside = y.set_aside ? u(y.set_aside) : null;
  const st = `${m0(done)} sur ${m0(goal)} depuis janvier${c.s ? ` · ${m0(c.s)} ce mois` : ""}${r > 0 && aside != null ? ` · ${m0(aside)} par mois d'ici décembre` : ""}`;
  return row(c, rest(r), st, bar(goal ? done / goal : 0, y.pace != null ? Number(y.pace) : null), `${c.name} : ${r < 0 ? "dépassé" : "reste"} ${n0(Math.abs(r))} ${base()} sur l'année`);
}

// le bloc ; flow = le diagramme de flux déjà dessiné par budget.js
export function mine(b, m, up, flow) {
  const view = pref("bview", "cats");
  const cats = (store.data("/finance/categories") || { items: [] }).items;
  const mode = (id) => (cats.find((c) => c.id === id) || { mode: "target" }).mode || "target";
  const lines = m.lines.filter((l) => l.category !== UNCAT);
  const fixed = lines.filter((l) => l.group === "fixed" && !l.yearly && mode(l.category) === "target" && (l.t != null || l.s > 0.5));
  const monthly = lines.filter((l) => l.group !== "fixed" && l.t != null && !l.yearly).sort((x, y) => rank(y) - rank(x) || y.s / y.t - x.s / x.t);
  const yearly = lines.filter((l) => l.yearly && l.yearly.target);
  const used = new Set([...fixed, ...monthly, ...yearly].map((l) => l.category));
  const loose = lines.filter((l) => !used.has(l.category) && l.s > 0.5);
  const off = b.off_budget || [];
  const seg = `<div class="seg small bview" role="group" aria-label="Affichage"><button type="button" data-a="bview" data-v="cats" aria-pressed="${view !== "flow"}">Catégories</button><button type="button" data-a="bview" data-v="flow" aria-pressed="${view === "flow"}">Flux</button></div>`;
  const head = `<div class="section-head"><h2 class="section-title" id="t-mine">Mon budget</h2><button class="linkish breg" type="button" data-a="plan" aria-haspopup="dialog">${ic("sliders")}Régler</button></div>${seg}`;
  if (view === "flow") return `<section class="card bflat" id="budCats" aria-labelledby="t-mine">${head}${flow}</section>`;
  const ms = monthly.reduce((t, c) => t + c.s, 0), mt = monthly.reduce((t, c) => t + c.t, 0);
  const ys = yearly.reduce((t, c) => t + u(c.yearly.spent), 0), yt = yearly.reduce((t, c) => t + u(c.yearly.target), 0);
  const ls = loose.reduce((t, c) => t + c.s, 0);
  const looseRows = loose.map((c) => row(c, `<span class="brest num">${m0(c.s)}</span>`, `${c.count} écriture${c.count > 1 ? "s" : ""} ce mois`)).join("")
    + off.map((x) => {
      const net = u(x.net);
      return row({ category: x.category, name: x.name, group: "variable" }, `<span class="brest num">${net > 0 ? "−" : "+"}${m0(Math.abs(net))}</span>`, "hors budget · ne compte pas dans le reste");
    }).join("");
  const body = fixedPart(fixed, up, m.current)
    + (monthly.length ? grp("Chaque mois", `${n0(ms)} / ${n0(mt)}`) + monthly.map((c) => monthRow(c, m.current ? m.expected : null)).join("") : "")
    + (yearly.length ? grp("Par an", `${n0(ys)} / ${n0(yt)}`) + yearly.map(yearRow).join("") : "")
    + (loose.length + off.length ? grp("Sans cible", `${n0(ls)} dépensés`) + looseRows : "");
  return `<section class="card bflat" id="budCats" aria-labelledby="t-mine">${head}${body || '<div class="empty">Aucune catégorie suivie pour l\'instant.</div>'}
    <p class="hint bfoot-h">Les autres catégories, sans cible ni dépense ce mois, sont dans <button class="linkish" type="button" data-a="plan">Régler</button>.</p></section>`;
}

export const actions = {
  bview: (v) => {
    setPref("bview", v);
    store.notify();
  },
};
