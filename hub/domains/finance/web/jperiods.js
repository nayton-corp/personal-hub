// Journal : les périodes proposées par le panneau de filtres.
import { monthSpan, shiftMonth, store } from "../../store.js";

export const PERIODS = [["m0", "Ce mois"], ["m1", "Mois dernier"], ["m3", "3 derniers mois"], ["y", "Cette année"]];

export function periodOf(k) {
  const m = store.today;
  if (k === "m0") return monthSpan(m);
  if (k === "m1") return monthSpan(shiftMonth(m, -1));
  if (k === "m3") return [monthSpan(shiftMonth(m, -2))[0], monthSpan(m)[1]];
  return [`${m.slice(0, 4)}-01-01`, `${m.slice(0, 4)}-12-31`];
}
