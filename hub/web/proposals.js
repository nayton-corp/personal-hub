// Double Sas dans l'app (L3-04) : les propositions en attente se valident par lot avec un seul
// Face ID. Le défi WebAuthn porte l'empreinte du lot (révisions et empreintes comprises) ; une
// proposition qui a changé entre-temps revient avec une nouvelle révision, jamais appliquée.
import { chf2, el, units } from "./format.js";
import { api, store } from "./store.js";
import { credentialJSON, requestOptions } from "./webauthn.js";

const $ = (id) => document.getElementById(id);
const BATCH = 50; // plafond de /approvals/challenge
const GROUP_LABEL = {
  income: "Revenus", fixed: "Fixe", variable: "Variable", savings: "Épargne", transfer: "Transferts",
};

export const pendingPath = "/proposals?status=pending";
const reviewPath = "/finance/review";
const selected = new Set();
const picks = new Map(); // contrepartie → catégorie choisie, gardée entre deux dessins
let busy = false;

function say(id, msg, error = false) {
  const n = $(id);
  n.textContent = msg || "";
  n.classList.toggle("error", error);
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

function outcome(results) {
  if (typeof results === "string") return [results, false];
  const applied = results.filter((r) => r.status === "applied").length;
  const changed = results.filter((r) => r.status === "superseded" || r.status === "pending").length;
  const failed = results.length - applied - changed;
  const parts = [`${applied} appliquée${applied > 1 ? "s" : ""}`];
  if (changed) parts.push(`${changed} ont changé entre-temps : relis-les`);
  if (failed) parts.push(`${failed} en échec`);
  return [parts.join(", "), failed > 0];
}

function propose(kind, params, bundle) {
  return api("/proposals", { domain: "finance", kind, params, bundle_id: bundle });
}

async function run(msgId, fn) {
  if (busy) return;
  busy = true;
  say(msgId, "");
  try {
    const [text, error] = outcome(await fn());
    say(msgId, text, error);
  } catch (e) {
    say(msgId, e.name === "NotAllowedError" ? "Validation annulée." : e.message, true);
  } finally {
    busy = false;
    selected.clear();
    window.dispatchEvent(new Event("hub:changed"));
    store.invalidate();
  }
}

// --- carte des propositions en attente (accueil) --------------------------------------------

export function pendingCard() {
  const list = $("prop-list");
  list.replaceChildren();
  const pe = store.use(pendingPath);
  const items = pe.status === "ok" ? pe.data.items : [];
  $("c-props").hidden = !items.length && !$("prop-msg").textContent;
  if (pe.status === "error") list.append(el("div", "empty", `Impossible de charger : ${pe.error.message}`));
  for (const id of [...selected]) if (!items.some((p) => p.id === id)) selected.delete(id);
  for (const p of items) {
    const r = el("label", "row pick");
    const box = el("input");
    box.type = "checkbox";
    box.checked = selected.has(p.id);
    box.addEventListener("change", () => {
      if (box.checked) selected.add(p.id);
      else selected.delete(p.id);
      store.notify();
    });
    const n = el("div", "n");
    n.append(el("b", "", p.preview.summary), el("span", "", p.revision > 1 ? `révision ${p.revision} · a changé, relis-la` : by(p.created_by)));
    const v = el("div", "v");
    const no = el("button", "link", "Refuser");
    no.type = "button";
    no.addEventListener("click", (e) => {
      e.preventDefault();
      run("prop-msg", async () => {
        await api(`/proposals/${p.id}/reject`, {});
        return "Proposition refusée.";
      });
    });
    v.append(no);
    r.append(box, n, v);
    list.append(r);
  }
  const ids = selected.size ? [...selected] : items.map((p) => p.id);
  const go = $("prop-accept");
  go.hidden = !items.length;
  go.disabled = busy;
  go.textContent = `Valider avec Face ID (${ids.length})`;
  go.onclick = () => run("prop-msg", () => approve(ids));
}

function by(principal) {
  if (principal.startsWith("system")) return "proposée par le hub";
  if (principal.startsWith("token:")) return "proposée par un assistant";
  return "proposée depuis l'app";
}

// --- à catégoriser, groupé par contrepartie (journal) ---------------------------------------

function categorySelect(cats, direction) {
  const s = el("select", "cat-pick");
  s.append(new Option("Catégorie…", ""));
  // un crédit peut être un remboursement de dépense : seules les dépenses excluent les revenus
  const wanted = (c) => c.active && (direction !== "debit" || c.group !== "income");
  for (const [g, label] of Object.entries(GROUP_LABEL)) {
    const gr = cats.filter((c) => c.group === g && wanted(c));
    if (!gr.length) continue;
    const og = el("optgroup");
    og.label = label;
    for (const c of gr) og.append(new Option(c.name, c.id));
    s.append(og);
  }
  return s;
}

export function reviewCard(categoriesPath) {
  const card = $("c-review");
  card.hidden = store.params.tx !== "todo" || store.params.q.length >= 3;
  if (card.hidden) return;
  const list = $("review-list");
  list.replaceChildren();
  const re = store.use(reviewPath);
  const cats = store.data(categoriesPath);
  if (re.status !== "ok" || !cats) {
    list.append(el("div", "empty", re.status === "error" ? `Impossible de charger : ${re.error.message}` : "Chargement…"));
    return;
  }
  if (!re.data.groups.length) list.append(el("div", "empty", "Tout est catégorisé."));
  for (const g of re.data.groups) {
    const box = el("div", "rv");
    const top = el("div", "l");
    const v = el("span", "v");
    v.append(el("b", "amt", chf2(units(g.total))));
    top.append(el("span", "", `${g.counterparty} · ${g.count}`), v);
    const pick = categorySelect(cats.items, g.direction);
    pick.value = picks.get(g.counterparty) || "";
    const acts = el("div", "acts");
    const once = el("button", "link", g.count > 1 ? `Ces ${g.entry_ids.length} écritures` : "Cette écriture");
    const always = el("button", "link", "Toujours");
    once.type = always.type = "button";
    const ready = () => {
      once.disabled = always.disabled = !pick.value || busy;
    };
    pick.addEventListener("change", () => {
      picks.set(g.counterparty, pick.value);
      ready();
    });
    ready();
    once.addEventListener("click", () => run("review-msg", async () => {
      const bundle = `review-${Date.now()}`;
      const ps = [];
      for (const id of g.entry_ids) ps.push(await propose("recategorize", { entry_id: id, category_id: pick.value }, bundle));
      return approve(ps.map((p) => p.id));
    }));
    // la règle catégorise aussi, à l'application, les écritures déjà en attente qui lui correspondent
    always.addEventListener("click", () => run("review-msg", async () => {
      const p = await propose("create_rule", { pattern: g.counterparty, direction: g.direction, category_id: pick.value });
      return approve([p.id]);
    }));
    acts.append(pick, once);
    if (g.counterparty !== "(inconnu)") acts.append(always);
    box.append(top, acts);
    list.append(box);
  }
}
