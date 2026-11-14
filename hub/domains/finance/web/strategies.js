// Stratégies : une décision écrite une fois, en une phrase (sur quoi, quand, le geste prévu),
// que le hub aide à tenir. Il ne passe jamais d'ordre : il prévient quand une étape est atteinte,
// puis constate l'opération au journal ou prend la réponse (c'est fait, plus tard, je passe).
// La section du patrimoine, le panneau d'une stratégie, celui où on l'écrit ; calculs : smodel.js.
import * as M from "./smodel.js";
import { SHEETS, SH, closeSheet, esc, failure, ibox, ic, n2, openSheet, renderSheet, skel, toast } from "../../ui.js";
import { base, date, decimals } from "../../format.js";
import { outcome, proposeAndApprove } from "./proposals.js";
import { api, store } from "../../store.js";
import { go } from "../../shell.js";

export const STRATS = "/finance/strategies";
const cash = (minor) => `${n2(minor / 10 ** decimals())} ${base()}`;
const items = () => (store.data(STRATS) || { items: [] }).items;
const find = (id) => items().find((s) => s.id === id) || null;
const mark = (s, size = "") => ibox(ic(M.KIND[s.kind].icon), M.KIND[s.kind].color, size);
const pill = (s) => `<span class="pill ${M.stateOf(s).tone}">${M.stateOf(s).label}</span>`;
const plural = (n, one, many) => `${n} ${n > 1 ? many : one}`;

// --- section du patrimoine --------------------------------------------------------------------

// la carte résumé du patrimoine
export function stratBrief() {
  const e = store.use(STRATS);
  if (e.status === "error") return { v: "Indisponibles", s: "" };
  if (!e.data) return { v: "…", s: "" };
  const live = e.data.items.filter((s) => s.status !== "ended");
  if (!live.length) return { v: "Aucune", s: "écris ta première décision" };
  const reached = live.filter((s) => s.step && s.step.state === "open").length;
  return { v: plural(live.length, "stratégie", "stratégies"), s: reached ? plural(reached, "étape atteinte", "étapes atteintes") : "rien à faire pour l'instant", hot: reached > 0 };
}

function card(s) {
  const sub = s.step ? M.stepLine(s, cash) : M.levelLine(s);
  return `<button class="row row2 go-row strat-row" type="button" data-a="strat-open" data-v="${esc(s.id)}">${mark(s)}
    <span class="row-main"><span class="row-title">${esc(s.name)} ${pill(s)}</span>
      <span class="strat-say">${esc(s.phrase)}</span>${sub ? `<span class="row-sub">${esc(sub)}</span>` : ""}</span>
    <span class="go">${ic("chev")}</span></button>`;
}

// le grand panneau de la carte Stratégies, comme Répartition et Rendement
SHEETS.wstrat = () => {
  const e = store.use(STRATS);
  const all = e.data ? e.data.items : [];
  const live = all.filter((s) => s.status !== "ended"), ended = all.length - live.length;
  const body = () => {
    if (e.status === "error") return `<div class="err-box" role="alert">Stratégies indisponibles : ${esc(e.error.message)}</div>`;
    if (!e.data) return skel("block");
    const list = live.length ? `<div class="list">${live.map(card).join("")}</div>`
      : '<div class="empty">Une stratégie, c\'est une décision prise à froid : « si ça arrive, je fais ça ». Le hub te prévient le jour venu.</div>';
    const old = ended ? `<button class="link-row" type="button" data-a="strat-ended">${plural(ended, "stratégie terminée", "stratégies terminées")}${ic("chev")}</button>` : "";
    return `${list}<button class="secondary strat-add" type="button" data-a="strat-new">Nouvelle stratégie</button>${old}
      <p class="hint">Le hub ne passe aucun ordre : il te prévient, tu décides, il constate au journal.</p>`;
  };
  return { title: "Stratégies", tall: true, body: body() };
};

// les lignes « À faire » de l'accueil : une étape atteinte qui attend une réponse
export function todoRows() {
  return items().filter((s) => s.step && s.step.state === "open").map((s) => (
    { ic: M.KIND[s.kind].icon, c: M.KIND[s.kind].color, t: `Stratégie ${s.name} : étape atteinte`, s: M.stepLine(s, cash), a: "strat-open", v: s.id }
  ));
}

// --- panneau d'une stratégie ------------------------------------------------------------------

const STEP_STATE = { open: "à faire", later: "plus tard", done: "tenue", skipped: "passée" };
const stepName = (s, st) => (s.kind === "ladder" ? `Palier ${M.levelLabel(Number(st.key.slice(1)))}`
  : s.kind === "recurring" ? `Achat du ${date(st.detail.due || st.opened_on)}` : `Baisse du ${date(st.opened_on)}`);

