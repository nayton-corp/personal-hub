// Connexions et comptes dans l'app (chantier « hub générique », G5) : ajouter une banque ou une
// plateforme, donner ses identifiants (chiffrés à la saisie, jamais relus), son horaire, ses
// réglages et ses portefeuilles, lier un consentement Enable Banking, puis créer les comptes
// dont les relevés attendent, par une proposition validée avec Face ID.
//
// La liste se redessine à chaque réponse ; les formulaires, eux, ne sont construits qu'à
// l'ouverture, pour ne jamais effacer une saisie en cours.
import { base, date, el, initials } from "./format.js";
import { approve, propose } from "./proposals.js";
import { api, store } from "./store.js";

const $ = (id) => document.getElementById(id);

export const paths = {
  states: "/collectors",
  connections: "/collectors/connections",
  catalog: "/collectors/catalog",
  accounts: "/finance/accounts",
  pending: "/finance/accounts/pending",
};

const MODE_LABEL = { enabled: "actif", degraded: "suspendu", disabled: "désactivé" };
const OUTCOME_LABEL = {
  ok: "réussi", nothing_new: "rien de nouveau", auth_pending_timeout: "validation non faite",
  auth_error: "connexion refusée", site_unavailable: "site indisponible",
  selector_missing: "page changée", invalid_file: "fichier refusé", unknown: "erreur",
};
const FIELD_LABEL = {
  contract: "Numéro de contrat", password: "Mot de passe", email: "E-mail",
  application_id: "Identifiant de l'application", private_key: "Clé privée (PEM)",
  flex_token: "Jeton Flex", query_id: "Numéro de la requête Flex", api_key: "Clé API",
  api_secret: "Secret API", passphrase: "Passphrase", key_name: "Nom de la clé",
  coingecko_key: "Clé CoinGecko (facultative)",
  aspsp_name: "Banque (nom chez Enable Banking)", aspsp_country: "Pays de la banque (ISO)",
  psu_type: "Type de compte (personal ou business)", consent_days: "Durée du consentement (jours)",
  max_syncs_per_day: "Synchronisations par jour au plus", currencies: "Devises suivies",
  crypto: "Cryptos suivies (symbole → id CoinGecko)", quotes: "Cours Yahoo (ISIN → symbole)",
};
const JSON_SETTINGS = new Set(["currencies", "crypto", "quotes"]);
const NUMBER_SETTINGS = new Set(["consent_days", "max_syncs_per_day"]);
const MULTILINE_SECRETS = new Set(["private_key"]);
const KIND_LABEL = { cash: "Cash", securities: "Titres", pension: "Prévoyance", crypto: "Crypto" };
const POLL_MS = 4000;

let busy = false;
let editing = null; // { id } ou { create: true }
let poller = null;

function say(id, text, error = false) {
  const n = $(id);
  n.textContent = text || "";
  n.classList.toggle("error", error);
}

function refresh(...keys) {
  for (const k of keys) store.cache.delete(k);
  store.notify();
}

async function act(msgId, fn) {
  if (busy) return;
  busy = true;
  say(msgId, "");
  try {
    const text = await fn();
    if (text) say(msgId, text);
  } catch (e) {
    say(msgId, e.name === "NotAllowedError" ? "Validation annulée." : e.message, true);
  } finally {
    busy = false;
    refresh(paths.states, paths.connections);
  }
}

function link(label, fn) {
  const b = el("button", "link", label);
  b.type = "button";
  b.disabled = busy;
  b.addEventListener("click", fn);
  return b;
}

function field(form, id, label, input, hint) {
  const l = el("label", "", label);
  l.htmlFor = id;
  input.id = id;
  form.append(l, input);
  if (hint) form.append(el("p", "hint", hint));
  return input;
}

function input(value, type = "text") {
  const i = el("input");
  i.type = type;
  i.value = value ?? "";
  i.autocapitalize = "off";
  i.spellcheck = false;
  return i;
}

function button(label, cls = "btn") {
  const b = el("button", cls, label);
  b.type = "button";
  return b;
}

const byName = (items) => Object.fromEntries((items || []).map((x) => [x.name ?? x.id, x]));

// --- liste --------------------------------------------------------------------------------

function sub(c, s) {
  if (!c.ready) return "identifiants à donner";
  const last = s && s.last_run;
  let text = last ? `${OUTCOME_LABEL[last.outcome] || last.outcome} le ${date(last.started_at.slice(0, 10))}` : "jamais lancé";
  if (s && s.check_requested) text += " · contrôle demandé";
  if (s && (s.link_requested || s.link_url)) text += " · liaison en cours";
  return text;
}

