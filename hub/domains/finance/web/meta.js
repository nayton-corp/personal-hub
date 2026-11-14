// Libellés, pictogrammes et teintes des catégories, des facettes du patrimoine et des actifs.
// Ce qui est propre au pays (commerçants, établissements, catégories de son pack de règles)
// vient du pack pays, publié par le profil ; le front ne nomme que les marques internationales.
import { BRANDS } from "./brands.js";
import { packs } from "../../store.js";
import { cv, esc, ibox, ic, monogram, pref } from "../../ui.js";

// le pack pays de la finance, compilé une fois par profil lu
let packSrc = null;
let packLook = { merchants: [], institutions: {}, categories: {}, merchantLogos: [], instLogos: {}, fundLogos: [] };
function countryLook() {
  const src = packs().finance || {};
  if (src !== packSrc) {
    packSrc = src;
    packLook = {
      merchants: (src.merchant_icons || []).map(([p, icon]) => [new RegExp(p, "i"), icon]),
      institutions: src.institution_marks || {},
      categories: src.category_icons || {},
      merchantLogos: (src.merchant_logos || []).map(([p, logo]) => [new RegExp(p, "i"), logo]),
      instLogos: src.institution_logos || {},
      fundLogos: (src.fund_logos || []).map(([p, logo]) => [new RegExp(p, "i"), logo]),
    };
  }
  return packLook;
}

// catégories du registre (base, packs) : pictogramme et teinte ; les autres prennent ceux de
// leur groupe
const CAT_LOOK = {
  logement: ["home", 0], assurances: ["shield", 1], impots: ["landmark", 5], telecom: ["wifi", 3],
  abonnements: ["repeat", 4], transports: ["train", 6], "voiture-credit": ["car", 5], "voiture-frais": ["car", 6], alimentation: ["cart", 1], restaurants: ["utensils", 2],
  sante: ["heart", 4], loisirs: ["ticket", 3], shopping: ["bag", 4], voyages: ["plane", 6], divers: ["dots", 5],
  retraits: ["banknote", 5], salaire: ["briefcase", 1], remboursements: ["arrowin", 6],
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
  const known = CAT_LOOK[id] || countryLook().categories[id];
  let [icon, c] = known || GROUP_LOOK[groupName] || ["dots", 5];
  if (!known && id) icon = wordIcon(id) || icon;
  return { icon, color: c === -1 ? "var(--faint)" : c === -2 ? "var(--accent)" : cv(c) };
}
export const catLook = look;
export function catMark(id, groupName, size = "sm") {
  if (!id) return ibox(ic("help"), "var(--accent)", size);
  const l = look(id, groupName);
  return ibox(ic(l.icon), l.color, size);
}

// --- logos de marques ---------------------------------------------------------------------
// pastille aux couleurs de la marque, logo blanc (ou sombre sur une couleur claire)
const light = (hex) => {
  const n = parseInt(hex.slice(1), 16);
  return 0.299 * (n >> 16) + 0.587 * ((n >> 8) & 255) + 0.114 * (n & 255) > 170;
};
export const brandSvg = (slug) => `<svg class="ic logo" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="${BRANDS[slug][2]}"/></svg>`;
export const brandColors = (slug) => {
  const hex = BRANDS[slug][1];
  return { bg: hex, fg: light(hex) ? "#14161a" : "#fff" };
};
export function brandMark(slug, size = "sm") {
  const { bg, fg } = brandColors(slug);
  return `<span class="ibox brand ${size}" data-css="--bg:${bg};--fg:${fg}" aria-hidden="true">${brandSvg(slug)}</span>`;
}

