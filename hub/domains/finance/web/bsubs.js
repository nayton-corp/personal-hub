// Budget, les abonnements repérés : la section repliée (/finance/recurring) et la fiche d'un
// abonnement, pour corriger la détection : le renommer, changer sa catégorie, le retirer (« ce
// n'est pas un abonnement ») ou le remettre, avec Face ID (set_recurring). « Rechercher à
// nouveau » relance la détection ; les corrections restent.
import { base, date, units } from "../../format.js";
import { SH, SHEETS, amount2, closeSheet, esc, failure, ibox, ic, openSheet, pref, renderSheet, skel, toast } from "../../ui.js";
import { foldHead } from "./bviews.js";
import { outcome, proposeAndApprove } from "./proposals.js";
import { api, store } from "../../store.js";

export const recurringPath = "/finance/recurring";
const CADENCE = { weekly: "chaque semaine", monthly: "mensuel", quarterly: "trimestriel", semiannual: "semestriel", yearly: "annuel" };
const u = (m) => (m ? units(m) : 0);
const all = () => store.data(recurringPath);
const find = (key) => ((all() || {}).items || []).find((x) => x.key === key);
const ccy = (m) => (m.currency === base() ? "" : ` ${esc(m.currency)}`);

function row(s) {
  const up = Math.abs(u(s.last_amount)) - Math.abs(u(s.amount));
  const cat = s.category_name ? ` · ${esc(s.category_name)}` : " · sans catégorie";
  return `<button class="kv kv-go" type="button" data-a="sub" data-v="${esc(s.key)}">${ibox(ic("repeat"), "var(--s4)", "sm")}
    <span>${esc(s.label)}<span class="s">${CADENCE[s.cadence] || esc(s.cadence)} · prochain le ${date(s.next_date)}${cat}</span>${up > 0.009
      ? ` <span class="pill warn">${ic("alert")}hausse +${amount2(up)}</span>` : ""}</span>
    <b class="num">${amount2(Math.abs(u(s.last_amount)))}${ccy(s.amount)}</b></button>`;
}

const removedRow = (s) => `<div class="kv">${ibox(ic("close"), "var(--s6)", "sm")}<span>${esc(s.label)}<span class="s">retiré · ${CADENCE[s.cadence] || esc(s.cadence)}</span></span>
  <button class="linkish" type="button" data-a="sub-show" data-v="${esc(s.key)}">Remettre</button></div>`;

export function subscriptions(re) {
  const r = re.data;
  const items = r && r.items ? r.items.filter((x) => x.active) : [];
  const removed = (r && r.removed) || [];
  if (!items.length && !removed.length) return "";
  const open = pref("subsOpen", false);
  const total = r.monthly_total.map((x) => `${amount2(Math.abs(u(x)))} ${esc(x.currency)}`).join(" + ");
  const next = items.slice().sort((a, b) => (a.next_date || "").localeCompare(b.next_date || ""))[0];
  const ups = items.filter((s) => Math.abs(u(s.last_amount)) - Math.abs(u(s.amount)) > 0.009).length;
  const sum = items.length
    ? `${items.length} abonnement${items.length > 1 ? "s" : ""} · ${total} par mois${next ? ` · prochain : ${esc(next.label)} le ${date(next.next_date)}` : ""}${ups ? ` · ${ups} en hausse` : ""}`
    : "aucun abonnement actif";
  return `<section class="card${open ? "" : " folded"}" id="subs" aria-labelledby="t-subs">
      ${foldHead("subs", "Abonnements", open, sum)}
      ${open ? `<div class="sec-body" id="subs-body">${items.map(row).join("")}
        ${removed.length ? `<h3>Retirés</h3>${removed.map(removedRow).join("")}` : ""}
        <p class="hint">Paiements réguliers repérés dans tes relevés ; les prochaines échéances sont estimées. Touche-en un pour le renommer, changer sa catégorie ou le retirer.</p>
        <button class="link-row" type="button" data-a="subs-find">Rechercher à nouveau${ic("chev")}</button></div>` : ""}
    </section>`;
}

// --- la fiche d'un abonnement -------------------------------------------------------------------

