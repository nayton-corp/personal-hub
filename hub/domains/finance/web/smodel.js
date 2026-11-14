// Stratégies : ce qui se calcule sans écran. La phrase d'une stratégie pendant qu'on la règle
// (le serveur écrit la même une fois enregistrée), les choix proposés (des seuils larges, jamais
// de réglage fin : ce n'est pas du trading), les réglages envoyés à `save_strategy`.

export const KIND = {
  recurring: { label: "Investir régulièrement", hint: "Un achat à date fixe, que le hub te rappelle", icon: "repeat", color: "var(--s1)" },
  dip: { label: "Profiter d'une grosse baisse", hint: "Un achat prévu si le cours chute vraiment", icon: "bolt", color: "var(--s3)" },
  ladder: { label: "Sortir d'une position", hint: "Vendre par paliers quand le prix d'achat est retrouvé", icon: "layers", color: "var(--s4)" },
};
// la quatrième intention, annoncée mais pas encore là
export const SOON = { label: "Garder mon équilibre", hint: "Une répartition cible, un plafond", icon: "shield", color: "var(--faint)" };
// niveaux d'un palier, en % du prix d'achat ; parts à vendre ; baisses ; fenêtres du plus haut
export const LEVELS = [80, 90, 100, 110, 120, 130, 150, 175, 200, 250, 300, 500];
export const PARTS = [10, 20, 25, 33, 50, 75, 100];
export const DROPS = [15, 20, 25, 30, 40, 50];
export const WINDOWS = [[90, "des 3 derniers mois"], [365, "des 12 derniers mois"]];
export const WEEKDAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"];
export const MAX_TIERS = 4;
export const MIN_GAP = 10;
// modèles de paliers : deux façons courantes de sortir
export const TEMPLATES = [
  { k: "even", label: "Sortir sans perte", hint: "La moitié au prix d'achat, le reste à +20 %", tiers: [[100, 50], [120, 100]] },
  { k: "stake", label: "Récupérer ma mise", hint: "La moitié quand la valeur a doublé", tiers: [[200, 50]] },
];

export const levelLabel = (at) => (at === 100 ? "au prix d'achat" : at > 100 ? `à +${at - 100} %` : `à −${100 - at} %`);
const tierText = (at) => (at === 100 ? "revient à son prix d'achat" : at > 100 ? `dépasse son prix d'achat de ${at - 100} %` : `remonte à ${100 - at} % sous son prix d'achat`);

// « 200 CHF » pour un montant rond, « 212.50 CHF » sinon ; `n0`, `n2` : les nombres de l'app
export const roundMoney = (minor, exp, ccy, n0, n2) => {
  const v = minor / 10 ** exp;
  return `${Number.isInteger(v) ? n0(v) : n2(v)} ${ccy}`;
};
export const dayLabel = (d) => (Number(d) === 1 ? "1er" : String(d));

// la stratégie en une phrase ; `money(centimes)` rend « 200 CHF » ; `account` : une cible compte
// (les versements sur un 3a), où l'on verse au lieu d'acheter
export function phrase(kind, name, p, money, account = false) {
  if (kind === "ladder") {
    const tiers = [...p.tiers].sort((a, b) => a.at_pct - b.at_pct);
    if (!tiers.length) return "";
    const [first, ...rest] = tiers;
    return `Quand ${name} ${tierText(first.at_pct)}, j'en vends ${first.sell_pct} %${rest.map((t) => ` ; ${levelLabel(t.at_pct)}, ${t.sell_pct} %`).join("")}.`;
  }
  if (!p.amount_minor) return "";
  if (kind === "recurring") {
    const when = p.cadence === "weekly" ? `Chaque ${WEEKDAYS[p.day]}` : `Le ${dayLabel(p.day)} du mois`;
    return account ? `${when}, je verse ${money(p.amount_minor)} sur ${name}.` : `${when}, j'achète pour ${money(p.amount_minor)} de ${name}.`;
  }
  const win = (WINDOWS.find(([d]) => d === p.window_days) || WINDOWS[0])[1];
  return `Si ${name} baisse de ${p.drop_pct} % depuis son plus haut ${win}, j'en achète pour ${money(p.amount_minor)}.`;
}

