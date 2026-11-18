// La fiche d'une catégorie, la même d'où qu'on vienne (Mon budget, Régler, le flux, l'accueil) :
// ce qui est dépensé, comment la suivre (par mois, par an, sans cible, hors budget) et le montant,
// les six derniers mois, ses abonnements, ses écritures, puis nom, icône, groupe, fusion et
// archivage repliés. Tous les changements partent en une seule validation Face ID. Aussi : le bas
// de « Régler » (catégories sans cible, nouvelle catégorie, abonnements) et le panneau d'un bloc
// du flux.
import { base, monthName, parseAmount, toMinor, units } from "../../format.js";
import { SH, SHEETS, amount, closeSheet, cv, esc, failure, ibox, ic, m0, openSheet, renderSheet, setPref, skel, toast } from "../../ui.js";
import { CAT_ICONS, GROUP_LABEL, catIcon, catLook, catMark } from "./meta.js";
import { outcome, proposeAndApprove } from "./proposals.js";
import { recurringPath, subscriptions } from "./bsubs.js";
import { store } from "../../store.js";

const P = store.params;
const CATS = "/finance/categories";
const u = (m) => (m ? units(m) : 0);
const bud = () => store.data(`/finance/budget?month=${P.month}&period=${P.period}`);
const cats = () => (store.data(CATS) || { items: [] }).items;
const expense = (g) => g === "fixed" || g === "variable";
const HOW = [["month", "Par mois"], ["year", "Par an"], ["tracked", "Sans cible"], ["off_budget", "Hors budget"]];
const HOW_HINT = {
  month: "Une enveloppe chaque mois, avec rythme et alertes.",
  year: "Une enveloppe pour l'année (vacances, frais annuels) : comparée au cumul depuis janvier, sans peser sur le reste du mois.",
  tracked: "Comptée dans le dépensé et le reste, sans cible ni alerte.",
  off_budget: "Ni dans le dépensé ni dans le reste : montrée à part, en net.",
};

// le réglage actuel d'une catégorie, tel que le serveur le donne ; montant par mois ou par an
function setting(c, b) {
  const l = b ? b.lines.find((x) => x.category === c.id) : null;
  const sv = c.group === "savings" && b ? b.plan.savings_lines.find((x) => x.category === c.id) : null;
  if (c.mode === "off_budget") return { how: "off_budget", amt: null };
  if (c.mode === "tracked") return { how: "tracked", amt: null };
  if (sv) return { how: "month", amt: u(sv.target) / (b.months.length || 1) };
  if (l && l.yearly) return { how: "year", amt: l.yearly.target ? u(l.yearly.target) : null };
  if (l && l.target) return { how: "month", amt: u(l.target) / (b.months.length || 1) };
  return { how: "month", amt: null };
}

function initial(c, b) {
  const s = c ? setting(c, b) : { how: "month", amt: null };
  const shown = c ? c.icon || catIcon(c.id, c.group) : "dots:0";
  return { name: c ? c.name : "", icon: shown, shown, group: c ? c.group : "variable", into: "", how: s.how, amt: s.amt, how0: s.how, amt0: s.amt };
}

const modeOf = (how) => (how === "tracked" || how === "off_budget" ? how : "target");

// les propositions qu'il faut pour passer du réglage actuel à celui de la fiche
function changes(c, t) {
  const name = t.name.trim();
  const mode = modeOf(t.how);
  if (!c) return name ? [["create_category", { name, grp: t.group, mode: expense(t.group) ? mode : null, icon: t.icon }]] : [];
  const out = [];
  const e = { category_id: c.id };
  if (name && name !== c.name) e.name = name;
  if (t.icon !== t.shown) e.icon = t.icon;
  if (t.group !== c.group) e.grp = t.group;
  if (expense(t.group) && mode !== (c.mode || "target")) e.mode = mode;
  if (Object.keys(e).length > 1) out.push(["edit_category", e]);
  const cadence = t.how === "year" && t.group !== "savings" ? "year" : "month";
  if (mode === "target" && (t.how !== t.how0 || (t.amt || 0) !== (t.amt0 || 0)) && (t.amt || t.amt0)) {
    out.push(["set_budget", { category_id: c.id, amount_minor: toMinor(t.amt || 0), cadence }]);
  }
  return out;
}

