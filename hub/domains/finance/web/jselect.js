// Journal : sélection multiple. Un appui long sur une écriture ouvre la sélection ; toucher
// d'autres lignes les ajoute ; la barre du bas classe tout d'un coup, sous une seule validation.
// Seules les écritures de mouvement se sélectionnent : un solde d'ouverture ne se classe pas.
import { SH, SHEETS, announce, closeSheet, esc, failure, fill, ic, openSheet, renderSheet, toast } from "../../ui.js";
import { outcome, proposeAndApprove } from "./proposals.js";
import { store } from "../../store.js";

const picked = new Set();
let D = null; // { items(), grid(cats, direction, current, action), cats(), reload() }, donné par journal.js
let skip = false; // le clic qui suit l'appui long ne doit pas rouvrir la ligne
const HOLD = 480;

export const selecting = () => picked.size > 0;
// le clic d'une ligne passe par ici : vrai s'il a servi la sélection
export function tap(id) {
  if (skip) { skip = false; return true; }
  if (!selecting()) return false;
  toggle(id);
  return true;
}
function toggle(id) {
  const e = D.items().find((x) => x.id === id);
  if (!e || e.kind !== "movement") return toast("Cette écriture ne se classe pas");
  if (picked.has(id)) picked.delete(id);
  else picked.add(id);
  paint();
  announce(`${picked.size} sélectionnée${picked.size > 1 ? "s" : ""}`);
}
export function clear() {
  picked.clear();
  paint();
}

// après chaque rendu du journal : l'état des lignes et la barre
export function paint() {
  const view = document.getElementById("journal");
  if (!view) return;
  const known = new Set(D.items().map((e) => e.id));
  for (const id of [...picked]) if (!known.has(id)) picked.delete(id);
  for (const row of view.querySelectorAll('#jBody [data-a="tx"]')) {
    const on = picked.has(row.dataset.v);
    row.classList.toggle("picked", on);
    if (selecting()) row.setAttribute("aria-pressed", String(on));
    else row.removeAttribute("aria-pressed");
  }
  let bar = document.getElementById("jsel");
  if (!selecting()) { if (bar) bar.remove(); return; }
  if (!bar) {
    bar = document.createElement("div");
    bar.id = "jsel";
    bar.className = "selbar";
    bar.setAttribute("role", "toolbar");
    bar.setAttribute("aria-label", "Écritures sélectionnées");
    view.append(bar);
  }
  fill(bar, `<button class="icon-btn" type="button" data-a="jsel-x" aria-label="Quitter la sélection">${ic("close")}</button>
    <b>${picked.size} sélectionnée${picked.size > 1 ? "s" : ""}</b>
    <button class="primary small" type="button" data-a="jsel-cat" aria-haspopup="dialog">Classer</button>`);
}

SHEETS.jselcat = (_, sh) => {
  const es = D.items().filter((e) => picked.has(e.id));
  const direction = es.length && es.every((e) => e.amount.minor > 0) ? "credit" : "debit";
  return {
    title: `Classer ${es.length} écriture${es.length > 1 ? "s" : ""}`,
    body: `${D.grid(D.cats(), direction, sh.tmp, "jsel-pick")}${sh.err ? `<div class="err" role="alert">${esc(sh.err)}</div>` : ""}`,
    foot: `<button class="primary" type="button" data-a="jsel-ok" ${sh.tmp && !sh.busy ? "" : "disabled"}>${ic("faceid")}${sh.busy ? "Validation…" : "Enregistrer avec Face ID"}</button>`,
  };
};

export const actions = {
  "jsel-x": clear,
  "jsel-cat": () => { openSheet("jselcat"); SH.tmp = ""; renderSheet(); },
  "jsel-pick": (v) => { SH.tmp = v; renderSheet(); },
  "jsel-ok": async () => {
    const cat = SH.tmp, ids = [...picked];
    SH.busy = true;
    SH.err = "";
    renderSheet();
    try {
      const [text, bad] = outcome(await proposeAndApprove(ids.map((id) => ["recategorize", { entry_id: id, category_id: cat }])));
      if (bad) SH.err = text;
      else {
        closeSheet();
        for (const id of ids) store.cache.delete(`/finance/entries/${encodeURIComponent(id)}`);
        picked.clear();
        D.reload();
        toast(`${ids.length} écriture${ids.length > 1 ? "s" : ""} classée${ids.length > 1 ? "s" : ""} en ${D.cats()[cat]?.name || cat}`);
      }
    } catch (err) {
      SH.err = failure(err);
    } finally {
      SH.busy = false;
      if (SH.kind) renderSheet();
    }
  },
};

export function init(deps) {
  D = deps;
  let timer = null, at = null;
  const stop = () => { clearTimeout(timer); timer = null; };
  document.addEventListener("pointerdown", (e) => {
    const row = e.target.closest ? e.target.closest('#jBody [data-a="tx"]') : null;
    if (!row || selecting()) return;
    at = [e.clientX, e.clientY];
    timer = setTimeout(() => {
      timer = null;
      skip = true;
      setTimeout(() => { skip = false; }, 700);
      toggle(row.dataset.v);
      if (navigator.vibrate) navigator.vibrate(10);
    }, HOLD);
  });
  document.addEventListener("pointermove", (e) => { if (timer && at && Math.hypot(e.clientX - at[0], e.clientY - at[1]) > 8) stop(); });
  for (const ev of ["pointerup", "pointercancel", "scroll"]) document.addEventListener(ev, stop, { passive: true, capture: true });
  // l'appui long ne doit pas ouvrir le menu du navigateur sur la ligne
  document.addEventListener("contextmenu", (e) => { if (e.target.closest && e.target.closest('#jBody [data-a="tx"]')) e.preventDefault(); });
}
