// Les balises de la finance, posées par la coquille avant tout rendu (export `markup` de
// finance.js) : ses styles, l'accueil « Premiers pas », ses trois écrans, ses rubriques des
// réglages.
// index.html ne connaît plus aucun domaine.

const WELCOME = `
      <section class="card form" id="c-welcome" aria-labelledby="t-welcome" hidden>
        <div class="head"><h2 id="t-welcome">Premiers pas</h2><button class="link" id="welcome-hide" type="button">Masquer</button></div>
        <p class="note" id="welcome-sub"></p>
        <div id="welcome-list"></div>
        <p class="message" id="welcome-msg" role="status"></p>
      </section>
`;

const VIEWS = `
    <!-- ================= PATRIMOINE ================= -->
    <section class="view" id="patrimoine" data-view="patrimoine" aria-labelledby="t-patrimoine" hidden>
      <header class="topbar" id="pat-top">
        <div class="topbar-row">
          <nav class="crumbs" id="patCrumbs" aria-label="Chemin" hidden></nav>
          <h1 class="topbar-title" id="t-patrimoine">Patrimoine<span class="topbar-sub" data-fresh></span><span class="topbar-mini num" id="miniTotal"></span></h1>
          <button class="icon-btn" type="button" data-a="hide" aria-pressed="false"></button>
          <button class="icon-btn" type="button" data-a="settings" aria-label="Sources et réglages"></button>
        </div>
        <div class="filterbar" id="filterbar"></div>
      </header>
      <div id="patBody"></div>
    </section>

    <!-- ================= BUDGET ================= -->
    <section class="view" id="budget" data-view="budget" aria-labelledby="t-budget" hidden>
      <header class="topbar">
        <div class="topbar-row">
          <h1 class="topbar-title" id="t-budget">Budget<span class="topbar-sub" data-fresh></span></h1>
          <button class="icon-btn" type="button" data-a="hide" aria-pressed="false"></button>
          <button class="icon-btn" type="button" data-a="settings" aria-label="Sources et réglages"></button>
        </div>
        <div class="ctxbar" id="budCtx"></div>
      </header>
      <div id="budBody"></div>
    </section>

    <!-- ================= JOURNAL ================= -->
    <section class="view" id="journal" data-view="journal" aria-labelledby="t-journal" hidden>
      <header class="topbar">
        <div class="topbar-row">
          <h1 class="topbar-title" id="t-journal">Journal<span class="topbar-sub" data-fresh></span></h1>
          <button class="icon-btn" type="button" data-a="hide" aria-pressed="false"></button>
          <button class="icon-btn" type="button" data-a="settings" aria-label="Sources et réglages"></button>
        </div>
        <div class="searchbox"><span id="search-ic"></span><input id="jq" type="search" placeholder="Contrepartie, libellé…" aria-label="Rechercher une écriture, 3 lettres au moins" autocomplete="off" enterkeyhint="search"></div>
        <div class="filterbar" id="jChips" role="group" aria-label="Filtrer le journal"></div>
      </header>
      <div id="jBody"></div>
    </section>
`;

const RUBRICS = `
      <section class="card" data-rubric="conn" aria-labelledby="t-conn">
        <div class="head"><h2 id="t-conn">Connexions</h2><span><button class="link" id="conn-refresh" type="button">Tout actualiser</button> <button class="link" id="conn-add" type="button">Ajouter</button></span></div>
        <p class="note">Banques, plateformes et cours que le hub collecte, chacun à son horaire ; « Actualiser » le lance tout de suite. Les identifiants sont chiffrés à la saisie et ne s'affichent plus jamais.</p>
        <div id="coll-list"></div>
        <p id="coll-msg" class="message" role="status"></p>
      </section>
      <section class="card form" data-rubric="conn" id="conn-editor" hidden></section>

      <section class="card" data-rubric="conn" aria-labelledby="t-pending">
        <div class="head"><h2 id="t-pending">Comptes en attente</h2><button class="link" id="acct-add" type="button">Ajouter</button></div>
        <p class="note">Les relevés d'un compte inconnu attendent sa création, validée avec Face ID.</p>
        <div id="acct-pending"></div>
        <p id="acct-msg" class="message" role="status"></p>
      </section>
      <section class="card form" data-rubric="conn" id="acct-editor" hidden></section>

      <section class="card" data-rubric="accounts" aria-labelledby="t-fresh">
        <div class="head"><h2 id="t-fresh">Comptes</h2></div>
        <p class="note">Date de la dernière donnée reçue pour chaque compte : au-delà de 45 jours, il est à rafraîchir. Touche un compte pour le renommer, le classer ou le masquer.</p>
        <div id="fresh-list"></div>
      </section>

      <section class="card" data-rubric="debts" aria-labelledby="t-debts">
        <div class="head"><h2 id="t-debts">Dettes</h2><button class="link" type="button" data-a="debt-add">Ajouter</button></div>
        <p class="note">Crédit, hypothèque, leasing, prêt étudiant : le solde est retranché du patrimoine et baisse avec chaque paiement de sa catégorie.</p>
        <div id="debt-list"></div>
      </section>

      <section class="card" data-rubric="budget" aria-labelledby="t-budget-set">
        <h2 class="section-title" id="t-budget-set">Budget</h2>
        <div id="budget-rows"></div>
      </section>

      <section class="card" data-rubric="tax" aria-labelledby="t-tax-set">
        <h2 class="section-title" id="t-tax-set">Impôts et 3a</h2>
        <div id="tax-rows"></div>
      </section>

      <section class="card" data-rubric="export" aria-labelledby="t-data">
        <h2 class="section-title" id="t-data">Exporter</h2>
        <p class="note">Le journal complet en CSV, tel qu'il est au registre.</p>
        <a class="secondary" id="export-link" href="/api/finance/export.csv" download>Exporter le journal (CSV)</a>
      </section>
`;

export const markup = [
  ["head", "beforeend", '<link rel="stylesheet" href="/d/finance/finance.css">'],
  ["#homeBody", "beforebegin", WELCOME],
  ["#sources", "beforebegin", VIEWS],
  ["#sources > .endspace", "beforebegin", RUBRICS],
];