function history(id, group, target) {
  const te = store.use(`/finance/trend?category=${encodeURIComponent(id)}&months=6&month=${P.month}`);
  if (!te.data) return skel("block");
  if (!te.data.series.some((x) => Math.abs(u(x.total)) >= 1)) return '<p class="hint">Rien sur les six derniers mois.</p>';
  const pts = te.data.series.map((x) => ({ m: x.month, v: Math.abs(u(x.total)) }));
  const mx = Math.max(1, ...pts.map((p) => p.v), target || 0) * 1.1;
  const look = catLook(id, group);
  return `<div class="mini-months" role="img" aria-label="${pts.map((p) => `${monthName(p.m).split(" ")[0]} ${Math.round(p.v)}`).join(", ")}">
    ${target != null ? `<span class="tline" data-css="--b:${(18 + (target / mx) * 72).toFixed(0)}px"></span>` : ""}
    ${pts.map((p) => `<div><i class="${p.m === P.month ? "" : "past"}" data-css="--h:${((p.v / mx) * 72).toFixed(0)}px;--c:${target != null && p.v > target ? "var(--neg)" : look.color}"></i><span>${monthName(p.m).split(" ")[0].slice(0, 4)}</span></div>`).join("")}</div>
    ${target != null ? '<p class="hint">Pointillés : la cible du mois.</p>' : ""}`;
}

// la ligne d'état sous le montant
function status(t, l, spent, saving) {
  if (saving) return `${m0(u(saving.done))} versés sur ${m0(u(saving.target))}`;
  if (l && l.yearly) return `${m0(u(l.yearly.spent))}${l.yearly.target ? ` sur ${m0(u(l.yearly.target))}` : ""} ${base()} depuis janvier`;
  if (t.how0 === "off_budget") return "Hors budget : ne compte pas dans le reste";
  if (!spent) return "Rien dépensé ce mois";
  if (t.how0 === "month" && t.amt0 != null) return spent > t.amt0 ? `<span class="neg">${m0(spent - t.amt0)} au-dessus de la cible</span>` : `Reste ${m0(t.amt0 - spent)}`;
  return t.how0 === "tracked" ? "Sans cible" : "Pas encore de cible";
}

SHEETS.fiche = (id, sh) => {
  const b = bud();
  store.use(CATS);
  const c = id ? cats().find((x) => x.id === id) : null;
  if ((id && !c) || !b) return { title: "Catégorie", body: skel("block") };
  if (!sh.tmp) sh.tmp = initial(c, b);
  const t = sh.tmp;
  const l = c ? b.lines.find((x) => x.category === c.id) : null;
  const saving = c && c.group === "savings" ? b.plan.savings_lines.find((x) => x.category === c.id) : null;
  const spent = l ? u(l.spent) : 0;
  const n = changes(c, t).length;
  const per = t.how === "year" ? "par an" : "par mois";
  const equiv = t.amt ? (t.how === "year" ? `soit ${m0(t.amt / 12)} ${base()} par mois` : `soit ${m0(t.amt * 12)} ${base()} par an`) : "";
  const withAmount = t.how === "month" || t.how === "year";
  const subs = c ? ((store.data(recurringPath) || { items: [] }).items || []).filter((s) => s.active && s.category === c.id) : [];
  const head = c ? `<div class="sheet-big num">${amount(spent)}${t.amt0 != null && t.how0 === "month" && !saving ? ` <small>sur ${amount(t.amt0)}</small>` : ""}</div>
      <span class="crow-st ok">${status(t, l, spent, saving)}</span>` : `<label class="field" for="f-name">Nom
        <input id="f-name" value="${esc(t.name)}" maxlength="60" autocomplete="off" placeholder="Frais annuels du logement"></label>
      <h3>Groupe</h3>${radios("cat-group", [["fixed", GROUP_LABEL.fixed], ["variable", GROUP_LABEL.variable], ["savings", GROUP_LABEL.savings]], t.group)}`;
  const choices = expense(t.group) ? HOW : [["month", "Par mois"]];
  const how = `<h3>Comment la suivre</h3>
      ${choices.length > 1 ? `<div class="seg how-seg" role="group" aria-label="Comment la suivre">${choices.map(([k, lab]) => `<button type="button" data-a="f-how" data-v="${k}" aria-pressed="${t.how === k}">${lab}</button>`).join("")}</div>
      <p class="hint">${esc(HOW_HINT[t.how])}</p>` : '<p class="hint">Ce que tu veux mettre de côté chaque mois : retiré du reste à dépenser.</p>'}
      ${withAmount ? `<div class="target"><button type="button" data-a="f-step" data-v="-10" aria-label="Diminuer de 10">−</button><input id="f-amt" inputmode="decimal" value="${t.amt || ""}" aria-label="Montant ${per} en ${base()}" placeholder="aucune"><button type="button" data-a="f-step" data-v="10" aria-label="Augmenter de 10">+</button></div>
      <p class="hint how-per"><b>${per}</b>${equiv ? ` · ${equiv}` : ""}</p>` : ""}`;
  const fold = (label) => `<button class="link-row" type="button" data-a="f-more" aria-expanded="${Boolean(sh.more)}">${label}${ic(sh.more ? "up" : "down")}</button>`;
  const more = c ? `${fold("Nom, icône, groupe, fusion")}${sh.more ? settings(c, t) : ""}` : `${fold("Icône")}${sh.more ? icons(t) : ""}`;
  return {
    title: c ? `${catMark(c.id, c.group)}<span>${esc(c.name)}</span>` : "Nouvelle catégorie",
    body: `${sh.note ? `<p class="hint">${esc(sh.note)}</p>` : ""}${head}${how}
      ${c ? `<h3>Six derniers mois</h3>${history(c.id, c.group, t.how === "month" && t.amt ? t.amt : null)}` : ""}
      ${subs.length ? `<h3>Abonnements rangés ici</h3>${subs.map((s) => `<button class="kv kv-go" type="button" data-a="sub" data-v="${esc(s.key)}">${ibox(ic("repeat"), "var(--s4)", "sm")}<span>${esc(s.label)}</span><b class="num">${m0(Math.abs(u(s.last_amount)))}</b></button>`).join("")}` : ""}
      ${l && l.count ? `<div class="stack-v"><button class="secondary" type="button" data-a="cat-tx" data-v="${esc(c.id)}">${ic("list")}${l.count > 1 ? `Voir les ${l.count} écritures` : "Voir l'écriture"}</button></div>` : ""}
      ${more}
      ${sh.bad || sh.err ? `<div class="err" role="alert">${esc(sh.bad || sh.err)}</div>` : ""}`,
    foot: `<button class="primary" type="button" data-a="f-save" ${n && !sh.busy && !sh.bad ? "" : "disabled"}>${ic("faceid")}${sh.busy ? "Validation…" : !c ? "Créer avec Face ID" : n ? `Enregistrer${n > 1 ? ` ${n} changements` : ""} avec Face ID` : "Tout est à jour"}</button>`,
  };
};

