// Coquille de l'app (chantier S5) : navigation, barre d'onglets, feuilles, page des réglages.
// Elle ne connaît aucun domaine : /api/domains lui donne les manifestes, et chaque module nommé
// (fichier du dossier web/ du domaine) est chargé puis monté.
//   - onglet (`tabs[].module`) : render(), actions ; facultatifs todoCount(), todoLabel,
//     unlink(lien) quand l'historique quitte un lien suivi ;
//   - accueil (`home`) : render(box), actions ; facultatifs lead, rows() (accueil.js) ; il
//     dessine dans [data-home=<domaine>] ;
//   - cartes (`cards`) : facultatifs detail(p), prepare(ids) (approvals.js) ;
//   - rubrique (`settings[].module`) : rubric(id) dessine la page, rubricStatus(id) l'état en
//     mots ([texte, ton] ou null) ;
//   - module du domaine (`module`) : init(), after() après chaque rendu, deeplink(hash).
// Tout module peut exporter init() (appelé une fois), actions (distribuées par data-a) et
// markup : ses balises, [sélecteur, position d'insertAdjacentHTML, html], posées avant tout
// rendu. Les modules d'un domaine sont servis sous /d/<domaine>/ ; ils n'importent que ceux
// de la coquille (../../ui.js…) et les leurs.
import * as accueil from "./accueil.js";
import * as approvals from "./approvals.js";
import * as sources from "./sources.js";
import { api, store } from "./store.js";
import {
  SH, announce, applyTheme, closeSheet, esc, fill, ic, initSheetSwipe, initToast, pref, renderSheet, setPref, sheetEntryOpen, sheetPop,
} from "./ui.js";

const $ = (id) => document.getElementById(id);
const P = store.params;
const CACHED = "hub.domains"; // les manifestes du dernier lancement, pour démarrer hors ligne
const TABS = [];
const VIEWS = { accueil: accueil.render, sources: sources.render };
const LABEL = { accueil: "Accueil", sources: "Sources et réglages" };
const ACTIONS = { ...sources.actions, ...approvals.actions };
const MODULES = []; // modules de domaine (champ `module`), dans l'ordre des domaines
const TODO = {}; // onglet → module qui compte ce qui reste à faire
const LINKED = []; // modules qui savent rendre les filtres d'un lien suivi
const scrolls = {};
let back = "accueil";
let drawn = null;
let depth = 0; // entrées ajoutées par l'app depuis son ouverture

// --- montage des domaines ---------------------------------------------------------------------

async function manifests() {
  try {
    const items = (await api("/domains")).items;
    try { localStorage.setItem(CACHED, JSON.stringify(items)); } catch { /* stockage plein ou interdit */ }
    return items;
  } catch {
    try { return JSON.parse(localStorage.getItem(CACHED)) || []; } catch { return []; }
  }
}

// un onglet sans balisage dans index.html reçoit une page générique, avant les réglages
function viewFor(tab) {
  if ($(tab.id)) return;
  const s = document.createElement("section");
  Object.assign(s, { className: "view", id: tab.id, hidden: true });
  s.dataset.view = tab.id;
  s.setAttribute("aria-labelledby", `t-${tab.id}`);
  s.innerHTML = `<header class="topbar"><div class="topbar-row">
    <h1 class="topbar-title" id="t-${esc(tab.id)}">${esc(tab.label)}</h1>
    <button class="icon-btn" type="button" data-a="hide" aria-pressed="false"></button>
    <button class="icon-btn" type="button" data-a="settings" aria-label="Sources et réglages"></button>
  </div></header><div id="${esc(tab.id)}-body"></div>`;
  $("sources").before(s);
}

async function mount() {
  const domains = await manifests();
  // les modules d'un domaine sont servis sous /d/<domaine>/, à côté de son code
  const path = (d, f) => `./d/${d.name}/${f}`;
  const files = new Set();
  for (const d of domains) {
    const app = d.app;
    for (const f of [app.module, app.home, app.cards, ...app.tabs.map((t) => t.module), ...app.settings.map((s) => s.module)]) if (f) files.add(path(d, f));
  }
  const loaded = {};
  await Promise.all([...files].map(async (f) => { loaded[f] = await import(f); }));
  for (const m of Object.values(loaded)) {
    Object.assign(ACTIONS, m.actions || {});
    for (const [sel, where, html] of m.markup || []) document.querySelector(sel).insertAdjacentHTML(where, html);
  }
  const tabs = [];
  for (const d of domains) {
    const app = d.app, mod = (f) => loaded[path(d, f)];
    if (app.module) MODULES.push(mod(app.module));
    if (app.home) accueil.add(d.name, mod(app.home));
    if (app.cards) approvals.addCards(d.name, mod(app.cards));
    for (const t of app.tabs) tabs.push({ ...t, m: mod(t.module) });
    sources.add(app.settings.map((s) => ({ ...s, m: mod(s.module) })));
  }
  tabs.sort((a, b) => a.order - b.order || a.id.localeCompare(b.id));
  TABS.push(["accueil", "Accueil", "home"]);
  TODO.accueil = accueil;
  for (const t of tabs) {
    viewFor(t);
    TABS.push([t.id, t.label, t.icon]);
    VIEWS[t.id] = t.m.render;
    LABEL[t.id] = t.label;
    if (t.m.todoCount) TODO[t.id] = t.m;
    if (t.m.unlink) LINKED.push(t.m);
  }
  for (const m of Object.values(loaded)) if (m.init) m.init();
}

