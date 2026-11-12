// Ce qu'un passage de collecteur n'a pas pu lire (`gaps` de /collectors), en mots : la collecte
// est incomplète, et l'accueil le dit avec ce qu'il faut faire (docs/finance-politique.md).
const NETWORKS = { eth: "Ethereum", base: "Base", arbitrum: "Arbitrum", polygon: "Polygon", bsc: "BNB Chain", sol: "Solana", cosmos: "Cosmos", btc: "Bitcoin" };
const net = (n) => NETWORKS[n] || n;

// une phrase par manque : ce qui manque, puis le geste
export function gapText(g) {
  const parts = g.scope.split(".");
  const [step] = parts;
  if (g.reason === "needs_key") return `Réseau ${net(parts[2])} non lu : ajoute la clé Etherscan`;
  if (g.reason === "pruned") return `Historique ${net(parts[2])} effacé par le nœud public : importe-le ou saisis le coût`;
  if (g.reason === "unsupported") return `Réseau ${net(parts[2])} pas encore lu par le hub`;
  if (step === "history" && parts[2]) {
    const where = `Historique ${net(parts[2])} de ${parts[1]}`;
    if (g.reason === "blocked") return `${where} : l'explorateur public refuse l'accès. Solde suivi, nouvel essai chaque semaine`;
    if (g.reason === "key" || g.reason === "auth_error") return `${where} non lu : clé Etherscan refusée, vérifie-la dans Identifiants`;
    if (g.reason === "http_429" || g.reason === "site_unavailable") return `${where} non lu : explorateur saturé, nouvel essai au prochain passage`;
    return `${where} non lu : réponse illisible de l'explorateur, nouvel essai au prochain passage`;
  }
  if (g.reason === "no_pair") return `${(parts[1] || "").toUpperCase()} sans cours`;
  if (g.reason.startsWith("skipped=")) return `${g.reason.slice(8)} période${g.reason.slice(8) === "1" ? "" : "s"} refusée${g.reason.slice(8) === "1" ? "" : "s"} par la source (${step})`;
  if (step === "prices" || step === "crypto" || step === "quotes" || step === "history_prices") return `Cours ${parts[1] ? `de ${parts[1].toUpperCase()} ` : ""}non lus, nouvel essai au prochain passage`;
  if (step === "funds") return "Compositions des fonds non lues, nouvel essai demain";
  if (step === "wallet") return `Solde de ${parts[1]} non lu, nouvel essai au prochain passage`;
  if (step === "history") return `Historique ${parts[1] ? `de ${parts[1]} ` : ""}non lu, nouvel essai au prochain passage`;
  return `${g.scope} non lu (${g.reason})`;
}

// un manque sans geste possible (explorateur fermé : le réseau est en « solde seul ») se dit sur
// la connexion, pas dans « À faire » : le rapprochement montre tout mouvement non expliqué
const quiet = (g) => g.reason === "blocked";

// le manque d'une connexion, à la suite de son dernier passage (liste des connexions)
export function gapNote(c) {
  const texts = [...new Set(((c && c.gaps) || []).map(gapText))];
  return texts.length ? ` · ${texts[0]}${texts.length > 1 ? ` · ${texts.length - 1} de plus` : ""}` : "";
}

// les lignes « À faire » de l'accueil : une par connexion incomplète
export function gapRows(collectors) {
  const todo = (c) => (c.gaps || []).filter((g) => !quiet(g));
  return (collectors ? collectors.items : []).filter((c) => todo(c).length && c.mode !== "disabled").map((c) => {
    const texts = [...new Set(todo(c).map(gapText))];
    return { ic: "alert", c: "var(--s3)", t: `${c.label} : collecte incomplète`, s: texts.slice(0, 2).join(" · ") + (texts.length > 2 ? ` · ${texts.length - 2} de plus` : ""), a: "rubric", v: "conn" };
  });
}
