// Module du domaine factice des tests (chantier S5) : un onglet, une rubrique et des cartes,
// montés par la coquille sans qu'une ligne de shell.js ou d'index.html change.
import { store } from "./store.js";
import { fill } from "./ui.js";

const $ = (id) => document.getElementById(id);
let started = 0;

export function init() {
  started += 1;
}

export function render() {
  const s = store.use("/demo/summary");
  fill($("demo-body"), `<section class="card"><h2 class="section-title">Éléments de démo</h2>
    <p class="note">${s.data ? s.data.count : "…"} élément(s) dans le domaine factice des tests, monté ${started} fois.</p></section>`);
}

export const todoCount = () => 2;
export const todoLabel = "à voir";

export function rubric(id) {
  fill($(`rub-${id}`), '<h2 class="section-title">Réglages de démo</h2><p class="note">Une rubrique venue du manifeste.</p>');
}

export const rubricStatus = () => ["prête", "ok"];

export const actions = {};