function stepBlock(s, busy) {
  const st = s.step;
  const coins = (st.rows || []).map((r) => `<div class="strat-coin"><span>${esc(r.name)}</span>
    <span class="num">${r.ratio_pct == null ? "—" : `${Math.round(Number(r.ratio_pct))} % du prix d'achat`}</span><span class="num">${cash(r.value.minor)}</span></div>`).join("");
  const seen = st.done.minor ? `<p class="hint">Le journal montre déjà ${cash(st.done.minor)} depuis l'alerte.</p>` : "";
  const off = busy ? "disabled" : "";
  return `<div class="strat-step" role="group" aria-label="Étape atteinte"><b>${esc(M.stepLine(s, cash))}</b>
    ${coins ? `<p class="hint">À toi de choisir quoi vendre. Aujourd'hui :</p><div class="strat-coins">${coins}</div>` : ""}${seen}
    <p class="hint">Fais l'opération chez ta plateforme : le hub la verra au journal et cochera l'étape tout seul.</p>
    <div class="strat-answers"><button class="btn" type="button" data-a="strat-answer" data-v="done" ${off}>C'est fait</button>
      ${st.state === "later" ? "" : `<button class="btn secondary" type="button" data-a="strat-answer" data-v="later" ${off}>Plus tard</button>`}
      <button class="btn secondary" type="button" data-a="strat-answer" data-v="skip" ${off}>Je passe</button></div></div>`;
}

SHEETS.strategy = (id, sh) => {
  const s = find(id);
  if (!s) return null;
  const past = s.steps.filter((x) => !s.step || x.id !== s.step.id);
  const level = M.levelLine(s);
  const off = sh.busy ? "disabled" : "";
  const live = s.status !== "ended";
  return {
    title: `${mark(s)}<span>${esc(s.name)}</span>`,
    body: `<p class="strat-say big">${esc(s.phrase)}</p>
      <p class="strat-now">${pill(s)}${level ? `<span>${esc(level)}</span>` : ""}</p>
      ${s.note ? `<p class="hint">Ensuite : ${esc(s.note)}</p>` : ""}
      ${s.step ? stepBlock(s, sh.busy) : ""}
      <h3 class="field">Étapes</h3>
      ${past.length ? `<dl class="dl">${past.map((x) => `<dt>${esc(stepName(s, x))}</dt><dd>${STEP_STATE[x.state]}${x.closed_by === "journal" ? " (vue au journal)" : ""}</dd>`).join("")}</dl>` : ""}
      <p class="hint">${esc(M.keptLine(s))}. Ce qui compte ici : tenir ce que tu avais décidé, pas un rendement.</p>
      ${sh.err ? `<div class="err" role="alert">${esc(sh.err)}</div>` : ""}`,
    foot: live ? `<div class="strat-foot"><button class="btn secondary" type="button" data-a="strat-edit" data-v="${esc(s.id)}" ${off}>Modifier</button>
      <button class="btn secondary" type="button" data-a="strat-status" data-v="${s.status === "paused" ? "active" : "paused"}" ${off}>${s.status === "paused" ? "Reprendre" : "Mettre en pause"}</button>
      <button class="btn secondary" type="button" data-a="strat-status" data-v="ended" ${off}>Terminer</button></div>` : "",
  };
};

SHEETS.stratended = () => ({
  title: "Stratégies terminées",
  body: `<div class="list">${items().filter((s) => s.status === "ended").map(card).join("")}</div>`,
});

// --- écrire ou modifier une stratégie ---------------------------------------------------------

const option = (v, label, cur) => `<option value="${esc(v)}" ${String(cur) === String(v) ? "selected" : ""}>${esc(label)}</option>`;
const select = (k, label, opts, cur) => `<label class="field" for="sf-${k}">${label}
  <select id="sf-${k}" data-sk="${k}" class="select-full">${opts.map(([v, l]) => option(v, l, cur)).join("")}</select></label>`;
const seg = (k, opts, cur) => `<div class="seg" role="group">${opts.map(([v, l]) => (
  `<button type="button" data-a="strat-pick" data-v="${k}|${v}" aria-pressed="${String(cur) === String(v)}">${l}</button>`)).join("")}</div>`;
const amountField = (t, label) => `<label class="field" for="sf-amount">${label}
  <input id="sf-amount" data-sk="amount" value="${esc(t.amount)}" inputmode="decimal" placeholder="0.00" autocomplete="off"></label>`;

function intentions() {
  const tile = (k, x, attrs) => `<button class="row row2 strat-row" type="button" ${attrs}>${ibox(ic(x.icon), x.color)}
    <span class="row-main"><span class="row-title">${x.label}</span><span class="row-sub">${x.hint}</span></span>
    ${k ? `<span class="go">${ic("chev")}</span>` : '<span class="pill plain">Bientôt</span>'}</button>`;
  return `<div class="list">${Object.entries(M.KIND).map(([k, x]) => tile(k, x, `data-a="strat-kind" data-v="${k}"`)).join("")}${tile(null, M.SOON, "disabled")}</div>
    <p class="hint">Des décisions simples, à seuils larges. Rien ici ne passe un ordre à ta place.</p>`;
}

function kindFields(t) {
  if (t.kind === "ladder") {
    const rows = t.tiers.map((x, i) => `<div class="strat-tier">
      <select data-sk="tier|${i}|at_pct" aria-label="Niveau du palier ${i + 1}">${M.LEVELS.map((v) => option(v, M.levelLabel(v), x.at_pct)).join("")}</select>
      <select data-sk="tier|${i}|sell_pct" aria-label="Part à vendre au palier ${i + 1}">${M.PARTS.map((v) => option(v, `vendre ${v} %`, x.sell_pct)).join("")}</select>
      <button class="icon-btn" type="button" data-a="strat-tier-del" data-v="${i}" aria-label="Retirer ce palier" ${t.tiers.length < 2 ? "disabled" : ""}>${ic("close")}</button></div>`).join("");
    const tpl = M.TEMPLATES.map((x) => `<button class="chip" type="button" data-a="strat-tpl" data-v="${x.k}" title="${esc(x.hint)}">${x.label}</button>`).join("");
    return `<h3 class="field">Paliers</h3><div class="strat-tpl">${tpl}</div>${rows}
      ${t.tiers.length < M.MAX_TIERS ? '<button class="linkish" type="button" data-a="strat-tier-add">Ajouter un palier</button>' : ""}
      <p class="hint">Le niveau se lit par rapport à ton prix d'achat moyen. La part se prend sur ce que tu tiens ce jour-là.</p>`;
  }
  if (t.kind === "recurring") {
    const days = t.cadence === "weekly" ? M.WEEKDAYS.map((d, i) => [i, d]) : Array.from({ length: 28 }, (_, i) => [i + 1, `le ${i + 1}`]);
    return `${seg("cadence", [["monthly", "Chaque mois"], ["weekly", "Chaque semaine"]], t.cadence)}
      <div class="two">${select("day", "Jour", days, t.day)}${amountField(t, "Montant")}</div>
      <p class="hint">Le jour venu, un rappel. Si l'achat est déjà au journal, l'étape se coche sans rien te demander.</p>`;
  }
  return `<div class="two">${select("drop_pct", "Baisse d'au moins", M.DROPS.map((v) => [v, `${v} %`]), t.drop_pct)}${amountField(t, "Montant à acheter")}</div>
    <h3 class="field">Depuis le plus haut</h3>${seg("window_days", M.WINDOWS.map(([d, l]) => [d, l.replace("des ", "")]), t.window_days)}
    <p class="hint">Une seule alerte par baisse : il faut un nouveau plus haut pour qu'elle revienne.</p>`;
}

