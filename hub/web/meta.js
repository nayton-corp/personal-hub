// Libellés, pictogrammes et teintes des catégories, des facettes du patrimoine et des actifs.
import { cv, esc, ibox, ic, monogram, pref } from "./ui.js";

// catégories du registre (base, packs) : pictogramme et teinte ; les autres prennent ceux de
// leur groupe
const CAT_LOOK = {
  logement: ["home", 0], assurances: ["shield", 1], impots: ["landmark", 5], telecom: ["wifi", 3],
  abonnements: ["repeat", 4], transports: ["train", 6], "voiture-credit": ["car", 5], "voiture-frais": ["car", 6], alimentation: ["cart", 1], restaurants: ["utensils", 2],
  sante: ["heart", 4], loisirs: ["ticket", 3], shopping: ["bag", 4], voyages: ["plane", 6], divers: ["dots", 5],
  retraits: ["banknote", 5], "twint-particuliers": ["swap", 6], salaire: ["briefcase", 1], remboursements: ["arrowin", 6],
  "autres-revenus": ["arrowin", 1], rendement: ["trend", 1], "epargne-3a": ["piggy", 0], investissements: ["trend", 0],
  crypto: ["coin", 2], "transfer-own": ["swap", -1], "transfer-titres": ["swap", -1], "frais-placement": ["landmark", 5],
  "a-categoriser": ["help", -2], "a-qualifier": ["help", -2], autres: ["dots", -1],
  allocations: ["users", 1], cadeaux: ["gift", 5], formation: ["book", 6], "frais-bancaires": ["receipt", 5],
  "interets-dividendes": ["percent", 1], soins: ["sparkle", 4], ventes: ["tag", 1],
};
// catégories créées à la main : pictogramme d'après les mots de leur identifiant
const CAT_WORDS = [
  [/voiture|auto|moto|leasing/, "car"], [/essence|carburant|fuel/, "fuel"], [/parking/, "parking"],
  [/train|bus|transport|velo|mobilit/, "train"], [/vacance|voyage|avion|hotel/, "plane"], [/loyer|logement|maison|menage|meuble/, "home"],
  [/electric|energie|chauffage/, "bolt"], [/internet|wifi/, "wifi"], [/telephon|mobile|natel/, "phone"], [/streaming|tv|film/, "play"],
  [/musique|music/, "music"], [/sport|fitness|gym|ski/, "dumbbell"], [/cafe|boulang/, "coffee"], [/resto|restaurant|sortie|bar/, "utensils"],
  [/course|aliment|epicer/, "cart"], [/vetement|habit|shopping|mode/, "bag"], [/cadeau/, "gift"], [/livre|formation|ecole|etude|cours/, "book"],
  [/pharma|medic|sante|medecin|dentist/, "cross"], [/coiff|beaute|soin|cosmet/, "sparkle"], [/animal|chat|chien|veto/, "paw"],
  [/enfant|famille|creche|allocation/, "users"], [/assurance|lamal/, "shield"], [/impot|taxe|amende/, "landmark"], [/credit|pret|dette/, "landmark"],
  [/abonnement/, "repeat"], [/epargne|3a|pilier/, "piggy"], [/invest|bourse|etf|action/, "trend"], [/crypto|bitcoin/, "coin"],
  [/salaire|paie|bonus/, "briefcase"], [/interet|dividende/, "percent"], [/frais|banque/, "receipt"], [/don|charite/, "heart"],
  [/loisir|concert|cinema|jeu/, "ticket"], [/tech|informatique|logiciel|app/, "cpu"], [/colis|poste/, "box"], [/vente/, "tag"],
];
const wordIcon = (s) => (CAT_WORDS.find(([re]) => re.test(s)) || [])[1];
const GROUP_LOOK = { income: ["arrowin", 1], fixed: ["home", 5], variable: ["cart", 2], savings: ["piggy", 0], transfer: ["swap", -1] };
export const GROUP_LABEL = { income: "Revenus", fixed: "Fixes", variable: "Variables", savings: "Épargne", transfer: "Transferts", mixed: "Autres" };

function look(id, groupName) {
  let [icon, c] = CAT_LOOK[id] || GROUP_LOOK[groupName] || ["dots", 5];
  if (!CAT_LOOK[id] && id) icon = wordIcon(id) || icon;
  return { icon, color: c === -1 ? "var(--faint)" : c === -2 ? "var(--accent)" : cv(c) };
}
export const catLook = look;
export function catMark(id, groupName, size = "sm") {
  if (!id) return ibox(ic("help"), "var(--accent)", size);
  const l = look(id, groupName);
  return ibox(ic(l.icon), l.color, size);
}

