// Module de la finance (chantier S5), monté par la coquille (shell.js) d'après son manifeste :
// ce qui démarre une fois, la fraîcheur sous chaque titre, et les liens des notifications.
// Ses écrans sont des modules à part (home, wealth, budget, journal, settings) ; comptes et
// dettes n'ont pas d'onglet, leurs actions passent par ici. Aucun chiffre n'est inventé : tout
// vient de /api/finance, en centimes.
import * as accounts from "./accounts.js";
import * as debts from "./debts.js";
import { initConnections } from "./connections.js";
import { freshLine } from "./format.js";
import * as journal from "./journal.js";
import { action, go } from "./shell.js";
import { api, store } from "./store.js";
import { initWelcome } from "./welcome.js";

export const actions = { ...accounts.actions, ...debts.actions };

export function init() {
  initConnections();
  initWelcome();
  window.addEventListener("hub:changed", () => journal.reset());
  // jour de début du mois budgétaire : le mois en cours en dépend
  api("/finance/settings").then((s) => store.setMonthStart(s.month_start_day)).catch(() => {});
}

// sous chaque titre : quand les chiffres ont été reçus, ou qu'ils sont ceux d'avant la coupure
export function after() {
  const fe = store.use("/finance/freshness");
  const line = freshLine(fe.data, store.offline, store.lastOk);
  for (const n of document.querySelectorAll("[data-fresh]")) {
    n.textContent = line.text;
    n.classList.toggle("warn", line.warn);
    n.classList.toggle("off", store.offline);
  }
}

// liens des notifications ntfy : #sources, #alert=<id opaque> ; true quand le lien est suivi
export async function deeplink(h) {
  if (h === "sources") {
    go("sources", { rubric: "conn" });
    return true;
  }
  if (!h.startsWith("alert=")) return false;
  const id = h.slice(6);
  try {
    const a = (await api("/observations?domain=finance")).items.find((x) => x.key === id);
    if (!a) return false;
    if (a.kind === "recurring_up") action("subs")();
    else if (a.kind === "pillar3a_margin") go("sources", { rubric: "tax" });
    else if (a.detail && a.detail.category) {
      store.set({ month: a.detail.month || store.today, period: "m" });
      go("budget");
      action("cat")(a.detail.category);
    } else go("budget");
  } catch {
    return false;
  }
  return true;
}