SHEETS.stratform = (id, sh) => {
  const s = id ? find(id) : null;
  if (id && !s) return null;
  if (!sh.tmp) sh.tmp = s ? M.initial(s.kind, s, decimals()) : {};
  const t = sh.tmp;
  if (!t.kind) return { title: "Que veux-tu faire ?", body: intentions() };
  const all = (store.use(STRATS).data || { scopes: [] }).scopes;
  const scopes = all.filter((x) => (t.kind === "ladder" ? x.kind !== "security" : x.kind !== "group"));
  if (!s && !t.scope && scopes.length) t.scope = scopes[0].key;
  const name = s ? s.name : (scopes.find((x) => x.key === t.scope) || { name: "…" }).name;
  let said = "";
  try { said = M.phrase(t.kind, name, { ...t, ...M.settings(t, decimals()) }, cash); } catch { said = ""; }
  const on = s ? "" : scopes.length ? select("scope", "Sur quoi", scopes.map((x) => [x.key, x.name]), t.scope)
    : `<p class="hint">Rien à cibler pour l'instant : il faut d'abord ${t.kind === "ladder" ? "une crypto" : "un placement"} dans le patrimoine.</p>`;
  return {
    title: `${ibox(ic(M.KIND[t.kind].icon), M.KIND[t.kind].color)}<span>${s ? esc(s.name) : M.KIND[t.kind].label}</span>`,
    body: `${on}${kindFields(t)}
      <label class="field" for="sf-note">Ensuite (facultatif)
        <input id="sf-note" data-sk="note" value="${esc(t.note)}" maxlength="200" placeholder="Ce que tu feras après" autocomplete="off"></label>
      <p class="strat-say big" aria-live="polite">${said ? esc(said) : "Complète les réglages pour lire ta décision."}</p>
      ${sh.err ? `<div class="err" role="alert">${esc(sh.err)}</div>` : ""}`,
    foot: `<button class="primary" type="button" data-a="strat-save" ${sh.busy || (!s && !scopes.length) ? "disabled" : ""}>
      ${ic("faceid")}${sh.busy ? "Validation…" : "Enregistrer avec Face ID"}</button>`,
  };
};

