// Généré par `make openapi` (scripts/jstypes.py) depuis l'OpenAPI : ne pas modifier à la
// main. Montants : des MoneyOut (centimes, devise, texte) ; parts et taux : du texte.

export interface AcceptIn {
  proposal_ids: string[];
  challenge_id: string;
  assertion: Record<string, any>;
}

export interface AcceptOut {
  results: AcceptResultOut[];
}

export interface AcceptResultOut {
  id: string;
  status: string;
  result?: Record<string, any> | null;
  problem?: Record<string, any> | null;
}

export interface AccountListOut {
  items: AccountOut[];
}

export interface AccountOut {
  id: string;
  institution: string;
  name: string;
  kind: string;
  iban: string | null;
  external_ref: string | null;
  liquid: boolean;
  budget_account: boolean;
  availability: string;
  availability_set: boolean;
  availability_auto: string;
  goal: string;
  goal_set: boolean;
  category: string | null;
  hidden: boolean;
  target: MoneyOut | null;
  spend_rule: SpendRuleOut | null;
  balance: MoneyOut;
  value: MoneyOut;
  missing_prices: string[];
  last_booking: string | null;
  last_clbd: ClbdOut | null;
}

export interface AnswerOut {
  answer?: string;
  done?: any[];
  proposals?: any[];
  confirm?: string | null;
  heard?: string | null;
  speech?: Record<string, string> | null;
}

export interface AppModuleOut {
  label?: string;
  icon?: string;
  tabs: TabOut[];
  home_cards: HomeCardOut[];
  settings: SettingsSectionOut[];
  cards: string | null;
  home?: string | null;
  module?: string | null;
}

export interface ApprovalChallengeIn {
  proposal_ids: string[];
  action?: "accept" | "revert";
}

export interface ApprovalChallengeOut {
  challenge_id: string;
  options: Record<string, any>;
  approval_digest: string;
}

export interface AssistantStatusOut {
  configured: boolean;
  ok: boolean;
  voice: boolean;
}

export interface BalanceRecordOut {
  on_date: string;
  amount: MoneyOut;
}

export interface BreakOut {
  id: string;
  kind: string;
  account_id: string;
  account: string;
  asset: string;
  symbol: string;
  quantity: string | null;
  value: MoneyOut | null;
  since: string;
  until: string | null;
  cause: string;
  actions: string[];
}

export interface BreaksOut {
  on_date: string;
  currency: string;
  items: BreakOut[];
  count: number;
  open_value: MoneyOut;
  invested: MoneyOut;
  explained: MoneyOut;
  completeness: string | null;
  tolerance: MoneyOut;
}

export interface BucketAssetOut {
  isin: string | null;
  account_id?: string | null;
  name: string;
  value: MoneyOut;
}

export interface BucketOut {
  bucket: string;
  code: string | null;
  kind: string;
  estimated: boolean;
  value: MoneyOut;
  weight: string;
  count: number;
  assets: BucketAssetOut[];
}

export interface BudgetLineOut {
  category: string;
  name: string;
  group: string;
  count: number;
  spent: MoneyOut;
  target: MoneyOut | null;
  ratio: string | null;
  over: boolean;
  rest?: MoneyOut | null;
  projected?: MoneyOut | null;
  state?: string | null;
  yearly?: YearlyOut | null;
  paid_on?: string | null;
  expected_on?: string | null;
}

export interface BudgetMonthsOut {
  currency: string;
  series: MonthTotalsOut[];
}

export interface BudgetOut {
  month: string;
  period: string;
  months: string[];
  start: string;
  end: string;
  current: boolean;
  days_left: number;
  currency: string;
  income: MoneyOut;
  expenses: MoneyOut;
  budgeted_expenses: MoneyOut;
  budget: MoneyOut | null;
  rest_to_live: MoneyOut | null;
  projection: MoneyOut | null;
  expected: string | null;
  pace: string | null;
  over_count: number;
  state: BudgetStateOut;
  lines: BudgetLineOut[];
  missing_fx: MissingFxOut[];
}

export interface BudgetStateOut {
  kind: string;
  over_by: MoneyOut | null;
}

