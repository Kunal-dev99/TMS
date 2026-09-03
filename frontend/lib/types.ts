/**
 * The contract, as the client sees it.
 *
 * A hand kept mirror of backend/app/schemas/models.py. It is generated from
 * the OpenAPI document once the real API is up; until then it is written by
 * hand and the contract tests are what keep the two honest.
 *
 * Nothing here is optional that the server sends as an explicit null, and
 * nothing here invents a field the server does not send.
 */

export type Instrument = "DEPOSIT" | "FX_FORWARD" | "MMF" | "GILT";
export type Enforcement = "HARD_BLOCK" | "WARN_WITH_OVERRIDE";
export type ApproverRole = "ANALYST" | "HEAD_OF_TREASURY" | "CFO";

export type CheckKey =
  | "COUNTERPARTY_ACTIVE"
  | "INSTRUMENT_PERMITTED"
  | "ENTITY_LIMIT"
  | "GROUP_LIMIT"
  | "TENOR_BAND"
  | "CONCENTRATION";

export interface CheckOutcome {
  key: CheckKey;
  name: string;
  passed: boolean;
  detail: string;
  workings: string[];
  /** Present only on a failure a smaller amount would clear. The client
   *  offers it as a control and never computes it. */
  resize_to_pence: number | null;
}

export interface CheckResult {
  check_run_id: string | null;
  as_of_date: string;
  counterparty_id: string;
  outcome: "PASS" | "FAIL" | "OVERRIDDEN";
  checks: CheckOutcome[];
  failed_count: number;
  measured_pence: number | null;
  measurement_basis: string | null;
  required_approver: ApproverRole | null;
  enforcement: Enforcement;
  verdict: string;
  limit_id: string | null;
  policy_version_id: string;
}

export interface BookRow {
  counterparty_id: string;
  name: string;
  group_id: string;
  group_name: string;
  rating: string;
  rating_status: string;
  status: string;
  limit_pence: number | null;
  limit_id: string | null;
  max_tenor_months: number | null;
  used_pence: number;
  headroom_pence: number | null;
  utilisation_bp: number | null;
  group_used_pence: number;
  group_limit_pence: number;
  group_utilisation_bp: number;
  instruments: Instrument[];
  has_open_breach: boolean;
}

export interface DealSummary {
  id: string;
  counterparty_id: string;
  counterparty_name: string;
  instrument: Instrument;
  principal_pence: number;
  currency: string;
  rate_bp: number;
  tenor_months: number;
  trade_date: string;
  value_date: string;
  maturity_date: string | null;
  status: string;
  capture_source: string;
  measured_pence: number;
  measurement_basis: string;
  stage: string;
  flag: "mismatch" | "breach" | "amended" | null;
  approved_by: string | null;
  required_approver: ApproverRole | null;
  accrual_today_pence: number | null;
  accrual_cumulative_pence: number | null;
}

export interface PolicyConfig {
  id: string;
  effective_from: string;
  concentration_cap_bp: number;
  threshold_analyst_pence: number;
  threshold_hot_pence: number;
  enforcement: Enforcement;
  fx_add_on_bp: number;
  approved_by: string;
}

export interface AdvisoryTicket {
  counterparty_id: string;
  instrument: Instrument;
  principal_pence: number;
  tenor_months: number;
  rate_bp: number;
}

export interface AdvisoryCard {
  run_id: string;
  as_of: string;
  gap_type: string;
  gap_amount_minor: number | null;
  gap_currency: string | null;
  gap_date: string | null;
  recommendation_id: string | null;
  headline: string;
  rationale: string | null;
  source: "MODEL" | "RULE_FALLBACK";
  alternatives: string[];
  ticket: AdvisoryTicket | null;
}

export interface QueueCounts {
  total: number;
  limit_failures: number;
  confirmation_mismatches: number;
}

/** What a rating entitles a counterparty to, before anybody signs. */
export interface RatingBandView {
  rating: string;
  ordinal: number;
  max_limit_pence: number;
  max_tenor_months: number;
}

export interface StateResponse {
  as_of_date: string;
  tenant_name: string;
  enforcement: Enforcement;
  policy: PolicyConfig;
  rating_bands: RatingBandView[];
  book: BookRow[];
  deals: DealSummary[];
  queue_counts: QueueCounts;
  breach_count: number;
  advisory: AdvisoryCard | null;
  advisory_run_id: string | null;
  uninvested_cash_pence: number;
  portfolio_total_pence: number;
}

export interface ApiError {
  error: { code: string; message: string; field: string | null };
}

/** The five ticket fields. Nothing else is needed to test a deal. */
export interface TicketFields {
  counterparty_id: string;
  instrument: Instrument;
  principal_pence: number;
  tenor_months: number;
  rate_bp: number;
}

export interface RecordDealResponse {
  deal: DealSummary;
  run: CheckResult;
  /** Set when the deal was blocked and an exception was raised. */
  queue_item_id: string | null;
}

export interface QueueItem {
  id: string;
  cause: "LIMIT_FAILURE" | "CONFIRMATION_MISMATCH";
  reason_code: string;
  detail: string;
  deal_id: string | null;
  confirmation_id: string | null;
  counterparty_id: string;
  counterparty_name: string;
  status: "OPEN" | "RESOLVED";
  resolution: string | null;
  raised_at: string;
  differences: MatchDifference[];
}

