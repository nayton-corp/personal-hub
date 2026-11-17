// Écran « Catégories » (refonte du budget, lot Q) : créer une catégorie, la renommer, changer son
// icône, son groupe ou son mode (avec cible, suivie sans cible, hors budget), la fusionner dans
// une autre ou l'archiver. L'identifiant vient du hub, l'historique reste juste ; tout passe par
// une proposition validée avec Face ID.
import { SH, SHEETS, closeSheet, cv, esc, failure, ibox, ic, openSheet, renderSheet, toast } from "../../ui.js";
import { CAT_ICONS, GROUP_LABEL, catMark } from "./meta.js";
import { outcome, proposeAndApprove } from "./proposals.js";
import { store } from "../../store.js";

const CATS = "/finance/categories";
const GROUPS = ["fixed", "variable", "savings", "income"];
export const MODE_LABEL = { target: "Avec cible", tracked: "Suivie sans cible", off_budget: "Hors budget" };
const MODE_HINT = {
  target: "Une cible, un rythme et des alertes.",
  tracked: "Comptée dans le dépensé et le reste, sans cible ni alerte (liquide, fourre-tout).",
  off_budget: "Ni dans le dépensé ni dans le reste : montrée à part, en net (envoyé − reçu).",
};
const HUES = [0, 1, 2, 3, 4, 5, 6];

/** @returns {any[]} */
const all = () => (store.data(CATS) || { items: [] }).items;
const find = (/** @type {string} */ id) => all().find((c) => c.id === id) || null;
const expense = (/** @type {string} */ g) => g === "fixed" || g === "variable";

const row = (/** @type {any} */ c) => `<button class="row" type="button" data-a="cat-edit" data-v="${esc(c.id)}" aria-label="${esc(c.name)}, ${esc(sub(c))}. Modifier">
    ${catMark(c.id, c.group)}<span class="row-main"><span class="row-title">${esc(c.name)}</span><span class="row-sub">${esc(sub(c))}</span></span>${ic("chev")}</button>`;
const sub = (/** @type {any} */ c) => (c.archived_at ? "archivée" : expense(c.group) ? MODE_LABEL[c.mode] || MODE_LABEL.target : GROUP_LABEL[c.group]);

SHEETS.cats = (_arg, sh) => {
  const e = store.use(CATS);
  if (!e.data) return { title: "Catégories", body: '<div class="empty">Chargement…</div>' };
  const live = all().filter((c) => c.active && c.group !== "transfer");
  const gone = all().filter((c) => !c.active && c.archived_at);
  const groups = GROUPS.map((g) => {
    const list = live.filter((c) => c.group === g).sort((a, b) => a.name.localeCompare(b.name, "fr"));
    return list.length ? `<h3>${esc(GROUP_LABEL[g])}</h3><div class="list">${list.map(row).join("")}</div>` : "";
  }).join("");
  const n = gone.length;
  const archived = n ? `<button class="link-row" type="button" data-a="cats-archived" aria-expanded="${Boolean(sh.archived)}">
      ${n} archivée${n > 1 ? "s" : ""}${ic("chev")}</button>
    ${sh.archived ? `<div class="list">${gone.map(row).join("")}</div>` : ""}` : "";
  return {
    title: "Catégories",
    body: `<p class="hint">Renomme, change l'icône ou le mode, fusionne deux catégories ou archive celles qui ne servent plus. L'historique reste juste.</p>${groups}${archived}`,
    foot: `<button class="primary" type="button" data-a="cat-new">${ic("plus")}Nouvelle catégorie</button>`,
  };
};

/** @param {any} c */
function initial(c) {
  if (!c) return { name: "", icon: null, group: "variable", mode: "target", into: "" };
  return { name: c.name, icon: c.icon, group: c.group, mode: c.mode || "target", into: "" };
}

/** ce que la proposition doit changer ; une erreur dite en clair sinon @param {any} c @param {any} t */
function params(c, t) {
  const name = String(t.name || "").trim();
  if (!name) throw new Error("Donne un nom à cette catégorie");
  if (!c) return ["create_category", { name, grp: t.group, mode: expense(t.group) ? t.mode : null, icon: t.icon || null }];
  /** @type {Record<string, unknown>} */
  const out = { category_id: c.id };
  if (name !== c.name) out.name = name;
  if (t.icon && t.icon !== c.icon) out.icon = t.icon;
  if (t.group !== c.group) out.grp = t.group;
  if (expense(t.group) && t.mode !== c.mode) out.mode = t.mode;
  if (Object.keys(out).length === 1) throw new Error("Rien n'a changé");
  return ["edit_category", out];
}

const radios = (/** @type {string} */ action, /** @type {[string, string][]} */ list, /** @type {string} */ cur, /** @type {string} */ label) =>
  `<div class="catgrid" role="radiogroup" aria-label="${label}">${list.map(([v, l]) =>
    `<button type="button" role="radio" aria-checked="${cur === v}" data-a="${action}" data-v="${v}">${esc(l)}</button>`).join("")}</div>`;