export interface BudgetTotalsOut {
  month: string;
  period: string;
  months: string[];
  start: string;
  end: string;
  currency: string;
  income: MoneyOut;
  expenses: MoneyOut;
  fixed: MoneyOut;
  variable: MoneyOut;
  savings: MoneyOut;
  invested: MoneyOut;
  budget: MoneyOut | null;
  budget_used: string | null;
  rate: string | null;
}

export interface CapabilitiesOut {
  domains: CapabilityOut[];
  profile: ProfileOut;
}

export interface CapabilityOut {
  domain: string;
  description: string;
  instructions: string;
  tools: string[];
  aggregates_only: boolean;
}

export interface CategorizationOut {
  category_id: string;
  source: string;
  rule_id: string | null;
  at: string;
}

export interface CategoryListOut {
  items: CategoryOut[];
}

export interface CategoryOut {
  id: string;
  name: string;
  group: string;
  active: boolean;
}

export interface CategoryRefOut {
  id: string;
  source: string;
}

export interface CategoryTotalOut {
  category: string;
  group: string;
  count: number;
  total: MoneyOut;
}

export interface ChallengeOut {
  challenge_id: string;
  options: Record<string, any>;
}

export interface ChangeOut {
  since: string;
  amount: MoneyOut;
  ratio: string | null;
}

export interface ClbdOut {
  on_date: string;
  amount: MoneyOut;
  gap: MoneyOut;
}

export interface CollectorGapOut {
  scope: string;
  reason: string;
}

export interface CollectorLinkIn {
  state: string;
}

export interface CollectorLinkOut {
  state: string;
  expires_at?: string | null;
  code?: string | null;
}

export interface CollectorLinkUrlIn {
  url?: string | null;
}

export interface CollectorListOut {
  items: CollectorOut[];
}

export interface CollectorModeIn {
  mode: "enabled" | "disabled";
}

export interface CollectorNeedsOut {
  needs: Record<string, (Record<string, string | boolean | null>)[]>;
}

export interface CollectorNotifyIn {
  event: "auth_pending" | "consent_expiring";
}

export interface CollectorNotifyOut {
  sent: boolean;
}

export interface CollectorOut {
  name: string;
  label: string;
  connector: string;
  ready: boolean;
  mode: string;
  consecutive_failures: number;
  since: string;
  check_requested: boolean;
  run_requested: boolean;
  last_run: CollectorRunOut | null;
  last_success_at: string | null;
  can_enable: boolean;
  link_requested: boolean;
  link_url: string | null;
  gaps?: CollectorGapOut[];
}

export interface CollectorRunIn {
  kind?: "run" | "check";
  outcome: "ok" | "nothing_new" | "auth_pending_timeout" | "site_unavailable" | "selector_missing" | "invalid_file" | "auth_error" | "unknown";
  started_at: string;
  ended_at: string;
  files?: number;
  detail?: string | null;
}

export interface CollectorRunOut {
  id: string;
  kind: string;
  outcome: string;
  started_at: string;
  ended_at: string | null;
  files: number;
  detail: string | null;
}

export interface CollectorRunsOut {
  items: CollectorRunOut[];
}

export interface ConfirmIn {
  challenge_id: string;
  credential: Record<string, any>;
}

export interface ConnectionIn {
  id: string;
  connector: string;
  label?: string | null;
  schedule?: string | null;
  settings?: Record<string, any>;
}

export interface ConnectionListOut {
  items: ConnectionOut[];
}

export interface ConnectionOut {
  id: string;
  connector: string;
  label: string;
  method: string | null;
  runner: string | null;
  schedule: string | null;
  custom_schedule: boolean;
  settings: Record<string, any>;
  secret_fields: string[];
  has_secrets: boolean;
  secrets_at: string | null;
  ready: boolean;
}

export interface ConnectionPatch {
  label?: string | null;
  schedule?: string | null;
  default_schedule?: boolean;
  settings?: Record<string, any> | null;
}

export interface ConnectionSecretsIn {
  values: Record<string, any>;
}

export interface ConnectorListOut {
  items: ConnectorOut[];
}

