// Budget : reste à vivre et rythme du mois, projection et taux d'épargne ; une section
// Catégories (variables d'abord, les dépassements en tête, puis les fixes repliées) ; le
// diagramme de flux (revenus → usage → postes), toujours ouvert ; abonnements et tendance sur
// six mois, repliés sur une ligne de résumé. Les montants, le rythme, l'état et la projection
// viennent de /finance/budget, /flows, /budget/months (audit M3) : ici on met en mots, on ne
// calcule pas.
import { go, reveal } from "../../shell.js";
import { MOIS, base, monthName, parseAmount, toMinor, units } from "../../format.js";
import { categories, shortMonth, trend } from "./bviews.js";
import { action, hero, heroActions } from "./bhero.js";
import { daily, outside, provisions, upcoming } from "./bmonth.js";
import * as bmove from "./bmove.js";
import * as bsubs from "./bsubs.js";
import { catState, model, yearState } from "./bmodel.js";
import { sankeyData, sankeyInfo, sankeySvg } from "./bflow.js";
import { GROUP_LABEL, catLook, catMark } from "./meta.js";
import { outcome, proposeAndApprove } from "./proposals.js";
import { linkTo } from "./journal.js";
import { MODE_LABEL } from "./categories.js";
import { monthStartDay, shiftMonth, store } from "../../store.js";
import {
  SHEETS, SH, amount, announce, closeSheet, errBox, esc, escNums, failure, fill, ic, m0, n0, openSheet, pref,
  renderSheet, setPref, skel, toast,
} from "../../ui.js";

const $ = (id) => document.getElementById(id);
const P = store.params;
const OLDEST = 36; // mois en arrière au plus
const B = { sk: null, bgroup: null, offOpen: false, paidOpen: false };

export const budgetPath = (month, period) => `/finance/budget?month=${month}&period=${period}`;
const flowsPath = () => `/finance/flows?month=${P.month}&period=${P.period}`;
const monthsPath = () => `/finance/budget/months?month=${P.month}&months=6`;
const upcomingPath = () => `/finance/budget/upcoming?month=${P.month}`;
const trendPath = (cat) => `/finance/trend?category=${encodeURIComponent(cat)}&months=6&month=${P.month}`;
const u = (m) => (m ? units(m) : 0);

// dates d'une période dont le mois ne commence pas le 1er : « 25 sept. – 24 oct. »
function spanLabel(b) {
  const last = new Date(Date.parse(`${b.end}T00:00:00Z`) - 864e5);
  const first = new Date(`${b.start}T00:00:00Z`);
  return `${first.getUTCDate()} ${MOIS[first.getUTCMonth()]} – ${last.getUTCDate()} ${MOIS[last.getUTCMonth()]}`;
}

function periodLabel(b) {
  if (P.period === "m") return monthName(P.month);
  const ms = b ? b.months : [shiftMonth(P.month, -3), shiftMonth(P.month, -1)];
  return `${shortMonth(ms[0])} – ${shortMonth(ms[ms.length - 1])} ${ms[ms.length - 1].slice(0, 4)}`;
}

// --- rendu ------------------------------------------------------------------------------------