// logos en couleur, fichiers de l'app (logos/<nom>.svg, carrés, fond compris) : servis avec elle,
// jamais demandés à un service tiers ; les établissements et commerçants du pays viennent du pack
// pays. Un nom sans logo garde son sigle ou ses initiales.
const LOGOS = new Set([
  "fidelity", "invesco", "ishares", "revolut", "ubs", "vanguard", "xtrackers",
  "binance", "coinbase", "coinbasewallet", "ibkr", "kucoin", "ledger", "metamask", "multiversx", "phantom", "swissborg", "trustwallet",
]);
// teinte d'un logo dans les graphiques (répartition par compte), quand l'établissement n'a pas de sigle
const LOGO_TINT = {
  binance: "#F0B90B", coinbase: "#0052FF", coinbasewallet: "#0052FF", ibkr: "#D81222", kucoin: "#01BC8D", ledger: "var(--ink)",
  metamask: "#F6851B", multiversx: "#23F7DD", phantom: "#AB9FF2", swissborg: "#01C38D", trustwallet: "#0500FF",
};
// icônes des apps (PNG 128 px, App Store) ; les cryptos, des tracés (coins/*.svg)
export const logoUrl = (logo) => new URL(`./logos/${logo}.${logo.startsWith("coins/") ? "svg" : "png"}`, import.meta.url).href;
export const logoImg = (logo) => `<img src="${logoUrl(logo)}" alt="" decoding="async">`;
export const logoMark = (logo, size = "sm") => `<span class="ibox logo ${size}" aria-hidden="true">${logoImg(logo)}</span>`;
// plateformes et portefeuilles connus partout (motifs sur le nom en minuscules, le plus précis d'abord)
const INST_LOGOS = [
  [/coinbase ?wallet/, "coinbasewallet"], [/\bcoinbase/, "coinbase"], [/\bbinance/, "binance"], [/\bkucoin/, "kucoin"],
  [/\bledger\b/, "ledger"], [/meta ?mask/, "metamask"], [/\bphantom\b/, "phantom"], [/\btrust( ?wallet)?\b/, "trustwallet"],
  [/multiversx|\begld\b|elrond|xportal/, "multiversx"], [/interactive ?brokers|\bibkr\b/, "ibkr"], [/swissborg/, "swissborg"], [/\brevolut\b/, "revolut"],
];
const MERCHANT_LOGOS = [[/revolut/, "revolut"], [/binance/, "binance"], [/coinbase/, "coinbase"], [/kucoin/, "kucoin"], [/interactive brokers|\bibkr\b/, "ibkr"]];
// un logo connu : international (ci-dessus) ou nommé par le pack pays, ses fichiers étant dans logos/
const known = (logo) => {
  const pk = countryLook();
  const ours = logo && (LOGOS.has(logo) || Object.values(pk.instLogos).includes(logo) || pk.merchantLogos.some(([, l]) => l === logo));
  return ours ? logo : undefined;
};
// logo d'un établissement, d'une plateforme ou d'un portefeuille (nom libre : « Ledger BTC »)
export function instLogo(v) {
  const k = instKey(v);
  if (!k) return undefined;
  const own = countryLook().instLogos;
  return known(own[k] || own[k.split(" ")[0]] || (INST_LOGOS.find(([re]) => re.test(k)) || [])[1]);
}
// logo d'un commerçant (libellé d'écriture)
export function merchantLogo(name) {
  const s = (name || "").toLowerCase();
  if (!s) return undefined;
  return known((countryLook().merchantLogos.find(([re]) => re.test(s)) || MERCHANT_LOGOS.find(([re]) => re.test(s)) || [])[1]);
}
const MERCHANT_BRANDS = [
  [/uber ?eats/, "ubereats"], [/\buber\b/, "uber"], [/netflix/, "netflix"], [/spotify/, "spotify"], [/apple music/, "applemusic"],
  [/icloud/, "icloud"], [/apple\.com|itunes|\bapple\b/, "apple"], [/youtube/, "youtube"], [/google/, "google"], [/galaxus/, "galaxus"],
  [/zalando/, "zalando"], [/\blidl/, "lidl"], [/aldi/, "aldisud"], [/sunrise/, "sunrise"], [/\bshell\b/, "shell"], [/ikea/, "ikea"],
  [/h&m|h & m|hennes/, "handm"], [/\bzara\b/, "zara"], [/easyjet/, "easyjet"], [/ryanair/, "ryanair"], [/lufthansa/, "lufthansa"],
  [/airbnb/, "airbnb"], [/booking\.com/, "bookingdotcom"], [/mc ?donald/, "mcdonalds"], [/starbucks/, "starbucks"], [/burger king/, "burgerking"],
  [/\bkfc\b/, "kfc"], [/steam(powered|games)?\b/, "steam"], [/playstation|sony interactive/, "playstation"], [/anthropic|claude\.ai/, "anthropic"],
  [/github/, "github"], [/aliexpress/, "aliexpress"], [/deezer/, "deezer"], [/\bdazn/, "dazn"], [/twitch/, "twitch"], [/\bdhl\b/, "dhl"],
  [/\bups\b/, "ups"], [/just ?eat/, "justeat"], [/deliveroo/, "deliveroo"], [/\bsncf/, "sncf"], [/dropbox/, "dropbox"], [/notion/, "notion"],
  [/revolut/, "revolut"], [/binance/, "binance"], [/coinbase/, "coinbase"], [/kucoin/, "kucoin"], [/\bwise\b|transferwise/, "wise"],
];
export const merchantBrand = (name) => {
  const s = (name || "").toLowerCase();
  return s ? (MERCHANT_BRANDS.find(([re]) => re.test(s)) || [])[1] : undefined;
};

