// Sources et réglages : connexions et comptes en attente (connections.js, formulaires construits
// à l'ouverture), comptes avec leur fraîcheur et leurs réglages (accounts.js), affichage de cet
// appareil, dettes (debts.js). Profil, passkeys et état du hub sont remplis par app.js.
import { accountsList } from "./accounts.js";
import { accountsCard, connectionsCard } from "./connections.js";
import { debtsList } from "./debts.js";
import { api, monthStartDay, store } from "./store.js";
import { esc, failure, fill, pref, toast } from "./ui.js";

const $ = (id) => document.getElementById(id);
const THEMES = [["system", "Système"], ["light", "Clair"], ["dark", "Sombre"]];
const SETTINGS = "/finance/settings";
const DAYS = Array.from({ length: 28 }, (_, i) => i + 1);

// exemple lisible du réglage : « novembre va du 25 octobre au 24 novembre »
function example(s) {
  if (!s) return "";
  const [a, b] = [s.current_period.start, s.current_period.end].map((x) => new Date(`${x}T00:00:00Z`));
  b.setUTCDate(b.getUTCDate() - 1);
  const f = (d) => d.toLocaleDateString("fr-CH", { day: "numeric", month: "long", timeZone: "UTC" });
  const name = new Date(`${s.current_month}-01T00:00:00Z`).toLocaleDateString("fr-CH", { month: "long", timeZone: "UTC" });
  return `Le mois en cours, ${name}, va du ${f(a)} au ${f(b)}.`;
}

export function render() {
  connectionsCard();
  accountsCard();
  accountsList();
  debtsList();
  const se = store.use(SETTINGS), day = se.data ? se.data.month_start_day : monthStartDay();
  fill($("budget-rows"), `
    <div class="setrow"><label for="month-start" id="month-start-lbl">Début du mois budgétaire<small>${se.data ? esc(example(se.data)) : "Le jour de ta paie, par exemple."} Après le 15, le mois porte le nom du mois où il finit.</small></label>
      <select id="month-start" class="select-day">${DAYS.map((d) => `<option value="${d}" ${d === day ? "selected" : ""}>le ${d === 1 ? "1er" : d}</option>`).join("")}</select></div>`);
  const hide = pref("hide", false), theme = pref("theme", "system");
  fill($("display-rows"), `
    <div class="setrow"><span id="hide-lbl">Masquer les montants<small>Floute les montants sur tous les écrans de cet appareil</small></span><button class="switch" type="button" role="switch" aria-checked="${hide}" aria-labelledby="hide-lbl" data-a="hide"></button></div>
    <div class="setrow"><span>Thème</span><div class="seg small" role="group" aria-label="Thème">${THEMES.map(([k, l]) => `<button type="button" data-a="theme" data-v="${k}" aria-pressed="${theme === k}">${l}</button>`).join("")}</div></div>`);
}

export const actions = {};

document.addEventListener("change", async (e) => {
  if (e.target.id !== "month-start") return;
  const day = Number(e.target.value);
  try {
    const s = await api(SETTINGS, { month_start_day: day });
    store.setMonthStart(s.month_start_day);
    toast(`Le mois budgétaire commence le ${day === 1 ? "1er" : day}`);
  } catch (err) {
    toast(failure(err), { error: true });
    store.invalidate();
  }
});
