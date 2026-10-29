// Sources et réglages : connexions et comptes en attente (connections.js, formulaires construits
// à l'ouverture), comptes avec leur fraîcheur et leurs réglages (accounts.js), affichage de cet
// appareil, dettes (debts.js). Profil, passkeys et état du hub sont remplis par app.js.
import { accountsList } from "./accounts.js";
import { accountsCard, connectionsCard } from "./connections.js";
import { debtsList } from "./debts.js";
import { STALE_DAYS, daysSince } from "./format.js";
import { TAX_RATES, taxRate } from "./meta.js";
import { api, monthStartDay, store } from "./store.js";
import { SHEETS, closeSheet, esc, openSheet, failure, fill, ibox, ic, pf, pref, setPref, toast } from "./ui.js";

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

// Rubriques : la liste groupée, puis une page par rubrique (son entrée d'historique, le geste
// retour revient à la liste). Chaque ligne dit son état en mots, la teinte ne fait que doubler.
const RUBRICS = [
  ["Données", [["conn", "Connexions", "plug"], ["accounts", "Comptes", "wallet"], ["debts", "Dettes", "landmark"], ["export", "Exporter", "download"]]],
  ["Préférences", [["budget", "Budget", "piggy"], ["tax", "Impôts et 3a", "shield"], ["display", "Affichage", "eye"], ["profile", "Profil", "user"]]],
  ["Compte", [["security", "Sécurité", "faceid"], ["health", "État du hub", "info"]]],
];
const NAMES = Object.fromEntries(RUBRICS.flatMap(([, rs]) => rs.map(([k, l]) => [k, l])));
export const rubricLabel = (k) => NAMES[k] || "Sources et réglages";
const P = store.params;

// [texte, ton] de chaque rubrique ; null tant que la donnée n'est pas là
function status(k) {
  const d = (path) => store.data(path);
  if (k === "conn") {
    const c = d("/collectors/connections"), pe = d("/finance/accounts/pending");
    if (!c) return null;
    const miss = c.items.filter((x) => !x.ready).length, wait = pe ? pe.items.length : 0;
    if (miss) return [`${miss} à régler`, "warn"];
    if (wait) return [`${wait} compte${wait > 1 ? "s" : ""} en attente`, "warn"];
    return c.items.length ? [`${c.items.length} active${c.items.length > 1 ? "s" : ""}`, "ok"] : ["aucune", ""];
  }
  if (k === "accounts") {
    const f = d("/finance/freshness");
    if (!f) return null;
    const vis = f.items.filter((x) => !x.hidden);
    const late = vis.filter((x) => { const a = daysSince(x.last_data); return a == null || a > STALE_DAYS; }).length;
    return late ? [`${late} en retard`, "warn"] : [`${vis.length} à jour`, "ok"];
  }
  if (k === "debts") {
    const x = d("/finance/debts");
    return x ? [x.items.length ? `${x.items.length}` : "aucune", ""] : null;
  }
  if (k === "budget") {
    const day = monthStartDay();
    return [`début le ${day === 1 ? "1er" : day}`, ""];
  }
  if (k === "tax") return [`${pf(taxRate(), 0)} %`, ""];
  if (k === "display") return [{ system: "Système", light: "Clair", dark: "Sombre" }[pref("theme", "system")] || "Système", ""];
  if (k === "security") {
    const x = d("/auth/passkeys");
    if (!x) return null;
    return x.items.length < 2 ? ["1 seule passkey", "warn"] : [`${x.items.length} passkeys`, "ok"];
  }
  if (k === "health") {
    const h = d("/health");
    return h ? [h.status === "ok" ? `v${h.version}` : "à vérifier", h.status === "ok" ? "ok" : "warn"] : null;
  }
  return null;
}

