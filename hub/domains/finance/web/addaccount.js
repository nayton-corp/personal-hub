// Ajouter un compte, en trois étapes : son type, sa plateforme, puis la façon dont le hub reçoit ses données
// (identifiants d'un connecteur du catalogue, adresses publiques d'un portefeuille, ou rien : à la main). La
// connexion, s'il en faut une, est créée en passant et resservira aux comptes suivants de la même plateforme ;
// le compte se crée par une proposition validée avec Face ID. Le parcours a sa page (la rubrique « Ajouter un
// compte », ouverte depuis Comptes) : chaque étape y remplace la précédente, et la fin ramène à Comptes. Aussi :
// les comptes que les relevés attendent.
import { base, date, el } from "../../format.js";
import {
  FIELD_LABEL, WALLET_ASSETS, button, field, input, instAv, link, networkChecks, open as openConnection, paths,
  readSetting, run, say, secretInput, settingInput, slug, walletOf,
} from "./connections.js";
import { approve, propose } from "./proposals.js";
import { action, go } from "../../shell.js";
import { api, store } from "../../store.js";

const $ = (id) => document.getElementById(id);
const KIND_LABEL = { cash: "Cash", securities: "Titres", pension: "Prévoyance", crypto: "Crypto" };
const TYPES = [
  ["cash", "Banque"], ["securities", "Titres"], ["pension", "Prévoyance"],
  ["crypto", "Crypto : plateforme"], ["wallet", "Crypto : portefeuille"], ["other", "Autre"],
];
const CHAIN_LABEL = { BTC: "Bitcoin", ETH: "Ethereum et réseaux EVM", SOL: "Solana", ATOM: "Cosmos", EGLD: "MultiversX" };

// une étape de la page : son titre quand il précise (la plateforme, la chaîne), son rang, l'étape
// d'avant ; la flèche du haut, elle, quitte la page
function editor(title, step, back) {
  const box = $("acct-editor");
  box.replaceChildren();
  if (title !== "Ajouter un compte") box.append(el("h2", "", title));
  if (step) box.append(el("p", "note", `Étape ${step} sur 3`));
  box.hidden = false;
  if (back) box.append(link("‹ Étape précédente", back));
  window.scrollTo({ top: 0 });
  return box;
}

// la page s'ouvre sur l'étape 1 ; quittée, elle se vide et repartira de zéro
export function enterAddAccount() {
  if (!$("acct-editor").childElementCount) addAccount();
}

function leaveAddAccount() {
  const box = $("acct-editor");
  box.hidden = true;
  box.replaceChildren();
}

// fin du parcours (ou Annuler) : retour à la page d'avant, Comptes ; `to` : une autre rubrique
function close(to) {
  if (to) go("sources", { rubric: to, replace: true });
  else action("back")();
}

function choices(box, items, pick) {
  const grid = el("div", "catgrid");
  for (const [value, label] of items) {
    const b = button(label, "");
    b.addEventListener("click", () => pick(value));
    grid.append(b);
  }
  box.append(grid);
}

function actions(box, label, fn) {
  const msg = el("p", "message");
  const acts = el("div", "acts");
  const go = button(label);
  const cancel = button("Annuler", "btn secondary");
  acts.append(go, cancel);
  box.append(acts, msg);
  cancel.addEventListener("click", () => close());
  go.addEventListener("click", () => run(go, msg, fn));
}

async function createAccount(params) {
  const p = await propose("create_account", params);
  const [result] = await approve([p.id]);
  if (!result || result.status !== "applied") {
    const why = result && result.problem && (result.problem.detail || result.problem.title);
    throw new Error(why || "Proposition non appliquée : relis-la dans l'accueil.");
  }
  store.invalidate();
}

// --- étape 1 : le type --------------------------------------------------------------------------

export function addAccount() {
  const box = editor("Ajouter un compte", 1);
  box.append(el("p", "hint", "Quel genre de compte ?"));
  choices(box, TYPES, (kind) => {
    if (kind === "other") openAccount();
    else if (kind === "wallet") pickChain();
    else pickPlatform(kind);
  });
  const cancel = button("Annuler", "btn secondary");
  cancel.addEventListener("click", () => close());
  box.append(cancel);
}

// --- étape 2 : la plateforme --------------------------------------------------------------------