SHEETS.sub = (key, sh) => {
  const s = find(key), cats = store.data("/finance/categories");
  if (!s || !cats) return { title: "Abonnement", body: skel("block") };
  if (sh.tmp == null) sh.tmp = { label: s.label, cat: s.category || "" };
  const opts = cats.items.filter((c) => c.active && (c.group === "fixed" || c.group === "variable"))
    .sort((a, b) => a.group.localeCompare(b.group) || a.name.localeCompare(b.name, "fr"))
    .map((c) => `<option value="${esc(c.id)}" ${c.id === sh.tmp.cat ? "selected" : ""}>${esc(c.name)}${c.group === "fixed" ? " (fixe)" : ""}</option>`).join("");
  const name = sh.tmp.label.trim(), changed = name !== s.label || (sh.tmp.cat || "") !== (s.category || "");
  return {
    title: `${ic("repeat")}<span>${esc(s.label)}</span>`,
    body: `<p class="hint">${CADENCE[s.cadence] || esc(s.cadence)} · ${s.occurrences} paiements, le dernier le ${date(s.last_date)}${s.account ? ` · ${esc(s.account)}` : ""}
        · ${amount2(Math.abs(u(s.last_amount)))}${ccy(s.amount)}${s.found_label !== s.label ? `<br>Repéré sous le nom « ${esc(s.found_label)} ».` : ""}</p>
      <label class="field" for="sub-name">Nom<input id="sub-name" value="${esc(sh.tmp.label)}" maxlength="80" autocomplete="off"></label>
      <label class="field" for="sub-cat">Catégorie<select id="sub-cat" class="select-full"><option value="" ${sh.tmp.cat ? "" : "selected"}>Sans catégorie</option>${opts}</select></label>
      <p class="hint">Rangé dans une catégorie fixe, il dit quand elle tombe dans « À venir ». La catégorie des écritures elles-mêmes ne change pas.</p>
      ${sh.err ? `<div class="err" role="alert">${esc(sh.err)}</div>` : ""}
      <button class="link-row" type="button" data-a="sub-hide">Ce n'est pas un abonnement${ic("chev")}</button>`,
    foot: `<button class="primary" type="button" data-a="sub-save" ${changed && name && !sh.busy ? "" : "disabled"}>${ic("faceid")}${sh.busy ? "Validation…" : "Enregistrer avec Face ID"}</button>`,
  };
};

document.addEventListener("input", (e) => {
  if (SH.kind !== "sub" || !SH.tmp) return;
  if (e.target.id === "sub-name") SH.tmp.label = e.target.value;
  else if (e.target.id === "sub-cat") SH.tmp.cat = e.target.value;
  else return;
  if (e.target.id === "sub-cat") renderSheet();
  else {
    const btn = document.querySelector('#sheet [data-a="sub-save"]'), s = find(SH.arg), name = SH.tmp.label.trim();
    if (btn && s) btn.disabled = !name || (name === s.label && (SH.tmp.cat || "") === (s.category || ""));
  }
});

/** @param {Record<string, unknown>} params @param {string} done */
async function send(params, done) {
  if (SH.kind) {
    SH.busy = true;
    SH.err = "";
    renderSheet();
  }
  try {
    const [text, bad] = outcome(await proposeAndApprove([["set_recurring", params]]));
    if (bad) {
      if (SH.kind) SH.err = text;
      else toast(text);
    } else {
      if (SH.kind) closeSheet();
      store.invalidate();
      toast(done);
    }
  } catch (err) {
    if (SH.kind) SH.err = failure(err);
    else toast(failure(err));
  } finally {
    SH.busy = false; // même fiche fermée : sinon la suivante s'ouvrirait « Validation… »
    if (SH.kind) renderSheet();
  }
}

export const actions = {
  sub: (key) => {
    store.use("/finance/categories");
    openSheet("sub", key);
  },
  "sub-save": () => {
    const s = find(SH.arg);
    if (!s) return;
    const label = SH.tmp.label.trim();
    return send({ key: s.key, label: label === s.found_label ? null : label, category_id: SH.tmp.cat || null }, "Abonnement corrigé");
  },
  "sub-hide": () => {
    const s = find(SH.arg);
    if (s) return send({ key: s.key, hidden: true, label: s.label === s.found_label ? null : s.label, category_id: s.category || null }, "Retiré des abonnements");
  },
  "sub-show": (key) => send({ key, hidden: false }, "Remis dans les abonnements"),
  "subs-find": async () => {
    try {
      const r = await api(`${recurringPath}/refresh`, {});
      store.invalidate();
      toast(`${r.count} abonnement${r.count > 1 ? "s" : ""} repéré${r.count > 1 ? "s" : ""}`);
    } catch (err) {
      toast(failure(err));
    }
  },
};