// commerçants connus : un pictogramme plus parlant que celui de la catégorie (la teinte reste
// celle de la catégorie) ; les commerçants du pays viennent du pack pays, avant ceux-ci
const MERCHANT_WORDS = [
  [/\b(lidl|aldi|carrefour|leclerc|auchan|intermarch|edeka|rewe)/, "cart"],
  [/uber ?eats|just ?eat|deliveroo|mcdonald|burger|pizz|kebab|sushi|restaurant|ristorante|trattoria|brasserie|bistro|takeaway|subway|kfc/, "utensils"],
  [/starbucks|caf[eé]\b|coffee|boulanger|bakery|confiserie|tea ?room|bäckerei/, "coffee"],
  [/\b(ratp|sncf|trenitalia|db bahn|flixbus)/, "train"],
  [/\b(shell|esso|eni|total ?energies|bp)\b/, "fuel"],
  [/parking|parkhaus|onepark|easypark/, "parking"],
  [/\buber\b|\btaxi|\bbolt\b|garage|carrosserie|pneu/, "car"],
  [/easyjet|ryanair|lufthansa|air france|klm|wizz|airbnb|booking\.com|hotel|expedia|hostel/, "plane"],
  [/netflix|disney|youtube|prime video|dazn|twitch|canal\+|paramount|max\.com|hbo/, "play"],
  [/spotify|apple music|deezer|tidal|soundcloud/, "music"],
  [/amazon|zalando|aliexpress|temu|shein|\bdhl|\bups\b/, "box"],
  [/h&m|zara|uniqlo|c&a|primark|bershka|mango|nike|adidas/, "bag"],
  [/pharma|apotheke/, "cross"],
  [/h[oô]pital|clinique|m[eé]decin|dentist|cabinet m|labor|physio/, "heart"],
  [/fitness|\bgym|decathlon|sport|piscine|t[eé]l[eé]ski|remont[eé]es/, "dumbbell"],
  [/apple\.com|itunes|icloud|google|microsoft|openai|anthropic|claude\.ai|github|adobe|steam|playstation|nintendo|xbox|dropbox|notion/, "cpu"],
  [/cin[eé]ma|fnac|concert|mus[eé]e/, "ticket"],
  [/\batm\b|retrait/, "banknote"],
  [/imp[oô]t|steuer/, "landmark"],
  [/assurance|\baxa|allianz|generali/, "shield"],
  [/loyer|immobili|ikea/, "home"],
  [/energie|[eé]lectricit/, "bolt"],
  [/coiff|barber|salon de|beaut[eé]|\bspa\b|massage|onglerie|esth[eé]ti/, "sparkle"],
  [/librairie|udemy|coursera|[eé]cole|universit/, "book"],
  [/v[eé]t[eé]rinaire|zooplus/, "paw"], [/smartbox|cadeau|gift/, "gift"],
  [/interactive brokers|ibkr|degiro|saxo|trade republic/, "trend"],
  [/binance|coinbase|kraken|kucoin|bitpanda|ledger|bitstamp/, "coin"],
];
export const merchantIcon = (name) => {
  const s = (name || "").toLowerCase();
  if (!s) return undefined;
  const found = countryLook().merchants.find(([re]) => re.test(s)) || MERCHANT_WORDS.find(([re]) => re.test(s));
  return found ? found[1] : undefined;
};
// pictogramme d'une écriture : celui du commerçant s'il est connu, sinon celui de la catégorie
export function txMark(name, id, groupName, size = "sm") {
  const logo = merchantLogo(name);
  if (logo) return logoMark(logo, size);
  const b = merchantBrand(name);
  if (b) return brandMark(b, size);
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
  { key: "cat", label: "Catégorie", values: ["cash", "funds", "crypto", "debt", "goods"], names: { cash: "Liquidités", funds: "Actions & fonds", crypto: "Crypto", goods: "Biens", debt: "Dettes" },
    icons: { cash: "banknote", funds: "trend", crypto: "coin", goods: "home", debt: "landmark" } },
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
// institutions : sigle court et teinte reconnaissables (sinon initiales et teinte de rang) ;
// les établissements du pays viennent du pack pays (sigle, jeton de teinte)
const INST_LOOK = {
  revolut: ["R", "ink"], ibkr: ["IB", "neg"], "interactive brokers": ["IB", "neg"],
  binance: ["B", "s3"], coinbase: ["C", "s1"], kucoin: ["K", "s2"], kraken: ["K", "s4"],
  ledger: ["L", "ink"], metamask: ["M", "s3"], "trust wallet": ["T", "s7"], trust: ["T", "s7"], phantom: ["P", "s4"],
  degiro: ["DG", "s7"], wise: ["W", "s2"], bitpanda: ["BP", "s2"], "trade republic": ["TR", "ink"], saxo: ["S", "s1"],
};
const instKey = (v) => (v || "").toLowerCase().replace(/^crypto:/, "").replace(/[-_]/g, " ").trim();
const INST_BRAND = { revolut: "revolut", binance: "binance", coinbase: "coinbase", kucoin: "kucoin", wise: "wise", neon: "neon" };
export function instLook(v) {
  const k = instKey(v);
  const inst = { ...INST_LOOK, ...countryLook().institutions };
  const l = inst[k] || inst[k.split(" ")[0]];
  const brand = INST_BRAND[k] || INST_BRAND[k.split(" ")[0]];
  const logo = instLogo(v);
  if (!l && !logo) return null;
  const c = brand ? BRANDS[brand][1] : l ? `var(--${l[1]})` : LOGO_TINT[logo] || facetColor("inst", "");
  return { t: l ? l[0] : monogram(v), c, brand, logo };
}
// `alts` : d'autres noms du compte (son nom, sa référence), quand l'établissement est générique
// (« Crypto » pour un portefeuille ou une plateforme)
export function instMark(v, size = "sm", alts = []) {
  const l = instLook(v);
  if (l && l.logo) return logoMark(l.logo, size);
  const alt = alts.map((a) => instLogo(a)).find(Boolean);
  if (alt) return logoMark(alt, size);
  if (l && l.brand) return brandMark(l.brand, size);
  const t = l ? l.t : monogram(v);
  return ibox(`<span class="${t.length > 2 ? "wm" : ""}">${esc(t)}</span>`, l ? l.c : facetColor("inst", v), size);
}

// halo d'un compte : la teinte de son groupe dans la répartition affichée, autour du logo
export function ringed(mark, color) {
  if (!color) return mark;
  const m = mark.replace('class="ibox', 'class="ibox ring');
  return m.includes('data-css="') ? m.replace('data-css="', `data-css="--ring:${color};`) : m.replace('class="ibox ring', `data-css="--ring:${color}" class="ibox ring`);
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

// logos des cryptos (logos/coins/<symbole>.svg, web3icons) et des émetteurs de fonds (d'après le
// nom du fonds ; ceux du pays viennent du pack pays)
const COINS = new Set([
  "1inch", "aave", "ada", "algo", "apt", "ar", "arb", "atom", "avax", "axs", "bch", "bnb", "btc", "cake", "celo",
  "chz", "comp", "cro", "crv", "dai", "dash", "doge", "dot", "egld", "eos", "etc", "eth", "ethw", "eurc", "fet",
  "fil", "flow", "ftm", "gala", "grt", "hbar", "hnt", "icp", "icx", "imx", "jasmy", "jup", "kas", "kava", "kcs",
  "ksm", "ldo", "link", "ltc", "luna", "lunc", "mana", "matic", "mina", "mkr", "near", "neo", "one", "op", "osmo",
  "paxg", "pepe", "pol", "pyth", "qnt", "rndr", "rose", "rune", "sand", "sei", "shib", "snx", "sol", "stx", "sui",
  "tao", "theta", "tia", "trx", "tusd", "uni", "usdc", "usdt", "ustc", "vet", "wbtc", "xlm", "xmr", "xrp", "xtz",
  "zec", "zil"
]);
const COIN_ALIAS = { render: "rndr" };
const FUND_LOGOS = [
  [/\bishares\b|blackrock/, "ishares"], [/vanguard/, "vanguard"], [/x-?trackers/, "xtrackers"], [/invesco/, "invesco"],
  [/fidelity/, "fidelity"], [/\bubs\b|\bcsif\b|credit suisse/, "ubs"],
];
const coinLogo = (sym) => {
  const raw = (sym || "").toLowerCase().replace(/^crypto:/, "");
  const k = COIN_ALIAS[raw] || raw;
  return COINS.has(k) ? k : undefined;
};
export function fundLogo(name) {
  const s = (name || "").toLowerCase();
  if (!s) return undefined;
  const found = countryLook().fundLogos.find(([re]) => re.test(s)) || FUND_LOGOS.find(([re]) => re.test(s));
  return found ? found[1] : undefined;
}
export function assetMark(a, size = "") {
  const coin = a.cat === "crypto" || a.symbol ? coinLogo(a.symbol) : undefined;
  if (coin) return logoMark(`coins/${coin}`, size);
  const fund = a.cat === "funds" ? fundLogo(a.name) : undefined;
  if (fund) return logoMark(fund, size);
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
// par code de région (`/finance/lookthrough`) : `home` est la région domestique du pack pays
const REGION_LOOK = {
  home: [ic("home"), "var(--neg)"], europe: ["EU", "var(--s1)"], north_america: ["US", "var(--s2)"], japan: ["JP", "var(--s5)"],
  pacific: ["AP", "var(--s7)"], emerging: ["ÉM", "var(--s3)"], crypto: [ic("coin"), "var(--s3)"],
};
const SECTOR_LOOK = {
  Technologie: "cpu", Finance: "landmark", "Santé": "heart", "Consommation discrétionnaire": "bag", "Consommation de base": "cart", Industrie: "factory",
  Communication: "radio", "Énergie": "bolt", "Matériaux": "cube", "Services publics": "drop", Immobilier: "home", Obligations: "doc",
  "Liquidités et dérivés": "banknote", Crypto: "coin",
};
export function lookMark(dim, bucket, color, size = "sm", code = null) {
  if (dim === "currency") return ccyMark(bucket, size);
  if (dim === "region") {
    const r = REGION_LOOK[code];
    if (r) return ibox(r[0].startsWith("<svg") ? r[0] : `<span>${esc(r[0])}</span>`, r[1], size);
    return ibox(ic("globe"), color, size);
  }
  return ibox(ic(SECTOR_LOOK[bucket] || "dots"), color, size);
}