const radios = (action, list, cur) => `<div class="catgrid" role="radiogroup">${list.map(([v, l]) =>
  `<button type="button" role="radio" aria-checked="${cur === v}" data-a="${action}" data-v="${v}">${esc(l)}</button>`).join("")}</div>`;

function icons(t) {
  const hue = Number(t.icon.split(":")[1] || 0), pict = t.icon.split(":")[0];
  return `<div class="catgrid icons" role="radiogroup" aria-label="Icône">${CAT_ICONS.map((n) => `<button type="button" role="radio" aria-checked="${pict === n}" aria-label="${n}" data-a="cat-icon" data-v="${n}">${ibox(ic(n), cv(hue), "xs")}</button>`).join("")}</div>
    <div class="catgrid icons" role="radiogroup" aria-label="Teinte">${[0, 1, 2, 3, 4, 5, 6].map((h) => `<button type="button" role="radio" aria-checked="${hue === h}" aria-label="Teinte ${h + 1}" data-a="cat-hue" data-v="${h}">${ibox("", cv(h), "xs")}</button>`).join("")}</div>`;
}

function settings(c, t) {
  const same = cats().filter((x) => x.active && x.id !== c.id && x.group === c.group);
  return `<div class="fiche-more"><label class="field" for="f-name">Nom
      <input id="f-name" value="${esc(t.name)}" maxlength="60" autocomplete="off"></label>
    <h3>Icône</h3>${icons(t)}
    <h3>Groupe</h3>${radios("cat-group", [["fixed", GROUP_LABEL.fixed], ["variable", GROUP_LABEL.variable], ["savings", GROUP_LABEL.savings]], t.group)}
    ${t.group !== c.group ? '<p class="hint">Possible seulement si aucun mois clos n\'a d\'écriture dans cette catégorie : sinon, crée-en une autre.</p>' : ""}
    ${same.length ? `<h3>Fusionner</h3><p class="hint">Les écritures, les règles et la cible passent sur la catégorie choisie ; celle-ci est archivée.</p>
      <label class="field" for="cat-into">Dans<select id="cat-into"><option value="">Choisir…</option>${same.map((x) => `<option value="${esc(x.id)}" ${t.into === x.id ? "selected" : ""}>${esc(x.name)}</option>`).join("")}</select></label>
      <button class="secondary" type="button" data-a="cat-merge" ${t.into ? "" : "disabled"}>${ic("faceid")}Fusionner avec Face ID</button>` : ""}
    <button class="link-row danger" type="button" data-a="cat-archive" data-v="${esc(c.id)}">Archiver cette catégorie${ic("chev")}</button></div>`;
}

