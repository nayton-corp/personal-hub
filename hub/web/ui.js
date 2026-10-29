// Briques de l'interface : icônes, mise en forme en HTML, panneau du bas, message éphémère,
// annonces pour les lecteurs d'écran. Le HTML est construit en texte : chaque valeur venue des
// données passe par esc(). Aucun attribut style (CSP) : data-css="prop:valeur;…" est appliqué
// en CSSOM par paint() après chaque rendu.
import { base } from "./format.js";

const $ = (id) => document.getElementById(id);

export const ICON = {
  home: "M3 11l9-8 9 8M5 10v10h14V10",
  trend: "M3 17l6-6 4 4 8-8M15 7h6v6",
  wallet: "M3 7h18v12H3zM3 11h18M16 15h.01",
  list: "M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01",
  eye: "M3 12s4-6 9-6 9 6 9 6-4 6-9 6-9-6-9-6zM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z",
  eyeoff: "M3 3l18 18M10.6 6.1A9.8 9.8 0 0 1 12 6c5 0 9 6 9 6a16 16 0 0 1-2.6 3.2M6.5 7.6A15.7 15.7 0 0 0 3 12s4 6 9 6a9 9 0 0 0 4.4-1.1M9.9 9.9a3 3 0 0 0 4.2 4.2",
  gear: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z",
  back: "M15 18l-6-6 6-6", chev: "M9 6l6 6-6 6", down: "M6 9l6 6 6-6", check: "M5 12l5 5 9-10", close: "M6 6l12 12M18 6L6 18",
  alert: "M12 3l10 18H2zM12 10v4M12 17h.01", info: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 11v5M12 8h.01",
  refresh: "M21 12a9 9 0 1 1-3-6.7L21 8M21 3v5h-5", search: "M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14zM21 21l-5-5",
  faceid: "M4 8V5a1 1 0 0 1 1-1h3M16 4h3a1 1 0 0 1 1 1v3M20 16v3a1 1 0 0 1-1 1h-3M8 20H5a1 1 0 0 1-1-1v-3M9 9v1M15 9v1M12 9v4h-1M9 16a4 4 0 0 0 6 0",
  key: "M14 10a4 4 0 1 0-1.2 2.8L20 20M17 17l2-2", plug: "M9 2v6M15 2v6M6 8h12v4a6 6 0 0 1-12 0zM12 18v4",
  download: "M12 3v12M7 10l5 5 5-5M4 21h16", user: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21a8 8 0 0 1 16 0",
  lockc: "M5 11h14v10H5zM8 11V7a4 4 0 0 1 8 0v4", filter: "M4 6h16M7 12h10M10 18h4", sort: "M8 4v16M4 16l4 4 4-4M16 20V4M12 8l4-4 4 4",
  banknote: "M2 6h20v12H2zM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM6 9h.01M18 15h.01",
  coin: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM9.5 8h4a2 2 0 0 1 0 4h-4h4.5a2 2 0 0 1 0 4H9.5zM9.5 8v8M11.5 6.5V8M11.5 16v1.5",
  bolt: "M13 2L4 14h7l-1 8 9-12h-7z", clock: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 7v5l3 2",
  shield: "M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z", plane: "M2 16l20-6-20-6 4 6zM6 10h8",
  piggy: "M5 11a7 6 0 0 1 13-2h2v4h-2a7 6 0 0 1-3 4v3h-3v-2h-3v2H6v-3a6 6 0 0 1-1-6zM15 9.5h.01",
  wifi: "M2 9a15 15 0 0 1 20 0M5 12.5a10 10 0 0 1 14 0M8.5 16a5 5 0 0 1 7 0M12 19.5h.01",
  repeat: "M17 2l4 4-4 4M3 11V9a3 3 0 0 1 3-3h15M7 22l-4-4 4-4M21 13v2a3 3 0 0 1-3 3H3",
  train: "M6 3h12a2 2 0 0 1 2 2v9a3 3 0 0 1-3 3H7a3 3 0 0 1-3-3V5a2 2 0 0 1 2-2zM4 10h16M8 21l2-4M16 21l-2-4", car: "M5 16V12l2-5h10l2 5v4zM5 16v2M19 16v2M8 13h.01M16 13h.01",
  landmark: "M3 21h18M5 21V10M19 21V10M9.5 21V10M14.5 21V10M2 10l10-6 10 6z",
  cart: "M3 4h2l2.4 11h11l2-8H6.2M9 20h.01M18 20h.01",
  utensils: "M7 3v8M4 3v5a3 3 0 0 0 6 0V3M7 11v10M17 3c-2 0-3 2-3 5v5h3M17 3v18",
  ticket: "M4 6h16v4a2 2 0 0 0 0 4v4H4v-4a2 2 0 0 0 0-4zM14 6v12", bag: "M5 8h14l-1 13H6zM9 8V6a3 3 0 0 1 6 0v2",
  heart: "M12 20s-7-4.5-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.5-7 10-7 10z",
  briefcase: "M3 7h18v13H3zM8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M3 13h18", arrowin: "M12 3v12M7 10l5 5 5-5M4 21h16",
  swap: "M7 4L3 8l4 4M3 8h14M17 20l4-4-4-4M21 16H7",
  help: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM9.5 9a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .8-1 1.4v.3M12 17h.01",
  dots: "M5 12h.01M12 12h.01M19 12h.01", cash: "M12 3v18M17 7H9.5a3 3 0 0 0 0 6h5a3 3 0 0 1 0 6H6",
};