export interface ConnectorOut {
  name: string;
  label: string;
  method: "open_banking" | "api" | "public" | "browser";
  country: string | null;
  accounts: string[];
  secrets: string[];
  schedule: string;
  formats: string[];
  settings: string[];
  required_settings: string[];
  runner: "api" | "browser";
  single?: boolean;
  refresh_hint?: string | null;
}

export interface CoreHealthOut {
  db: string;
  revision: string | null;
  ok: boolean;
}

export interface CorrectionOut {
  id: string;
  amount: MoneyOut;
  booking_date: string;
}

export interface CountersOut {
  files: number;
  statements: number;
  new_entries: number;
  duplicate_entries: number;
  duplicate_files: number;
  rejected_files: number;
  ignored_files: number;
  applied: number;
  needs_review: number;
}

export interface CryptoAssetOut {
  quantity: string;
  value: MoneyOut;
  cost: MoneyOut;
  unrealized: MoneyOut;
  realized: MoneyOut;
  income: MoneyOut;
  result: MoneyOut;
  unknown_cost_value: MoneyOut;
}

export interface CryptoOut {
  invested: MoneyOut;
  value: MoneyOut;
  result: MoneyOut;
  missing_prices: boolean;
  since_purchase: CryptoResultOut | null;
}

export interface CryptoResultOut {
  on_date: string;
  currency: string;
  value: MoneyOut;
  cost: MoneyOut;
  unrealized: MoneyOut;
  realized: MoneyOut;
  result: MoneyOut;
  income: MoneyOut;
  result_usd: MoneyOut | null;
  crypto_effect: MoneyOut | null;
  fx_effect: MoneyOut | null;
  unknown_cost_value: MoneyOut;
  arrived_from_outside: MoneyOut;
  sent_outside_cost: MoneyOut;
  unexplained_out_cost: MoneyOut;
  sold_without_history: MoneyOut;
  missing_prices: boolean;
  by_asset: Record<string, CryptoAssetOut>;
}

export interface DebtListOut {
  items: DebtOut[];
}

export interface DebtOut {
  id: string;
  key: string;
  name: string;
  lender: string;
  kind: string;
  currency: string;
  original: MoneyOut;
  rate_pct: string | null;
  day_count: string;
  payment: MoneyOut | null;
  ends_on: string | null;
  category_id: string | null;
  category_name: string | null;
  account_id: string | null;
  account_name: string | null;
  closed_on: string | null;
  balance: MoneyOut;
  stated: MoneyOut | null;
  stated_on: string | null;
  paid_since: MoneyOut | null;
  interest_since: MoneyOut | null;
  payments_since: number;
  last_payment: string | null;
  usual_payment: MoneyOut | null;
  projected_end: string | null;
  balances: BalanceRecordOut[];
}

export interface DigestItemOut {
  id: string;
  urn: string;
  domain: string;
  kind: string;
  params: Record<string, any>;
  revision: number;
  status: string;
  tier: string;
  preview: PreviewOut;
  reason: string | null;
  bundle_id: string | null;
  created_by: string;
  created_at: string;
  expires_at: string;
  decided_at: string | null;
  result: Record<string, any> | null;
  reversible: boolean;
  reverted_by: string | null;
}

export interface DigestOut {
  day: string;
  items: DigestItemOut[];
}

export interface DomainHealthOut {
  db: string;
  schema_version: number;
  ok: boolean;
}

export interface DomainListOut {
  items: DomainOut[];
}

export interface DomainOut {
  name: string;
  description: string;
  schema_version: number;
  app: AppModuleOut;
  importers: ImporterOut[];
  connectors: string[];
}

export interface EntryDetailOut {
  id: string;
  account_id: string;
  kind: string;
  booking_date: string;
  value_date: string | null;
  amount: MoneyOut;
  counterparty: string | null;
  merchant: string | null;
  counterparty_iban: string | null;
  label: string | null;
  remittance: string | null;
  bank_tx_code: string | null;
  category: CategoryRefOut | null;
  categorizations: CategorizationOut[];
  notes: NoteOut[];
  corrections: CorrectionOut[];
}

export interface EntryListOut {
  items: EntryOut[];
  next_cursor: string | null;
}