// mode, dernier passage et actions ; jamais de montant : le collecteur n'en remonte aucun
export function connectionsCard() {
  const list = $("coll-list");
  list.replaceChildren();
  const cs = store.use(paths.connections);
  const st = store.use(paths.states);
  if (cs.status !== "ok" || st.status !== "ok") {
    const e = cs.error || st.error;
    list.append(el("div", "empty", e ? `Impossible de charger : ${e.message}` : "Chargement…"));
    return;
  }
  const states = byName(st.data.items);
  if (!cs.data.items.length) list.append(el("div", "empty", "Aucune connexion : « Ajouter » pour la première."));
  for (const c of cs.data.items) {
    const s = states[c.id];
    const mode = s ? s.mode : "enabled";
    const r = el("div", "row");
    const av = el("div", "av", initials(c.label));
    const n = el("div", "n");
    const line = el("span", !c.ready || mode !== "enabled" ? "warn" : "", sub(c, s));
    n.append(el("b", "", c.label), line);
    const v = el("div", "v");
    v.append(el("b", mode === "enabled" && c.ready ? "muted" : "warn", c.ready ? MODE_LABEL[mode] || mode : "à régler"));
    const post = (what, body) => api(`/collectors/${c.id}/${what}`, body);
    if (s && c.ready) {
      if (mode === "enabled") {
        v.append(link("Désactiver", () => act("coll-msg", async () => { await post("mode", { mode: "disabled" }); return `${c.label} désactivé.`; })));
      } else if (s.can_enable) {
        v.append(link("Réactiver", () => act("coll-msg", async () => { await post("mode", { mode: "enabled" }); return `${c.label} réactivé.`; })));
      } else if (!s.check_requested) {
        v.append(link("Contrôler", () => act("coll-msg", async () => { await post("check", {}); return "Contrôle demandé : le collecteur le lance dans la minute."; })));
      }
    }
    v.append(link("Régler", () => open({ id: c.id })));
    r.append(av, n, v);
    list.append(r);
  }
  linkStatus();
}

// --- formulaire d'une connexion -------------------------------------------------------------

function close() {
  editing = null;
  $("conn-editor").hidden = true;
  $("conn-editor").replaceChildren();
  stopPolling();
}

function open(what) {
  editing = what;
  const box = $("conn-editor");
  box.replaceChildren(el("p", "note", "Chargement…"));
  box.hidden = false;
  Promise.all([api(paths.catalog), api(paths.connections)])
    .then(([cat, cs]) => {
      if (editing !== what) return;
      if (what.create) buildCreate(box, cat.items);
      else {
        const c = cs.items.find((x) => x.id === what.id);
        const spec = cat.items.find((x) => x.name === c?.connector);
        if (!c || !spec) return close();
        buildEdit(box, c, spec);
      }
      box.scrollIntoView({ behavior: "smooth", block: "start" });
    })
    .catch((e) => box.replaceChildren(el("p", "message error", e.message)));
}

function slug(s) {
  return s.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "").slice(0, 40);
}

function settingInput(key, value) {
  if (JSON_SETTINGS.has(key)) {
    const t = el("textarea");
    t.value = value === undefined ? "" : JSON.stringify(value, null, 1);
    t.spellcheck = false;
    return t;
  }
  return input(value, NUMBER_SETTINGS.has(key) ? "number" : "text");
}

function readSetting(key, node) {
  const raw = node.value.trim();
  if (!raw) return undefined;
  if (JSON_SETTINGS.has(key)) {
    try {
      return JSON.parse(raw);
    } catch {
      throw new Error(`${FIELD_LABEL[key] || key} : JSON invalide`);
    }
  }
  if (NUMBER_SETTINGS.has(key)) return Number(raw);
  if (key === "aspsp_country") return raw.toUpperCase();
  return raw;
}