function keep(e) {
  const k = e.target.dataset && e.target.dataset.sk;
  if (SH.kind !== "stratform" || !SH.tmp || !k) return;
  const [a, i, field] = k.split("|");
  if (a === "tier") SH.tmp.tiers[Number(i)][field] = Number(e.target.value);
  else SH.tmp[k] = e.target.value;
  SH.err = "";
  renderSheet();
}
document.addEventListener("input", keep);
document.addEventListener("change", keep);

async function run(list, done, close = true) {
  SH.busy = true;
  SH.err = "";
  renderSheet();
  try {
    const [text, bad] = outcome(await proposeAndApprove(list));
    if (bad) SH.err = text;
    else {
      if (close) closeSheet();
      toast(done);
    }
  } catch (e) {
    SH.err = failure(e);
  } finally {
    SH.busy = false;
    if (SH.kind) renderSheet();
  }
}

const ANSWERED = { done: "Étape cochée", later: "Étape gardée pour plus tard", skip: "Étape passée" };
const STATUS_DONE = { paused: "Stratégie en pause", active: "Stratégie reprise", ended: "Stratégie terminée" };

export const actions = {
  "strat-open": (id) => openSheet("strategy", id),
  "strat-ended": () => openSheet("stratended"),
  "strat-new": () => openSheet("stratform", null),
  "strat-edit": (id) => openSheet("stratform", id),
  "strat-kind": (k) => { SH.tmp = M.initial(k, null, decimals()); renderSheet(); },
  "strat-pick": (v) => {
    const i = v.indexOf("|"), k = v.slice(0, i);
    SH.tmp[k] = k === "window_days" ? Number(v.slice(i + 1)) : v.slice(i + 1);
    if (k === "cadence") SH.tmp.day = SH.tmp.cadence === "weekly" ? 0 : 1;
    renderSheet();
  },
  "strat-tpl": (k) => {
    SH.tmp.tiers = M.TEMPLATES.find((x) => x.k === k).tiers.map(([at_pct, sell_pct]) => ({ at_pct, sell_pct }));
    renderSheet();
  },
  "strat-tier-add": () => {
    const top = Math.max(...SH.tmp.tiers.map((x) => x.at_pct));
    SH.tmp.tiers.push({ at_pct: M.LEVELS.find((v) => v >= top + M.MIN_GAP) || top + 50, sell_pct: 50 });
    renderSheet();
  },
  "strat-tier-del": (i) => { SH.tmp.tiers.splice(Number(i), 1); renderSheet(); },
  "strat-save": async () => {
    const s = SH.arg ? find(SH.arg) : null;
    let params;
    try {
      params = M.saveParams(SH.tmp, s, decimals());
    } catch (e) {
      SH.err = e.message;
      return renderSheet();
    }
    await run([["save_strategy", params]], s ? "Stratégie modifiée" : "Stratégie écrite : le hub veille");
  },
  "strat-status": async (v) => { await run([["save_strategy", { strategy_id: SH.arg, status: v }]], STATUS_DONE[v], v === "ended"); },
  "strat-answer": async (v) => {
    const s = find(SH.arg);
    if (s && s.step) await run([["answer_strategy_step", { step_id: s.step.id, answer: v }]], ANSWERED[v], false);
  },
};

// lien d'une notification : #strategy=<étape> ouvre la stratégie de cette étape
export async function deeplink(stepId) {
  const d = await api(STRATS);
  const s = d.items.find((x) => x.steps.some((st) => st.id === stepId));
  if (!s) return false;
  go("patrimoine", { page: null });
  store.cache.set(STRATS, { status: "ok", data: d, error: null, stale: false, busy: false });
  openSheet("strategy", s.id);
  return true;
}
