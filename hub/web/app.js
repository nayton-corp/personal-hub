// Coquille de l'app (L0-09) : connexion par passkey, puis les écrans Finance (finance.js). Aucun
// script en ligne : la CSP de Caddy n'autorise que les fichiers servis par le hub.
import { start } from "./finance.js";
import { setBase } from "./format.js";
import { api, setTimeZone, store, timeZone } from "./store.js";
import { toast } from "./ui.js";
import { creationOptions, credentialJSON, requestOptions } from "./webauthn.js";

const $ = (id) => document.getElementById(id);
const AUTH_VIEWS = ["loading", "bootstrap", "login"];
let started = false;

function showAuth(name) {
  for (const v of AUTH_VIEWS) $(`view-${v}`).hidden = v !== name;
  $("auth").hidden = false;
  $("shell").hidden = true;
  $("tabbar").hidden = true;
}

// connecté : un message éphémère ; sinon, sous le formulaire de connexion
function say(text, error = false) {
  if (!$("shell").hidden) {
    if (text) toast(text, { error });
    return;
  }
  const el = $("message");
  el.textContent = text || "";
  el.classList.toggle("error", error);
}

// « 2026-10-28 09:12:03 » (SQLite) n'est pas lu par Safari : il faut le T et le fuseau
function when(v) {
  if (v == null || v === "") return null;
  if (typeof v === "number") return new Date(v < 1e12 ? v * 1000 : v);
  let s = String(v).trim().replace(" ", "T");
  if (/T\d{2}:\d{2}(:\d{2}(\.\d+)?)?$/.test(s)) s += "Z";
  const d = new Date(s);
  return Number.isNaN(d.getTime()) ? null : d;
}
const fmt = (v) => {
  const d = when(v);
  return d ? d.toLocaleString("fr-CH", { timeZone: timeZone(), day: "numeric", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit" }) : "—";
};

function row(dl, label, value, ok) {
  const dt = document.createElement("dt");
  dt.textContent = label;
  const dd = document.createElement("dd");
  dd.textContent = value;
  if (ok !== undefined) dd.className = ok ? "ok" : "bad";
  dl.append(dt, dd);
}

function renderProfile(p) {
  const tz = setTimeZone(p.timezone);
  const ccy = setBase(p.currency);
  if (tz || ccy) store.invalidate();
  $("profile-name").value = p.display_name || "";
  $("profile-country").value = p.country;
  const modules = p.modules.length ? ` · modules : ${p.modules.join(", ")}` : "";
  $("profile-info").textContent = `Fuseau ${p.timezone} (HUB_TZ) · devise ${p.currency} (HUB_CURRENCY)${modules}.`;
}

async function renderSettings(session) {
  const [health, keys, profile] = await Promise.all([api("/health"), api("/auth/passkeys"), api("/profile")]);
  renderProfile(profile);
  const dl = $("health");
  dl.replaceChildren();
  row(dl, "Hub", `${health.status} · v${health.version}`, health.status === "ok");
  row(dl, "core.db", health.core.db, health.core.ok);
  const domains = Object.entries(health.domains);
  if (domains.length === 0) row(dl, "Domaines", "aucun pour l'instant");
  for (const [name, d] of domains) row(dl, name, `${d.db} · schéma ${d.schema_version}`, d.ok);
  $("session-info").textContent = `Connecté jusqu'au ${fmt(session.expires_at)}.`;
  const ul = $("passkeys");
  ul.replaceChildren();
  for (const k of keys.items) {
    const li = document.createElement("li");
    const name = document.createElement("span");
    name.textContent = k.device_name || "Passkey";
    const when = document.createElement("small");
    when.textContent = `ajoutée le ${fmt(k.created_at)}`;
    li.append(name, when);
    ul.append(li);
  }
  const badge = $("badge");
  badge.hidden = false;
  badge.textContent = keys.items.length < 2 ? "1 seule passkey" : `${keys.items.length} passkeys`;
  badge.className = `badge ${keys.items.length < 2 ? "bad" : "ok"}`;
}

async function enter(session) {
  $("auth").hidden = true;
  $("shell").hidden = false;
  $("tabbar").hidden = false;
  if (!started) {
    started = true;
    start();
  }
  await renderSettings(session);
}

async function refresh() {
  try {
    const session = await api("/auth/session");
    if (session.authenticated) return enter(session);
    showAuth(session.needs_bootstrap ? "bootstrap" : "login");
  } catch (e) {
    showAuth("login");
    say(`Hub injoignable : ${e.message}`, true);
  }
}

async function register(code, deviceName) {
  const begin = await api("/auth/passkey/register/begin", { bootstrap_code: code || null });
  const cred = await navigator.credentials.create({ publicKey: creationOptions(begin.options) });
  await api("/auth/passkey/register/finish", {
    challenge_id: begin.challenge_id,
    credential: credentialJSON(cred),
    device_name: deviceName || null,
    bootstrap_code: code || null,
  });
}

async function login() {
  const begin = await api("/auth/passkey/login/begin", {});
  const cred = await navigator.credentials.get({ publicKey: requestOptions(begin.options) });
  await api("/auth/passkey/login/finish", { challenge_id: begin.challenge_id, credential: credentialJSON(cred) });
}

function guard(fn) {
  return async (event) => {
    event.preventDefault();
    const button = event.submitter || event.currentTarget;
    if (button) button.disabled = true;
    say("");
    try {
      await fn();
      await refresh();
    } catch (e) {
      say(e.name === "NotAllowedError" ? "Opération annulée." : e.message, true);
    } finally {
      if (button) button.disabled = false;
    }
  };
}

$("form-bootstrap").addEventListener("submit", guard(async () => {
  await register($("code").value.trim(), $("device").value.trim());
  say("Passkey créée. Ajoute maintenant une passkey de secours.");
}));
$("btn-login").addEventListener("click", guard(login));
$("form-backup").addEventListener("submit", guard(async () => {
  await register(null, $("backup-name").value.trim() || "Passkey de secours");
  $("backup-name").value = "";
  store.invalidate(); // les premiers pas comptent les passkeys
  say("Passkey de secours ajoutée.");
}));
$("form-profile").addEventListener("submit", guard(async () => {
  await api("/profile", {
    display_name: $("profile-name").value.trim(),
    country: $("profile-country").value.trim().toUpperCase(),
  });
  store.invalidate(); // le pays ouvre ou ferme le pilier 3a des chiffres clés
  say("Profil enregistré.");
}));
window.addEventListener("hub:auth", () => refresh());

if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
refresh();