function buildCreate(box, catalog) {
  box.replaceChildren(el("h2", "", "Nouvelle connexion"));
  const pick = el("select");
  for (const c of catalog) {
    const o = el("option", "", c.label);
    o.value = c.name;
    pick.append(o);
  }
  field(box, "conn-new-connector", "Connecteur", pick);
  const label = field(box, "conn-new-label", "Nom affiché", input(""));
  const id = field(box, "conn-new-id", "Identifiant", input(""),
    "Minuscules, chiffres et tirets ; il ne change plus (état, mémoire et adresse de retour).");
  const extra = el("div");
  box.append(extra);
  let touched = false;
  id.addEventListener("input", () => { touched = true; });
  const fill = () => {
    const spec = catalog.find((c) => c.name === pick.value);
    if (!label.value || label.dataset.auto === "1") {
      label.value = spec.label;
      label.dataset.auto = "1";
    }
    if (!touched) id.value = slug(spec.name === "enable_banking" ? "banque" : spec.name);
    extra.replaceChildren();
    for (const key of spec.required_settings) {
      const n = field(extra, `conn-new-${key}`, `${FIELD_LABEL[key] || key} *`, settingInput(key));
      n.dataset.key = key;
    }
    if (spec.name === "enable_banking") {
      extra.append(el("p", "hint", "Nom et pays tels qu'Enable Banking les liste, par exemple Revolut et LT, ou N26 et DE."));
    }
  };
  label.addEventListener("input", () => { label.dataset.auto = "0"; if (!touched) id.value = slug(label.value); });
  pick.addEventListener("change", fill);
  fill();
  const msg = el("p", "message");
  const acts = el("div", "acts");
  const go = button("Créer");
  const cancel = button("Annuler", "btn secondary");
  acts.append(go, cancel);
  box.append(acts, msg);
  cancel.addEventListener("click", close);
  go.addEventListener("click", async () => {
    go.disabled = true;
    msg.textContent = "";
    try {
      const settings = {};
      for (const n of extra.querySelectorAll("[data-key]")) {
        const v = readSetting(n.dataset.key, n);
        if (v !== undefined) settings[n.dataset.key] = v;
      }
      const c = await api(paths.connections, {
        id: id.value.trim(), connector: pick.value, label: label.value.trim() || null, settings,
      });
      refresh(paths.states, paths.connections);
      say("coll-msg", `${c.label} ajoutée : donne maintenant ses identifiants.`);
      open({ id: c.id });
    } catch (e) {
      msg.textContent = e.message;
      msg.classList.add("error");
      go.disabled = false;
    }
  });
}

function buildEdit(box, c, spec) {
  box.replaceChildren(el("h2", "", c.label));
  box.append(el("p", "note", `${spec.label} · ${c.runner === "browser" ? "navigateur" : "API"} · identifiant ${c.id}`));
  const msg = el("p", "message");

  // réglages : nom, horaire, réglages du connecteur, portefeuilles
  const label = field(box, `ce-label`, "Nom affiché", input(c.label));
  const schedule = field(box, "ce-schedule", "Horaire (cron, fuseau de l'instance)", input(c.custom_schedule ? c.schedule : ""),
    `minute heure jour mois jour-de-semaine ; vide : horaire par défaut (${spec.schedule || "aucun"}).`);
  schedule.placeholder = spec.schedule || "";
  const inputs = {};
  for (const key of spec.settings) {
    if (key === "wallets") continue;
    const req = spec.required_settings.includes(key);
    inputs[key] = field(box, `ce-${key}`, `${FIELD_LABEL[key] || key}${req ? " *" : ""}`, settingInput(key, c.settings[key]),
      JSON_SETTINGS.has(key) ? "JSON ; vide : la valeur du service (deploy/settings.toml)." : null);
  }
  const wallets = spec.settings.includes("wallets") ? walletsEditor(box, c.settings.wallets || []) : null;
  const save = button("Enregistrer les réglages");
  box.append(save);
  save.addEventListener("click", () => run(save, msg, async () => {
    const settings = {};
    for (const [key, node] of Object.entries(inputs)) {
      const v = readSetting(key, node);
      if (v !== undefined) settings[key] = v;
    }
    if (wallets) settings.wallets = wallets.read();
    const sched = schedule.value.trim();
    await api(`${paths.connections}/${c.id}`, {
      label: label.value.trim() || null,
      ...(sched ? { schedule: sched } : { default_schedule: true }),
      settings,
    }, "PATCH");
    return "Réglages enregistrés.";
  }));

  // identifiants : remplacés en bloc, jamais relus
  const fields = spec.secrets.length ? spec.secrets : (spec.name === "market" ? ["coingecko_key"] : []);
  if (fields.length) {
    box.append(el("h3", "", "Identifiants"));
    box.append(el("p", "hint", c.has_secrets
      ? `Enregistrés le ${date(c.secrets_at)}. Les remplacer demande tous les champs ; ils ne s'affichent jamais.`
      : spec.secrets.length ? "Pas encore donnés : la connexion ne tourne pas sans eux." : "Facultatifs."));
    const secretInputs = {};
    for (const key of fields) {
      const node = MULTILINE_SECRETS.has(key) ? el("textarea") : input("", "password");
      node.autocomplete = "off";
      secretInputs[key] = field(box, `ce-secret-${key}`, FIELD_LABEL[key] || key, node);
    }
    const store_ = button(c.has_secrets ? "Remplacer les identifiants" : "Enregistrer les identifiants", "btn secondary");
    box.append(store_);
    store_.addEventListener("click", () => run(store_, msg, async () => {
      const values = {};
      for (const [key, node] of Object.entries(secretInputs)) if (node.value) values[key] = node.value;
      await api(`${paths.connections}/${c.id}/secrets`, { values }, "PUT");
      for (const node of Object.values(secretInputs)) node.value = "";
      open({ id: c.id }); // relit « enregistrés le … »
      return "Identifiants chiffrés et enregistrés.";
    }));
  }

  // consentement Enable Banking
  if (c.connector === "enable_banking") {
    box.append(el("h3", "", "Consentement"));
    box.append(el("p", "hint", "Ouvre l'autorisation chez la banque (180 jours au plus). Toute l'histoire est reprise juste après, si la banque la donne."));
    const status = el("div");
    status.id = "ce-link";
    const go = button("Lier le compte", "btn secondary");
    go.disabled = !c.ready;
    box.append(status, go);
    go.addEventListener("click", () => run(go, msg, async () => {
      await api(`/collectors/${c.id}/link`, {});
      startPolling();
      return "Liaison demandée : le service prépare l'autorisation (une minute au plus).";
    }));
  }

  box.append(el("h3", "", "Retirer"));
  box.append(el("p", "hint", "Retire la connexion et son état ; l'historique des passages reste, les comptes aussi."));
  const acts = el("div", "acts");
  const del = button("Retirer la connexion", "btn danger");
  const done = button("Fermer", "btn secondary");
  acts.append(del, done);
  box.append(acts, msg);
  done.addEventListener("click", close);
  del.addEventListener("click", () => {
    if (!window.confirm(`Retirer ${c.label} ?`)) return;
    run(del, msg, async () => {
      await api(`${paths.connections}/${c.id}`, undefined, "DELETE");
      close();
      say("coll-msg", `${c.label} retirée.`);
      return null;
    });
  });
  linkStatus();
}

