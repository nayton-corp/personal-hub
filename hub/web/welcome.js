// Premiers pas (chantier « hub générique », G6) : sur l'accueil, ce qui reste à faire après
// l'installation, lu dans les données et non retenu à part. Passkey de secours, profil, règles
// de catégorisation, première connexion, premier compte ; la carte disparaît quand tout est fait,
// ou quand on la masque.
import { el } from "./format.js";
import { approve, propose } from "./proposals.js";
import { store } from "./store.js";

const $ = (id) => document.getElementById(id);
const HIDDEN_KEY = "hub.welcome";
const PATHS = {
  passkeys: "/auth/passkeys",
  profile: "/profile",
  packs: "/finance/rules/packs",
  connections: "/collectors/connections",
  accounts: "/finance/accounts",
};
let busy = false;

function hidden() {
  try {
    return localStorage.getItem(HIDDEN_KEY) === "hidden";
  } catch {
    return false;
  }
}

function hide() {
  try {
    localStorage.setItem(HIDDEN_KEY, "hidden");
  } catch {
    /* navigation privée : la carte reviendra */
  }
  $("c-welcome").hidden = true;
}

function say(text, error = false) {
  const n = $("welcome-msg");
  n.textContent = text || "";
  n.classList.toggle("error", error);
}

// ouvre Sources et amène le formulaire voulu à l'écran
function goSources(target) {
  store.set({ tab: "sources" });
  requestAnimationFrame(() => requestAnimationFrame(() => {
    const node = $(target);
    if (!node) return;
    if (node.tagName === "BUTTON") node.click();
    else node.scrollIntoView({ behavior: "smooth", block: "start" });
  }));
}

async function installPacks(names) {
  if (busy) return;
  busy = true;
  say("");
  try {
    const ids = [];
    for (const name of names) ids.push((await propose("install_pack", { name })).id);
    const results = await approve(ids);
    const failed = results.filter((r) => r.status !== "applied");
    if (failed.length) {
      const p = failed[0].problem;
      throw new Error((p && (p.detail || p.title)) || "Pack non installé : relis la proposition dans l'accueil.");
    }
    say("Règles installées : les écritures sans catégorie viennent d'être reprises.");
  } catch (e) {
    say(e.name === "NotAllowedError" ? "Validation annulée." : e.message, true);
  } finally {
    busy = false;
    window.dispatchEvent(new Event("hub:changed"));
    store.invalidate();
  }
}

// fait dès qu'une règle est active : une base reprise d'avant les packs garde les siennes
function packStep(p) {
  const labels = Object.fromEntries(p.items.map((i) => [i.name, i.label]));
  const missing = p.suggested.filter((n) => !p.items.some((i) => i.name === n && i.installed));
  const names = (missing.length ? missing : p.suggested).map((n) => labels[n] || n).join(" et ");
  const sub = p.active_rules > 0
    ? `${p.active_rules} règles actives`
    : `aucune règle : ${names} classe${missing.length > 1 ? "nt" : ""} les achats courants`;
  return [p.active_rules > 0, "Règles de catégorisation", sub,
    missing.length ? ["Installer", () => installPacks(missing)] : null];
}

export function welcomeCard() {
  const card = $("c-welcome");
  if (hidden()) {
    card.hidden = true;
    return;
  }
  const data = Object.fromEntries(Object.entries(PATHS).map(([k, v]) => [k, store.data(v)]));
  if (Object.values(data).some((d) => d === null)) {
    card.hidden = true; // tout arrive en même temps ; une route en erreur cache la carte
    return;
  }
  const { passkeys, profile, packs, connections, accounts } = data;
  const steps = [
    [passkeys.items.length >= 2, "Passkey de secours", "si ce téléphone se perd",
      ["Ajouter", () => goSources("form-backup")]],
    [Boolean(profile.display_name), "Profil", `prénom de l'assistant, pays (${profile.country})`,
      ["Remplir", () => goSources("form-profile")]],
    packStep(packs),
    [connections.items.length > 0, "Première connexion", "banque, plateforme ou cours",
      ["Ajouter", () => goSources("conn-add")]],
    [accounts.items.length > 0, "Premier compte", "créé avec ses premiers relevés",
      ["Voir", () => goSources("acct-pending")]],
  ];
  const left = steps.filter(([done]) => !done).length;
  card.hidden = left === 0;
  if (!left) return;
  $("welcome-sub").textContent = `${steps.length - left} sur ${steps.length} fait${steps.length - left > 1 ? "s" : ""}`;
  const list = $("welcome-list");
  list.replaceChildren();
  steps.forEach(([done, title, sub, action], i) => {
    const r = el("div", "row");
    r.append(el("div", done ? "av g" : "av", done ? "✓" : String(i + 1)));
    const n = el("div", "n");
    n.append(el("b", done ? "muted" : "", title), el("span", "", sub));
    const v = el("div", "v");
    if (!done && action) {
      const b = el("button", "link", action[0]);
      b.type = "button";
      b.disabled = busy;
      b.addEventListener("click", action[1]);
      v.append(b);
    }
    r.append(n, v);
    list.append(r);
  });
}

export function initWelcome() {
  $("welcome-hide").addEventListener("click", hide);
}