SHEETS["cat-edit"] = (id, sh) => {
  const c = id ? find(id) : null;
  if (id && !c) return { title: "Catégorie", body: '<div class="empty">Chargement…</div>' };
  if (!sh.tmp) sh.tmp = initial(c);
  const t = sh.tmp;
  const hue = t.icon ? Number(t.icon.split(":")[1]) : 0;
  const pict = t.icon ? t.icon.split(":")[0] : null;
  const icons = CAT_ICONS.map((n) => `<button type="button" role="radio" aria-checked="${pict === n}" aria-label="${n}"
    data-a="cat-icon" data-v="${n}">${ibox(ic(n), cv(hue), "xs")}</button>`).join("");
  const hues = HUES.map((h) => `<button type="button" role="radio" aria-checked="${Boolean(pict) && hue === h}"
    aria-label="Teinte ${h + 1}" data-a="cat-hue" data-v="${h}">${ibox("", cv(h), "xs")}</button>`).join("");
  const same = c ? all().filter((x) => x.active && x.id !== c.id && x.group === c.group) : [];
  const merge = c && c.active && same.length ? `<h3>Fusionner</h3>
      <p class="hint">Les écritures, les règles et la cible de ${esc(c.name)} passent sur la catégorie choisie ; ${esc(c.name)} est archivée.</p>
      <label class="field" for="cat-into">Dans
        <select id="cat-into" data-k="into"><option value="">Choisir…</option>${same.map((x) =>
          `<option value="${esc(x.id)}" ${t.into === x.id ? "selected" : ""}>${esc(x.name)}</option>`).join("")}</select></label>
      <button class="secondary" type="button" data-a="cat-merge" ${t.into && !sh.busy ? "" : "disabled"}>${ic("faceid")}Fusionner avec Face ID</button>` : "";
  const archive = c ? `<button class="link-row ${c.active ? "danger" : ""}" type="button" data-a="cat-archive" data-v="${esc(c.id)}">
      ${c.active ? "Archiver cette catégorie" : "Restaurer cette catégorie"}${ic("chev")}</button>` : "";
  return {
    title: c ? `${catMark(c.id, c.group)}<span>${esc(c.name)}</span>` : "Nouvelle catégorie",
    body: `<label class="field" for="cat-name">Nom
        <input id="cat-name" data-k="name" value="${esc(t.name)}" maxlength="60" autocomplete="off" placeholder="Cours de piano, animaux…"></label>
      <h3>Icône</h3><div class="catgrid icons" role="radiogroup" aria-label="Icône">${icons}</div>
      <div class="catgrid icons" role="radiogroup" aria-label="Teinte">${hues}</div>
      <h3>Groupe</h3>${radios("cat-group", GROUPS.map((g) => [g, GROUP_LABEL[g]]), t.group, "Groupe")}
      ${c && t.group !== c.group ? '<p class="hint">Possible seulement si aucun mois clos n\'a d\'écriture dans cette catégorie : sinon, crée-en une autre.</p>' : ""}
      ${expense(t.group) ? `<h3>Dans le budget</h3>${radios("cat-mode", Object.entries(MODE_LABEL), t.mode, "Mode")}<p class="hint">${esc(MODE_HINT[t.mode])}</p>` : ""}
      ${sh.err ? `<div class="err" role="alert">${esc(sh.err)}</div>` : ""}
      ${merge}${archive}`,
    foot: `<button class="primary" type="button" data-a="cat-save" ${sh.busy ? "disabled" : ""}>
      ${ic("faceid")}${sh.busy ? "Validation…" : c ? "Enregistrer avec Face ID" : "Créer avec Face ID"}</button>`,
  };
};

document.addEventListener("input", (e) => {
  const el = /** @type {HTMLInputElement} */ (e.target);
  const k = el.dataset && el.dataset.k;
  if (k && el.id === `cat-${k}` && SH.kind === "cat-edit" && SH.tmp) SH.tmp[k] = el.value;
});
document.addEventListener("change", (e) => {
  const el = /** @type {HTMLSelectElement} */ (e.target);
  if (el.id === "cat-into" && SH.kind === "cat-edit" && SH.tmp) {
    SH.tmp.into = el.value;
    renderSheet();
  }
});

/** @param {[string, Record<string, unknown>][]} items @param {string} done */
async function send(items, done) {
  SH.busy = true;
  SH.err = "";
  renderSheet();
  try {
    const [text, bad] = outcome(await proposeAndApprove(items));
    if (bad) SH.err = text;
    else {
      closeSheet();
      store.invalidate();
      toast(done);
    }
  } catch (err) {
    SH.err = failure(err);
  } finally {
    SH.busy = false;
    if (SH.kind) renderSheet();
  }
}

const pick = (/** @type {string} */ k, /** @type {string} */ v) => {
  SH.tmp[k] = v;
  renderSheet();
};

export const actions = {
  cats: () => openSheet("cats", null),
  "cats-archived": () => {
    SH.archived = !SH.archived;
    renderSheet();
  },
  "cat-new": () => openSheet("cat-edit", null),
  "cat-edit": (/** @type {string} */ id) => openSheet("cat-edit", id),
  "cat-group": (/** @type {string} */ v) => pick("group", v),
  "cat-mode": (/** @type {string} */ v) => pick("mode", v),
  "cat-icon": (/** @type {string} */ v) => pick("icon", `${v}:${SH.tmp.icon ? SH.tmp.icon.split(":")[1] : 0}`),
  "cat-hue": (/** @type {string} */ v) => pick("icon", `${SH.tmp.icon ? SH.tmp.icon.split(":")[0] : "dots"}:${v}`),
  "cat-save": () => {
    const c = SH.arg ? find(SH.arg) : null;
    let p;
    try {
      p = params(c, SH.tmp);
    } catch (e) {
      SH.err = /** @type {Error} */ (e).message;
      return renderSheet();
    }
    return send([p], c ? "Catégorie mise à jour" : "Catégorie créée");
  },
  "cat-merge": () => {
    const c = find(SH.arg);
    if (c && SH.tmp.into) send([["merge_categories", { from_id: c.id, into_id: SH.tmp.into }]], "Catégories fusionnées");
  },
  "cat-archive": (/** @type {string} */ id) => {
    const c = find(id);
    if (c) send([["archive_category", { category_id: id, archived: c.active }]], c.active ? "Catégorie archivée" : "Catégorie restaurée");
  },
};
