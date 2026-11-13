// Patrimoine : les cartes Revenus et Frais, et leur détail dans un grand panneau. Revenus : les
// dividendes et intérêts des douze derniers mois (/finance/performance). Frais : ce que les
// frais courants des fonds coûtent par an et sur trente ans (/finance/fees) ; un fonds sans TER
// connu est dit « frais inconnus », et son TER se saisit ici, sous Face ID.
import { SH, SHEETS, amount, closeSheet, esc, failure, ibox, ic, openSheet, pf, renderSheet, toast } from "../../ui.js";
import { asOf, iso, perfPath } from "./wstate.js";
import { outcome, proposeAndApprove } from "./proposals.js";
import { store } from "../../store.js";
import { units } from "./perf.js";

const FEES = "/finance/fees";
function yearPath() {
  const d = new Date(`${asOf()}T00:00:00Z`);
  d.setUTCFullYear(d.getUTCFullYear() - 1);
  return perfPath(iso(d), null, "month");
}
const card = (kind, label, val, sub) => `<button class="sumcard" type="button" data-a="w-more" data-v="${kind}" aria-haspopup="dialog">
  <span class="l">${label}</span><span class="v">${val}</span><span class="s">${sub}</span></button>`;

function income() {
  const p = store.use(yearPath()).data;
  const s = p ? p.owned || p.summary : null;
  return s ? { total: units(s.income), value: p.items.length ? units(p.items[p.items.length - 1].value) : 0 } : null;
}

// les deux cartes, sur tout le patrimoine ; rien tant qu'il n'y a ni revenu ni fonds
export function moreCards() {
  const inc = income(), f = store.use(FEES).data;
  let h = "";
  if (inc && inc.total >= 1) h += card("income", "Revenus", amount(inc.total), "dividendes et intérêts · 12 mois");
  if (f && f.items.length) {
    const known = f.items.filter((i) => i.ter_pct != null).length;
    h += known ? card("fees", "Frais des fonds", `${amount(units(f.yearly_cost))}`,
      `par an${known < f.items.length ? ` · ${f.items.length - known} inconnu${f.items.length - known > 1 ? "s" : ""}` : ""}`)
      : card("fees", "Frais des fonds", "Inconnus", `${f.items.length} fonds à renseigner`);
  }
  return h;
}

SHEETS.wincome = () => {
  const inc = income();
  if (!inc) return null;
  const y = inc.value > 0 ? inc.total / inc.value : null;
  return {
    title: "Revenus", tall: true,
    body: `<div class="sheet-big num">${amount(inc.total)} <small>sur 12 mois</small></div>
      <dl class="dl"><dt>Par mois, en moyenne</dt><dd>${amount(inc.total / 12)}</dd>
      ${y == null ? "" : `<dt>Rapporté à ton patrimoine</dt><dd>${pf(y, 1)} % par an</dd>`}</dl>
      <p class="hint">Dividendes et intérêts reçus sur tes comptes, tels que tes relevés les montrent. Un fonds qui réinvestit ses dividendes n'en verse pas : son revenu est dans son cours.</p>`,
  };
};

SHEETS.wfees = () => {
  const f = store.use(FEES).data;
  if (!f) return null;
  const rows = f.items.map((i) => `<button class="row go-row" type="button" data-a="fee-edit" data-v="${esc(i.isin)}" aria-label="${esc(i.name)}, ${i.ter_pct == null ?
    "frais inconnus, saisir" : `${i.ter_pct} % par an, modifier`}">
    ${ibox(ic("trend"), i.ter_pct == null ? "var(--warn)" : "var(--accent)")}<span class="row-main"><span class="row-title">${esc(i.name)}</span><span class="row-sub">${amount(
      units(i.value))} détenus</span></span>
    <span class="row-num">${i.ter_pct == null ?
      '<span class="pill warn">Inconnus</span>' : `<span class="row-val num">${amount(units(i.yearly_cost))}</span><span class="row-delta">${esc(i.ter_pct)} % par an</span>`}</span>
    <span class="go">${ic("chev")}</span></button>`).join("");
  const unknown = units(f.unknown_value);
  return {
    title: "Frais des fonds", tall: true,
    body: `<div class="sheet-big num">${amount(units(f.yearly_cost))} <small>par an</small></div>
      <dl class="dl"><dt>Sur ${f.years} ans, si rien ne change</dt><dd>${amount(units(f.cost_over_years))}</dd></dl>
      <p class="hint">Les frais courants (TER) sont prélevés dans le cours du fonds : tu ne les vois sur aucun relevé.
        Sur ${f.years} ans : l'écart de valeur finale pour tes parts d'aujourd'hui, à ${esc(f.assumed_return_pct)} % par an avant frais. Un ordre de grandeur, pas une prévision.</p>
      ${unknown >= 1 ? `<p class="hint">${amount(unknown)} dans des fonds aux frais inconnus, hors de ces totaux. Le TER est sur la fiche du fonds (KID) : touche la ligne pour le saisir.</p>` : ""}
      <div class="list">${rows}</div>`,
  };
};

SHEETS.wfee = (isin, sh) => {
  const f = store.data(FEES), i = f ? f.items.find((x) => x.isin === isin) : null;
  if (!i) return null;
  if (sh.tmp == null) sh.tmp = i.ter_pct || "";
  return {
    title: esc(i.name),
    body: `<label class="field" for="fee-ter">Frais courants (TER), en % par an
        <input id="fee-ter" value="${esc(sh.tmp)}" inputmode="decimal" placeholder="0.20" autocomplete="off" data-autofocus></label>
      <p class="hint">Tel que l'émetteur le publie, sur la fiche du fonds (${esc(isin)}).</p>
      ${sh.err ? `<div class="err" role="alert">${esc(sh.err)}</div>` : ""}`,
    foot: `<button class="primary" type="button" data-a="fee-save" ${sh.busy ? "disabled" : ""}>${ic("faceid")}${sh.busy ? "Validation…" : "Enregistrer avec Face ID"}</button>`,
  };
};

document.addEventListener("input", (e) => { if (e.target.id === "fee-ter" && SH.kind === "wfee") SH.tmp = e.target.value; });

export const actions = {
  "w-more": (v) => openSheet(v === "income" ? "wincome" : "wfees"),
  "fee-edit": (isin) => openSheet("wfee", isin),
  "fee-save": async () => {
    const ter = String(SH.tmp || "").replace(",", ".").replace("%", "").trim();
    if (!/^\d(\.\d{1,3})?$/.test(ter)) { SH.err = "Frais illisibles (en %, par exemple 0,20)"; return renderSheet(); }
    SH.busy = true;
    SH.err = "";
    renderSheet();
    try {
      const [text, bad] = outcome(await proposeAndApprove([["set_fund_fee", { isin: SH.arg, ter_pct: ter }]]));
      if (bad) SH.err = text;
      else {
        closeSheet();
        store.invalidate();
        toast("Frais enregistrés");
      }
    } catch (err) {
      SH.err = failure(err);
    } finally {
      SH.busy = false;
      if (SH.kind) renderSheet();
    }
  },
};