// « 1'250,50 » → centimes ; vide ou illisible → null
export function minor(text, exp = 2) {
  const t = String(text ?? "").replace(/['’\s]/g, "").replace(",", ".");
  return /^\d+(\.\d{1,2})?$/.test(t) ? Math.round(Number(t) * 10 ** exp) : null;
}

// le formulaire de départ d'un genre, ou celui d'une stratégie à modifier
export function initial(kind, s, exp = 2) {
  const p = s ? s.params : {};
  const amount = p.amount_minor ? String(p.amount_minor / 10 ** exp) : "";
  return {
    kind, scope: s ? s.scope : "", note: s ? s.note || "" : "", amount,
    tiers: (p.tiers || [{ at_pct: 100, sell_pct: 50 }]).map((t) => ({ ...t })),
    cadence: p.cadence || "monthly", day: p.day ?? 1, drop_pct: p.drop_pct || 20, window_days: p.window_days || 90,
  };
}

// pourquoi ces paliers ne vont pas, ou null (les mêmes règles que le serveur)
export function tiersProblem(tiers) {
  if (!tiers.length || tiers.length > MAX_TIERS) return `Entre 1 et ${MAX_TIERS} paliers`;
  const at = tiers.map((t) => t.at_pct).sort((a, b) => a - b);
  return at.some((v, i) => i && v - at[i - 1] < MIN_GAP) ? `Au moins ${MIN_GAP} points entre deux paliers` : null;
}

// les réglages du genre tirés du formulaire ; lève une erreur lisible s'il manque quelque chose
export function settings(t, exp = 2) {
  if (t.kind === "ladder") {
    const bad = tiersProblem(t.tiers);
    if (bad) throw new Error(bad);
    return { tiers: [...t.tiers].sort((a, b) => a.at_pct - b.at_pct).map((x) => ({ at_pct: Number(x.at_pct), sell_pct: Number(x.sell_pct) })) };
  }
  const amount = minor(t.amount, exp);
  if (!amount || amount < 100) throw new Error("Montant requis");
  if (t.kind === "recurring") return { cadence: t.cadence, day: Number(t.day), amount_minor: amount };
  return { drop_pct: Number(t.drop_pct), window_days: Number(t.window_days), amount_minor: amount };
}

// paramètres de save_strategy : tout pour une création, les seuls réglages changés sinon
export function saveParams(t, s, exp = 2) {
  const set = settings(t, exp), note = t.note.trim();
  if (!s) {
    if (!t.scope) throw new Error("Choisis sur quoi porte la stratégie");
    return { kind: t.kind, scope: t.scope, ...set, ...(note ? { note } : {}) };
  }
  const out = { strategy_id: s.id };
  for (const [k, v] of Object.entries(set)) if (JSON.stringify(v) !== JSON.stringify(s.params[k])) out[k] = v;
  if (note !== (s.note || "")) out.note = note;
  if (Object.keys(out).length === 1) throw new Error("Aucun changement");
  return out;
}

const STATE = {
  active: ["Active", "ok"], reached: ["Étape atteinte", "info"], complete: ["Paliers passés", "plain"],
  paused: ["En pause", "warn"], ended: ["Terminée", "plain"],
};
export const stateOf = (s) => {
  const [label, tone] = STATE[s.state] || STATE.active;
  return { label: s.step && s.step.state === "later" ? "Plus tard" : label, tone: s.step && s.step.state === "later" ? "plain" : tone };
};

const fr = (iso) => iso.split("-").reverse().join(".");
// où en est la stratégie aujourd'hui, en une ligne sous la phrase
export function levelLine(s) {
  const l = s.level || {};
  if (s.status !== "active") return s.status === "paused" ? "Rien n'est vérifié pendant la pause" : "";
  if (s.kind === "ladder") {
    if (l.ratio_pct == null) return "Prix d'achat inconnu : rien à comparer pour l'instant";
    const r = Number(l.ratio_pct), next = l.next_at_pct;
    const now = `Aujourd'hui ${String(Math.round(r))} % du prix d'achat`;
    return next == null || s.step ? now : `${now} · prochain palier ${levelLabel(next)}`;
  }
  if (s.kind === "recurring") return l.next_on ? `Prochaine échéance le ${fr(l.next_on)}` : "";
  if (l.drop_pct == null) return "Pas de cours récent";
  return `Aujourd'hui −${String(l.drop_pct).replace(".", ",")} % sous le plus haut du ${fr(l.peak_on)}`;
}

// ce que l'étape atteinte demande, en une ligne ; `money` comme pour la phrase
export function stepLine(s, money) {
  const st = s.step;
  if (!st) return "";
  const planned = st.planned ? money(st.planned.minor) : "";
  if (s.kind === "ladder") return `Palier ${levelLabel(st.detail.at_pct)} atteint : vendre ${st.detail.sell_pct} %, environ ${planned}`;
  if (s.kind === "recurring") return `Achat prévu le ${fr(st.detail.due || st.opened_on)} : ${planned}`;
  return `Baisse de ${String(st.detail.drop_pct).replace(".", ",")} % : achat prévu de ${planned}`;
}

// une stratégie repérée par le hub dans le journal, validée par la personne
export const isDetected = (s) => s.origin === "detected";
export const isAccount = (scope) => String(scope || "").startsWith("account:");

// la tenue de la stratégie : des étapes tenues, pas un rendement
export function keptLine(s) {
  const { done, skipped } = s.kept || { done: 0, skipped: 0 };
  if (!done && !skipped) return "Aucune étape pour l'instant";
  const n = (k, w) => `${k} étape${k > 1 ? "s" : ""} ${w}${k > 1 ? "s" : ""}`;
  return [done ? n(done, "tenue") : "", skipped ? n(skipped, "passée") : ""].filter(Boolean).join(" · ");
}
