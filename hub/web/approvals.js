// Double Sas dans l'app (L3-04), au cœur de la coquille : les propositions en attente de tous
// les domaines se valident par lot avec un seul Face ID. Le défi WebAuthn porte l'empreinte du
// lot (révisions et empreintes comprises) ; une proposition qui a changé entre-temps revient avec
// une nouvelle révision, jamais appliquée.
// Le module de cartes d'un domaine (manifeste `cards`) peut exporter detail(p) (ce qui se déplie
// sous la carte) et prepare(ids) (remplace des cartes retouchées avant le Face ID).
import { chosen, tick, ticked } from "./picks.js";
import { api, store } from "./store.js";
import { SHEETS, closeSheet, esc, failure, ic, openSheet, toast } from "./ui.js";
import { credentialJSON, requestOptions } from "./webauthn.js";

const BATCH = 50; // plafond de /approvals/challenge

export const pendingPath = "/proposals?status=pending";

const CARDS = new Map(); // domaine → son module de cartes
const choices = new Map(); // coches posées ou retirées à la main (picks.js)
let busy = false;

export function addCards(domain, module) {
  CARDS.set(domain, module);
}

export function pendingCount() {
  const pe = store.data(pendingPath);
  return pe ? pe.items.length : 0;
}

// un Face ID par tranche de 50 ; renvoie les résultats de chaque proposition
export async function approve(ids, action = "accept") {
  const results = [];
  for (let i = 0; i < ids.length; i += BATCH) {
    const part = ids.slice(i, i + BATCH);
    const ch = await api("/approvals/challenge", { proposal_ids: part, action });
    const cred = await navigator.credentials.get({ publicKey: requestOptions(ch.options) });
    const out = await api("/proposals/accept", {
      proposal_ids: part, challenge_id: ch.challenge_id, assertion: credentialJSON(cred),
    });
    results.push(...out.results);
  }
  return results;
}

// texte du résultat d'un lot, et s'il contient un échec
export function outcome(results) {
  const applied = results.filter((r) => r.status === "applied").length;
  const changed = results.filter((r) => r.status === "superseded" || r.status === "pending").length;
  const failed = results.length - applied - changed;
  const parts = [`${applied} appliquée${applied > 1 ? "s" : ""}`];
  if (changed) parts.push(`${changed} ont changé entre-temps : relis-les`);
  if (failed) {
    const p = results.find((r) => r.problem)?.problem;
    parts.push(`${failed} en échec${p ? ` (${p.detail || p.title})` : ""}`);
  }
  return [parts.join(", "), failed > 0 || changed > 0];
}

function by(principal) {
  if (principal.startsWith("system")) return "proposée par le hub";
  if (principal.startsWith("token:")) return "proposée par un assistant · à cocher toi-même";
  return "proposée depuis l'app";
}

const pending = () => store.data(pendingPath)?.items ?? [];
const sign = (ids) => `${ic("faceid")}${busy ? "Validation…" : ids.length ? `Valider ${ids.length} avec Face ID` : "Rien de coché"}`;

const capital = (s) => s.charAt(0).toUpperCase() + s.slice(1);

function detail(p) {
  const m = CARDS.get(p.domain);
  return m && m.detail ? m.detail(p) : "";
}

SHEETS.props = () => {
  const list = pending();
  if (!list.length && !busy) return null;
  const ids = chosen(list, choices);
  const several = new Set(list.map((p) => p.domain)).size > 1;
  return {
    title: "À valider",
    body: `<p class="hint">Rien ne change sans ton Face ID. Il signe ce qui est coché ici, rien d'autre.</p>` + list.map((p) => `
      <div class="prop"><input type="checkbox" id="prop-${esc(p.id)}" data-prop="${esc(p.id)}" ${ticked(p, choices) ? "checked" : ""}>
        <label for="prop-${esc(p.id)}"><b>${esc(p.preview.summary)}</b><span><span>${several ? `${esc(capital(p.domain))} · ` : ""}${p.revision > 1 ? `révision ${p.revision} · a changé, relis-la` : by(p.created_by)}</span>${p.reason && p.created_by.startsWith("token:") ? `<span>« ${esc(p.reason)} »</span>` : ""}</span></label>
        <button class="reject" type="button" data-a="prop-reject" data-v="${esc(p.id)}">Refuser</button></div>${detail(p)}`).join(""),
    foot: `<button class="primary" type="button" data-a="props-ok" ${ids.length && !busy ? "" : "disabled"}>${sign(ids)}</button>`,
  };
};

// la carte « À valider » en tête de l'accueil : les premières propositions à cocher, et un
// Face ID qui ne signe qu'elles ; « Tout voir » ouvre le panneau (les autres, détails, refus)
const INLINE = 3;
export function card() {
  const list = pending();
  if (!list.length) return "";
  const ids = chosen(list, choices, INLINE);
  const rest = list.length - INLINE;
  const rows = list.slice(0, INLINE).map((p) => `
      <div class="prop"><input type="checkbox" id="hp-${esc(p.id)}" data-prop="${esc(p.id)}" ${ticked(p, choices) ? "checked" : ""}>
        <label for="hp-${esc(p.id)}"><b>${esc(p.preview.summary)}</b><span><span>${esc(capital(p.domain))} · ${p.revision > 1 ? "a changé, relis-la" : by(p.created_by)}</span></span></label></div>`).join("");
  const others = rest > 0 ? `<p class="hint">${rest} autre${rest > 1 ? "s" : ""} dans « Tout voir » : ce Face ID ne ${rest > 1 ? "les" : "la"} signe pas.</p>` : "";
  const more = list.length > INLINE ? `<button class="link" type="button" data-a="props">Tout voir (${list.length})</button>` : `<button class="link" type="button" data-a="props">Détails</button>`;
  return `<section class="card" aria-labelledby="t-approve">
      <div class="section-head"><h2 class="section-title" id="t-approve">À valider</h2>${more}</div>${rows}
      <button class="primary" type="button" data-a="props-ok" data-v="home" ${ids.length && !busy ? "" : "disabled"}>${sign(ids)}</button>${others}
    </section>`;
}

document.addEventListener("change", (e) => {
  const id = e.target.dataset && e.target.dataset.prop;
  if (!id) return;
  const p = pending().find((x) => x.id === id);
  if (p) tick(p, choices, e.target.checked);
  store.notify();
});

async function validate(ids) {
  busy = true;
  store.notify();
  try {
    for (const m of CARDS.values()) if (m.prepare) ids = await m.prepare(ids);
    const [text, bad] = outcome(await approve(ids));
    toast(text, { error: bad });
    if (!bad) closeSheet();
  } catch (e) {
    toast(failure(e), { error: true });
  } finally {
    busy = false;
    window.dispatchEvent(new Event("hub:changed"));
    store.invalidate();
  }
}

export const actions = {
  props: () => openSheet("props"),
  // le bouton de l'accueil ne signe que ses lignes ; celui du panneau, tout ce qui y est coché
  "props-ok": (where) => {
    const ids = chosen(pending(), choices, where === "home" ? INLINE : undefined);
    if (ids.length) validate(ids);
  },
  "prop-reject": async (id) => {
    try {
      await api(`/proposals/${id}/reject`, {});
      toast("Proposition refusée.");
    } catch (e) {
      toast(e.message, { error: true });
    }
    store.invalidate();
  },
};
