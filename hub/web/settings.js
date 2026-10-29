// Sources et réglages : connexions et comptes en attente (connections.js, formulaires construits
// à l'ouverture), fraîcheur des relevés, affichage de cet appareil. Profil, passkeys et état du
// hub sont remplis par app.js.
import { accountsCard, connectionsCard } from "./connections.js";
import { date, daysSince } from "./format.js";
import { store } from "./store.js";
import { esc, fill, ibox, ic, pref } from "./ui.js";

const $ = (id) => document.getElementById(id);
const STALE_DAYS = 45;
const THEMES = [["system", "Système"], ["light", "Clair"], ["dark", "Sombre"]];

export function render() {
  connectionsCard();
  accountsCard();
  const f = store.use("/finance/freshness");
  if (f.status !== "ok") fill($("fresh-list"), `<div class="empty">${f.status === "error" ? `Impossible de charger : ${esc(f.error.message)}` : "Chargement…"}</div>`);
  else if (!f.data.items.length) fill($("fresh-list"), '<div class="empty">Aucun compte pour l\'instant.</div>');
  else {
    fill($("fresh-list"), f.data.items.map((a) => {
      const clbd = a.last_clbd && a.last_clbd.on_date;
      const age = daysSince(clbd);
      const stale = age == null || age > STALE_DAYS;
      return `<div class="row">${ibox(ic(stale ? "clock" : "check"), stale ? "var(--s3)" : "var(--pos)", "sm")}
        <span class="row-main"><span class="row-title">${esc(a.name)}</span><span class="row-sub">${clbd ? `relevé du ${date(clbd)}${a.last_import ? ` · importé le ${date(a.last_import.slice(0, 10))}` : ""}` : "aucun relevé importé"}</span></span>
        <span class="pill ${stale ? "warn" : "ok"}">${age == null ? "—" : `${age} j`}</span></div>`;
    }).join(""));
  }
  const hide = pref("hide", false), theme = pref("theme", "system");
  fill($("display-rows"), `
    <div class="setrow"><span id="hide-lbl">Masquer les montants<small>Floute les montants sur tous les écrans de cet appareil</small></span><button class="switch" type="button" role="switch" aria-checked="${hide}" aria-labelledby="hide-lbl" data-a="hide"></button></div>
    <div class="setrow"><span>Thème</span><div class="seg small" role="group" aria-label="Thème">${THEMES.map(([k, l]) => `<button type="button" data-a="theme" data-v="${k}" aria-pressed="${theme === k}">${l}</button>`).join("")}</div></div>`);
}

export const actions = {};