function pickPlatform(kind) {
  const box = editor("Ajouter un compte", 2, addAccount);
  box.append(el("p", "note", "Chargement…"));
  Promise.all([api(paths.catalog), api(paths.connections)])
    .then(([cat, cs]) => {
      const specs = cat.items.filter((c) => c.accounts.includes(kind) && !c.single);
      box.lastChild.remove();
      box.append(el("p", "hint", "Où est ce compte ?"));
      choices(box, [...specs.map((c) => [c.name, c.label]), ["", "Autre (à la main)"]], (name) => {
        const spec = specs.find((c) => c.name === name);
        if (spec) connect(kind, spec, cs.items);
        else openAccount({ kind });
      });
    })
    .catch((e) => box.append(el("p", "message error", e.message)));
}

function pickChain() {
  const box = editor("Ajouter un portefeuille", 2, addAccount);
  box.append(el("p", "hint", "Sur quelle chaîne ?"));
  choices(box, WALLET_ASSETS.map((a) => [a, CHAIN_LABEL[a] || a]), wallet);
}

// --- étape 3 : comment le hub reçoit ses données ---------------------------------------------------

function connect(kind, spec, existing) {
  const box = editor(spec.label, 3, () => pickPlatform(kind));
  const mine = existing.filter((c) => c.connector === spec.name);
  // une banque Enable Banking par connexion ; les autres plateformes : une connexion sert tous leurs comptes
  if (mine.length && spec.method !== "open_banking") {
    box.append(el("p", "hint", `${mine[0].label} est déjà branché : ses comptes arrivent avec ses relevés. S'il en manque un, il attend dans « Comptes en attente ».`));
    const acts = el("div", "acts");
    const settings = button("Régler la connexion", "btn secondary");
    settings.addEventListener("click", () => { close("conn"); openConnection({ id: mine[0].id }); });
    const done = button("Fermer", "btn secondary");
    done.addEventListener("click", () => close());
    acts.append(settings, done);
    box.append(acts);
    return;
  }
  const crypto = spec.accounts.includes("crypto");
  const label = field(box, "aa-label", "Nom affiché", input(spec.method === "open_banking" ? "" : spec.label));
  const settings = {};
  for (const key of spec.required_settings) settings[key] = field(box, `aa-${key}`, `${FIELD_LABEL[key] || key} *`, settingInput(key));
  if (spec.method === "open_banking") box.append(el("p", "hint", "Nom et pays tels qu'Enable Banking les liste, par exemple Revolut et LT, ou N26 et DE."));
  const secrets = {};
  for (const key of spec.secrets) secrets[key] = field(box, `aa-secret-${key}`, FIELD_LABEL[key] || key, secretInput(key));
  if (spec.secrets.length) box.append(el("p", "hint", "Chiffrés à la saisie, jamais réaffichés. Pour une plateforme, une clé en lecture seule."));
  let c = null; // créée au premier essai : un Face ID annulé ne la recrée pas
  actions(box, crypto ? "Brancher et créer le compte avec Face ID" : "Brancher", async () => {
    const name = label.value.trim() || spec.label;
    const given = Object.fromEntries(Object.entries(secrets).map(([k, n]) => [k, n.value]).filter(([, v]) => v));
    if (!c) {
      const taken = new Set(existing.map((x) => x.id));
      let id = slug(name) || spec.name;
      for (let i = 2; taken.has(id); i++) id = `${slug(name) || spec.name}-${i}`;
      const values = {};
      for (const [key, node] of Object.entries(settings)) {
        const v = readSetting(key, node);
        if (v !== undefined) values[key] = v;
      }
      c = await api(paths.connections, { id, connector: spec.name, label: name, settings: values });
      if (Object.keys(given).length) await api(`${paths.connections}/${c.id}/secrets`, { values: given }, "PUT");
    }
    // le compte avant le premier relevé : l'import le trouve, rien n'attend
    if (crypto) await createAccount({ institution: spec.label, name, kind: "crypto", currency: base(), external_ref: `crypto:${c.id}` });
    if (Object.keys(given).length === spec.secrets.length && spec.method !== "open_banking") await api(`/collectors/${c.id}/refresh`, {});
    close(spec.method === "open_banking" ? "conn" : undefined);
    if (spec.method === "open_banking") {
      openConnection({ id: c.id });
      say("coll-msg", `${name} branchée : « Lier le compte » ouvre l'autorisation chez la banque.`);
    } else if (Object.keys(given).length === spec.secrets.length) {
      say("acct-msg", `${name} branché : premier relevé dans la minute.${crypto ? "" : " Ses comptes arrivent ensuite dans « Comptes en attente »."}`);
    } else say("acct-msg", `${name} créé, sans identifiants : « Régler » dans Connexions pour les donner.`);
    return null;
  });
}