export interface EntryOut {
  id: string;
  account_id: string;
  kind: string;
  booking_date: string;
  value_date: string | null;
  amount: MoneyOut;
  counterparty: string | null;
  merchant: string | null;
  counterparty_iban: string | null;
  label: string | null;
  remittance: string | null;
  bank_tx_code: string | null;
  category: CategoryRefOut | null;
}

export interface EntrySearchOut {
  items: EntryOut[];
}

export interface ExtremeOut {
  on_date: string;
  value: MoneyOut;
}

export interface ExtremesOut {
  high: ExtremeOut;
  low: ExtremeOut;
}

export interface FeesOut {
  on_date: string;
  currency: string;
  items: FundFeeOut[];
  yearly_cost: MoneyOut;
  covered_value: MoneyOut;
  unknown_value: MoneyOut;
  cost_over_years: MoneyOut;
  years: number;
  assumed_return_pct: string;
}

export interface FlowGroupOut {
  group: string;
  total: MoneyOut;
  items: FlowItemOut[];
}

export interface FlowItemOut {
  category: string;
  name: string;
  count: number;
  total: MoneyOut;
}

export interface FlowsOut {
  month: string;
  period: string;
  months: string[];
  currency: string;
  income: MoneyOut;
  sources: FlowItemOut[];
  groups: FlowGroupOut[];
  remainder: MoneyOut;
}

export interface FreshnessListOut {
  items: FreshnessOut[];
}

export interface FreshnessOut {
  account_id: string;
  name: string;
  institution: string;
  hidden: boolean;
  last_import: string | null;
  last_data: string | null;
  last_clbd: ClbdOut | null;
  collector: string | null;
}

export interface FundFeeOut {
  isin: string;
  name: string;
  value: MoneyOut;
  ter_pct: string | null;
  source: string | null;
  yearly_cost: MoneyOut | null;
}

export interface GoodListOut {
  items: GoodOut[];
}

export interface GoodOut {
  id: string;
  key: string;
  name: string;
  kind: string;
  currency: string;
  yearly_change_pct: string | null;
  closed_on: string | null;
  value: MoneyOut;
  stated: MoneyOut | null;
  stated_on: string | null;
  values: BalanceRecordOut[];
}

export interface HTTPValidationError {
  detail?: ValidationError[];
}

export interface HealthOut {
  status: string;
  version: string;
  core: CoreHealthOut;
  domains: Record<string, DomainHealthOut>;
}

export interface HistoryOut {
  items: Record<string, any>[];
  waiting?: Record<string, any>[];
}

export interface HitOut {
  domain: string;
  rank: number;
  urn: string;
  title: string;
  date: string | null;
  excerpt: string | null;
}

export interface HoldingOut {
  account_id: string;
  account: string | null;
  isin: string;
  name: string;
  asset_class: string | null;
  sub_class: string | null;
  quantity: string;
  price: string | null;
  price_currency: string | null;
  kind: string;
  price_date: string | null;
  value: MoneyOut;
  cost: MoneyOut | null;
  gain: MoneyOut | null;
  weight: string | null;
}

export interface HoldingsOut {
  on_date: string;
  currency: string;
  items: HoldingOut[];
  value: MoneyOut;
  cost: MoneyOut | null;
  missing_prices: string[];
  crypto: CryptoOut | null;
}

export interface HomeCardOut {
  id: string;
  label: string;
  endpoint: string;
}

export interface ImportDetailOut {
  id: string;
  source: string;
  file_name: string;
  received_at: string;
  status: string;
  stats: Record<string, any>;
  statements: StatementOut[];
  proposal_id: string | null;
}

export interface ImporterOut {
  name: string;
  label: string;
  suffixes: string[];
}

