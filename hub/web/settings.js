// Sources et réglages : connexions et comptes en attente (connections.js, formulaires construits
// à l'ouverture), comptes avec leur fraîcheur et leurs réglages (accounts.js), affichage de cet
// appareil. Profil, passkeys et état du hub sont remplis par app.js.
import { accountsList } from "./accounts.js";
import { accountsCard, connectionsCard } from "./connections.js";
import { fill, pref } from "./ui.js";

const $ = (id) => document.getElementById(id);
const THEMES = [["system", "Système"], ["light", "Clair"], ["dark", "Sombre"]];

export function render() {
  connectionsCard();
  accountsCard();
  accountsList();
  const hide = pref("hide", false), theme = pref("theme", "system");
  fill($("display-rows"), `
    <div class="setrow"><span id="hide-lbl">Masquer les montants<small>Floute les montants sur tous les écrans de cet appareil</small></span><button class="switch" type="button" role="switch" aria-checked="${hide}" aria-labelledby="hide-lbl" data-a="hide"></button></div>
    <div class="setrow"><span>Thème</span><div class="seg small" role="group" aria-label="Thème">${THEMES.map(([k, l]) => `<button type="button" data-a="theme" data-v="${k}" aria-pressed="${theme === k}">${l}</button>`).join("")}</div></div>`);
}

export const actions = {};
