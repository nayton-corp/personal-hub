// Coquille de l'app (maquette du 28/10/2026) : onglets, rendu, actions. Chaque écran est un
// module (home, wealth, budget, journal, settings) qui dessine ses blocs depuis le store et
// déclare ses actions ; un seul écouteur de clics les distribue par data-a. Aucun chiffre n'est
// inventé ici : tout vient de /api/finance, en centimes.
import * as accounts from "./accounts.js";
import * as budget from "./budget.js";
import * as debts from "./debts.js";
import { initConnections } from "./connections.js";
import * as home from "./home.js";
import * as journal from "./journal.js";
import * as settings from "./settings.js";
import { api, store } from "./store.js";
import {
  SH, announce, applyTheme, closeSheet, fill, ic, initToast, pref, renderSheet, setPref,
} from "./ui.js";
import { initWelcome } from "./welcome.js";
import * as wealth from "./wealth.js";

const $ = (id) => document.getElementById(id);
const P = store.params;
const TABS = [["accueil", "Accueil", "home"], ["patrimoine", "Patrimoine", "trend"], ["budget", "Budget", "wallet"], ["journal", "Journal", "list"]];
const VIEWS = { accueil: home.render, patrimoine: wealth.render, budget: budget.render, journal: journal.render, sources: settings.render };
const LABEL = { accueil: "Accueil", patrimoine: "Patrimoine", budget: "Budget", journal: "Journal", sources: "Sources et réglages" };
const ACTIONS = { ...accounts.actions, ...debts.actions, ...home.actions, ...wealth.actions, ...budget.actions, ...journal.actions, ...settings.actions };
const scrolls = {};
let back = "accueil";
let drawn = null;

// --- navigation -------------------------------------------------------------------------------

export function go(tab, opts = {}) {
  if (!VIEWS[tab]) tab = "accueil";
  closeSheet(true);
  if (tab === P.tab) {
    if (opts.top) window.scrollTo({ top: 0, behavior: reduced() ? "auto" : "smooth" });
    return;
  }
  scrolls[P.tab] = window.scrollY;
  if (tab === "sources") back = P.tab;
  store.set({ tab });
  if (opts.top) scrolls[tab] = 0;
  announce(LABEL[tab]);
}

const reduced = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

// amène un élément sous la barre du haut de l'écran affiché
export function reveal(node, extra = 0) {
  if (!node) return;
  setTimeout(() => {
    const top = document.querySelector(`#${P.tab} .topbar`);
    const y = node.getBoundingClientRect().top + window.scrollY - (top ? top.offsetHeight : 0) - 8 - extra;
    window.scrollTo({ top: Math.max(0, y), behavior: reduced() ? "auto" : "smooth" });
  }, 40);
}

Object.assign(ACTIONS, {
  tab: (v) => go(v, { top: v === P.tab }),
  settings: () => go("sources"),
  back: () => go(back || "accueil"),
  "sheet-close": () => closeSheet(),
  hide: () => {
    const on = !pref("hide", false);
    setPref("hide", on);
    shell();
    announce(on ? "Montants masqués" : "Montants affichés");
  },
  theme: (v) => {
    setPref("theme", v);
    applyTheme(v);
    store.notify();
  },
});

// --- rendu ------------------------------------------------------------------------------------

function selectorFor(node) {
  if (node.id) return `#${CSS.escape(node.id)}`;
  const at = [...node.attributes].filter((a) => a.name.startsWith("data-") && a.name !== "data-css").map((a) => `[${a.name}="${CSS.escape(a.value)}"]`).join("");
  return at ? node.tagName.toLowerCase() + at : null;
}

function shell() {
  const hide = pref("hide", false);
  document.body.classList.toggle("hide-amounts", hide);
  for (const b of document.querySelectorAll('.icon-btn[data-a="hide"]')) {
    b.innerHTML = ic(hide ? "eyeoff" : "eye");
    b.setAttribute("aria-pressed", String(hide));
    b.setAttribute("aria-label", hide ? "Afficher les montants" : "Masquer les montants");
  }
  for (const b of document.querySelectorAll('[data-a="settings"]')) if (!b.firstChild) b.innerHTML = ic("gear");
  for (const b of document.querySelectorAll('[data-a="back"]')) if (!b.firstChild) b.innerHTML = ic("back");
  const badges = { accueil: home.todoCount(), journal: journal.todoCount() };
  fill($("tabs"), TABS.map(([k, l, i]) => {
    const n = badges[k] || 0;
    const what = k === "journal" ? "à classer" : "à traiter";
    return `<button type="button" data-a="tab" data-v="${k}" ${P.tab === k ? 'aria-current="page"' : ""} aria-label="${l}${n ? `, ${n} ${what}` : ""}">${ic(i)}${l}${n ? `<span class="badge" aria-hidden="true">${n > 99 ? "99+" : n}</span>` : ""}</button>`;
  }).join(""));
}

export function draw() {
  if ($("shell").hidden) return; // déconnecté : l'écran de connexion reste affiché
  const active = document.activeElement;
  const focus = active && active !== document.body && document.body.contains(active) ? selectorFor(active) : null;
  for (const id of Object.keys(VIEWS)) $(id).hidden = id !== P.tab;
  shell();
  VIEWS[P.tab]();
  if (SH.kind) renderSheet();
  if (drawn !== P.tab) {
    drawn = P.tab;
    window.scrollTo(0, scrolls[P.tab] || 0);
  }
  if (focus && !(active && document.body.contains(active))) {
    const n = document.querySelector(focus);
    if (n && (SH.kind ? $("sheet").contains(n) : !$("sheet").contains(n))) n.focus({ preventScroll: true });
  }
}

export function start() {
  if (!VIEWS[P.tab]) P.tab = "accueil";
  applyTheme(pref("theme", "system"));
  document.addEventListener("click", (e) => {
    const t = e.target.closest("[data-a]");
    if (!t || t.disabled || t.getAttribute("aria-disabled") === "true") return;
    const fn = ACTIONS[t.dataset.a];
    if (!fn) return;
    e.preventDefault();
    fn(t.dataset.v, t, e);
  });
  // éléments SVG ou blocs à rôle de bouton : Entrée et Espace comme un clic
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && SH.kind) {
      e.preventDefault();
      closeSheet();
      return;
    }
    const t = e.target.closest && e.target.closest('[role="button"][data-a]');
    if (t && t.tagName !== "BUTTON" && (e.key === "Enter" || e.key === " ")) {
      e.preventDefault();
      t.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    }
  });
  $("backdrop").addEventListener("click", () => closeSheet());
  initToast(() => store.notify());
  initConnections();
  initWelcome();
  wealth.init();
  journal.init();
  // au retour dans l'app (iPhone), les chiffres sont relus
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") store.invalidate();
  });
  window.addEventListener("hub:changed", () => journal.reset());
  store.on(draw);
  draw();
  // jour de début du mois budgétaire : le mois en cours en dépend
  api("/finance/settings").then((s) => store.setMonthStart(s.month_start_day)).catch(() => {});
}
