// Coquille de l'app (L0-09) : connexion par passkey et page d'état. Aucun script en ligne :
// la CSP de Caddy n'autorise que les fichiers servis par le hub.
import { creationOptions, credentialJSON, requestOptions } from "./webauthn.js";

const $ = (id) => document.getElementById(id);
const views = ["loading", "bootstrap", "login", "status"];

function show(name) {
  for (const v of views) $(`view-${v}`).hidden = v !== name;
}

function say(text, error = false) {
  const el = $("message");
  el.textContent = text || "";
  el.classList.toggle("error", error);
}

async function api(path, body) {
  const res = await fetch(`/api${path}`, {
    method: body === undefined ? "GET" : "POST",
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    credentials: "same-origin",
  });
  if (res.status === 204) return null;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error(data.title || `Erreur ${res.status}`);
    err.type = data.type;
    throw err;
  }
  return data;
}

const fmt = (iso) => (iso ? new Date(iso).toLocaleString("fr-CH", { timeZone: "Europe/Zurich" }) : "—");

function row(dl, label, value, ok) {
  const dt = document.createElement("dt");
  dt.textContent = label;
  const dd = document.createElement("dd");
  dd.textContent = value;
  if (ok !== undefined) dd.className = ok ? "ok" : "bad";
  dl.append(dt, dd);
}

async function renderStatus(session) {
  const [health, keys] = await Promise.all([api("/health"), api("/auth/passkeys")]);
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
  show("status");
}

async function refresh() {
  try {
    const session = await api("/auth/session");
    if (session.authenticated) return renderStatus(session);
    $("badge").hidden = true;
    show(session.needs_bootstrap ? "bootstrap" : "login");
  } catch (e) {
    show("login");
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
  say("Passkey de secours ajoutée.");
}));
$("btn-logout").addEventListener("click", guard(() => api("/auth/logout", {})));

if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
refresh();