export function render() {
  const be = store.use(budgetPath(P.month, P.period));
  const b = be.data;
  const fe = store.use(flowsPath());
  const me = store.use(monthsPath());
  const re = store.use(bsubs.recurringPath);
  const lab = periodLabel(b);
  const oldest = shiftMonth(store.today, -OLDEST);
  fill($("budCtx"), `<div class="stepper" role="group" aria-label="Mois affiché">
      <button type="button" data-a="bm" data-v="-1" aria-label="Mois précédent" ${P.month <= oldest ? "disabled" : ""}>${ic("back")}</button>
      <b aria-live="polite">${esc(lab)}${b && monthStartDay() !== 1 ? `<small class="per-dates">${esc(spanLabel(b))}</small>` : ""}</b>
      <button type="button" data-a="bm" data-v="1" aria-label="Mois suivant" ${P.month >= store.today ? "disabled" : ""}>${ic("chev")}</button></div>
    <div class="seg small" role="group" aria-label="Période"><button type="button" data-a="bper" data-v="m" aria-pressed="${P.period === "m"}">Mois</button><button type="button" data-a="bper" data-v="q" aria-pressed="${P.period === "q"}" aria-label="Trois mois complets avant le mois choisi">3 mois</button></div>`);
  if (be.status === "error") return fill($("budBody"), errBox(`Impossible de charger le budget : ${be.error.message}`));
  if (!b) return fill($("budBody"), skel());
  const m = model(b);
  const up = P.period === "m" ? store.use(upcomingPath()).data : null;
  if (P.period === "m") store.use(CATS);
  // flux
  let flow = "";
  if (fe.data) {
    const sd = sankeyData(fe.data);
    if (B.sk && ![...sd.srcs, ...sd.mids, ...sd.mids.flatMap((x) => x.kids)].some((n) => n.id === B.sk)) B.sk = null;
    const spentF = sd.out - sd.S;
    flow = `<section class="card bflat" aria-labelledby="t-flow">
      <div class="section-head"><h2 class="section-title" id="t-flow">Où va l'argent</h2></div>
      <p class="hint">Entré ${amount(sd.I)} · dépensé ${amount(spentF)} · épargné ${amount(sd.S)}</p>
      ${sd.tot > 1 ? `<div class="skcols" aria-hidden="true"><span>Revenus</span><span>Usage</span><span>Postes</span></div>${sankeySvg(sd, B.sk)}${sankeyInfo(sd, B.sk)}` : '<div class="empty">Aucun mouvement sur la période.</div>'}
    </section>`;
  } else if (fe.status === "error") flow = errBox(`Flux indisponible : ${fe.error.message}`);
  const head = hero(b, m), tail = bsubs.subscriptions(re) + trend(me.data, P);
  const foot = `<div class="bfoot"><button class="secondary" type="button" data-a="plan" aria-haspopup="dialog">${ic("sliders")}${m.T == null ? "Créer mon budget" : "Ajuster le budget"}</button>
    <button class="linkish bfoot-l" type="button" data-a="cats">${ic("list")}Gérer les catégories</button></div>`;
  // le mois : la tête, une action, le quotidien, le hors budget, le flux, ce qui arrive, les
  // provisions ; trois mois ou un filtre venu du flux : la liste des catégories d'avant
  const body = P.period === "m" && !B.bgroup
    ? head + action(b, m, up) + daily(m, B) + outside(b) + flow + upcoming(up, b, B) + provisions(m) + tail + foot
    : head + categories(m, B, fe.data) + flow + tail;
  fill($("budBody"), `${body}<div class="endspace"></div>`);
}

const spent12 = (b, id) => u(((b && b.year_spent) || []).find((x) => x.category === id)?.spent);

// --- panneau d'une catégorie ------------------------------------------------------------------

