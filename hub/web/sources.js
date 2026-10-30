// Sources et réglages, page de la coquille (chantier S5) : la liste groupée des rubriques, puis
// une page par rubrique (son entrée d'historique, le geste retour revient à la liste). Les
// rubriques des domaines viennent de leurs manifestes et se dessinent dans leur module ; celles
// de la coquille (affichage, profil, sécurité, état du hub) sont ici et dans app.js. Chaque
// ligne dit son état en mots, la teinte ne fait que doubler.
import { api, store } from "./store.js";
import { SHEETS, closeSheet, esc, failure, fill, ibox, ic, openSheet, pref, toast } from "./ui.js";

const $ = (id) => document.getElementById(id);
const P = store.params;
const THEMES = [["system", "Système"], ["light", "Clair"], ["dark", "Sombre"]];
const HUB = "Hub"; // les rubriques de la coquille d'abord, puis une section par domaine
const OWN = [
  { id: "profile", label: "Profil", icon: "user", group: HUB },
  { id: "display", label: "Affichage", icon: "eye", group: HUB },
  { id: "security", label: "Sécurité", icon: "faceid", group: HUB },
  { id: "health", label: "État du hub", icon: "info", group: HUB },
];
const RUBRICS = []; // { id, label, icon, group, m } ; m absent : rubrique de la coquille
let ordered = null;

export function add(sections) {
  RUBRICS.push(...sections);
  ordered = null;
}

// la section de la coquille, puis celle de chaque domaine, dans l'ordre des domaines
function groups() {
  if (ordered) return ordered;
  const all = [...OWN, ...RUBRICS];
  const names = all.map((r) => r.group);
  ordered = [...new Set(names)].map((g) => [g, all.filter((r) => r.group === g)]).filter(([, rs]) => rs.length);
  return ordered;
}

const find = (k) => RUBRICS.find((r) => r.id === k) || OWN.find((r) => r.id === k);
export const rubricLabel = (k) => (find(k) || {}).label || "Sources et réglages";

// [texte, ton] de chaque rubrique ; null tant que la donnée n'est pas là
function status(r) {
  if (r.m) return r.m.rubricStatus ? r.m.rubricStatus(r.id) : null;
  if (r.id === "display") return [{ system: "Système", light: "Clair", dark: "Sombre" }[pref("theme", "system")] || "Système", ""];
  if (r.id === "security") {
    const x = store.data("/auth/passkeys");
    if (!x) return null;
    return x.items.length < 2 ? ["1 seule passkey", "warn"] : [`${x.items.length} passkeys`, "ok"];
  }
  if (r.id === "health") {
    const h = store.data("/health");
    return h ? [h.status === "ok" ? `v${h.version}` : "à vérifier", h.status === "ok" ? "ok" : "warn"] : null;
  }
  return null;
}

function rubrics() {
  return groups().map(([g, rs]) => `<section class="card rub" aria-labelledby="rg-${esc(g)}"><h2 class="grp-title" id="rg-${esc(g)}">${esc(g)}</h2>
    ${rs.map((r) => {
      const st = status(r);
      return `<button class="trow press" type="button" data-a="rubric" data-v="${esc(r.id)}">${ibox(ic(r.icon), "var(--accent)", "sm")}<span class="t">${esc(r.label)}</span>
        <span class="row-num">${st ? `<span class="pill ${st[1]}">${st[1] === "warn" ? ic("alert") : ""}${esc(st[0])}</span>` : ""}${ic("chev", "chev-r")}</span></button>`;
    }).join("")}</section>`).join("") + `<section class="card"><button class="secondary danger" type="button" data-a="logout">Se déconnecter</button></section>`;
}

// une rubrique de domaine sans balisage dans index.html reçoit une carte vide, que son module
// remplit
function cardFor(r) {
  if (document.querySelector(`#sources [data-rubric="${CSS.escape(r.id)}"]`)) return;
  const s = Object.assign(document.createElement("section"), { className: "card", id: `rub-${r.id}` });
  s.dataset.rubric = r.id;
  $("sources").querySelector(".endspace").before(s);
}

export function render() {
  const r = P.rubric;
  $("t-sources").textContent = rubricLabel(r);
  const found = r && find(r);
  if (found && found.m) cardFor(found);
  for (const n of document.querySelectorAll("#sources [data-rubric]")) {
    // les éditeurs gardent leur propre état hidden : seule la rubrique hors page les cache
    n.classList.toggle("off-rubric", n.dataset.rubric !== r);
  }
  const list = $("rubrics");
  list.hidden = Boolean(r);
  if (!r) {
    store.use("/auth/passkeys");
    store.use("/health");
    fill(list, rubrics());
    return;
  }
  if (found && found.m) found.m.rubric(r);
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