async function run(btn, msg, fn) {
  btn.disabled = true;
  msg.textContent = "";
  msg.classList.remove("error");
  try {
    const text = await fn();
    if (text) msg.textContent = text;
  } catch (e) {
    msg.textContent = e.message;
    msg.classList.add("error");
  } finally {
    btn.disabled = false;
    refresh(paths.states, paths.connections);
  }
}

// --- portefeuilles (connecteur market) ------------------------------------------------------

function walletsEditor(box, initial) {
  box.append(el("h3", "", "Portefeuilles"));
  box.append(el("p", "hint", "Adresses publiques, ou clé publique étendue (xpub, ypub, zpub) d'un compte BTC. Jamais de clé privée ni de phrase de récupération."));
  const list = el("div");
  box.append(list);
  const add = button("Ajouter un portefeuille", "btn secondary");
  box.append(add);
  const rows = [];

  const addRow = (w = {}) => {
    const wrap = el("div", "wallet form");
    const i = rows.length;
    const account = field(wrap, `w-${i}-account`, "Compte (crypto:nom)", input(w.account || "crypto:"));
    const asset = el("select");
    for (const a of ["BTC", "ETH", "SOL"]) {
      const o = el("option", "", a);
      o.value = a;
      asset.append(o);
    }
    asset.value = (w.asset || "BTC").toUpperCase();
    field(wrap, `w-${i}-asset`, "Crypto", asset);
    const keys = el("textarea");
    keys.value = [...(w.xpubs || (w.xpub ? [w.xpub] : [])), ...(w.addresses || [])].join("\n");
    keys.spellcheck = false;
    field(wrap, `w-${i}-keys`, "Adresses ou xpub, une par ligne", keys);
    const remove = link("Retirer", () => { wrap.remove(); row.removed = true; });
    wrap.append(remove);
    const row = { w, account, asset, keys, removed: false };
    rows.push(row);
    list.append(wrap);
  };
  for (const w of initial) addRow(w);
  add.addEventListener("click", () => addRow());

  return {
    read() {
      return rows.filter((r) => !r.removed).map((r) => {
        const lines = r.keys.value.split(/\s+/).map((s) => s.trim()).filter(Boolean);
        const xpubs = lines.filter((s) => /^[xyz]pub/.test(s));
        const addresses = lines.filter((s) => !/^[xyz]pub/.test(s));
        const { xpub: _x, xpubs: _xs, addresses: _a, ...rest } = r.w;
        const out = { ...rest, account: r.account.value.trim(), asset: r.asset.value };
        if (xpubs.length === 1) out.xpub = xpubs[0];
        else if (xpubs.length) out.xpubs = xpubs;
        if (addresses.length) out.addresses = addresses;
        return out;
      });
    },
  };
}

