// Budget : reste à vivre et rythme du mois, projection ; une action quand il y a lieu ; « Mon
// budget », un seul bloc où chaque catégorie suivie a une place (bmine.js), ou le diagramme de flux
// à sa place ; la tendance sur six mois en bas. « Régler » règle toutes les catégories, et chacune
// s'ouvre sur sa fiche (bfiche.js). Les montants, le rythme, l'état et la projection viennent de
// /finance/budget, /flows, /budget/months (audit M3) : ici on met en mots, on ne calcule pas.
import { go } from "../../shell.js";
import { MOIS, base, monthName, parseAmount, toMinor, units } from "../../format.js";
import { shortMonth, trend } from "./bviews.js";
import { action, hero, heroActions } from "./bhero.js";
import * as bmine from "./bmine.js";
import * as fiche from "./bfiche.js";
import * as bmove from "./bmove.js";
import * as bsubs from "./bsubs.js";
import { model } from "./bmodel.js";
import { sankeyData, sankeyInfo, sankeySvg } from "./bflow.js";
import { GROUP_LABEL, catMark } from "./meta.js";
import { outcome, proposeAndApprove } from "./proposals.js";
import { linkTo } from "./journal.js";
import { monthStartDay, shiftMonth, store } from "../../store.js";
import {
  SHEETS, SH, amount, announce, closeSheet, errBox, esc, failure, fill, ic, m0, openSheet, pref,
  renderSheet, setPref, skel, toast,
} from "../../ui.js";

const $ = (id) => document.getElementById(id);
const P = store.params;
const OLDEST = 36; // mois en arrière au plus
const B = { sk: null };

export const budgetPath = (month, period) => `/finance/budget?month=${month}&period=${period}`;
const flowsPath = () => `/finance/flows?month=${P.month}&period=${P.period}`;
const monthsPath = () => `/finance/budget/months?month=${P.month}&months=6`;
const upcomingPath = () => `/finance/budget/upcoming?month=${P.month}`;
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
    flow = `<p class="hint">Entré ${amount(sd.I)} · dépensé ${amount(spentF)} · épargné ${amount(sd.S)}</p>
      ${sd.tot > 1 ? `<div class="skcols" aria-hidden="true"><span>Revenus</span><span>Usage</span><span>Postes</span></div>${sankeySvg(sd, B.sk)}${sankeyInfo(sd, B.sk)}` : '<div class="empty">Aucun mouvement sur la période.</div>'}`;
  } else if (fe.status === "error") flow = errBox(`Flux indisponible : ${fe.error.message}`);
  // la tête, une action s'il y a lieu, Mon budget (ou le flux), la tendance
  const body = hero(b, m) + action(b, m, up) + bmine.mine(b, m, up, flow) + trend(me.data, P);
  fill($("budBody"), `${body}<div class="endspace"></div>`);
}

// --- Régler : une cible par catégorie de dépense, proposée d'après les 3 derniers mois

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

// suivie à l'année : réglée telle quelle, ou changée sur la ligne (sh.cad) ; jamais l'épargne
const isYear = (r, sh) => r.group !== "savings" && (sh.cad && sh.cad[r.id] != null ? sh.cad[r.id] : r.year);
const planChanges = (d, sh) => d.rows.filter((r) => {
  const v = sh.tmp[r.id];
  if (v == null || (r.now == null && v === 0)) return false;
  return v !== (r.now ?? 0) || (v > 0 && isYear(r, sh) !== r.year);
});