export interface BreachView {
  id: string;
  counterparty_id: string;
  counterparty_name: string;
  deal_id: string | null;
  type: "AMOUNT" | "TENOR" | "GROUP" | "CONCENTRATION" | "RATING";
  detail: string;
  status: "OPEN" | "RESPONDED";
  response: string | null;
  response_reason: string | null;
  original_check_run_id: string | null;
  raised_at: string;
}

export interface LimitVersion {
  id: string;
  counterparty_id: string;
  amount_pence: number;
  max_tenor_months: number;
  source: "BAND" | "MANUAL";
  effective_from: string;
  superseded_at: string | null;
  reason: string | null;
  approved_by: string;
}

export interface UtilisationRow {
  key: string;
  label: string;
  used_pence: number;
  limit_pence: number | null;
  utilisation_bp: number | null;
}

/** Counterparty exposure. Pence. Never joined to currency exposure. */
export interface ExposureView {
  as_of_date: string;
  portfolio_total_pence: number;
  uninvested_cash_pence: number;
  by_group: UtilisationRow[];
  by_rating_band: UtilisationRow[];
  by_maturity_bucket: UtilisationRow[];
}

export interface TimelineEvent {
  key: string;
  title: string;
  detail: string;
  occurred_at: string | null;
  source: "PLATFORM" | "OUTSIDE" | "ORACLE";
  state: "DONE" | "WARN" | "FUTURE";
}

/**
 * Everything the deal panel needs, in one object.
 *
 * Five of the collections are empty until phases two and three. They are
 * declared now because the panel is built against the contract rather than
 * against what happens to exist.
 */
export interface JournalSummary {
  period: string;
  status: "BUILT" | "POSTED" | "FAILED";
  count: number;
  amount_pence: number;
  oracle_reference: string | null;
}

export interface DealDetail {
  deal: DealSummary;
  timeline: TimelineEvent[];
  run: CheckResult | null;
  limit: LimitVersion | null;
  confirmation: ConfirmationSummary | null;
  accruals: AccrualRow[];
  journals: JournalSummary[];
  settlement: SettlementView | null;
  amendments: AmendmentView[];
  breaches: BreachView[];
}

export interface AdvisoryCandidate {
  id: string;
  counterparty_id: string;
  counterparty_name: string;
  instrument: Instrument;
  amount_pence: number;
  tenor_months: number;
  indicative_rate_bp: number;
  score_bp: number;
  excluded: boolean;
  exclusion_reason: string | null;
  rank: number | null;
}

export interface AdvisoryValidation {
  test: "ID_IS_REAL" | "CHECKS_RERUN_CLEAN" | "FIGURES_AGREE";
  passed: boolean;
  detail: string | null;
}

/** The full run, as the advisory panel reads it. */
export interface AdvisoryRunView {
  card: AdvisoryCard;
  candidates: AdvisoryCandidate[];
  validation: AdvisoryValidation[];
  outcome: string;
  model_enabled: boolean;
  model_name: string | null;
  started_at: string;
  finished_at: string | null;
}

export interface AmendmentPreview {
  accruals_affected: number;
  amount_to_reverse_pence: number;
  periods_affected: string[];
  any_period_closed: boolean;
}

export interface AmendmentView {
  id: string;
  type: string;
  effective_date: string;
  new_principal_pence: number | null;
  new_rate_bp: number | null;
  new_maturity_date: string | null;
  reason: string;
  status: "RAISED" | "APPLIED" | "REJECTED";
  raised_by: string;
  raised_at: string;
  applied_at: string | null;
}

export interface MatchDifference {
  field_name: string;
  keyed_value: string;
  confirmed_value: string;
}

export interface ConfirmationSummary {
  id: string;
  deal_id: string | null;
  counterparty_id: string | null;
  message_type: string;
  reference: string;
  received_at: string;
  match_status: "UNMATCHED" | "MATCHED" | "MISMATCHED" | "DISPUTED";
  differences: MatchDifference[];
}

export interface SettlementView {
  id: string;
  expected_principal_pence: number;
  expected_interest_pence: number;
  confirmed_amount_pence: number | null;
  statement_amount_pence: number | null;
  match_status: "PENDING" | "AGREED" | "BREAK";
  break_detail: string | null;
  closed_at: string | null;
}

export interface AccrualRow {
  id: string;
  accrual_date: string;
  day_count: number;
  rate_bp: number;
  amount_pence: number;
  cumulative_pence: number;
  reversal_of: string | null;
  amendment_id: string | null;
}

export interface StatementLine {
  id: string;
  account_name: string;
  amount_pence: number;
  value_date: string;
  reference: string | null;
  received_at: string;
}

export interface HedgeLinkView {
  id: string;
  deal_id: string;
  covered_amount_minor: number;
  currency: string;
  linked_at: string;
  unlinked_at: string | null;
  unlink_reason: string | null;
}

export interface CurrencyBucket {
  bucket: string;
  net_minor: number;
  covered_minor: number;
  target_cover_bp: number;
  covered_bp: number;
}

export interface CurrencyExposureRow {
  id: string;
  currency: string;
  amount_minor: number;
  direction: "PAYABLE" | "RECEIVABLE";
  expected_date: string;
  source: string;
  source_reference: string | null;
  status: "IDENTIFIED" | "PARTIALLY_COVERED" | "COVERED" | "SETTLED";
  hedges: HedgeLinkView[];
}

/** Never netted against counterparty exposure. The warning ships with it. */
export interface CurrencyExposureView {
  as_of_date: string;
  currency: string;
  buckets: CurrencyBucket[];
  exposures: CurrencyExposureRow[];
  warning: string;
}