export const ic = (n, cls = "") =>
  `<svg class="ic ${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${ICON[n] || ICON.help}"/></svg>`;
export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
// pastille teintée : pictogramme ou monogramme (déjà échappé)
export const ibox = (inner, color, size = "") =>
  `<span class="ibox tint ${size}" data-css="--c:${color}" aria-hidden="true">${inner}</span>`;
export const css = (pairs) => `data-css="${pairs}"`;

// applique les data-css du sous-arbre (CSSOM : permis par style-src 'self')
export function paint(root) {
  for (const node of root.querySelectorAll("[data-css]")) {
    for (const part of node.dataset.css.split(";")) {
      const i = part.indexOf(":");
      if (i > 0) node.style.setProperty(part.slice(0, i).trim(), part.slice(i + 1).trim());
    }
  }
}

export function fill(node, html) {
  node.innerHTML = html;
  paint(node);
}

// --- nombres ---------------------------------------------------------------------------------
const group = (s) => s.replace(/\B(?=(\d{3})+(?!\d))/g, "'");
export const n0 = (v) => group(String(Math.round(Math.abs(v))));
export const n2 = (v) => {
  const [i, d] = Math.abs(v).toFixed(2).split(".");
  return `${group(i)}.${d}`;
};
const minus = (v, s) => (v < 0 && s !== "0" && s !== "0.00" ? "−" : "") + s;
export const nf = (v) => minus(v, n0(v));
export const nf2 = (v) => minus(v, n2(v));
export const pf = (x, d = 1) => (x * 100).toFixed(d).replace(".", ",");
export const sgn = (v) => (v >= 0 ? "+" : "−");
export const money = (v) => `<span class="money num">${nf(v)}</span>`;
export const amount = (v) => `${money(v)} ${base()}`;
export const amount2 = (v) => `<span class="money num">${nf2(v)}</span>`;
export const share = (p) => `${pf(p)} %`;
export const signed = (v, p) =>
  `<span class="delta ${v >= 0 ? "pos" : "neg"} num"><span class="money">${sgn(v)}${n0(v)}</span> ${base()}${p == null ? "" : ` · ${sgn(p)}${pf(Math.abs(p))} %`}</span>`;
export const pctOnly = (p) =>
  p == null ? '<span class="delta new">nouveau</span>' : `<span class="delta ${p >= 0 ? "pos" : "neg"} num">${sgn(p)}${pf(Math.abs(p))} %</span>`;
export const qty = (v) => {
  const s = String(v);
  const [i, d] = s.replace("-", "").split(".");
  const dec = d ? d.replace(/0+$/, "").slice(0, 6) : "";
  return (s.startsWith("-") ? "−" : "") + group(i) + (dec ? `.${dec}` : "");
};

export const COLORS = ["--s1", "--s2", "--s3", "--s4", "--s5", "--s6", "--s7"];
export const cv = (i) => `var(${COLORS[((i % COLORS.length) + COLORS.length) % COLORS.length]})`;
export const monogram = (s) =>
  (s || "?").replace(/[^\p{L}\p{N}\s]/gu, " ").split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join("").toUpperCase() || "?";