function wallet(asset) {
  const box = editor(CHAIN_LABEL[asset] || asset, 3, pickChain);
  const name = field(box, "aa-wname", "Nom du portefeuille", input(""), "Ledger, MetaMask, Phantom…");
  const ref = el("p", "hint", "");
  box.append(ref);
  const show = () => { ref.textContent = slug(name.value) ? `Compte créé : crypto:${slug(name.value)}` : ""; };
  name.addEventListener("input", show);
  const keys = el("textarea");
  keys.spellcheck = false;
  field(box, "aa-wkeys", asset === "BTC" ? "Adresses ou xpub, une par ligne" : "Adresses publiques, une par ligne", keys);
  let boxes = {};
  if (asset === "ETH") {
    const nets = networkChecks();
    boxes = nets.boxes;
    box.append(el("label", "", "Réseaux"), nets.nets);
  }
  box.append(el("p", "hint", "Adresses publiques seulement : jamais de clé privée ni de phrase de récupération."));
  let id = null; // portefeuille enregistré au premier essai : un Face ID annulé ne le redemande pas
  actions(box, "Ajouter avec Face ID", async () => {
    const label = name.value.trim();
    if (!slug(label)) throw new Error("Donne un nom au portefeuille.");
    const account = `crypto:${slug(label)}`;
    const w = walletOf({}, account, asset, keys.value, boxes);
    if (!w.addresses && !w.xpub && !w.xpubs) throw new Error("Une adresse au moins.");
    if (!id) {
      const cs = await api(paths.connections);
      const market = cs.items.find((c) => c.connector === "market");
      const known = (market && market.settings.wallets) || [];
      if (known.some((x) => x.account === account)) throw new Error(`${account} est déjà suivi : choisis un autre nom.`);
      // tous les portefeuilles vivent dans la connexion « Cours et cryptos » ; ses autres réglages restent
      id = market
        ? (await api(`${paths.connections}/${market.id}`, { settings: { ...market.settings, wallets: [...known, w] } }, "PATCH")).id
        : (await api(paths.connections, { id: "market", connector: "market", label: "Cours et cryptos", settings: { wallets: [w] } })).id;
    }
    await createAccount({ institution: label, name: label, kind: "crypto", currency: base(), external_ref: account });
    await api(`/collectors/${id}/refresh`, {});
    close();
    say("acct-msg", `${label} ajouté : soldes et transactions lus dans la minute.`);
    return null;
  });
}

// --- à la main : le formulaire complet du compte ------------------------------------------------------

export function openAccount(preset = {}) {
  const box = editor("Nouveau compte", 0, preset.external_ref ? null : addAccount);
  const institution = field(box, "ac-institution", "Établissement", input(preset.institution || ""));
  const name = field(box, "ac-name", "Nom du compte", input(preset.name || ""));
  const kind = el("select");
  for (const [k, l] of Object.entries(KIND_LABEL)) {
    const o = el("option", "", l);
    o.value = k;
    kind.append(o);
  }
  kind.value = preset.kind || "cash";
  field(box, "ac-kind", "Type", kind);
  const currency = field(box, "ac-currency", "Devise", input(preset.currency || base()));
  const iban = field(box, "ac-iban", "IBAN (compte bancaire)", input(preset.iban || ""));
  const ref = field(box, "ac-ref", "Référence externe (sinon)", input(preset.external_ref || ""),
    "Celle des relevés : revolut:CHF, crypto:ledger, crypto:binance… Un IBAN ou une référence. Vide : un compte tenu à la main.");
  const check = (id, text, on) => {
    const l = el("label", "check");
    const b = input("", "checkbox");
    b.id = id;
    b.checked = Boolean(on);
    l.append(b, document.createTextNode(text));
    box.append(l);
    return b;
  };
  const liquid = check("ac-liquid", "Compte de liquidités", preset.liquid);
  const budget = check("ac-budget", "Suivi par le budget", preset.budget_account);
  actions(box, "Créer avec Face ID", async () => {
    const params = {
      institution: institution.value.trim(),
      name: name.value.trim(),
      kind: kind.value,
      currency: currency.value.trim().toUpperCase(),
      liquid: liquid.checked,
      budget_account: budget.checked,
    };
    if (iban.value.trim()) params.iban = iban.value.replace(/\s+/g, "").toUpperCase();
    if (ref.value.trim()) params.external_ref = ref.value.trim();
    await createAccount(params);
    close();
    say("acct-msg", `Compte « ${params.name} » créé ; ses relevés en attente sont repris.`);
    return null;
  });
}

