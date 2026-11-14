// État du hub › Entretien : ce que le serveur fait seul (contrôle d'intégrité, sauvegarde,
// contrôle des sauvegardes, santé, ménage de la nuit), son dernier passage et « Lancer ». Le
// planificateur prend une demande dans la minute (core.tasks) ; une tâche en échec prévient
// aussi par la notification habituelle.
import { ago } from "./format.js";
import { api, store } from "./store.js";
import { esc, failure, fill, ibox, ic, paint, toast } from "./ui.js";

const TASKS = "/tasks";
const POLL_MS = 10_000;
const LOOK = {
  "hub.verify": ["shield", "var(--s2)"], "hub.backup": ["download", "var(--accent)"],
  "hub.backup_check": ["lockc", "var(--s4)"], "hub.health": ["gauge", "var(--faint)"], "hub.housekeeping": ["gear", "var(--faint)"],
};
let poller = null;

function line(t) {
  if (t.running) return [`lancée ${ago(Date.parse(t.started_at))}`, "", "en cours…"];
  if (t.requested) return ["dans la minute", "", "en file"];
  if (!t.outcome) return [`${t.when} · pas encore passée`, "", null];
  const when = ago(Date.parse(t.ended_at));
  if (t.outcome === "failed") return [`${t.when} · échec ${when}`, "warn", null];
  return [`${t.when} · ${t.summary ? `${t.summary}, ` : "réussie "}${when}`, "", null];
}

function row(t) {
  const [sub, tone, state] = line(t);
  const [icon, color] = LOOK[t.name] || ["refresh", "var(--accent)"];
  const act = state === null ? `<button class="link" type="button" data-a="upkeep-run" data-v="${esc(t.name)}">Lancer</button>` : `<b class="muted">${state}</b>`;
  return `<div class="row">${ibox(ic(icon), color)}<div class="n"><b>${esc(t.label)}</b><span class="${tone}">${esc(sub)}</span></div><div class="v">${act}</div></div>`;
}

function follow(on) {
  if (on && !poller) poller = setInterval(() => { store.cache.delete(TASKS); store.notify(); }, POLL_MS);
  if (!on && poller) { clearInterval(poller); poller = null; }
}

export function renderUpkeep() {
  const e = store.use(TASKS), box = document.getElementById("upkeep");
  if (e.status !== "ok") {
    fill(box, `<div class="empty">${e.error ? `Impossible de charger : ${esc(e.error.message)}` : "Chargement…"}</div>`);
    return;
  }
  const mine = e.data.items.filter((t) => t.domain === "hub");
  fill(box, mine.map(row).join(""));
  paint(box);
  follow(mine.some((t) => t.requested || t.running));
}

export const actions = {
  "upkeep-run": async (name, btn) => {
    btn.disabled = true;
    try {
      const out = await api(`${TASKS}/${name}/run`, {});
      const t = out.items.find((x) => x.name === name);
      toast(`${t ? t.label : "Tâche"} : demandée, le serveur la lance dans la minute`);
    } catch (err) {
      btn.disabled = false;
      toast(failure(err), { error: true });
    } finally {
      store.cache.delete(TASKS);
      store.notify();
    }
  },
};