// --- navigation -------------------------------------------------------------------------------

// Chaque écran (et chaque rubrique des réglages) a son entrée d'historique : le geste retour
// d'iOS revient à l'écran d'avant, comme un lien. state = { tab, rubric, link }.
const entry = () => ({ tab: P.tab, rubric: P.rubric || null, link: P.jlink || null });
const title = () => (P.rubric ? sources.rubricLabel(P.rubric) : LABEL[P.tab]);

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
  announce(title());
}

// retour du navigateur : l'écran de l'entrée revient ; un lien suivi depuis un autre écran
// (Journal filtré) rend ses filtres en partant
function popped(e) {
  if (sheetPop()) return;
  const s = e.state || { tab: "accueil" };
  depth = Math.max(0, depth - 1);
  if (P.jlink && s.link !== P.jlink) for (const m of LINKED) m.unlink(P.jlink);
  scrolls[P.tab + (P.rubric || "")] = window.scrollY;
  store.set({ tab: VIEWS[s.tab] ? s.tab : "accueil", rubric: s.rubric || null, jlink: s.link || null });
  announce(title());
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

export const action = (name) => ACTIONS[name];

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
    chrome();
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

function chrome() {
  const hide = pref("hide", false);
  document.body.classList.toggle("hide-amounts", hide);
  for (const b of document.querySelectorAll('.icon-btn[data-a="hide"]')) {
    b.innerHTML = ic(hide ? "eyeoff" : "eye");
    b.setAttribute("aria-pressed", String(hide));
    b.setAttribute("aria-label", hide ? "Afficher les montants" : "Masquer les montants");
  }
  for (const b of document.querySelectorAll('[data-a="settings"]')) if (!b.firstChild) b.innerHTML = ic("gear");
  for (const b of document.querySelectorAll('[data-a="back"]')) if (!b.firstChild) b.innerHTML = ic("back");
  fill($("tabs"), TABS.map(([k, l, i]) => {
    const n = TODO[k] ? TODO[k].todoCount() || 0 : 0;
    const what = (TODO[k] && TODO[k].todoLabel) || "à traiter";
    return `<button type="button" data-a="tab" data-v="${k}" ${P.tab === k ? 'aria-current="page"' : ""} aria-label="${l}${n ? `, ${n} ${what}` : ""}">${ic(i)}${l}${n ? `<span class="badge" aria-hidden="true">${n > 99 ? "99+" : n}</span>` : ""}</button>`;
  }).join(""));
}

export function draw() {
  if ($("shell").hidden) return; // déconnecté : l'écran de connexion reste affiché
  const active = document.activeElement;
  const focus = active && active !== document.body && document.body.contains(active) ? selectorFor(active) : null;
  for (const id of Object.keys(VIEWS)) $(id).hidden = id !== P.tab;
  chrome();
  VIEWS[P.tab]();
  if (SH.kind) renderSheet();
  for (const m of MODULES) if (m.after) m.after();
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

// liens des notifications (#todo, et ceux des domaines) ; le hash est effacé une fois suivi,
// le retour revient à l'écran d'avant
async function deeplink() {
  const h = location.hash.slice(1);
  if (!h) return;
  history.replaceState(history.state, "", location.pathname + location.search);
  for (const m of MODULES) if (m.deeplink && (await m.deeplink(h))) return;
  go("accueil", { top: true });
}

export async function start() {
  await mount();
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
  // au retour dans l'app (iPhone), les chiffres sont relus
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") store.invalidate();
  });
  window.addEventListener("popstate", popped);
  window.addEventListener("hashchange", deeplink);
  initSheetSwipe();
  history.replaceState(entry(), "");
  deeplink();
  store.on(draw);
  draw();
}