SHEETS.plan = (_arg, sh) => {
  const d = planData();
  if (!d) return { title: "Régler le budget", body: skel("block") };
  // l'épargne n'est proposée qu'une fois choisie : rien n'est mis de côté sans le demander
  if (!sh.tmp) sh.tmp = Object.fromEntries(d.rows.map((r) => [r.id, r.now ?? (r.group === "savings" ? 0 : roundUp(r.avg))]));
  const sum = (save) => d.rows.filter((r) => (r.group === "savings") === save).reduce((t, r) => t + (sh.tmp[r.id] || 0) / (isYear(r, sh) ? 12 : 1), 0);
  const total = sum(false), saved = sum(true);
  const ch = planChanges(d, sh);
  const from = `${shortMonth(d.months[0])} – ${shortMonth(d.months[d.months.length - 1])}`;
  let g = null;
  const rows = d.rows.map((r) => {
    const head = r.group !== g ? `<div class="grp"><span>${GROUP_LABEL[r.group]}</span></div>` : "";
    g = r.group;
    const v = sh.tmp[r.id];
    return `${head}<div class="plan-row">${catMark(r.id, r.group, "sm")}
      <label for="plan-${esc(r.id)}"><b><button type="button" class="plan-name" data-a="cat" data-v="${esc(r.id)}">${esc(r.name)}</button></b><small>${spentNote(r)}${r.now != null && (v !== r.now || isYear(r, sh) !== r.year) ? ` · avant ${m0(r.now)}${r.year ? " par an" : ""}` : ""}</small></label>
      <span class="plan-in"><input id="plan-${esc(r.id)}" data-plan="${esc(r.id)}" inputmode="decimal" value="${v ? v : ""}" placeholder="—" aria-label="Cible ${isYear(r, sh) ? "annuelle" : "mensuelle"} ${esc(r.name)} en ${base()}">
      ${r.group === "savings" ? "" : `<button class="plan-cad" type="button" data-a="plan-cad" data-v="${esc(r.id)}" aria-pressed="${isYear(r, sh)}" aria-label="Suivi de ${esc(r.name)} : ${isYear(r, sh) ? "par an" : "par mois"}, toucher pour changer">${isYear(r, sh) ? "par an" : "par mois"}</button>`}</span></div>`;
  }).join("");
  return {
    title: "Régler le budget",
    body: `<p class="hint">Toutes tes catégories. Une cible par mois ou par an (touche « par mois » pour changer), proposée d'après ta moyenne des derniers mois (${esc(from)}) et arrondie à la dizaine. Laisse vide ce que tu ne veux pas suivre ; touche un nom pour ouvrir sa fiche.</p>
      <div class="plan-sum"><span>Revenus<b class="num">${amount(d.income)}</b></span><span>Budget<b class="num">${amount(total)}</b></span>
        <span>Reste<b class="num${d.income - total - saved < 0 ? " neg" : ""}">${amount(d.income - total - saved)}</b></span></div>
      ${saved ? `<p class="hint">Dont ${amount(saved)} d'épargne visée, retirée du reste.</p>` : ""}
      ${rows}${fiche.planExtra()}${sh.bad || sh.err ? `<div class="err" role="alert">${esc(sh.bad || sh.err)}</div>` : ""}`,
    foot: `<button class="primary" type="button" data-a="plan-save" ${ch.length && !sh.busy && !sh.bad ? "" : "disabled"}>${ic("faceid")}${sh.busy ? "Validation…" : ch.length ? `${sh.touched ? "Enregistrer" : "Accepter"} ${ch.length} cible${ch.length > 1 ? "s" : ""} avec Face ID` : "Tout est à jour"}</button>`,
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
  ...bmine.actions,
  ...fiche.actions,
  cat: (id) => {
    if (P.tab !== "budget") {
      store.set({ month: store.today, period: "m" });
      go("budget");
    }
    store.use(CATS);
    store.use(bsubs.recurringPath);
    openSheet("fiche", id);
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
  bfold: (k) => {
    const key = `${k}Open`;
    setPref(key, !pref(key, false));
    store.notify();
  },
  plan: () => {
    for (const p of [budgetPath(store.today, "m"), budgetPath(store.today, "q"), CATS, `/finance/flows?month=${store.today}&period=q`]) store.use(p);
    openSheet("plan");
  },
  "plan-cad": (id) => {
    const d = planData(), r = d && d.rows.find((x) => x.id === id);
    if (!r) return;
    SH.cad = { ...(SH.cad || {}), [id]: !isYear(r, SH) };
    SH.touched = true;
    renderSheet();
  },
  "plan-save": async () => {
    const d = planData();
    if (!d) return;
    const ch = planChanges(d, SH);
    if (!ch.length) return;
    SH.busy = true;
    SH.err = "";
    renderSheet();
    try {
      const items = ch.map((r) => ["set_budget", { category_id: r.id, amount_minor: toMinor(SH.tmp[r.id]), cadence: isYear(r, SH) ? "year" : "month", valid_from: `${store.today}-01` }]);
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

