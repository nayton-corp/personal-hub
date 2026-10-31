// L'assistant dans l'app (cœur) : l'orbe au centre de la barre du bas, sur tous les écrans, et
// l'écran de la conversation. Toucher l'orbe ouvre la conversation ; la maintenir écoute (le son
// part au hub, qui le relaie à l'assistant du Mac). Hors de la conversation, la réponse sort de
// l'orbe dans une carte de verre qui reste jusqu'à ce qu'on la ferme ; une pastille signale une
// réponse pas encore lue. L'assistant garde la conversation ; l'app ne garde rien.
import { mountOrb } from "./orb.js";
import { ApiError, api, store } from "./store.js";
import { announce, esc, ic, pref, setPref } from "./ui.js";

const $ = (id) => document.getElementById(id);
const HOLD_MS = 350; // au-delà, un appui devient une écoute
const HINTS = 3; // l'aide « touche / maintiens » s'affiche aux premières ouvertures
const SUGGEST = ["Quoi de neuf ?", "Mes dépenses ce mois", "Entretiens à faire"];

const S = {
  status: null, // { configured, ok, voice }
  items: null, // la conversation, du plus ancien au plus récent
  error: null,
  busy: false,
  unread: false,
  card: null, // la réponse montrée hors de la conversation
  listening: false,
};
let orb = null;
let big = null;
let open = () => {};
let here = () => false;

// --- humeur de l'orbe -------------------------------------------------------------------------

function mood() {
  if (S.listening) return "listening";
  if (S.busy) return "thinking";
  if (S.status && !S.status.ok) return "offline";
  if (S.speaking) return "speaking";
  return "idle";
}

function paintOrb() {
  const m = mood();
  if (orb) orb.set(m);
  if (big) big.set(m);
  $("orb").querySelector(".dot").hidden = !S.unread;
  const label = S.status && !S.status.ok ? "Assistant (hors ligne)" : "Assistant";
  $("orb").setAttribute("aria-label", `${label} : toucher pour écrire, maintenir pour parler${S.unread ? ", réponse non lue" : ""}`);
}

function speak(text) {
  S.speaking = true;
  paintOrb();
  clearTimeout(S.speakT);
  S.speakT = setTimeout(() => {
    S.speaking = false;
    paintOrb();
  }, Math.min(6000, 1200 + String(text || "").length * 45));
}

// --- échanges ---------------------------------------------------------------------------------

async function refresh() {
  try {
    S.status = await api("/assistant/status");
  } catch {
    S.status = { configured: true, ok: false, voice: false };
  }
  paintOrb();
  if (!S.status.ok) return store.notify();
  try {
    S.items = (await api("/assistant/history")).items;
    S.error = null;
  } catch (e) {
    S.error = e.message;
  }
  store.notify();
}

function reason(e) {
  if (e instanceof ApiError && e.type && e.type.endsWith("unconfigured")) return "Aucun assistant n'est relié au hub.";
  if (e instanceof ApiError && e.status === 503) return "L'assistant ne répond pas : le Mac dort peut-être.";
  return e.message || "L'assistant a trébuché.";
}

function answered(question, a, voice) {
  const item = { kind: "talk", at: new Date().toISOString(), text: a.heard ?? question, answer: a.answer, voice };
  S.items = [...(S.items || []), item];
  if (!here()) {
    S.card = item;
    S.unread = true;
  }
  if (a.speech && a.speech.data) {
    const bytes = Uint8Array.from(atob(a.speech.data), (c) => c.charCodeAt(0));
    const audio = new Audio(URL.createObjectURL(new Blob([bytes], { type: a.speech.mime })));
    audio.play().catch(() => {});
  }
  announce(a.answer);
  speak(a.answer);
}

async function send(question) {
  const text = question.trim();
  if (!text || S.busy) return;
  S.busy = true;
  S.pending = text;
  paintOrb();
  store.notify();
  try {
    answered(text, await api("/assistant/talk", { text }), false);
  } catch (e) {
    S.error = reason(e);
    if (!here()) S.card = { text, answer: S.error, failed: true };
  } finally {
    S.busy = false;
    S.pending = null;
    paintOrb();
    store.notify();
  }
}

// --- écoute -----------------------------------------------------------------------------------

let rec = null;
let chunks = [];

async function listen() {
  if (S.busy || S.listening) return;
  if (!navigator.mediaDevices || !window.MediaRecorder || (S.status && !S.status.voice)) {
    open();
    return;
  }
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch {
    open(); // micro refusé : on écrit
    return;
  }
  chunks = [];
  rec = new MediaRecorder(stream);
  rec.ondataavailable = (e) => chunks.push(e.data);
  rec.start();
  S.listening = true;
  showListen(true);
}