// --- comptes que les relevés attendent : Revolut (Enable Banking), portefeuilles, plateformes ----------

function walletAccounts() {
  const cs = store.data(paths.connections);
  const out = [];
  for (const c of (cs && cs.items) || []) {
    for (const w of c.settings.wallets || []) out.push({ ref: w.account, asset: w.asset });
  }
  return out;
}

const PLATFORMS = new Set(["binance", "kucoin", "coinbase"]);

export function accountsCard() {
  const list = $("acct-pending");
  list.replaceChildren();
  const pe = store.use(paths.pending);
  const ac = store.use(paths.accounts);
  if (pe.status !== "ok" || ac.status !== "ok") {
    const e = pe.error || ac.error;
    list.append(el("div", "empty", e ? `Impossible de charger : ${e.message}` : "Chargement…"));
    return;
  }
  const known = new Set(ac.data.items.map((a) => a.external_ref).filter(Boolean));
  const todo = pe.data.items.map((p) => ({
    ref: p.ref,
    title: p.ref,
    sub: `${p.entries} écriture${p.entries > 1 ? "s" : ""} en attente${p.from ? ` du ${date(p.from)} au ${date(p.to)}` : ""}`,
    preset: { institution: p.institution, name: `${p.institution} ${p.currency || ""}`.trim(), kind: p.kind, currency: p.currency || base(), external_ref: p.ref, liquid: true, budget_account: true },
  }));
  const seen = new Set(todo.map((t) => t.ref));
  for (const w of walletAccounts()) {
    if (known.has(w.ref) || seen.has(w.ref)) continue;
    seen.add(w.ref);
    const name = w.ref.slice(7);
    todo.push({ ref: w.ref, title: w.ref, sub: `portefeuille ${w.asset} suivi, compte à créer`,
      preset: { institution: name.charAt(0).toUpperCase() + name.slice(1), name: name.charAt(0).toUpperCase() + name.slice(1), kind: "crypto", currency: base(), external_ref: w.ref } });
  }
  const cs = store.data(paths.connections);
  for (const c of (cs && cs.items) || []) {
    const ref = `crypto:${c.id}`; // le compte par défaut du collecteur d'une plateforme
    if (!PLATFORMS.has(c.connector) || known.has(ref) || seen.has(ref)) continue;
    seen.add(ref);
    todo.push({ ref, title: ref, sub: "plateforme reliée, compte à créer",
      preset: { institution: c.label, name: c.label, kind: "crypto", currency: base(), external_ref: ref } });
  }
  if (!todo.length) list.append(el("div", "empty", "Aucun compte en attente."));
  for (const t of todo) {
    const r = el("div", "row");
    const n = el("div", "n");
    n.append(el("b", "", t.title), el("span", "", t.sub));
    const v = el("div", "v");
    v.append(link("Créer", () => { go("sources", { rubric: "add-account" }); openAccount(t.preset); }));
    r.append(instAv(t.preset.institution, t.preset.institution, "av g"), n, v);
    list.append(r);
  }
}

// la connexion qui alimente un compte : portefeuille suivi, plateforme ou banque de sa référence, sinon son
// établissement ; null pour un compte tenu à la main ou par fichiers déposés
export function sourceOf(a, connections) {
  const ref = a.external_ref || "";
  const market = connections.find((c) => c.connector === "market");
  if (market && (market.settings.wallets || []).some((w) => w.account === ref)) return market;
  const head = ref.startsWith("crypto:") ? ref.slice(7) : ref.split(":")[0];
  const inst = (a.institution || "").toLowerCase();
  return (head && (connections.find((c) => c.id === head) || connections.find((c) => c.connector === head)))
    || connections.find((c) => c.label.toLowerCase() === inst) || null;
}

export function initAddAccount() {
  store.on(() => {
    if (store.params.tab !== "sources" || store.params.rubric !== "add-account") leaveAddAccount();
  });
}
