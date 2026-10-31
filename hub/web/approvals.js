// Double Sas dans l'app (L3-04), au cœur de la coquille : les propositions en attente de tous
// les domaines se valident par lot avec un seul Face ID. Le défi WebAuthn porte l'empreinte du
// lot (révisions et empreintes comprises) ; une proposition qui a changé entre-temps revient avec
// une nouvelle révision, jamais appliquée.
// Le module de cartes d'un domaine (manifeste `cards`) peut exporter detail(p) (ce qui se déplie
// sous la carte) et prepare(ids) (remplace des cartes retouchées avant le Face ID).
import { api, store } from "./store.js";
import { SHEETS, closeSheet, esc, failure, ic, openSheet, toast } from "./ui.js";
import { credentialJSON, requestOptions } from "./webauthn.js";

const BATCH = 50; // plafond de /approvals/challenge

export const pendingPath = "/proposals?status=pending";

const CARDS = new Map(); // domaine → son module de cartes
const unchecked = new Set(); // propositions décochées dans le panneau « À valider »
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
  if (principal.startsWith("token:")) return "proposée par un assistant";
  return "proposée depuis l'app";
}

const capital = (s) => s.charAt(0).toUpperCase() + s.slice(1);

function detail(p) {
  const m = CARDS.get(p.domain);
  return m && m.detail ? m.detail(p) : "";
}

SHEETS.props = () => {
  const pe = store.data(pendingPath);
  const list = pe ? pe.items : [];
  if (!list.length && !busy) return null;
  const ids = list.filter((p) => !unchecked.has(p.id)).map((p) => p.id);
  const several = new Set(list.map((p) => p.domain)).size > 1;
  return {
    title: "À valider",
    body: `<p class="hint">Rien ne change sans ton Face ID. Décoche ce que tu veux garder pour plus tard.</p>` + list.map((p) => `
      <div class="prop"><input type="checkbox" id="prop-${esc(p.id)}" data-prop="${esc(p.id)}" ${unchecked.has(p.id) ? "" : "checked"}>
        <label for="prop-${esc(p.id)}"><b>${esc(p.preview.summary)}</b><span><span>${several ? `${esc(capital(p.domain))} · ` : ""}${p.revision > 1 ? `révision ${p.revision} · a changé, relis-la` : by(p.created_by)}</span>${p.reason && p.created_by.startsWith("token:") ? `<span>« ${esc(p.reason)} »</span>` : ""}</span></label>
        <button class="reject" type="button" data-a="prop-reject" data-v="${esc(p.id)}">Refuser</button></div>${detail(p)}`).join(""),
    foot: `<button class="primary" type="button" data-a="props-ok" ${ids.length && !busy ? "" : "disabled"}>${ic("faceid")}${busy ? "Validation…" : ids.length ? `Valider ${ids.length} avec Face ID` : "Rien de coché"}</button>`,
  };
};

// la carte « À valider » en tête de l'accueil : les premières propositions à cocher, et le
// Face ID du lot sans ouvrir le panneau ; « Tout voir » l'ouvre (détails, refus)
const INLINE = 3;
export function card() {
  const pe = store.data(pendingPath);
  const list = pe ? pe.items : [];
  if (!list.length) return "";
  const ids = list.filter((p) => !unchecked.has(p.id)).map((p) => p.id);
  const rows = list.slice(0, INLINE).map((p) => `
      <div class="prop"><input type="checkbox" id="hp-${esc(p.id)}" data-prop="${esc(p.id)}" ${unchecked.has(p.id) ? "" : "checked"}>
        <label for="hp-${esc(p.id)}"><b>${esc(p.preview.summary)}</b><span><span>${esc(capital(p.domain))} · ${p.revision > 1 ? "a changé, relis-la" : by(p.created_by)}</span></span></label></div>`).join("");
  const more = list.length > INLINE ? `<button class="link" type="button" data-a="props">Tout voir (${list.length})</button>` : `<button class="link" type="button" data-a="props">Détails</button>`;
  return `<section class="card" aria-labelledby="t-approve">
      <div class="section-head"><h2 class="section-title" id="t-approve">À valider</h2>${more}</div>${rows}
      <button class="primary" type="button" data-a="props-ok" ${ids.length && !busy ? "" : "disabled"}>${ic("faceid")}${busy ? "Validation…" : ids.length ? `Valider ${ids.length} avec Face ID` : "Rien de coché"}</button>
    </section>`;
}

document.addEventListener("change", (e) => {
  const id = e.target.dataset && e.target.dataset.prop;
  if (!id) return;
  if (e.target.checked) unchecked.delete(id);
  else unchecked.add(id);
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
  "props-ok": () => {
    const pe = store.data(pendingPath);
    const ids = (pe ? pe.items : []).filter((p) => !unchecked.has(p.id)).map((p) => p.id);
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