// --- liaison : adresse à ouvrir, rafraîchie tant qu'elle se prépare --------------------------

function linkStatus() {
  const node = document.getElementById("ce-link");
  if (!node || !editing || editing.create) return;
  const st = store.data(paths.states);
  const s = st && st.items.find((x) => x.name === editing.id);
  node.replaceChildren();
  if (!s) return;
  if (s.link_url) {
    const a = el("a", "btn", "Ouvrir la banque pour valider");
    a.href = s.link_url;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    node.append(a, el("p", "hint", "Valide chez la banque (de préférence sur le téléphone de l'app bancaire) ; le retour arrive sur le hub et la reprise démarre."));
    startPolling();
  } else if (s.link_requested) {
    node.append(el("p", "hint", "Le service collecteur prépare l'autorisation…"));
    startPolling();
  } else {
    if (s.last_run && s.last_run.kind === "check") {
      const ok = s.last_run.outcome === "ok";
      node.append(el("p", `hint ${ok ? "ok" : "bad"}`, `Dernière liaison ou contrôle : ${OUTCOME_LABEL[s.last_run.outcome] || s.last_run.outcome} le ${date(s.last_run.started_at.slice(0, 10))}.`));
    }
    stopPolling();
  }
}

function startPolling() {
  if (poller) return;
  poller = setInterval(() => refresh(paths.states), POLL_MS);
}

function stopPolling() {
  if (poller) clearInterval(poller);
  poller = null;
}

// --- comptes ---------------------------------------------------------------------------------

function walletAccounts() {
  const cs = store.data(paths.connections);
  const out = [];
  for (const c of (cs && cs.items) || []) {
    for (const w of c.settings.wallets || []) out.push({ ref: w.account, asset: w.asset });
  }
  return out;
}

const PLATFORM_LABEL = { binance: "Binance", kucoin: "KuCoin", coinbase: "Coinbase" };

// comptes que les relevés attendent : Revolut (Enable Banking), portefeuilles, plateformes
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
    const ref = `crypto:${c.connector}`;
    if (!PLATFORM_LABEL[c.connector] || known.has(ref) || seen.has(ref)) continue;
    seen.add(ref);
    todo.push({ ref, title: ref, sub: "plateforme reliée, compte à créer",
      preset: { institution: PLATFORM_LABEL[c.connector], name: PLATFORM_LABEL[c.connector], kind: "crypto", currency: base(), external_ref: ref } });
  }
  if (!todo.length) list.append(el("div", "empty", "Aucun compte en attente."));
  for (const t of todo) {
    const r = el("div", "row");
    const n = el("div", "n");
    n.append(el("b", "", t.title), el("span", "", t.sub));
    const v = el("div", "v");
    v.append(link("Créer", () => openAccount(t.preset)));
    r.append(el("div", "av g", initials(t.preset.institution)), n, v);
    list.append(r);
  }
}

function openAccount(preset = {}) {
  const box = $("acct-editor");
  box.replaceChildren(el("h2", "", "Nouveau compte"));
  box.hidden = false;
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
    "Celle des relevés : revolut:CHF, crypto:ledger, crypto:binance… Un IBAN ou une référence.");
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
  const msg = el("p", "message");
  const acts = el("div", "acts");
  const go = button("Créer avec Face ID");
  const cancel = button("Annuler", "btn secondary");
  acts.append(go, cancel);
  box.append(acts, msg);
  cancel.addEventListener("click", () => { box.hidden = true; box.replaceChildren(); });
  go.addEventListener("click", () => run(go, msg, async () => {
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
    const p = await propose("create_account", params);
    const [result] = await approve([p.id]);
    if (!result || result.status !== "applied") {
      const why = result && result.problem && (result.problem.detail || result.problem.title);
      throw new Error(why || "Proposition non appliquée : relis-la dans l'accueil.");
    }
    box.hidden = true;
    box.replaceChildren();
    say("acct-msg", `Compte « ${params.name} » créé ; ses relevés en attente sont repris.`);
    store.invalidate();
    return null;
  }));
  box.scrollIntoView({ behavior: "smooth", block: "start" });
}

export function initConnections() {
  $("conn-add").addEventListener("click", () => open({ create: true }));
  $("acct-add").addEventListener("click", () => openAccount());
}