function rubrics() {
  return RUBRICS.map(([g, rs]) => `<section class="card rub" aria-labelledby="rg-${esc(g)}"><h2 class="grp-title" id="rg-${esc(g)}">${esc(g)}</h2>
    ${rs.map(([k, l, i]) => {
      const st = status(k);
      return `<button class="trow press" type="button" data-a="rubric" data-v="${k}">${ibox(ic(i), "var(--accent)", "sm")}<span class="t">${esc(l)}</span>
        <span class="row-num">${st ? `<span class="pill ${st[1]}">${st[1] === "warn" ? ic("alert") : ""}${esc(st[0])}</span>` : ""}${ic("chev", "chev-r")}</span></button>`;
    }).join("")}</section>`).join("") + `<section class="card"><button class="secondary danger" type="button" data-a="logout">Se déconnecter</button></section>`;
}

export function render() {
  const r = P.rubric;
  document.getElementById("t-sources").textContent = rubricLabel(r);
  for (const n of document.querySelectorAll("#sources [data-rubric]")) {
    // les éditeurs gardent leur propre état hidden : seule la rubrique hors page les cache
    n.classList.toggle("off-rubric", n.dataset.rubric !== r);
  }
  const list = $("rubrics");
  list.hidden = Boolean(r);
  if (!r) {
    for (const p of ["/collectors/connections", "/finance/accounts/pending", "/finance/freshness", "/finance/debts", "/auth/passkeys", "/health"]) store.use(p);
    fill(list, rubrics());
    return;
  }
  if (r === "conn") { connectionsCard(); accountsCard(); }
  if (r === "accounts") accountsList();
  if (r === "debts") debtsList();
  if (r === "budget") {
    const se = store.use(SETTINGS), day = se.data ? se.data.month_start_day : monthStartDay();
    fill($("budget-rows"), `
    <div class="setrow"><label for="month-start" id="month-start-lbl">Début du mois budgétaire<small>${se.data ? esc(example(se.data)) : "Le jour de ta paie, par exemple."} Après le 15, le mois porte le nom du mois où il finit.</small></label>
      <select id="month-start" class="select-day">${DAYS.map((d) => `<option value="${d}" ${d === day ? "selected" : ""}>le ${d === 1 ? "1er" : d}</option>`).join("")}</select></div>`);
  }
  if (r === "tax") {
    const t = taxRate();
    fill($("tax-rows"), `
    <div class="setrow col"><span id="tax-lbl">Ton taux marginal d'impôt<small>Sert à estimer l'impôt économisé par tes versements 3a, sur l'accueil. Gardé sur cet appareil : il dépend de ton revenu et de ta commune.</small></span>
      <div class="scroll-x"><div class="seg small" role="group" aria-labelledby="tax-lbl">${TAX_RATES.map((x) => `<button type="button" data-a="tax" data-v="${x}" aria-pressed="${Math.abs(t - x) < 1e-9}">${pf(x, 0)} %</button>`).join("")}</div></div></div>`);
  }
  if (r === "display") {
    const hide = pref("hide", false), theme = pref("theme", "system");
    fill($("display-rows"), `
    <div class="setrow"><span id="hide-lbl">Masquer les montants<small>Floute les montants sur tous les écrans de cet appareil</small></span><button class="switch" type="button" role="switch" aria-checked="${hide}" aria-labelledby="hide-lbl" data-a="hide"></button></div>
    <div class="setrow"><span>Thème</span><div class="seg small" role="group" aria-label="Thème">${THEMES.map(([k, l]) => `<button type="button" data-a="theme" data-v="${k}" aria-pressed="${theme === k}">${l}</button>`).join("")}</div></div>`);
  }
}

SHEETS.logout = () => ({
  title: "Se déconnecter ?",
  body: '<p class="note">Il faudra Face ID ou ta passkey pour revenir. Rien n\'est effacé.</p>',
  foot: '<div class="stack-v"><button class="primary danger-bg" type="button" data-a="logout-go" data-autofocus>Se déconnecter</button><button class="secondary" type="button" data-a="sheet-close">Rester connecté</button></div>',
});

export const actions = {
  tax: (v) => {
    setPref("tax", Number(v));
    store.notify();
  },
  logout: () => openSheet("logout"),
  "logout-go": async (_v, btn) => {
    btn.disabled = true;
    try {
      await api("/auth/logout", {});
      closeSheet(true);
      location.replace("/");
    } catch (e) {
      btn.disabled = false;
      toast(failure(e), { error: true });
    }
  },
};

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
