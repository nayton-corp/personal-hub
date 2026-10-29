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
import { freshLine } from "./format.js";
import {
  SH, announce, applyTheme, closeSheet, fill, ic, initSheetSwipe, initToast, pref, renderSheet, setPref, sheetEntryOpen, sheetPop,
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
let depth = 0; // entrées ajoutées par l'app depuis son ouverture

// --- navigation -------------------------------------------------------------------------------

// Chaque écran (et chaque rubrique des réglages) a son entrée d'historique : le geste retour
// d'iOS revient à l'écran d'avant, comme un lien. state = { tab, rubric, link }.
const entry = () => ({ tab: P.tab, rubric: P.rubric || null, link: P.jlink || null });

function remember(replace) {
  const s = entry();
  if (replace || sheetEntryOpen()) history.replaceState(s, "");
  else {
    history.pushState(s, "");
    depth += 1;
  }
}

export function go(tab, opts = {}) {
  if (!VIEWS[tab]) tab = "accueil";
  const inSheet = sheetEntryOpen();
  closeSheet(true, false, true);
  const rubric = tab === "sources" ? (opts.rubric ?? null) : null;
  if (tab === P.tab && rubric === (P.rubric || null)) {
    if (inSheet) history.replaceState(entry(), "");
    if (opts.top) window.scrollTo({ top: 0, behavior: reduced() ? "auto" : "smooth" });
    return;
  }
  scrolls[P.tab + (P.rubric || "")] = window.scrollY;
  if (tab === "sources" && P.tab !== "sources") back = P.tab;
  store.set({ tab, rubric, jlink: opts.link || null });
  if (opts.top) scrolls[tab + (rubric || "")] = 0;
  remember(inSheet || opts.replace);
  announce(rubric ? settings.rubricLabel(rubric) : LABEL[tab]);
}

// retour du navigateur : l'écran de l'entrée revient ; un lien suivi depuis un autre écran
// (Journal filtré) rend ses filtres en partant
function popped(e) {
  if (sheetPop()) return;
  const s = e.state || { tab: "accueil" };
  depth = Math.max(0, depth - 1);
  if (P.jlink && s.link !== P.jlink) journal.unlink(P.jlink);
  scrolls[P.tab + (P.rubric || "")] = window.scrollY;
  store.set({ tab: VIEWS[s.tab] ? s.tab : "accueil", rubric: s.rubric || null, jlink: s.link || null });
  announce(s.rubric ? settings.rubricLabel(s.rubric) : LABEL[P.tab]);
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
  rubric: (v) => go("sources", { rubric: v }),
  back: () => {
    if (depth > 0) history.back();
    else go(P.rubric ? "sources" : back || "accueil", { replace: true });
  },
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

// sous chaque titre : quand les chiffres ont été reçus, ou qu'ils sont ceux d'avant la coupure
function freshness() {
  const fe = store.use("/finance/freshness");
  const line = freshLine(fe.data, store.offline, store.lastOk);
  for (const n of document.querySelectorAll("[data-fresh]")) {
    n.textContent = line.text;
    n.classList.toggle("warn", line.warn);
    n.classList.toggle("off", store.offline);
  }
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
  freshness();
  const key = P.tab + (P.rubric || "");
  if (drawn !== key) {
    drawn = key;
    window.scrollTo(0, scrolls[key] || 0);
  }
  if (focus && !(active && document.body.contains(active))) {
    const n = document.querySelector(focus);
    if (n && (SH.kind ? $("sheet").contains(n) : !$("sheet").contains(n))) n.focus({ preventScroll: true });
  }
}

// liens des notifications ntfy : #sources, #todo, #alert=<id opaque> ; le hash est effacé une
// fois suivi, le retour revient à l'écran d'avant
async function deeplink() {
  const h = location.hash.slice(1);
  if (!h) return;
  history.replaceState(history.state, "", location.pathname + location.search);
  if (h === "sources") return go("sources", { rubric: "conn" });
  if (h === "todo") return go("accueil", { top: true });
  const id = h.startsWith("alert=") ? h.slice(6) : null;
  if (!id) return;
  try {
    const a = (await api("/finance/alerts")).items.find((x) => x.id === id);
    if (!a) return go("accueil", { top: true });
    if (a.kind === "recurring_up") return ACTIONS.subs();
    if (a.kind === "pillar3a_margin") return go("sources", { rubric: "tax" });
    if (a.detail && a.detail.category) {
      store.set({ month: a.detail.month || store.today, period: "m" });
      go("budget");
      return ACTIONS.cat(a.detail.category);
    }
    go("budget");
  } catch {
    go("accueil");
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
  window.addEventListener("popstate", popped);
  window.addEventListener("hashchange", deeplink);
  initSheetSwipe();
  history.replaceState(entry(), "");
  deeplink();
  store.on(draw);
  draw();
  // jour de début du mois budgétaire : le mois en cours en dépend
  api("/finance/settings").then((s) => store.setMonthStart(s.month_start_day)).catch(() => {});
}