SHEETS.cat = (id, sh) => {
  const b = store.data(budgetPath(P.month, P.period));
  const cats = store.data("/finance/categories");
  const c = cats ? cats.items.find((x) => x.id === id) : null;
  const l = b ? b.lines.find((x) => x.category === id) : null;
  if (!c && !l) return { title: "Catégorie", body: skel("block") };
  const name = c ? c.name : l.name, group = c ? c.group : l.group;
  const m = b ? model(b) : null;
  const line = m ? m.lines.find((x) => x.category === id) : null;
  const spent = line ? line.s : 0;
  const n = P.period === "q" ? 3 : 1;
  const year = line && line.yearly ? (line.yearly.target ? u(line.yearly.target) : null) : null;
  const saving = group === "savings" && b ? b.plan.savings_lines.find((x) => x.category === id) : null; // épargne visée (lot A)
  const target = saving ? u(saving.target) / n : line && line.yearly ? (year != null ? year / 12 : null) : line && line.t != null ? line.t / n : null; // cible mensuelle
  if (sh.cad == null) sh.cad = line && line.yearly ? "year" : "month";
  if (sh.tmp == null) sh.tmp = sh.cad === "year" ? Math.round(year || 0) : target != null ? Math.round(target) : 0;
  const was = line && line.yearly ? "year" : "month";
  const shown = was === "year" ? Math.round(year ?? -1) : Math.round(target ?? -1);
  const s = line ? (line.yearly ? yearState(line) : catState(line)) : { k: "ok", txt: group === "savings" ? "Épargne" : "Aucune dépense" };
  const te = store.use(trendPath(id));
  let hist = skel("block");
  if (te.data) {
    const pts = te.data.series.map((x) => ({ m: x.month, v: Math.abs(u(x.total)) }));
    const mx = Math.max(1, ...pts.map((p) => p.v), target || 0) * 1.1;
    const look = catLook(id, group);
    hist = `<div class="mini-months" role="img" aria-label="${pts.map((p) => `${monthName(p.m).split(" ")[0]} ${n0(p.v)}`).join(", ")}${target != null ? `, cible ${n0(target)}` : ""}">
      ${target != null ? `<span class="tline" data-css="--b:${(18 + (target / mx) * 72).toFixed(0)}px"></span>` : ""}
      ${pts.map((p) => `<div><i class="${p.m === P.month ? "" : "past"}" data-css="--h:${((p.v / mx) * 72).toFixed(0)}px;--c:${target != null && p.v > target ? "var(--neg)" : look.color}"></i><span>${shortMonth(p.m)}</span></div>`).join("")}</div>
      ${target != null ? '<p class="hint">Pointillés : la cible mensuelle.</p>' : ""}`;
  }
  const budgetable = (group === "fixed" || group === "variable" || group === "savings") && (!c || (c.mode || "target") === "target"); // suivie sans cible, hors budget : pas de cible
  const removing = budgetable && !(sh.tmp > 0) && shown > 0, changed = removing || (budgetable && sh.tmp > 0 && (sh.tmp !== shown || sh.cad !== was)); // champ vidé : cible retirée
  const per = sh.cad === "year" ? "annuelle" : "mensuelle";
  return {
    title: `${catMark(id, group)}<span>${esc(name)}</span>`,
    body: `<div class="sheet-big num">${saving ? `${amount(u(saving.done))} <small>versés sur ${amount(u(saving.target))}</small>` : `${amount(spent)}${line && line.t != null ? ` <small>sur ${amount(line.t)}</small>` : ""}`}</div>
      <span class="crow-st ${s.k}">${escNums(s.txt)} · ${esc(periodLabel(b))}</span>
      <h3>Six derniers mois</h3>${hist}
      ${budgetable ? `<h3>Cible ${per}</h3>
      ${group === "savings" ? '<p class="hint">Ce que tu veux mettre de côté chaque mois : compté dans l\'épargne visée du plan, retiré du reste à dépenser.</p>' : ""}
      <div class="seg cad-seg" role="group" aria-label="Suivi"${group === "savings" ? " hidden" : ""}>${[["month", "Par mois"], ["year", "Par an"]].map(([k, l]) => `<button type="button" data-a="tcad" data-v="${k}" aria-pressed="${sh.cad === k}">${l}</button>`).join("")}</div>
      <div class="target"><button type="button" data-a="tstep" data-v="-10" aria-label="Diminuer de 10">−</button><input id="t-input" inputmode="decimal" value="${sh.tmp || ""}" aria-label="Cible ${per} en ${base()}" placeholder="aucune"><button type="button" data-a="tstep" data-v="10" aria-label="Augmenter de 10">+</button></div>
      ${sh.cad === "year" ? `<p class="hint">Pour les dépenses par à-coups (vacances, entretien) : comparée au cumul depuis janvier, sans peser sur le reste à vivre du mois.${line && line.yearly ? ` Dépensé depuis janvier : ${m0(u(line.yearly.spent))} ${base()}.` : ""}${spent12(b, id) ? ` Sur douze mois : ${m0(spent12(b, id))} ${base()}.` : ""}</p>` : ""}
      ${sh.bad || sh.err ? `<div class="err" role="alert">${esc(sh.bad || sh.err)}</div>` : ""}` : '<p class="hint">Les cibles portent sur les dépenses fixes et variables.</p>'}
      ${c && !budgetable && (group === "fixed" || group === "variable") ? `<p class="hint">${esc(MODE_LABEL[c.mode] || "")} :
        ${c.mode === "off_budget" ? "ni dans le dépensé ni dans le reste." : "comptée dans le dépensé, sans cible ni alerte."}</p>` : ""}
      ${c ? `<button class="link-row" type="button" data-a="cat-edit" data-v="${esc(id)}">Gérer la catégorie (nom, icône, mode)${ic("chev")}</button>` : ""}
      ${line && line.count ? `<div class="stack-v"><button class="secondary" type="button" data-a="cat-tx" data-v="${esc(id)}">${ic("list")}${line.count > 1 ? `Voir les ${line.count} écritures` : "Voir l'écriture"}</button></div>` : ""}`,
    foot: budgetable ? `<button class="primary" type="button" data-a="target-save" ${changed && !sh.busy && !sh.bad ? "" : "disabled"}>${ic("faceid")}${sh.busy ? "Validation…" : removing ? "Retirer la cible avec Face ID" : "Enregistrer la cible avec Face ID"}</button>` : "",
  };
};