function stopListening(cancel) {
  if (!rec) return;
  const r = rec;
  rec = null;
  r.onstop = async () => {
    for (const t of r.stream.getTracks()) t.stop();
    S.listening = false;
    showListen(false);
    if (cancel || !chunks.length) return paintOrb();
    const blob = new Blob(chunks, { type: r.mimeType || "audio/webm" });
    S.busy = true;
    paintOrb();
    try {
      const res = await fetch("/api/assistant/voice", { method: "POST", body: blob, headers: { "Content-Type": blob.type }, credentials: "same-origin" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new ApiError(data.title || `Erreur ${res.status}`, res.status, data.type);
      answered(data.heard || "", data, true);
    } catch (e) {
      S.card = { text: "", answer: reason(e), failed: true };
    } finally {
      S.busy = false;
      paintOrb();
      store.notify();
    }
  };
  r.stop();
}

function showListen(on) {
  const box = $("listen");
  box.hidden = !on;
  if (on) {
    big = mountOrb(box.querySelector("canvas"), "listening");
  } else if (big) {
    big.dispose();
    big = null;
  }
  paintOrb();
}

// --- l'orbe de la barre -------------------------------------------------------------------------

function wireOrb() {
  const b = $("orb");
  orb = mountOrb(b.querySelector("canvas"), "idle");
  let timer = 0;
  let held = false;
  let startY = 0;
  b.addEventListener("pointerdown", (e) => {
    held = false;
    startY = e.clientY;
    clearTimeout(timer);
    timer = setTimeout(() => {
      held = true;
      listen();
    }, HOLD_MS);
  });
  const end = (cancel) => (e) => {
    clearTimeout(timer);
    if (held) stopListening(cancel || e.clientY - startY > 60); // glisser vers le bas annule
  };
  b.addEventListener("pointerup", end(false));
  b.addEventListener("pointercancel", end(true));
  b.addEventListener("contextmenu", (e) => e.preventDefault());
  b.addEventListener("click", (e) => {
    e.preventDefault();
    if (held) {
      held = false;
      return;
    }
    open();
  });
}

// --- rendu ------------------------------------------------------------------------------------

const time = (at) => new Date(at).toLocaleTimeString("fr-CH", { hour: "2-digit", minute: "2-digit" });

function bubbles() {
  const out = [];
  for (const i of S.items || []) {
    if (i.kind === "message") {
      out.push(`<div class="bot"><b>${esc(i.title)}</b><span>${esc(i.text)}</span></div>`);
      continue;
    }
    if (i.text) out.push(`<p class="me">${esc(i.text)}<small>${i.voice ? "dit · " : ""}${time(i.at)}</small></p>`);
    out.push(`<div class="bot"><span>${esc(i.answer)}</span></div>`);
  }
  if (S.pending) out.push(`<p class="me">${esc(S.pending)}</p><div class="bot typing" aria-label="L'assistant réfléchit"><i></i><i></i><i></i></div>`);
  return out.join("");
}

export function render() {
  S.unread = false;
  S.card = null;
  paintOrb();
  const chat = $("chat");
  let html;
  if (!S.status) html = '<p class="chat-note">Connexion à l\'assistant…</p>';
  else if (!S.status.configured) html = '<p class="chat-note">Aucun assistant n\'est relié au hub. Renseigne la section <code>[assistant]</code> des réglages du hub.</p>';
  else if (!S.status.ok) html = '<p class="chat-note">L\'assistant ne répond pas : le Mac dort peut-être. L\'orbe est grise tant qu\'il est injoignable.</p>';
  else html = bubbles() || '<p class="chat-note">Pose une question, ou maintiens l\'orbe pour parler.</p>';
  if (S.error && S.status && S.status.ok) html += `<p class="chat-note warn" role="alert">${esc(S.error)}</p>`;
  chat.innerHTML = html;
  $("suggest").innerHTML = SUGGEST.map((s) => `<button type="button" data-a="ask" data-v="${esc(s)}">${esc(s)}</button>`).join("");
  $("ask").disabled = S.busy;
  requestAnimationFrame(() => window.scrollTo(0, document.documentElement.scrollHeight));
}

// la carte de verre et l'aide, au-dessus de la barre, hors de la conversation
export function after() {
  const card = $("orbAnswer");
  const c = here() ? null : S.card;
  card.hidden = !c;
  if (c) {
    card.innerHTML = `<p class="answer-text">${esc(c.answer)}</p>${c.text ? `<span class="said">Tu as dit « ${esc(c.text)} »</span>` : ""}
      <div class="pills"><button class="pill p1" type="button" data-a="assistant-open">Ouvrir la discussion</button><button class="pill p3" type="button" data-a="assistant-close">Fermer</button></div>`;
  }
  const seen = Number(pref("orbHints", 0));
  $("orbHint").hidden = Boolean(c) || store.params.tab !== "accueil" || seen >= HINTS;
}

export const actions = {
  ask: (v) => send(v),
  "assistant-open": () => open(),
  "assistant-close": () => {
    S.card = null;
    store.notify();
  },
};

export function init(opts) {
  open = opts.open;
  here = opts.here;
  setPref("orbHints", Number(pref("orbHints", 0)) + 1);
  $("ask-send").innerHTML = ic("send");
  $("askForm").addEventListener("submit", (e) => {
    e.preventDefault();
    const v = $("ask").value;
    $("ask").value = "";
    send(v);
  });
  wireOrb();
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") refresh();
  });
  refresh();
}