// commerçants connus : un pictogramme plus parlant que celui de la catégorie (la teinte reste
// celle de la catégorie)
const MERCHANT_WORDS = [
  [/\b(migros|coop(?! ?bau)|denner|lidl|aldi|spar|volg|aligro|landi|carrefour|leclerc|auchan|intermarch|edeka|rewe)/, "cart"],
  [/uber ?eats|just ?eat|smood|eat\.ch|deliveroo|mcdonald|burger|pizz|kebab|sushi|restaurant|ristorante|trattoria|brasserie|bistro|takeaway|subway|kfc/, "utensils"],
  [/starbucks|caf[eé]\b|coffee|boulanger|bakery|confiserie|tea ?room|bäckerei/, "coffee"],
  [/\b(sbb|cff|ffs|tpg|tpf|bls|postauto|car postal|ratp|sncf|trenitalia|db bahn|flixbus|mobility|publibike|tl lausanne)/, "train"],
  [/\b(shell|avia|tamoil|socar|agrola|esso|migrol|eni|total ?energies|bp)\b/, "fuel"],
  [/parking|parkhaus|onepark|parkingpay|easypark/, "parking"],
  [/\buber\b|\btaxi|\bbolt\b|garage|amag|emil frey|carrosserie|pneu/, "car"],
  [/easyjet|swiss intl|swiss int|ryanair|lufthansa|edelweiss|air france|klm|wizz|airbnb|booking\.com|hotel|expedia|hostel/, "plane"],
  [/netflix|disney|youtube|prime video|blue tv|teleclub|dazn|twitch|canal\+|paramount|max\.com|hbo/, "play"],
  [/spotify|apple music|deezer|tidal|soundcloud/, "music"],
  [/swisscom|sunrise|init7|quickline|upc|green\.ch/, "wifi"], [/\bsalt\b|wingo|yallo|lebara|m-budget mobile|digital republic/, "phone"],
  [/amazon|galaxus|digitec|zalando|aliexpress|temu|shein|ricardo|la poste|post ch|\bdhl|\bups\b|brack/, "box"],
  [/h&m|zara|uniqlo|c&a|manor|globus|primark|bershka|mango|nike|adidas|ochsner|vögele|bucherer/, "bag"],
  [/pharma|apotheke|amavita|sun ?store|benu|drogerie|dropa|topPharm/i, "cross"],
  [/h[oô]pital|clinique|m[eé]decin|dentist|cabinet m|labor|physio|hirslanden/, "heart"],
  [/fitness|\bgym|basic-fit|update fitness|activ fitness|decathlon|sport|piscine|t[eé]l[eé]ski|remont[eé]es/, "dumbbell"],
  [/apple\.com|itunes|icloud|google|microsoft|openai|anthropic|claude\.ai|github|adobe|steam|playstation|nintendo|xbox|dropbox|notion/, "cpu"],
  [/cin[eé]ma|path[eé]|ticketcorner|fnac|concert|mus[eé]e|starticket|eventfrog/, "ticket"],
  [/bancomat|postomat|\batm\b|retrait/, "banknote"], [/twint/, "swap"],
  [/imp[oô]t|administration fiscale|steuer|service des contributions|\bafc\b/, "landmark"],
  [/assurance|\baxa|helvetia|mobili[eè]re|zurich ins|allianz|generali|baloise|\bcss\b|helsana|groupe mutuel|swica|sanitas|visana|assura|concordia|sympany|\bkpt|atupri|vaudoise/, "shield"],
  [/loyer|r[eé]gie|g[eé]rance|immobili|ikea|hornbach|jumbo|\bobi\b|coop bau|do it/, "home"],
  [/groupe e\b|romande energie|\bsig\b|\bewz\b|\bbkw\b|energie|[eé]lectricit/, "bolt"],
  [/serafe|billag/, "receipt"], [/coiff|barber|salon de|beaut[eé]|\bspa\b|massage|onglerie|esth[eé]ti/, "sparkle"],
  [/payot|orell|thalia|librairie|udemy|coursera|[eé]cole|universit|epfl|unil|unige|hes-so/, "book"],
  [/fressnapf|qualipet|v[eé]t[eé]rinaire|zooplus/, "paw"], [/smartbox|cadeau|gift/, "gift"],
  [/viac|frankly|finpension/, "piggy"], [/interactive brokers|ibkr|degiro|swissquote|saxo|trade republic/, "trend"],
  [/binance|coinbase|kraken|kucoin|swissborg|bitpanda|ledger|bitstamp/, "coin"],
];
export const merchantIcon = (name) => {
  const s = (name || "").toLowerCase();
  return s ? (MERCHANT_WORDS.find(([re]) => re.test(s)) || [])[1] : undefined;
};
// pictogramme d'une écriture : celui du commerçant s'il est connu, sinon celui de la catégorie
export function txMark(name, id, groupName, size = "sm") {
  const m = merchantIcon(name);
  if (!m) return catMark(id, groupName, size);
  return ibox(ic(m), id ? look(id, groupName).color : "var(--accent)", size);
}