// --- préparer le budget : une cible par catégorie de dépense, proposée d'après les 3 derniers mois

const CATS = "/finance/categories";
const roundUp = (v) => (v > 0 ? Math.ceil(v / 10) * 10 : 0);

function planData() {
  const cur = store.data(budgetPath(store.today, "m")), past = store.data(budgetPath(store.today, "q")), cats = store.data(CATS);
  if (!cur || !past || !cats) return null;
  // une catégorie suivie à l'année se règle en montant annuel
  const year = new Set(cur.lines.filter((l) => l.yearly).map((l) => l.category));
  const now = Object.fromEntries(cur.lines.map((l) => [l.category, l.yearly ? (l.yearly.target ? u(l.yearly.target) : null) : l.target ? u(l.target) : null]));
  const y12 = Object.fromEntries((cur.year_spent || []).map((x) => [x.category, u(x.spent)]));
  // suivie à l'année : ce qu'elle a coûté sur douze mois ; sinon la moyenne des trois derniers
  const avg = Object.fromEntries(past.lines.filter((l) => !year.has(l.category)).map((l) => [l.category, u(l.spent) / past.months.length]));
  for (const c of year) avg[c] = y12[c] || 0;
  // l'épargne visée : les cibles des catégories d'épargne, la moyenne versée d'après le flux
  for (const x of cur.plan.savings_lines) now[x.category] = u(x.target);
  const fq = store.data(`/finance/flows?month=${store.today}&period=q`);
  for (const i of fq ? fq.groups.find((x) => x.group === "savings")?.items || [] : []) avg[i.category] = u(i.total) / past.months.length;
  const ORDER = { fixed: 0, variable: 1, savings: 2 };
  const rows = cats.items.filter((c) => c.active && (c.mode || "target") === "target" && c.group in ORDER)
    .map((c) => ({ id: c.id, name: c.name, group: c.group, now: now[c.id] ?? null, avg: avg[c.id] || 0, y12: y12[c.id] || 0, year: year.has(c.id) }))
    .sort((a, b) => ORDER[a.group] - ORDER[b.group] || b.avg - a.avg || a.name.localeCompare(b.name, "fr"));
  return { rows, income: u(past.income) / past.months.length, months: past.months };
}

// ce qu'une catégorie a coûté : la moyenne des 3 derniers mois, ou sur 12 mois (annuelle, ou
// une dépense plus ancienne que 3 mois)
function spentNote(r) {
  if (r.group === "savings") return r.avg ? `moyenne ${m0(r.avg)}` : "rien versé";
  if (r.year) return r.y12 ? `${m0(r.y12)} sur 12 mois` : "rien sur 12 mois";
  if (r.avg) return `moyenne ${m0(r.avg)}`;
  return r.y12 ? `rien sur 3 mois · ${m0(r.y12)} sur 12 mois` : "rien dépensé sur 12 mois";
}

const planChanges = (d, tmp) => d.rows.filter((r) => tmp[r.id] != null && tmp[r.id] !== (r.now ?? 0) && !(r.now == null && tmp[r.id] === 0));