export interface KpisOut {
  month: string;
  as_of: string;
  currency: string;
  net_worth: MoneyOut;
  envelopes: Record<string, MoneyOut>;
  change_1m: ChangeOut;
  change_ytd: ChangeOut;
  deposits_ytd: MoneyOut;
  market_ytd: MoneyOut;
  income: MoneyOut;
  expenses: MoneyOut;
  savings: MoneyOut;
  savings_rate: string | null;
  budget: MoneyOut | null;
  budget_used: string | null;
  rest_to_live: MoneyOut | null;
  days_left: number;
  liquid: MoneyOut;
  months_covered: string | null;
  savings_rate_3m: string | null;
  stale_accounts: number;
  to_categorize: number;
  unmatched_transfers: number;
  pillar3a: Pillar3aOut | null;
  last_statement: string | null;
  missing_fx: string[];
  missing_prices: string[];
}

export interface LineSummaryOut {
  start: MoneyOut;
  end: MoneyOut;
  net_flows: MoneyOut;
  gain: MoneyOut;
  price_effect: MoneyOut;
  income: MoneyOut;
  fees: MoneyOut;
  twr: string | null;
  twr_yearly: string | null;
  mwr: string | null;
  personal?: string | null;
  complete: boolean;
}

export interface LinkOut {
  from_urn: string;
  to_urn: string;
  rel: string;
  other: RefOut | null;
}

export interface LinksOut {
  outgoing: LinkOut[];
  incoming: LinkOut[];
}

export interface LoginFinishIn {
  challenge_id: string;
  credential: Record<string, any>;
}

export interface LookthroughOut {
  dimension: string;
  on_date: string;
  currency: string;
  total: MoneyOut;
  owed: MoneyOut;
  covered: string | null;
  compositions_since: string | null;
  items: BucketOut[];
  unpriced: UnpricedOut[];
}

export interface MissingFxOut {
  currency: string;
  on_date: string;
  count: number;
}

export interface MoneyOut {
  minor: number;
  currency: string;
  display: string;
}

export interface MonthRuleOut {
  valid_from: string;
  start_day: number;
}

export interface MonthTotalsOut {
  month: string;
  income: MoneyOut;
  expenses: MoneyOut;
  fixed: MoneyOut;
  variable: MoneyOut;
  savings: MoneyOut;
  invested: MoneyOut;
  rate: string | null;
  budget?: MoneyOut | null;
  budgeted_expenses?: MoneyOut | null;
  over?: MoneyOut | null;
}

export interface NetworthHistoryOut {
  as_of: string | null;
  currency: string;
  items: NetworthPointOut[];
}

export interface NetworthPointOut {
  on_date: string;
  net_worth: MoneyOut;
  deposits_cum: MoneyOut;
  by_envelope: Record<string, MoneyOut>;
  by_account: Record<string, MoneyOut>;
}

export interface NoteOut {
  text: string;
  at: string;
}

export interface ObservationListOut {
  items: ObservationOut[];
}

export interface ObservationOut {
  domain: string;
  key: string;
  kind: string;
  severity: string;
  title: string;
  on_date: string;
  urn: string | null;
  detail: Record<string, any>;
}

export interface PackOut {
  name: string;
  label: string;
  description: string;
  country: string | null;
  version: number;
  installed: number | null;
  rules: number;
}

export interface PasskeyOut {
  id: string;
  device_name: string | null;
  created_at: string;
  last_used_at: string | null;
}

export interface PasskeysOut {
  items: PasskeyOut[];
}

export interface PendingAccountOut {
  ref: string;
  institution: string;
  kind: string;
  currency: string | null;
  imports: number;
  entries: number;
  from?: string | null;
  to: string | null;
  can_open: boolean;
}

export interface PendingAccountsOut {
  items: PendingAccountOut[];
}

export interface PerformanceEventOut {
  on_date: string;
  kind: string;
  amount: MoneyOut;
}

export interface PerformanceOut {
  currency: string;
  from?: string | null;
  to?: string | null;
  first_day?: string | null;
  lines: number;
  items: PerformancePointOut[];
  extremes?: ExtremesOut | null;
  summary: LineSummaryOut | null;
  owned?: LineSummaryOut | null;
  by_account: Record<string, LineSummaryOut>;
  by_asset: Record<string, LineSummaryOut>;
  by_line: Record<string, LineSummaryOut>;
  by_month: PeriodRowOut[];
  by_year: PeriodRowOut[];
  events: PerformanceEventOut[];
  missing: string[];
  risk: RiskOut | null;
}