document.addEventListener("input", (e) => {
  if (SH.kind !== "fiche" || !SH.tmp) return;
  const el = /** @type {HTMLInputElement} */ (e.target);
  if (el.id === "f-name") {
    SH.tmp.name = el.value;
    renderSheet();
  }
  if (el.id === "f-amt") {
    const r = parseAmount(el.value);
    SH.bad = r.error || "";
    if (r.value != null) SH.tmp.amt = r.value;
    renderSheet();
  }
});
document.addEventListener("change", (e) => {
  const el = /** @type {HTMLSelectElement} */ (e.target);
  if (el.id === "cat-into" && SH.kind === "fiche" && SH.tmp) {
    SH.tmp.into = el.value;
    renderSheet();
  }
});

// --- Régler : le bas du panneau -------------------------------------------------------------

export function planExtra() {
  const xs = cats().filter((c) => c.active && expense(c.group) && (c.mode === "tracked" || c.mode === "off_budget"))
    .sort((a, z) => a.name.localeCompare(z.name, "fr"));
  return `<div class="plan-extra">${xs.length ? `<div class="grp"><span>Sans cible ou hors budget</span></div>
    ${xs.map((c) => `<div class="plan-row">${catMark(c.id, c.group, "sm")}<span class="plan-lab"><button type="button" class="plan-name" data-a="cat" data-v="${esc(c.id)}">${esc(c.name)}</button><small>${c.mode === "tracked" ? "sans cible" : "hors budget"}</small></span></div>`).join("")}` : ""}
    <button class="link-row" type="button" data-a="cat-new">${ic("plus")} Nouvelle catégorie${ic("chev")}</button>
    <button class="link-row" type="button" data-a="subs">Abonnements repérés${ic("chev")}</button>
    <button class="link-row" type="button" data-a="cats">Toutes les catégories (revenus, archivées)${ic("chev")}</button></div>`;
}

SHEETS.subslist = () => ({ title: "Abonnements repérés", body: subscriptions(store.use(recurringPath)) || '<div class="empty">Aucun abonnement repéré.</div>' });

// --- un bloc du flux : ses catégories, dans un panneau --------------------------------------

SHEETS.bgroup = (g) => {
  const f = store.data(`/finance/flows?month=${P.month}&period=${P.period}`);
  if (!f) return { title: "Catégories", body: skel("block") };
  const grp = f.groups.find((x) => x.group === g);
  const items = grp ? grp.items.filter((i) => u(i.total) > 0) : [];
  return {
    title: esc(GROUP_LABEL[g] || "Catégories"),
    body: items.length ? items.map((i) => `<button class="crow" type="button" data-a="cat" data-v="${esc(i.category)}">${catMark(i.category, g)}<span><span class="crow-top"><b>${esc(i.name)}</b><span class="brest num">${m0(u(i.total))}</span></span></span></button>`).join("")
      : '<div class="empty">Rien sur la période.</div>',
  };
};

export const actions = {
  "sk-list": (g) => openSheet("bgroup", g),
  subs: () => {
    setPref("subsOpen", true);
    store.use(recurringPath);
    openSheet("subslist");
  },
  "f-how": (k) => {
    SH.tmp.how = k; // le nombre tapé reste : seul le rythme change
    renderSheet();
  },
  "f-step": (v) => {
    SH.bad = "";
    SH.tmp.amt = Math.max(0, Math.round(((SH.tmp.amt || 0) + Number(v)) * 100) / 100);
    renderSheet();
  },
  "f-more": () => {
    SH.more = !SH.more;
    renderSheet();
  },
  "f-save": async () => {
    const c = SH.arg ? cats().find((x) => x.id === SH.arg) : null;
    const t = SH.tmp;
    const items = changes(c, t);
    if (!items.length) return;
    SH.busy = true;
    SH.err = "";
    renderSheet();
    try {
      const res = await proposeAndApprove(items);
      const [text, bad] = outcome(res);
      const made = !c && !bad ? res.find((r) => r.result && r.result.category_id)?.result.category_id : null;
      if (bad) SH.err = text;
      else if (made && modeOf(t.how) === "target" && t.amt) {
        // l'identifiant vient du hub : la cible se valide sur la fiche de la catégorie créée
        openSheet("fiche", made, { ...t, name: t.name.trim(), shown: t.icon, how0: "month", amt0: null });
        SH.note = "Catégorie créée. Il reste à valider sa cible.";
        toast("Catégorie créée");
      } else {
        closeSheet();
        toast(c ? "Catégorie mise à jour" : "Catégorie créée");
      }
    } catch (e) {
      SH.err = failure(e);
    } finally {
      SH.busy = false;
      if (SH.kind) renderSheet();
    }
  },
};