SHEETS.plan = (_arg, sh) => {
  const d = planData();
  if (!d) return { title: "Préparer le budget", body: skel("block") };
  // l'épargne n'est proposée qu'une fois choisie : rien n'est mis de côté sans le demander
  if (!sh.tmp) sh.tmp = Object.fromEntries(d.rows.map((r) => [r.id, r.now ?? (r.group === "savings" ? 0 : roundUp(r.avg))]));
  const sum = (save) => d.rows.filter((r) => (r.group === "savings") === save).reduce((t, r) => t + (sh.tmp[r.id] || 0) / (r.year ? 12 : 1), 0);
  const total = sum(false), saved = sum(true);
  const ch = planChanges(d, sh.tmp);
  const from = `${shortMonth(d.months[0])} – ${shortMonth(d.months[d.months.length - 1])}`;
  let g = null;
  const rows = d.rows.map((r) => {
    const head = r.group !== g ? `<div class="grp"><span>${GROUP_LABEL[r.group]}</span></div>` : "";
    g = r.group;
    const v = sh.tmp[r.id];
    return `${head}<div class="plan-row">${catMark(r.id, r.group, "sm")}
      <label for="plan-${esc(r.id)}"><b>${esc(r.name)}${r.year ? ' <span class="pill">par an</span>' : ""}</b><small>${spentNote(r)}${r.now != null ? ` · cible ${m0(r.now)}` : ""}</small></label>
      <input id="plan-${esc(r.id)}" data-plan="${esc(r.id)}" inputmode="decimal" value="${v ? v : ""}" placeholder="—" aria-label="Cible ${r.year ? "annuelle" : "mensuelle"} ${esc(r.name)} en ${base()}"></div>`;
  }).join("");
  return {
    title: "Préparer le budget",
    body: `<p class="hint">Une cible par mois et par catégorie, proposée d'après ta moyenne des derniers mois (${esc(from)}) et arrondie à la dizaine. Laisse vide ce que tu ne veux pas suivre.</p>
      <div class="plan-sum"><span>Revenus<b class="num">${amount(d.income)}</b></span><span>Budget<b class="num">${amount(total)}</b></span>
        <span>Reste<b class="num${d.income - total - saved < 0 ? " neg" : ""}">${amount(d.income - total - saved)}</b></span></div>
      ${saved ? `<p class="hint">Dont ${amount(saved)} d'épargne visée, retirée du reste.</p>` : ""}
      ${rows}${sh.bad || sh.err ? `<div class="err" role="alert">${esc(sh.bad || sh.err)}</div>` : ""}`,
    foot: `<button class="primary" type="button" data-a="plan-save" ${ch.length && !sh.busy && !sh.bad ? "" : "disabled"}>${ic("faceid")}${sh.busy ? "Validation…" : ch.length ? `${sh.touched ? "Enregistrer" : "Accepter"} ${ch.length} cible${ch.length > 1 ? "s" : ""}${sh.touched ? "" : " proposée" + (ch.length > 1 ? "s" : "")} avec Face ID` : "Aucun changement"}</button>`,
  };
};

document.addEventListener("input", (e) => {
  const id = e.target.dataset && e.target.dataset.plan;
  if (!id || SH.kind !== "plan" || !SH.tmp) return;
  const r = parseAmount(e.target.value);
  SH.bad = r.error || "";
  SH.touched = true;
  if (r.value != null) SH.tmp[id] = r.value;
  renderSheet();
});

document.addEventListener("input", (e) => {
  if (e.target.id !== "t-input" || SH.kind !== "cat") return;
  const r = parseAmount(e.target.value);
  SH.bad = r.error || "";
  SH.conv = null;
  if (r.value != null) SH.tmp = r.value;
  renderSheet();
});

function setMonth(month) {
  if (month > store.today || month < shiftMonth(store.today, -OLDEST)) return;
  B.sk = null;
  store.set({ month });
  announce(P.period === "m" ? monthName(month) : periodLabel(null));
}

export const actions = {
  ...heroActions,
  ...bmove.actions,
  ...bsubs.actions,
  bpaid: () => {
    B.paidOpen = !B.paidOpen;
    store.notify();
  },
  cat: (id) => {
    if (P.tab !== "budget") {
      store.set({ month: store.today, period: "m" });
      go("budget");
    }
    store.use("/finance/categories");
    openSheet("cat", id);
  },
  bm: (v) => setMonth(shiftMonth(P.month, Number(v))),
  bper: (v) => {
    B.sk = null;
    store.set({ period: v });
  },
  month: (v) => {
    B.sk = null;
    store.set({ month: v, period: "m" });
    window.scrollTo({ top: 0, behavior: "smooth" });
    announce(monthName(v));
  },
  sk: (v) => {
    B.sk = !v || B.sk === v ? null : v;
    store.notify();
  },
  "sk-list": (g) => {
    B.bgroup = g;
    store.notify();
    requestAnimationFrame(() => reveal($("budCats")));
  },
  bgroupx: () => {
    B.bgroup = null;
    store.notify();
  },
  bfold: (k) => {
    const key = `${k}Open`;
    setPref(key, !pref(key, false));
    store.notify();
  },
  boff: () => {
    B.offOpen = !B.offOpen;
    store.notify();
  },
  bfixed: () => {
    setPref("fixedOpen", !pref("fixedOpen", false));
    store.notify();
  },
  subs: () => {
    setPref("subsOpen", true);
    store.set({ month: store.today, period: "m" });
    go("budget");
    requestAnimationFrame(() => requestAnimationFrame(() => reveal($("subs"))));
  },
  tcad: (k) => {
    if (SH.cad === k) return;
    // la même enveloppe, exprimée par an ou par mois ; un aller-retour sans retouche rend la
    // valeur tapée, sans arrondi perdu en chemin
    const back = SH.conv && SH.conv.to === SH.tmp ? SH.conv.from : null;
    const next = back ?? (k === "year" ? (SH.tmp || 0) * 12 : Math.round(((SH.tmp || 0) / 12) * 100) / 100);
    SH.conv = back == null ? { from: SH.tmp || 0, to: next } : null;
    SH.tmp = next;
    SH.cad = k;
    renderSheet();
  },
  tstep: (v) => {
    SH.conv = null;
    SH.bad = "";
    SH.tmp = Math.max(0, Math.round(((SH.tmp || 0) + Number(v)) * 100) / 100);
    renderSheet();
  },
  plan: () => {
    for (const p of [budgetPath(store.today, "m"), budgetPath(store.today, "q"), CATS, `/finance/flows?month=${store.today}&period=q`]) store.use(p);
    openSheet("plan");
  },
  "plan-save": async () => {
    const d = planData();
    if (!d) return;
    const ch = planChanges(d, SH.tmp);
    if (!ch.length) return;
    SH.busy = true;
    SH.err = "";
    renderSheet();
    try {
      const items = ch.map((r) => ["set_budget", { category_id: r.id, amount_minor: toMinor(SH.tmp[r.id]), cadence: r.year && r.group !== "savings" ? "year" : "month", valid_from: `${store.today}-01` }]);
      const [text, bad] = outcome(await proposeAndApprove(items));
      if (bad) {
        if (SH.kind === "plan") SH.err = text;
        else toast(`Budget non enregistré : ${text}`, { error: true });
      } else {
        if (SH.kind === "plan") closeSheet();
        toast(`${ch.length} cible${ch.length > 1 ? "s" : ""} enregistrée${ch.length > 1 ? "s" : ""}`);
      }
    } catch (e) {
      if (SH.kind === "plan") SH.err = failure(e);
      else toast(`Budget non enregistré : ${failure(e)}`, { error: true });
    } finally {
      SH.busy = false;
      if (SH.kind) renderSheet();
    }
  },
  "target-save": async () => {
    const id = SH.arg, value = SH.tmp, yearly = SH.cad === "year";
    SH.busy = true;
    SH.err = "";
    renderSheet();
    try {
      const [text, bad] = outcome(await proposeAndApprove([["set_budget", { category_id: id, amount_minor: toMinor(value), cadence: yearly ? "year" : "month" }]]));
      if (bad) {
        if (SH.kind === "cat" && SH.arg === id) SH.err = text;
        else toast(`Cible non enregistrée : ${text}`, { error: true });
      } else {
        if (SH.kind === "cat" && SH.arg === id) closeSheet();
        toast(value > 0 ? `Cible enregistrée : ${n0(value)} ${base()} par ${yearly ? "an" : "mois"}` : "Cible retirée");
      }
    } catch (e) {
      // le panneau a pu être fermé pendant la validation : l'échec se dit quand même
      if (SH.kind === "cat" && SH.arg === id) SH.err = failure(e);
      else toast(`Cible non enregistrée : ${failure(e)}`, { error: true });
    } finally {
      SH.busy = false;
      if (SH.kind) renderSheet();
    }
  },
  "cat-tx": (id) => {
    const b = store.data(budgetPath(P.month, P.period));
    const months = P.period === "m" ? [P.month] : (b?.months || [P.month]);
    // les bornes du serveur (fin exclue), qui suivent le jour de début en vigueur chaque mois
    const span = b ? [b.start, new Date(Date.parse(`${b.end}T00:00:00Z`) - 864e5).toISOString().slice(0, 10)] : null;
    const link = linkTo({ kind: "cat", id, label: id });
    store.set({ txcat: { id, from: months[0], to: months[months.length - 1], span } });
    // go ferme le panneau en remplaçant son entrée : le retour revient au Budget
    go("journal", { top: true, link });
  },
};

