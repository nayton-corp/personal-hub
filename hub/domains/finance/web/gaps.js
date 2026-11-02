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
  if (g.reason === "no_pair") return `${(parts[1] || "").toUpperCase()} sans cours`;
  if (g.reason.startsWith("skipped=")) return `${g.reason.slice(8)} période${g.reason.slice(8) === "1" ? "" : "s"} refusée${g.reason.slice(8) === "1" ? "" : "s"} par la source (${step})`;
  if (step === "prices" || step === "crypto" || step === "quotes" || step === "history_prices") return `Cours ${parts[1] ? `de ${parts[1].toUpperCase()} ` : ""}non lus, nouvel essai au prochain passage`;
  if (step === "wallet") return `Solde de ${parts[1]} non lu, nouvel essai au prochain passage`;
  if (step === "history") return `Historique ${parts[1] ? `de ${parts[1]} ` : ""}non lu, nouvel essai au prochain passage`;
  return `${g.scope} non lu (${g.reason})`;
}

// les lignes « À faire » de l'accueil : une par connexion incomplète
export function gapRows(collectors) {
  return (collectors ? collectors.items : []).filter((c) => c.gaps && c.gaps.length && c.mode !== "disabled").map((c) => {
    const texts = [...new Set(c.gaps.map(gapText))];
    return { ic: "alert", c: "var(--s3)", t: `${c.label} : collecte incomplète`, s: texts.slice(0, 2).join(" · ") + (texts.length > 2 ? ` · ${texts.length - 2} de plus` : ""), a: "rubric", v: "conn" };
  });
}
