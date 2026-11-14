// État des sources : « Tout actualiser » (les connexions, puis les calculs de la nuit) et la
// carte Calculs, une ligne par morceau de la nuit de la Finance avec son dernier passage et son
// « Actualiser ». Le planificateur du serveur prend une demande dans la minute (core.tasks) ;
// tant qu'une tâche attend ou tourne, la carte se relit toute seule.
import { ago } from "../../format.js";
import { api, store } from "../../store.js";
import { esc, failure, fill, ibox, ic, paint, toast } from "../../ui.js";
import { paths as conn, refreshHints } from "./connections.js";

export const TASKS = "/tasks";
const POLL_MS = 10_000;
const LOOK = {
  snapshots: ["trend", "var(--s1)"], strategies: ["repeat", "var(--s2)"], sentinels: ["alert", "var(--s3)"],
  reviews: ["doc", "var(--s4)"], compositions: ["grid", "var(--s5)"], ledger: ["shield", "var(--faint)"],
};
const $ = (id) => document.getElementById(id);
let poller = null;
let busy = false;

const mine = (items) => items.filter((t) => t.domain === "finance");
const waits = (t) => t.requested || t.running;

// ce que la ligne dit : où en est la tâche, sinon son horaire et son dernier passage
export function taskLine(t) {
  if (t.running) return [`lancée ${ago(Date.parse(t.started_at))}`, "", "en cours…"];
  if (t.requested) return [t.after_sources ? "après les sources" : "dans la minute", "", "en file"];
  if (!t.available) return [`${t.when} · aucune connexion active`, "", ""];
  if (!t.outcome) return [`${t.when} · pas encore lancée`, "", null];
  const when = ago(Date.parse(t.ended_at));
  if (t.outcome === "failed") return [`${t.when} · échec ${when}`, "warn", null];
  return [`${t.when} · ${t.summary ? `${t.summary}, ` : "réussi "}${when}`, "", null];
}

function row(t) {
  const [sub, tone, state] = taskLine(t);
  const [icon, color] = LOOK[t.name.split(".")[1]] || ["refresh", "var(--accent)"];
  const run = `<button class="link" type="button" data-a="task-run" data-v="${esc(t.name)}">Actualiser</button>`;
  const act = state === null ? run : state ? `<b class="muted">${state}</b>` : "";
  return `<div class="row">${ibox(ic(icon), color)}<div class="n"><b>${esc(t.label)}</b><span class="${tone}">${esc(sub)}</span></div><div class="v">${act}</div></div>`;
}

// le rapprochement n'a pas de tâche : il se refait à chaque lecture du patrimoine
const LIVE = `<div class="row">${ibox(ic("swap"), "var(--s6)")}<div class="n"><b>Rapprochement</b>
  <span>refait à chaque ouverture · toujours à jour</span></div><div class="v"><b class="muted">à jour</b></div></div>`;

// relit les tâches tant que l'une attend ou tourne ; à la fin, tous les chiffres se relisent
// (nouvelles cartes « À valider », courbe recalculée)
export function follow(on) {
  if (on && !poller) poller = setInterval(() => { store.cache.delete(TASKS); store.cache.delete(conn.states); store.notify(); }, POLL_MS);
  if (!on && poller) {
    clearInterval(poller);
    poller = null;
    setTimeout(() => store.invalidate(), 0);
  }
}

// la tâche `name` de la finance telle que l'app la connaît (null tant qu'elle n'est pas lue)
export function financeTask(name) {
  const e = store.use(TASKS);
  return e.data ? e.data.items.find((t) => t.name === name) || null : null;
}

export function tasksCard() {
  const e = store.use(TASKS), st = store.use(conn.states);
  const box = $("task-list");
  if (e.status !== "ok") {
    fill(box, `<div class="empty">${e.error ? `Impossible de charger : ${esc(e.error.message)}` : "Chargement…"}</div>`);
    return;
  }
  const items = mine(e.data.items);
  fill(box, items.map(row).join("") + LIVE);
  paint(box);
  const sources = st.data ? st.data.items.some((s) => s.run_requested) : false;
  const going = sources || items.some(waits);
  follow(going);
  const btn = $("conn-refresh");
  btn.disabled = busy || going;
  btn.textContent = going ? "Actualisation en cours…" : "Tout actualiser maintenant";
  $("all-note").textContent = going
    ? "En cours : les sources d'abord, puis les calculs. Tu peux quitter la page, le hub continue."
    : "Relit toutes les sources, puis refait les calculs de la nuit. Compte quelques minutes ; une banque peut te demander de valider sur ton téléphone.";
}

async function act(msg, fn) {
  if (busy) return;
  busy = true;
  $(msg).textContent = "";
  $(msg).classList.remove("error");
  try {
    $(msg).textContent = (await fn()) || "";
  } catch (err) {
    $(msg).textContent = err.message;
    $(msg).classList.add("error");
  } finally {
    busy = false;
    store.cache.delete(TASKS);
    store.cache.delete(conn.states);
    store.notify();
  }
}

// une tâche, depuis la carte Calculs ou depuis un écran (« Chercher maintenant » des stratégies) ;
// la réponse passe par un toast, visible d'où qu'on l'ait demandée
export async function runTask(name) {
  if (busy) return;
  busy = true;
  try {
    const out = await api(`${TASKS}/${name}/run`, {});
    const t = out.items.find((x) => x.name === name);
    toast(`${t ? t.label : "Tâche"} : demandée, le hub la lance dans la minute`);
  } catch (err) {
    toast(failure(err), { error: true });
  } finally {
    busy = false;
    store.cache.delete(TASKS);
    store.cache.delete(conn.states);
    store.notify();
  }
}

async function refreshAll() {
  await act("all-msg", async () => {
    await api(`${TASKS}/refresh`, {});
    const states = await api(conn.states);
    const asked = states.items.filter((s) => s.run_requested);
    const hints = await refreshHints();
    const todo = [...new Set(asked.map((s) => hints[s.connector]).filter(Boolean))];
    const what = asked.length ? `${asked.length} connexion${asked.length > 1 ? "s" : ""}, puis les calculs.` : "Aucune connexion active : les calculs seulement.";
    return `${what}${todo.length ? ` ${todo.join(" ")}` : ""}`;
  });
}

export const actions = {
  "task-run": (v) => runTask(v),
};

export function initTasks() {
  $("conn-refresh").addEventListener("click", refreshAll);
}
