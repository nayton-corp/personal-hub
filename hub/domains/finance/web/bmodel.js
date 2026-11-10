// @ts-check
// Le budget en mots : l'état d'une période et de chaque catégorie, tels que le serveur les
// calcule (/finance/budget : state, pace, expected, projection ; model/pace.py, la même règle que
// les sentinelles, audit M3). Ici on lit et on met en mots, on ne calcule pas.
import { MOIS, base, ratio, units } from "../../format.js";
import { n0, n2, pf } from "../../ui.js";

/** @typedef {import("../../api").BudgetOut} BudgetOut */
/** @typedef {import("../../api").BudgetLineOut} BudgetLineOut */
/** @typedef {import("../../api").MoneyOut} MoneyOut */
/** @typedef {BudgetLineOut & {s: number, t: number | null, p: number | null}} Line */

/** @param {MoneyOut | null | undefined} m */
const u = (m) => (m == null ? 0 : (units(m) ?? 0));


// l'état de la période, en mots, d'après `state.kind` du serveur (no_budget, closed_ok,
// closed_over, over, likely_over, on_pace)
/**
 * @param {string} kind
 * @param {{rest: number | null, over: number, ratio: number, expected: number | null}} x
 */
function periodState(kind, { rest, over, ratio, expected }) {
  const pace = expected != null ? `${pf(ratio, 0)} % dépensés, ${pf(expected, 0)} % attendus à ce jour` : `${pf(ratio, 0)} % du budget dépensé`;
  switch (kind) {
    case "closed_ok": return { k: "good", short: "Clos", color: "var(--accent)", icon: "check", text: `Période close avec ${n0(rest)} ${base()} d'avance sur le budget` };
    case "closed_over": return { k: "bad", short: "Dépassé", color: "var(--neg)", icon: "alert", text: `Période close avec un dépassement de ${n0(over)} ${base()}` };
    case "over": return { k: "bad", short: "Dépassé", color: "var(--neg)", icon: "alert", text: `Budget dépassé de ${n0(over)} ${base()}` };
    // au-dessus du rythme n'est pas un dépassement : dit, sans couleur d'alerte
    case "likely_over": return { k: "ok", short: "Au-dessus du rythme", color: "var(--accent)", icon: "info", text: `Au-dessus du rythme : ${pace}` };
    case "on_pace": return { k: "good", short: "Dans le rythme", color: "var(--accent)", icon: "check", text: expected != null ? `Dans le rythme : ${pace}` : pace };
    default: return { k: "ok", short: "Sans budget", color: "var(--accent)", icon: "info", text: "Pas encore de budget : fixe une cible par catégorie pour suivre le reste à vivre." };
  }
}

// chiffres d'une période, tels que le serveur les donne : dépensé, budget, reste, rythme (part
// de la période écoulée), part attendue à ce jour, état, projection à la fin de la période
/** @param {BudgetOut} b */
export function model(b) {
  /** @type {Line[]} */
  const lines = b.lines.map((l) => ({ ...l, s: u(l.spent), t: l.target ? units(l.target) : null, p: l.projected ? units(l.projected) : null }));
  const T = b.budget ? units(b.budget) : null;
  // hors catégories suivies à l'année : elles ont leur propre jauge, depuis janvier
  const spent = u(b.budgeted_expenses || b.expenses);
  const rest = T == null ? null : u(b.rest_to_live);
  const over = b.state && b.state.over_by ? (units(b.state.over_by) ?? 0) : 0;
  const r = T ? spent / T : 0;
  const expected = ratio(b.expected);
  const state = periodState(b.state ? b.state.kind : "no_budget", { rest, over, ratio: r, expected });
  const projection = b.projection ? units(b.projection) : null;
  return { lines, T, spent, rest, ratio: r, pace: ratio(b.pace), expected, state, projection, current: Boolean(b.current), daysLeft: b.days_left, months: b.months.length || 1, missingFx: b.missing_fx || [] };
}

// un écart sous l'unité s'écrit avec ses décimales : « Dépassé de 0.35 », jamais « de 0 »
/** @param {number} v */
const gap = (v) => (Math.abs(v) < 1 ? n2(v) : n0(v));

// l'état d'une catégorie, en mots, d'après `state` du serveur (untracked, over, likely_over,
// paid, ok). Une seule couleur à l'écran : seul le dépassement (`k: "bad"`) passe en rouge.
/** @param {Line} l */
export function catState(l) {
  const t = l.t ?? 0;
  switch (l.state) {
    case "over": return { k: "bad", txt: `Dépassé de ${gap(l.s - t)}` };
    case "likely_over": return { k: "ok", txt: `Reste ${n0(t - l.s)} · au-dessus du rythme` };
    case "paid": return { k: "ok", txt: "Payé" };
    case "ok": return { k: "ok", txt: `Reste ${n0(t - l.s)}` };
    default: return { k: "ok", txt: "Hors budget" };
  }
}

/** @param {string} d une date AAAA-MM-JJ → « 1 nov. » */
const dayMonth = (d) => `${Number(d.slice(8, 10))} ${MOIS[Number(d.slice(5, 7)) - 1]}`;

// une charge fixe est due en entier, un jour donné : payée (et quand), ou attendue vers son
// jour habituel (`paid_on`, `expected_on` du serveur) ; payée en partie, il en reste
/**
 * @param {Line} l
 * @param {string} today AAAA-MM-JJ
 * @returns {{k: string, txt: string, done?: boolean}}
 */
export function fixedState(l, today) {
  const s = catState(l);
  if (l.state === "paid") return { k: "ok", done: true, txt: l.paid_on ? `Payé le ${dayMonth(l.paid_on)}` : "Payé" };
  if (l.state !== "ok" || l.s > 0.5 || !l.expected_on) return s;
  return { k: "ok", txt: `Attendu vers le ${dayMonth(l.expected_on)}${l.expected_on < today ? ", pas encore vu" : ""}` };
}

// catégorie suivie à l'année : le cumul depuis janvier face à la cible annuelle
/** @param {Line} c */
export function yearState(c) {
  const y = c.yearly;
  if (!y) return { k: "ok", txt: "Sans cible annuelle" };
  const done = u(y.spent), goal = y.target ? u(y.target) : null;
  return goal == null ? { k: "ok", txt: "Sans cible annuelle" }
    : c.state === "over" ? { k: "bad", txt: `Dépassé de ${gap(done - goal)} sur l'année` }
    : { k: "ok", txt: `Reste ${n0(goal - done)} sur l'année` };
}

// gravité pour le tri : dépassé, puis au-dessus du rythme, puis le reste par part consommée
/** @type {Record<string, number>} */
const RANK = { over: 2, likely_over: 1 };
/** @param {Line} c */
export const rank = (c) => (c.state ? RANK[c.state] || 0 : 0);