export interface PerformancePointOut {
  on_date: string;
  value: MoneyOut;
  net_flows: MoneyOut;
  gain: MoneyOut;
  twr: string | null;
  personal?: string | null;
  drawdown: string | null;
  complete: boolean;
}

export interface PeriodOut {
  start: string;
  end: string;
}

export interface PeriodRowOut {
  period: string;
  gain: MoneyOut;
  net_flows: MoneyOut;
  twr: string | null;
}

export interface Pillar3aOut {
  year: number;
  cap: MoneyOut;
  paid: MoneyOut;
  margin: MoneyOut;
  source: string;
}

export interface PreviewOut {
  summary: string;
  details: Record<string, any>;
}

export interface PricePointOut {
  on_date: string;
  price: string;
}

export interface PricesOut {
  isin: string;
  name: string | null;
  currency: string | null;
  mixed_currencies: boolean;
  items: PricePointOut[];
}

export interface ProfileIn {
  display_name?: string | null;
  country?: string | null;
}

export interface ProfileOut {
  display_name: string | null;
  country: string;
  timezone: string;
  locale: string;
  currency: string;
  currency_exponent: number;
  modules: string[];
  packs: Record<string, Record<string, any>>;
}

export interface ProposalCreateIn {
  domain: string;
  kind: string;
  params: Record<string, any>;
  reason?: string | null;
  bundle_id?: string | null;
  external_text?: boolean | null;
}

export interface ProposalListOut {
  items: ProposalOut[];
}

export interface ProposalOut {
  id: string;
  urn: string;
  domain: string;
  kind: string;
  params: Record<string, any>;
  revision: number;
  status: string;
  tier: string;
  preview: PreviewOut;
  reason: string | null;
  bundle_id: string | null;
  created_by: string;
  created_at: string;
  expires_at: string;
  decided_at: string | null;
  result: Record<string, any> | null;
}

export interface RecurringByCategoryOut {
  category: string;
  monthly: MoneyOut;
}

export interface RecurringItemOut {
  label: string;
  category: string | null;
  category_name: string | null;
  cadence: string;
  amount: MoneyOut;
  last_amount: MoneyOut;
  monthly: MoneyOut;
  occurrences: number;
  last_date: string;
  next_date: string;
  active: boolean;
  account: string | null;
  last_entry_id: string | null;
}

export interface RecurringOut {
  as_of: string;
  count: number;
  due_30d: number;
  monthly_total: MoneyOut[];
  by_category: RecurringByCategoryOut[];
  items?: RecurringItemOut[] | null;
}

export interface RefOut {
  urn: string;
  title: string;
  date: string | null;
  href: string;
}

export interface RegisterBeginIn {
  bootstrap_code?: string | null;
  confirm?: ConfirmIn | null;
}

export interface RegisterFinishIn {
  challenge_id: string;
  credential: Record<string, any>;
  device_name?: string | null;
  bootstrap_code?: string | null;
}

export interface RevertIn {
  challenge_id: string;
  assertion: Record<string, any>;
}

export interface ReviewGroupOut {
  key: string;
  counterparty: string;
  direction: string;
  count: number;
  total: MoneyOut;
  min: MoneyOut;
  max: MoneyOut;
  first_date: string;
  last_date: string;
  accounts: string[];
  bank_tx_codes: string[];
  labels: string[];
  remittances: string[];
  history: string[];
  guess: string | null;
  entry_ids: string[];
  samples: ReviewSampleOut[];
}

export interface ReviewOut {
  groups: ReviewGroupOut[];
}

export interface ReviewSampleOut {
  id: string;
  account_id: string;
  booking_date: string;
  amount: MoneyOut;
  label: string | null;
  remittance: string | null;
}

export interface RiskOut {
  volatility: string | null;
  max_drawdown: string | null;
  peak_on: string | null;
  trough_on: string | null;
  recovered_on: string | null;
}

export interface RulePacksOut {
  items: PackOut[];
  suggested: string[];
  active_rules: number;
}

export interface RunnerConnectionOut {
  id: string;
  connector: string;
  label: string;
  schedule: string | null;
  settings: Record<string, any>;
  secrets: string | null;
}