export function catIc(id, groupName) {
  const l = look(id, groupName);
  return `<span class="tint-ic" data-css="color:${l.color};display:inline-flex">${ic(l.icon)}</span>`;
}

// --- patrimoine : facettes ------------------------------------------------------------------
export const FACETS = [
  { key: "cat", label: "Catégorie", values: ["cash", "funds", "crypto", "debt"], names: { cash: "Liquidités", funds: "Actions & fonds", crypto: "Crypto", debt: "Dettes" }, icons: { cash: "banknote", funds: "trend", crypto: "coin", debt: "landmark" } },
  { key: "liq", label: "Disponibilité", values: ["immediate", "days", "locked"], names: { immediate: "Immédiate", days: "Sous quelques jours", locked: "Bloquée" }, icons: { immediate: "bolt", days: "clock", locked: "lockc" } },
  { key: "goal", label: "Objectif", values: ["current", "safety", "projects", "long_term", "retirement"], names: { current: "Courant", safety: "Réserve de sécurité", projects: "Projets", long_term: "Long terme", retirement: "Retraite" }, icons: { current: "wallet", safety: "shield", projects: "plane", long_term: "trend", retirement: "piggy" } },
  { key: "inst", label: "Institution", values: [], names: {} }, // rempli depuis les comptes
];
export const FACET = Object.fromEntries(FACETS.map((f) => [f.key, f]));

export function setInstitutions(names) {
  const f = FACET.inst;
  f.values = [...new Set(names)].sort((a, b) => a.localeCompare(b, "fr"));
  f.names = Object.fromEntries(f.values.map((v) => [v, v]));
}
// institutions : sigle court et teinte reconnaissables (sinon initiales et teinte de rang)
const INST_LOOK = {
  bcf: ["BCF", "var(--s2)"], viac: ["VIAC", "var(--s1)"], revolut: ["R", "var(--ink)"], ibkr: ["IB", "var(--neg)"], "interactive brokers": ["IB", "var(--neg)"],
  binance: ["B", "var(--s3)"], coinbase: ["C", "var(--s1)"], kucoin: ["K", "var(--s2)"], swissborg: ["SB", "var(--s2)"], kraken: ["K", "var(--s4)"],
  ledger: ["L", "var(--ink)"], metamask: ["M", "var(--s3)"], "trust wallet": ["T", "var(--s7)"], trust: ["T", "var(--s7)"], phantom: ["P", "var(--s4)"],
  postfinance: ["PF", "var(--s3)"], ubs: ["UBS", "var(--neg)"], raiffeisen: ["R", "var(--neg)"], yuh: ["yuh", "var(--s4)"], neon: ["N", "var(--s2)"],
  frankly: ["F", "var(--s1)"], finpension: ["fp", "var(--s5)"], swissquote: ["SQ", "var(--s3)"], degiro: ["DG", "var(--s7)"], wise: ["W", "var(--s2)"],
  bitpanda: ["BP", "var(--s2)"], "trade republic": ["TR", "var(--ink)"], saxo: ["S", "var(--s1)"], bcv: ["BCV", "var(--s2)"], bcge: ["BCGE", "var(--neg)"],
};
const instKey = (v) => (v || "").toLowerCase().replace(/^crypto:/, "").replace(/[-_]/g, " ").trim();
export function instLook(v) {
  const k = instKey(v);
  const l = INST_LOOK[k] || INST_LOOK[k.split(" ")[0]];
  return l ? { t: l[0], c: l[1] } : null;
}
export function instMark(v, size = "sm") {
  const l = instLook(v);
  const t = l ? l.t : monogram(v);
  return ibox(`<span class="${t.length > 2 ? "wm" : ""}">${esc(t)}</span>`, l ? l.c : facetColor("inst", v), size);
}

export const facetName = (key, v) => FACET[key].names[v] ?? v;
export const facetColor = (key, v) => (key === "inst" && instLook(v) ? instLook(v).c : cv(Math.max(0, FACET[key].values.indexOf(v))));
export function facetMark(key, v, size = "sm") {
  if (key === "inst") return instMark(v, size);
  const f = FACET[key];
  const inner = f.icons ? ic(f.icons[v]) : `<span>${esc(monogram(v))}</span>`;
  return ibox(inner, facetColor(key, v), size);
}
export function facetIc(key, v) {
  const f = FACET[key];
  return f.icons ? `<span data-css="--c:${facetColor(key, v)};display:inline-flex">${ic(f.icons[v])}</span>` : `<i data-css="--c:${facetColor(key, v)}"></i>`;
}

