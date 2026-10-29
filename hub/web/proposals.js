// Double Sas dans l'app (L3-04) : les propositions en attente se valident par lot avec un seul
// Face ID. Le défi WebAuthn porte l'empreinte du lot (révisions et empreintes comprises) ; une
// proposition qui a changé entre-temps revient avec une nouvelle révision, jamais appliquée.
import { api, store } from "./store.js";
import { credentialJSON, requestOptions } from "./webauthn.js";

const BATCH = 50; // plafond de /approvals/challenge

export const pendingPath = "/proposals?status=pending";

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

export function propose(kind, params, bundle) {
  return api("/proposals", { domain: "finance", kind, params, bundle_id: bundle });
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

// propose puis valide d'un seul Face ID ; le registre a changé : tout se relit
export async function proposeAndApprove(items) {
  const bundle = `app-${Date.now()}`;
  const ids = [];
  for (const [kind, params] of items) ids.push((await propose(kind, params, bundle)).id);
  try {
    return await approve(ids);
  } catch (e) {
    // Face ID annulé : les cartes créées ici ne restent pas en attente
    if (e.name === "NotAllowedError") await Promise.allSettled(ids.map((id) => api(`/proposals/${id}/reject`, {})));
    throw e;
  } finally {
    window.dispatchEvent(new Event("hub:changed"));
    store.invalidate();
  }
}
