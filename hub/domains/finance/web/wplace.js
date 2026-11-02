// Patrimoine : les soldes qu'aucune opération connue n'explique (le rapprochement,
// docs/finance-politique.md). Une ligne sous le grand chiffre, comme « Fin de courbe estimée »,
// ouvre la liste chiffrée : compte, actif, montant et cause. Rien n'est caché ni compté en silence.
// Tout vient de /finance/breaks, en centimes.
import { SHEETS, amount, closeSheet, esc, ic, openSheet } from "../../ui.js";
import { store } from "../../store.js";
import { date } from "../../format.js";
import { go } from "../../shell.js";
import { units } from "./perf.js";

export const breaksPath = "/finance/breaks";

const NAME = {
  "unexplained+": (s) => `${s} sans historique d'achat`,
  "unexplained-": (s) => `${s} : des sorties que l'historique ne montre pas`,
  sent_outside: (s) => `${s} envoyés vers un portefeuille non suivi`,
  arrived_outside: (s) => `${s} arrivés d'un portefeuille non suivi`,
  no_price: (s) => `${s} sans cours`,
  stale_price: (s) => `Cours ancien : ${s}`,
};
const CAUSE = {
  no_history: "aucun achat ni arrivée connus (souvent un historique que le hub n'a pas pu lire)",
  missing_out: "une sortie n'a pas été lue",
  untracked_wallet: "l'autre côté est un portefeuille que le hub ne suit pas",
  no_price: "aucun cours connu, hors du patrimoine",
  stale: "dernier cours trop ancien",
};
const key = (b) => (b.kind === "unexplained" ? `unexplained${Number(b.quantity) >= 0 ? "+" : "-"}` : b.kind);
const worth = (b) => (b.value ? Math.abs(units(b.value)) : 0);

function itemsFor(accs) {
  const r = store.use(breaksPath).data;
  if (!r || !r.items.length) return [];
  return accs ? r.items.filter((b) => accs.has(b.account_id)) : r.items;
}
let shown = null; // les comptes de la ligne affichée, pour la liste

// la ligne d'avertissement sous le grand chiffre, pour les comptes de la sélection
export function breaksLine(sel) {
  shown = new Set((sel || []).map((l) => l.acc));
  const items = itemsFor(shown);
  if (!items.length) return "";
  const total = items.reduce((t, b) => t + worth(b), 0);
  return `<button class="warnline" type="button" data-a="w-brk"><span>${ic("alert")}</span><span>${items.length} solde${items.length > 1 ? "s" : ""} non expliqué${items.length > 1 ? "s" : ""} · ${amount(total)}</span></button>`;
}

SHEETS.brk = () => {
  const items = itemsFor(shown);
  if (!items.length) return { title: "Tout est expliqué", body: '<p class="note">Chaque solde vient d\'une opération connue.</p>' };
  return {
    title: "Soldes non expliqués",
    body: `<p class="note">Ces montants ne viennent d'aucune opération connue. Ils restent hors du gain jusqu'à ce que l'historique manquant soit importé.</p>
      <div class="list">${items.map((b) => `<div class="row row2"><span class="row-main"><span class="row-title">${esc(NAME[key(b)](b.symbol))}</span><span class="row-sub">${esc(b.account)} · depuis le ${date(b.since)} · ${esc(CAUSE[b.cause] || "")}</span></span>
        <span class="row-num"><span class="row-val num">${b.value ? amount(worth(b)) : "—"}</span></span></div>`).join("")}</div>`,
    foot: '<button class="primary" type="button" data-a="w-brk-conn">Ouvrir les connexions</button>',
  };
};

export const actions = {
  "w-brk": () => openSheet("brk"),
  "w-brk-conn": () => { closeSheet(true); go("sources", { rubric: "conn" }); },
};
