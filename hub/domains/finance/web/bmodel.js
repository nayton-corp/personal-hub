// Le budget en mots : l'état d'une période et de chaque catégorie, tels que le serveur les
// calcule (/finance/budget : state, pace, expected, projection ; model/pace.py, la même règle que
// les sentinelles, audit M3). Ici on lit et on met en mots, on ne calcule pas.
import { base, ratio, units } from "../../format.js";
import { n0, pf } from "../../ui.js";

const u = (m) => (m ? units(m) : 0);


// l'état de la période, en mots, d'après `state.kind` du serveur (no_budget, closed_ok,
// closed_over, over, likely_over, on_pace)
function periodState(kind, { rest, over, ratio, expected }) {
  const pace = expected != null ? `${pf(ratio, 0)} % dépensés, ${pf(expected, 0)} % attendus à ce jour` : `${pf(ratio, 0)} % du budget dépensé`;
  switch (kind) {
    case "closed_ok": return { k: "good", short: "Clos", color: "var(--accent)", icon: "check", text: `Période close avec ${n0(rest)} ${base()} d'avance sur le budget` };
    case "closed_over": return { k: "bad", short: "Dépassé", color: "var(--neg)", icon: "alert", text: `Période close avec un dépassement de ${n0(over)} ${base()}` };
    case "over": return { k: "bad", short: "Dépassé", color: "var(--neg)", icon: "alert", text: `Budget dépassé de ${n0(over)} ${base()}` };
    case "likely_over": return { k: "warn", short: "Au-dessus du rythme", color: "var(--s3)", icon: "alert", text: `Au-dessus du rythme : ${pace}` };
    case "on_pace": return { k: "good", short: "Dans le rythme", color: "var(--accent)", icon: "check", text: expected != null ? `Dans le rythme : ${pace}` : pace };
    default: return { k: "ok", short: "Sans budget", color: "var(--accent)", icon: "info", text: "Pas encore de budget : fixe une cible par catégorie pour suivre le reste à vivre." };
  }
}

// chiffres d'une période, tels que le serveur les donne : dépensé, budget, reste, rythme (part
// de la période écoulée), part attendue à ce jour, état, projection à la fin de la période
export function model(b) {
  const lines = b.lines.map((l) => ({ ...l, s: u(l.spent), t: l.target ? units(l.target) : null, p: l.projected ? units(l.projected) : null }));
  const T = b.budget ? units(b.budget) : null;
  // hors catégories suivies à l'année : elles ont leur propre jauge, depuis janvier
  const spent = u(b.budgeted_expenses || b.expenses);
  const rest = T == null ? null : u(b.rest_to_live);
  const over = b.state && b.state.over_by ? units(b.state.over_by) : 0;
  const r = T ? spent / T : 0;
  const expected = ratio(b.expected);
  const state = periodState(b.state ? b.state.kind : "no_budget", { rest, over, ratio: r, expected });
  const projection = b.projection ? units(b.projection) : null;
  return { lines, T, spent, rest, ratio: r, pace: ratio(b.pace), expected, state, projection, current: Boolean(b.current), daysLeft: b.days_left, missingFx: b.missing_fx || [] };
}

// l'état d'une catégorie, en mots, d'après `state` du serveur (untracked, over, likely_over,
// paid, ok)
export function catState(l) {
  switch (l.state) {
    case "over": return { k: "bad", col: "var(--neg)", txt: `Dépassé de ${n0(l.s - l.t)}` };
    case "likely_over": return { k: "warn", col: "var(--s3)", txt: `Reste ${n0(l.t - l.s)}, au-dessus du rythme` };
    case "paid": return { k: "ok", col: "var(--pos)", txt: "Payé" };
    case "ok": return { k: "ok", col: "var(--pos)", txt: `Reste ${n0(l.t - l.s)}` };
    default: return { k: "ok", col: "var(--faint)", txt: "Hors budget" };
  }
}


// catégorie suivie à l'année : le cumul depuis janvier face à la cible annuelle
export function yearState(c) {
  const y = c.yearly, done = u(y.spent), goal = y.target ? u(y.target) : null;
  return goal == null ? { k: "ok", col: "var(--faint)", txt: "Sans cible annuelle" }
    : c.state === "over" ? { k: "bad", col: "var(--neg)", txt: `Dépassé de ${n0(done - goal)} sur l'année` }
    : { k: "ok", col: "var(--pos)", txt: `Reste ${n0(goal - done)} sur l'année` };
}

// gravité pour le tri : dépassé, puis au-dessus du rythme, puis le reste par part consommée
export const rank = (c) => ({ over: 2, likely_over: 1 })[c.state] || 0;

