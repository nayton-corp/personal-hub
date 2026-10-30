// Les cartes de la finance (manifeste `cards`) : créer une proposition du domaine, la valider
// aussitôt, et la carte « plusieurs écritures, une catégorie » dont chaque écriture se décoche
// dans « À valider » (approvals.js).
import { approve, pendingPath } from "../../approvals.js";
import { date } from "../../format.js";
import { api, store } from "../../store.js";
import { esc, n2 } from "../../ui.js";

export { approve, outcome } from "../../approvals.js";

const dropped = new Map(); // carte à plusieurs écritures → écritures décochées

export function propose(kind, params, bundle) {
  return api("/proposals", { domain: "finance", kind, params, bundle_id: bundle });
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

// la liste des écritures se déplie sous la carte, chaque écriture se décoche
const capital = (s) => s.charAt(0).toUpperCase() + s.slice(1);
export function detail(p) {
  if (p.kind !== "categorize_entries") return "";
  const off = dropped.get(p.id) || new Set();
  const list = p.preview.details.entries || [];
  return `<details class="prop-more"${off.size ? " open" : ""}><summary>Voir les ${list.length} écritures${off.size ? ` · ${off.size} retirée${off.size > 1 ? "s" : ""}` : ""}</summary>
    ${list.map((e) => `<label class="check-in"><input type="checkbox" data-pentry="${esc(p.id)}" data-eid="${esc(e.id)}" ${off.has(e.id) ? "" : "checked"}>
      <span>${esc(e.merchant ? capital(e.merchant) : e.counterparty || "Écriture")}</span><span class="num">${date(e.booking_date)} · ${n2(e.amount.minor / 100)}</span></label>`).join("")}
  </details>`;
}

document.addEventListener("change", (e) => {
  const pid = e.target.dataset && e.target.dataset.pentry;
  if (!pid) return;
  const off = dropped.get(pid) || new Set();
  if (e.target.checked) off.delete(e.target.dataset.eid);
  else off.add(e.target.dataset.eid);
  dropped.set(pid, off);
  store.notify();
});

// une carte dont on a retiré des écritures est remplacée par une carte sans elles, validée du
// même Face ID ; toutes retirées, elle est refusée
export async function prepare(ids) {
  const pe = store.data(pendingPath);
  const byId = new Map((pe ? pe.items : []).map((p) => [p.id, p]));
  const out = [];
  for (const id of ids) {
    const p = byId.get(id);
    const off = dropped.get(id);
    if (!p || !off || !off.size) {
      out.push(id);
      continue;
    }
    const keep = p.params.entry_ids.filter((e) => !off.has(e));
    if (keep.length) out.push((await propose(p.kind, { ...p.params, entry_ids: keep }, `app-${Date.now()}`)).id);
    await api(`/proposals/${id}/reject`, {});
    dropped.delete(id);
  }
  return out;
}