// --- annonces et messages ---------------------------------------------------------------------
let liveT = null;
export function announce(msg) {
  clearTimeout(liveT);
  liveT = setTimeout(() => { $("live").textContent = msg; }, 120);
}

let undoFn = null;
let toastT = null;
export function toast(msg, opts = {}) {
  undoFn = opts.undo || null;
  const t = $("toast");
  $("toast-msg").textContent = msg;
  $("toast-undo").hidden = !undoFn;
  t.classList.toggle("error", Boolean(opts.error));
  t.classList.add("show");
  clearTimeout(toastT);
  toastT = setTimeout(() => t.classList.remove("show"), opts.error ? 7000 : 4500);
}

export function initToast(after) {
  $("toast-undo").addEventListener("click", () => {
    if (undoFn) undoFn();
    undoFn = null;
    $("toast").classList.remove("show");
    after();
  });
}

// erreur d'une validation : annulée par l'utilisateur ou refusée par le hub
export function failure(e) {
  return e && e.name === "NotAllowedError" ? "Validation annulée." : (e && e.message) || "Échec";
}

// --- panneau du bas ---------------------------------------------------------------------------
// Chaque type de panneau est une fonction (arg, state) → { title, act?, body, foot? } ; le
// panneau est redessiné à chaque rendu tant qu'il est ouvert.
export const SHEETS = {};
export const SH = { kind: null, arg: null, opener: null, tmp: null };

export function openSheet(kind, arg, tmp = null) {
  const wasOpen = Boolean(SH.kind);
  Object.assign(SH, { kind, arg, tmp, err: "", cad: null });
  if (!wasOpen) SH.opener = document.activeElement;
  document.documentElement.classList.add("sheet-open");
  $("shell").inert = true;
  $("tabbar").inert = true;
  renderSheet();
  setTimeout(() => {
    const s = $("sheet");
    const f = s.querySelector("[data-autofocus]") || s.querySelector(".sheet-body button:not([disabled]), .sheet-body input, .sheet-head button");
    if (f) f.focus({ preventScroll: true });
  }, 80);
}

export function closeSheet(silent = false) {
  if (!SH.kind) return;
  SH.kind = null;
  document.documentElement.classList.remove("sheet-open");
  $("shell").inert = false;
  $("tabbar").inert = false;
  if (!silent && SH.opener && document.contains(SH.opener)) SH.opener.focus({ preventScroll: true });
}

export function renderSheet() {
  if (!SH.kind || !SHEETS[SH.kind]) return;
  const s = SHEETS[SH.kind](SH.arg, SH);
  if (!s) return closeSheet(true);
  fill($("sheet-title"), s.title);
  fill($("sheet-act"), `${s.act || ""}<button class="icon-btn" type="button" data-a="sheet-close" aria-label="Fermer">${ic("close")}</button>`);
  // la saisie en cours (champ actif) n'est pas écrasée
  const body = $("sheet-body");
  const active = document.activeElement;
  const keep = active && body.contains(active) && active.tagName === "INPUT" && active.type !== "checkbox" ? active.id : null;
  const caret = keep ? [active.value, active.selectionStart] : null;
  fill(body, s.body);
  if (keep && $(keep)) {
    const n = $(keep);
    n.value = caret[0];
    n.focus({ preventScroll: true });
    try { n.setSelectionRange(caret[1], caret[1]); } catch { /* type sans curseur */ }
  }
  fill($("sheet-foot"), s.foot || "");
}

// --- préférences de l'appareil -----------------------------------------------------------------
export function pref(key, fallback) {
  try {
    const v = localStorage.getItem(`hub.${key}`);
    return v == null ? fallback : JSON.parse(v);
  } catch {
    return fallback;
  }
}

export function setPref(key, value) {
  try {
    localStorage.setItem(`hub.${key}`, JSON.stringify(value));
  } catch {
    /* navigation privée : rien à retenir */
  }
}

export function applyTheme(theme) {
  if (theme === "light" || theme === "dark") document.documentElement.dataset.theme = theme;
  else delete document.documentElement.dataset.theme;
}