export interface RunnerListOut {
  items: RunnerConnectionOut[];
}

export interface SearchOut {
  items: HitOut[];
}

export interface SessionOut {
  authenticated: boolean;
  actor?: string | null;
  expires_at?: string | null;
  passkeys: number;
  needs_bootstrap: boolean;
}

export interface SettingsOut {
  month_start_day: number;
  current_month: string;
  current_period: PeriodOut;
  rules: MonthRuleOut[];
  stale_days: number;
}

export interface SettingsSectionOut {
  id: string;
  label: string;
  icon: string;
  group: string;
  module: string;
  listed?: boolean;
}

export interface SpendRuleOut {
  rule_id: string;
  category_id: string;
}

export interface StatementOut {
  index: number;
  account_id: string | null;
  opbd_date: string | null;
  clbd_date: string | null;
  status: string;
  reasons: string[];
  new: number;
  duplicates: number;
}

export interface StrategiesOut {
  items: StrategyOut[];
  scopes: StrategyScopeOut[];
}

export interface StrategyKeptOut {
  done: number;
  skipped: number;
}

export interface StrategyOut {
  id: string;
  kind: string;
  scope: string;
  name: string;
  phrase: string;
  params: Record<string, any>;
  note: string | null;
  status: string;
  state: string;
  created_on: string;
  origin?: string | null;
  level: Record<string, any>;
  step: StrategyStepOut | null;
  steps: StrategyStepOut[];
  kept: StrategyKeptOut;
}

export interface StrategyRowOut {
  key: string;
  name: string;
  value: MoneyOut;
  cost: MoneyOut;
  ratio_pct: string | null;
}

export interface StrategyScopeOut {
  key: string;
  name: string;
  kind: string;
  value: MoneyOut;
}

export interface StrategyStepOut {
  id: string;
  key: string;
  state: string;
  opened_on: string;
  planned: MoneyOut | null;
  done: MoneyOut;
  detail: Record<string, any>;
  closed_on: string | null;
  closed_by: string | null;
  rows?: StrategyRowOut[] | null;
}

export interface SummaryOut {
  month: string;
  currency: string;
  income: MoneyOut;
  expenses: MoneyOut;
  savings: MoneyOut;
  transfers: MoneyOut;
  uncategorized: MoneyOut;
  by_group: Record<string, MoneyOut>;
  by_category: CategoryTotalOut[];
  missing_fx: MissingFxOut[];
}

export interface TabOut {
  id: string;
  label: string;
  icon: string;
  module: string;
  order: number;
}

export interface TalkIn {
  text: string;
  confirm?: string | null;
}

export interface TodoOut {
  to_categorize: number;
  today: string;
}

export interface ToolCallOut {
  result: any;
}

export interface ToolOut {
  name: string;
  description: string;
  input_schema: Record<string, any>;
}

export interface ToolsOut {
  domain: string;
  items: ToolOut[];
}

export interface TradeListOut {
  items: TradeOut[];
}

export interface TradeOut {
  id: string;
  account_id: string;
  trade_date: string;
  isin: string;
  name: string;
  quantity: string;
  amount: MoneyOut;
}

export interface TransfersOut {
  pairs: number;
  by_method: Record<string, number>;
  unmatched: number;
  unmatched_items?: UnmatchedOut[] | null;
}

export interface TrendOut {
  category: string | null;
  series: TrendPointOut[];
}

export interface TrendPointOut {
  month: string;
  count: number;
  total: MoneyOut;
}

export interface UnmatchedOut {
  id: string;
  account_id: string;
  account: string;
  date: string;
  amount: MoneyOut;
}

export interface UnpricedOut {
  isin: string;
  account_id: string;
  name: string;
}

export interface UploadItemOut {
  import_id: string | null;
  status: string;
}

export interface UploadOut {
  items: UploadItemOut[];
  counters: CountersOut;
}

export interface ValidationError {
  loc: (string | number)[];
  msg: string;
  type: string;
  input?: any;
  ctx?: Record<string, any>;
}

export interface YearlyOut {
  from?: string | null;
  target: MoneyOut;
  spent: MoneyOut;
  ratio: string | null;
}