// --- actifs ---------------------------------------------------------------------------------
export const CCY_NAME = { CHF: "Franc suisse", EUR: "Euro", USD: "Dollar US", GBP: "Livre sterling", JPY: "Yen" };
const GLYPH = { CHF: "Fr.", EUR: "€", USD: "$", GBP: "£", JPY: "¥", CAD: "C$", AUD: "A$", SEK: "kr", NOK: "kr", DKK: "kr", CNY: "¥", HKD: "HK$",
  BTC: "₿", ETH: "Ξ", USDT: "₮", USDC: "$", SOL: "◎", LTC: "Ł", XRP: "✕", ADA: "₳", DOT: "●", DOGE: "Ð", BNB: "◆", XMR: "ɱ", ETC: "ξ", DAI: "◈" };
const CRYPTO_TINT = { BTC: "var(--s3)", ETH: "var(--s4)", USDT: "var(--s2)", USDC: "var(--s7)", SOL: "var(--s5)", BNB: "var(--s3)", DOGE: "var(--s3)",
  ADA: "var(--s1)", DOT: "var(--s5)", AVAX: "var(--s5)", LINK: "var(--s1)", MATIC: "var(--s4)", POL: "var(--s4)", NEAR: "var(--s6)", TAO: "var(--s6)",
  XRP: "var(--s6)", LTC: "var(--s6)", ATOM: "var(--s6)", TRX: "var(--s5)", DAI: "var(--s3)", XMR: "var(--s3)" };
const CCY_TINT = { CHF: "var(--neg)", EUR: "var(--s1)", USD: "var(--s2)", GBP: "var(--s4)", JPY: "var(--s5)" };

export function assetMark(a, size = "") {
  const g = GLYPH[a.symbol] || monogram(a.name);
  const color = CRYPTO_TINT[a.symbol] || facetColor("cat", a.cat);
  return ibox(`<span class="${g.length === 1 ? "glyph" : ""}">${esc(g)}</span>`, color, size);
}

// Taux marginal d'impôt (estimation gardée sur l'appareil) : l'impôt économisé par le 3a.
export const TAX_RATES = [0.15, 0.2, 0.25, 0.3, 0.35, 0.4];
export const taxRate = () => {
  const t = pref("tax", null);
  if (typeof t === "number") return t;
  const w = pref("wealth", {});
  return typeof w.tax === "number" ? w.tax : 0.25;
};

// --- devises, régions et secteurs (contenu des fonds) -------------------------------------------
export function ccyMark(code, size = "sm") {
  if (code === "Crypto") return ibox(ic("coin"), "var(--s3)", size);
  const g = GLYPH[code] || code.slice(0, 3);
  return ibox(`<span class="${g.length === 1 ? "glyph" : ""}">${esc(g)}</span>`, CCY_TINT[code] || CRYPTO_TINT[code] || "var(--s6)", size);
}
const REGION_LOOK = {
  Suisse: [ic("cross"), "var(--neg)"], "Europe (hors Suisse)": ["EU", "var(--s1)"], "Amérique du Nord": ["US", "var(--s2)"], Japon: ["JP", "var(--s5)"],
  "Pacifique (hors Japon)": ["AP", "var(--s7)"], "Marchés émergents": ["ÉM", "var(--s3)"], Crypto: [ic("coin"), "var(--s3)"],
};
const SECTOR_LOOK = {
  Technologie: "cpu", Finance: "landmark", "Santé": "heart", "Consommation discrétionnaire": "bag", "Consommation de base": "cart", Industrie: "factory",
  Communication: "radio", "Énergie": "bolt", "Matériaux": "cube", "Services publics": "drop", Immobilier: "home", Obligations: "doc",
  "Liquidités et dérivés": "banknote", Crypto: "coin",
};
export function lookMark(dim, bucket, color, size = "sm") {
  if (dim === "currency") return ccyMark(bucket, size);
  if (dim === "region") {
    const r = REGION_LOOK[bucket];
    if (r) return ibox(r[0].startsWith("<svg") ? r[0] : `<span>${esc(r[0])}</span>`, r[1], size);
    return ibox(ic("globe"), color, size);
  }
  return ibox(ic(SECTOR_LOOK[bucket] || "dots"), color, size);
}
