/**
 * The request layer.
 *
 * One origin, because Next.js rewrites /api to whichever API is running.
 * Nothing here knows whether the mock or the real API answered.
 *
 * Cancellation lives here rather than in a component. Without it a slow
 * response can arrive after a newer one and paint a verdict for an amount
 * the user has already changed. That is a wrong answer, not a slow one.
 *
 * Nothing in this file decides anything. It sends what the user typed and
 * returns what the server said. There is no check logic, no limit
 * arithmetic, no approval threshold and no candidate filtering in the
 * client, and any pull to put one here is a design failure to raise rather
 * than accommodate.
 *
 * Since phase 1.5 every call carries a bearer token and no call carries an
 * actor. Who is acting is a fact the server establishes from the token, not
 * a claim the client makes in a body.
 */

import { currentToken, endSession, startSession, type SignedInUser } from "./session";
import type {
  ApiError,
  BreachView,
  CheckResult,
  AdvisoryCard,
  AdvisoryRunView,
  AmendmentPreview,
  CurrencyExposureView,
  DealDetail,
  ExposureView,
  StatementLine,
  LimitVersion,
  PolicyConfig,
  QueueItem,
  RecordDealResponse,
  StateResponse,
  TicketFields,
} from "./types";

const BASE = "/api/v1";

export class RequestFailed extends Error {
  code: string;
  field: string | null;
  status: number;

  constructor(status: number, body: ApiError) {
    super(body.error.message);
    this.status = status;
    this.code = body.error.code;
    this.field = body.error.field;
  }
}

/** Fired when a token expires mid session, so the surface can ask again. */
export type SessionEndedHandler = () => void;
let onSessionEnded: SessionEndedHandler = () => undefined;

export function whenSessionEnds(handler: SessionEndedHandler): void {
  onSessionEnded = handler;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = currentToken();
  const response = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      "content-type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init.headers ?? {}),
    },
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as ApiError | null;
    if (response.status === 401) {
      // A token expires after twelve hours, and it can expire between one
      // call and the next. The surface asks again rather than showing an
      // error the user cannot act on.
      endSession();
      onSessionEnded();
    }
    if (body?.error) throw new RequestFailed(response.status, body);
    throw new Error(`${response.status} on ${path}`);
  }
  return (await response.json()) as T;
}

function post<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  return request<T>(path, { method: "POST", body: JSON.stringify(body), signal });
}

function put<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  return request<T>(path, { method: "PUT", body: JSON.stringify(body), signal });
}

function get<T>(path: string, signal?: AbortSignal): Promise<T> {
  return request<T>(path, { method: "GET", signal });
}

// -- signing in -----------------------------------------------------------

export async function signIn(
  email: string,
  password: string,
): Promise<SignedInUser> {
  const body = await request<{ token: string; user: SignedInUser }>(
    "/auth/token",
    { method: "POST", body: JSON.stringify({ email, password }) },
  );
  startSession(body.token, body.user);
  return body.user;
}

export async function whoAmI(): Promise<SignedInUser> {
  return request<SignedInUser>("/auth/me");
}

export async function signOut(): Promise<void> {
  try {
    await post("/auth/logout", {});
  } finally {
    endSession();
  }
}

// -- reads -----------------------------------------------------------------

/** Everything the surface needs, in one call. Refetched whole after a write. */
export function getState(signal?: AbortSignal): Promise<StateResponse> {
  return request<StateResponse>("/state", { signal });
}

export function getPolicy(): Promise<PolicyConfig> {
  return request<PolicyConfig>("/policy");
}

export function getQueue(): Promise<QueueItem[]> {
  return request<QueueItem[]>("/queue");
}

export function getBreaches(): Promise<BreachView[]> {
  return request<BreachView[]>("/breaches");
}

export function getLimits(counterpartyId: string): Promise<LimitVersion[]> {
  return request<LimitVersion[]>(`/counterparties/${counterpartyId}/limits`);
}

// -- the gate --------------------------------------------------------------

/**
 * The check that persists nothing.
 *
 * Called on every pause in typing. The caller passes the signal from an
 * AbortController it replaces on each keystroke, so only the newest answer
 * can arrive.
 */
export function checkDeal(
  ticket: TicketFields,
  signal?: AbortSignal,
): Promise<CheckResult> {
  return post<CheckResult>("/deals/check", ticket, signal);
}

/**
 * Record a deal.
 *
 * The server re-runs the same engine as the control. There is deliberately
 * no field here for the result the client already has, so a stale browser
 * cannot hand the server a verdict to trust.
 *
 * A blocked deal comes back as a 201 with status BLOCKED, not as an error.
 * The record was created and the exception was raised, so the control
 * worked.
 */
export function recordDeal(
  ticket: TicketFields,
  overrideReason?: string,
  recommendationId?: string | null,
): Promise<RecordDealResponse> {
  return post<RecordDealResponse>("/deals", {
    ...ticket,
    override_reason: overrideReason ?? null,
    // The dashed edge. The deal endpoint writes back to the recommendation
    // once the deal has passed the six checks, which is the only direction
    // that edge runs in.
    recommendation_id: recommendationId ?? null,
  });
}

/**
 * Sign a deal.
 *
 * The signature is the caller. A deal cannot be signed by the person who
 * proposed it, and the role has to be one the signer actually holds, so this
 * is refused far more often than it was before phase 1.5 and that is the
 * point.
 */
export function approveDeal(
  dealId: string,
  role: string,
): Promise<{ deal_id: string; status: string; approved_by: string }> {
  return post(`/deals/${dealId}/approve`, { role });
}

export function instructDeal(dealId: string) {
  return post(`/deals/${dealId}/instruct`, {});
}

/** One click, one panel, one call. */
export function getDeal(dealId: string, signal?: AbortSignal): Promise<DealDetail> {
  return request<DealDetail>(`/deals/${dealId}`, { signal });
}

/**
 * Counterparty exposure. Pence.
 *
 * There is no getExposure that returns both figures, because there is no
 * endpoint that returns both. A forward increases counterparty exposure and
 * reduces currency exposure, and the two are never netted.
 */
export function getExposure(signal?: AbortSignal): Promise<ExposureView> {
  return request<ExposureView>("/exposure/counterparty", { signal });
}

// -- Performance ---------------------------------------------------------

export type PerformanceByCounterparty = {
  counterparty_id: string;
  name: string;
  rating: string;
  band: string;
  interest_pence: number;
  deal_count: number;
  share_bp: number;
};

export type PerformanceByBand = {
  band: string;
  interest_pence: number;
  share_bp: number;
};

export type PerformanceByMonth = {
  month: string;
  interest_pence: number;
  cumulative_pence: number;
};

export type PerformanceInsight = {
  kind: "positive" | "neutral" | "watch";
  title: string;
  body: string;
};

export type PerformanceLens = "yield" | "diversification" | "safety";

export type PerformanceProjection = {
  based_on_month: string;
  monthly_run_rate_pence: number;
  three_month_pence: number;
  six_month_pence: number;
  twelve_month_pence: number;
};

export type PerformanceView = {
  total_interest_pence: number;
  weighted_rate_bp: number;
  days_recognised: number;
  by_counterparty: PerformanceByCounterparty[];
  by_band: PerformanceByBand[];
  by_month: PerformanceByMonth[];
  /** Default lens ("yield") for backwards compatibility. */
  insights: PerformanceInsight[];
  /** Insights broken out per lens; UI toggles between them. */
  insights_by_lens: Record<PerformanceLens, PerformanceInsight[]>;
  projection: PerformanceProjection | null;
};

export function getPerformance(signal?: AbortSignal): Promise<PerformanceView> {
  return request<PerformanceView>("/performance", { signal });
}

// -- Accounting events (mock) --------------------------------------------

export type AccountingEventRule = {
  stage: string;
  is_event: boolean;
  event_class: string;
  event_type: string;
  posts_to: string;
  integration: string;
  cadence: string;
  note: string;
};

export type AccountingEventTarget = {
  key: string;
  label: string;
};

export type AccountingEventSettings = {
  rules: AccountingEventRule[];
  lifecycle_stages: string[];
  /** Book-wide destination (e.g. "ORACLE_FUSION_AHCS"). */
  target_gl: string;
  /** Human label for `target_gl`. */
  target_label: string;
  /** Available destinations the connector can route to. */
  supported_targets: AccountingEventTarget[];
  /** First-party connector name — never OIC. */
  connector_name: string;
};

export function getAccountingEvents(): Promise<AccountingEventSettings> {
  return get<AccountingEventSettings>("/accounting/events");
}

export function updateAccountingEvents(
  patch: { rules: AccountingEventRule[]; target_gl?: string },
): Promise<AccountingEventSettings> {
  return put<AccountingEventSettings>("/accounting/events", patch);
}

export function resetAccountingEvents(): Promise<AccountingEventSettings> {
  return post<AccountingEventSettings>("/accounting/events/reset", {});
}

// -- Counterparty data sources (Bloomberg / Fitch / ISINs) ---------------

export type InstrumentCode = {
  instrument: string;
  isin: string;
  code: string;
  source: string;
};

export type CounterpartySource = {
  rating_source: string;
  rating_as_of: string;
  instruments: InstrumentCode[];
};

export type CounterpartySourcesView = {
  sources: Record<string, CounterpartySource>;
  notice: string;
};

export function getCounterpartySources(
  signal?: AbortSignal,
): Promise<CounterpartySourcesView> {
  return get<CounterpartySourcesView>("/counterparties/sources", signal);
}

// -- Rate quote (Bloomberg BGN pre-fill) ---------------------------------

export type RateQuote = {
  counterparty_id: string;
  instrument: string;
  tenor_months: number;
  rate_bp: number;
  rating_used: string;
  source: string;
  quality: string;
  as_of: string;
  notice: string;
};

export function getRateQuote(
  counterpartyId: string,
  instrument: string,
  tenorMonths: number,
  signal?: AbortSignal,
): Promise<RateQuote> {
  const q = new URLSearchParams({
    counterparty_id: counterpartyId,
    instrument,
    tenor_months: String(tenorMonths),
  });
  return get<RateQuote>(`/rates/quote?${q.toString()}`, signal);
}

// -- System policy (Control) --------------------------------------------

export type SystemPolicyBand = {
  rating: string;
  ordinal: number;
  max_limit_pence: number;
  max_tenor_months: number;
};

export type SystemPolicySource = {
  field: string;
  source: string;
  editable: string;
  shown_on: string;
};

export type SystemPolicyView = {
  policy: {
    concentration_cap_bp: number;
    enforcement: "HARD_BLOCK" | "WARN_WITH_OVERRIDE";
    threshold_analyst_pence: number;
    threshold_hot_pence: number;
    fx_add_on_bp: number;
  };
  rating_bands: SystemPolicyBand[];
  rate_curve: Record<string, Record<string, number>>;
  curve_tenors: number[];
  rating_ladder: string[];
  sources: SystemPolicySource[];
};

export function getSystemPolicy(signal?: AbortSignal): Promise<SystemPolicyView> {
  return get<SystemPolicyView>("/system-policy", signal);
}

export function updateSystemPolicy(patch: {
  policy?: Partial<SystemPolicyView["policy"]>;
  rating_bands?: Array<Partial<SystemPolicyBand> & { rating: string }>;
  rate_curve?: Record<string, Record<string, number>>;
}): Promise<SystemPolicyView> {
  return put<SystemPolicyView>("/system-policy", patch);
}

export function resetRateCurve(): Promise<SystemPolicyView> {
  return post<SystemPolicyView>("/system-policy/reset-rate-curve", {});
}

// -- the advisory layer ----------------------------------------------------

/** Null is a valid answer, not a 404. */
export function getAdvisoryLatest(signal?: AbortSignal): Promise<AdvisoryCard | null> {
  return request<AdvisoryCard | null>("/advisory/latest", { signal });
}

export function getAdvisoryRun(
  runId: string,
  signal?: AbortSignal,
): Promise<AdvisoryRunView> {
  return request<AdvisoryRunView>(`/advisory/runs/${runId}`, { signal });
}

/**
 * Record what a person decided. Books nothing.
 *
 * On acceptance this returns the payload the deal form loads: the same five
 * fields somebody would have typed. Recording the deal is a separate call to
 * the ordinary endpoint, which runs the ordinary six checks.
 */
export function decideRecommendation(
  recommendationId: string,
  decision: "ACCEPTED" | "EDITED" | "REJECTED",
  reason?: string,
): Promise<{ ok: boolean; ticket: Record<string, unknown> | null }> {
  return post(`/advisory/recommendations/${recommendationId}/decide`, {
    decision,
    reason: reason ?? null,
  });
}

/** Accrual, then journals, then advisory. Returns 202. */
export function runNightly(force = false) {
  return post("/jobs/nightly", { force });
}


// -- the deal lifecycle ----------------------------------------------------

/**
 * Raise an amendment. Records what is proposed and returns what applying it
 * would change, without changing it.
 *
 * Two calls rather than one, because a reversal that reaches into a closed
 * period is a conversation with the accountants and has to be visible before
 * it happens.
 */
export function raiseAmendment(
  dealId: string,
  body: {
    type: string;
    effective_date: string;
    reason: string;
    new_principal_pence?: number | null;
    new_rate_bp?: number | null;
    new_maturity_date?: string | null;
  },
): Promise<{ amendment_id: string; preview: AmendmentPreview }> {
  return post(`/deals/${dealId}/amendments`, {
    new_principal_pence: null,
    new_rate_bp: null,
    new_maturity_date: null,
    ...body,
  });
}

export function applyAmendment(amendmentId: string) {
  return post(`/amendments/${amendmentId}/apply`, {});
}

/** Three sources have to agree. Two of three is not enough. */
export function settleDeal(dealId: string, statementLineId: string) {
  return post<{
    match_status: string;
    break_detail: string | null;
    closed_at: string | null;
  }>(`/deals/${dealId}/settle`, { statement_line_id: statementLineId });
}

export function getStatements(): Promise<StatementLine[]> {
  return request<StatementLine[]>("/statements");
}

export function recordStatementLine(body: {
  account_name: string;
  amount_pence: number;
  value_date: string;
  reference?: string | null;
}) {
  return post<{ statement_line_id: string }>("/statements", {
    reference: null,
    ...body,
  });
}

// -- currency risk ---------------------------------------------------------

/**
 * Currency exposure. Minor units, with a currency on every figure.
 *
 * There is no call here that returns both exposures, because there is no
 * endpoint that does. A forward increases counterparty exposure and reduces
 * currency exposure, and the two are never netted.
 */
export function getCurrencyExposure(
  currency = "EUR",
  signal?: AbortSignal,
): Promise<CurrencyExposureView> {
  return request<CurrencyExposureView>(
    `/exposure/currency?currency=${currency}`,
    { signal },
  );
}

export function recordCurrencyExposure(body: {
  currency: string;
  amount_minor: number;
  direction: string;
  expected_date: string;
  source: string;
  source_reference?: string | null;
}) {
  return post("/currency-exposures", { source_reference: null, ...body });
}

export function linkHedge(
  exposureId: string,
  dealId: string,
  coveredAmountMinor: number,
) {
  return post(`/currency-exposures/${exposureId}/hedges`, {
    deal_id: dealId,
    covered_amount_minor: coveredAmountMinor,
  });
}

/** Coverage is recomputed and the status can move backwards. */
export function unlinkHedge(linkId: string, reason: string) {
  return post(`/hedge-links/${linkId}/unlink`, { reason });
}

// -- the queue and breaches ------------------------------------------------

export function resolveQueueItem(
  itemId: string,
  resolution: string,
  reason?: string,
) {
  return post(`/queue/${itemId}/resolve`, { resolution, reason: reason ?? null });
}

/** Records the decision. Does not clear the breach. */
export function respondToBreach(breachId: string, response: string, reason?: string) {
  return post(`/breaches/${breachId}/respond`, { response, reason: reason ?? null });
}

// -- the world moving ------------------------------------------------------

/** One call in, an unknown number of breaches out. */
export function applyRatingAction(
  counterpartyId: string,
  newRating: string,
  newStatus: string = "WATCH",
): Promise<{
  action: string;
  new_limit_pence: number | null;
  new_max_tenor_months: number | null;
  positions_tested: number;
  breaches_raised: number;
}> {
  return post(`/counterparties/${counterpartyId}/rating`, {
    new_rating: newRating,
    new_status: newStatus,
  });
}

export function setEnforcement(enforcement: string): Promise<PolicyConfig> {
  return post<PolicyConfig>("/admin/enforcement", { enforcement });
}

export function setClock(today: string) {
  return post("/admin/clock", { today_date: today });
}

export function resetBook() {
  return post("/admin/reset", {});
}

// -- onboarding ------------------------------------------------------------

export function createCounterparty(
  name: string,
): Promise<{ counterparty_id: string; status: string }> {
  return post("/counterparties", { name });
}

export function verifyCounterparty(
  counterpartyId: string,
  body: {
    legal_entity_identifier: string;
    group_parent_name: string;
    rating: string;
    country: string;
    instruments: string[];
  },
): Promise<{
  status: string;
  proposed_limit_pence: number;
  proposed_max_tenor_months: number;
}> {
  return post(`/counterparties/${counterpartyId}/verify`, body);
}

export function setCounterpartyLimit(
  counterpartyId: string,
  body: {
    amount_pence: number;
    max_tenor_months: number;
    approved_by: string;
    reason?: string;
  },
) {
  return post(`/counterparties/${counterpartyId}/limit`, {
    ...body,
    reason: body.reason ?? null,
  });
}

export function activateCounterparty(counterpartyId: string) {
  return post(`/counterparties/${counterpartyId}/activate`, {});
}

// -- What-if scenarios ---------------------------------------------------
//
// The deterministic core produces every figure; the AI writes the paragraph
// that reads them. All three endpoints are read-only from the book's point
// of view: rating change runs inside a savepoint that is rolled back, and
// the other two never touch the database at all.

export type ScenarioResult = {
  scenario: "RATING_CHANGE" | "NOT_ROLLED" | "CAP_CHANGE";
  inputs: Record<string, unknown>;
  before: Record<string, unknown>;
  after: Record<string, unknown>;
  changes: string[];
  narrative: string;
};

export function whatIfRatingChange(body: {
  counterparty_id: string;
  new_rating: string;
  new_status?: string;
}): Promise<ScenarioResult> {
  return post("/what-if/rating-change", body) as Promise<ScenarioResult>;
}

export function whatIfNotRolled(deal_id: string): Promise<ScenarioResult> {
  return post("/what-if/not-rolled", { deal_id }) as Promise<ScenarioResult>;
}

export function whatIfCapChange(new_cap_bp: number): Promise<ScenarioResult> {
  return post("/what-if/cap-change", { new_cap_bp }) as Promise<ScenarioResult>;
}

// -- Cash Deployment Planner --------------------------------------------

export type PlannerAllocation = {
  counterparty_id: string;
  counterparty_name: string;
  counterparty_rating: string;
  group_name: string;
  principal_pence: number;
  tenor_months: number;
  rate_bp: number;
  expected_annual_interest_pence: number;
  resulting_utilisation_bp: number;
  resulting_group_utilisation_bp: number;
};

export type PlannerCandidate = {
  // Built-in kinds: MAX_YIELD, DIVERSIFIED, PRESERVE_HEADROOM, CONSERVATIVE.
  // Custom strategies added from the settings modal have arbitrary kinds.
  kind: string;
  label: string;
  tagline: string;
  allocations: PlannerAllocation[];
  weighted_rate_bp: number;
  expected_annual_interest_pence: number;
  concentration_change_bp: number;
  deployed_pence: number;
  undeployed_pence: number;
};

export type PlannerSettingsInUse = {
  min_rating: string;
  max_tenor_months: number;
  per_name_cap_pct: number;
  group_concentration_cap_pct: number;
  buckets: Record<string, number>;
};

export type DeploymentPlan = {
  idle_cash_pence: number;
  portfolio_total_pence: number;
  concentration_cap_bp: number;
  candidates: PlannerCandidate[];
  recommendation_kind: string;
  recommendation_reason: string;
  per_candidate_labels: Record<string, string>;
  settings_in_use: PlannerSettingsInUse | null;
};

export function deployCash(): Promise<DeploymentPlan> {
  return post("/planner/deploy-cash", {}) as Promise<DeploymentPlan>;
}

// -- Cash Deployment Planner: editable settings --------------------------

export type PlannerStrategyMeta = {
  kind: string;
  label: string;
  tagline: string;
};

export type CustomStrategy = {
  kind: string;
  label: string;
  tagline: string;
  based_on: string;
  min_rating: string;
  max_tenor_months: number;
};

export type PlannerSettings = {
  min_rating: string;
  max_tenor_months: number;
  per_name_cap_pct: number;
  group_concentration_cap_pct: number;
  /** Rating-band allocation buckets — must sum to 100 for Save to be valid. */
  buckets: Record<string, number>;
  enabled_strategies: string[];
  custom_strategies: CustomStrategy[];
  builtin_strategies: PlannerStrategyMeta[];
  rating_ladder: string[];
  /** Bucket labels in display order (highest rating first). */
  rating_bands: string[];
};

export function getPlannerSettings(): Promise<PlannerSettings> {
  return get<PlannerSettings>("/planner/settings");
}

export function updatePlannerSettings(
  patch: Partial<PlannerSettings>,
): Promise<PlannerSettings> {
  return put<PlannerSettings>("/planner/settings", patch);
}

export function resetPlannerSettings(): Promise<PlannerSettings> {
  return post<PlannerSettings>("/planner/settings/reset", {});
}

// -- Confirmation parser (AI) -----------------------------------------------

export type ParsedConfirmation = {
  message_type: string | null;
  reference: string | null;
  counterparty_id: string | null;
  counterparty_name: string | null;
  instrument: string | null;
  principal_pence: number | null;
  rate_bp: number | null;
  value_date: string | null;
  maturity_date: string | null;
  raw_payload: string;
  warnings: string[];
  fields_extracted: string[];
  fields_missing: string[];
};

export function parseConfirmation(raw_text: string): Promise<ParsedConfirmation> {
  return post("/confirmations/parse", { raw_text }) as Promise<ParsedConfirmation>;
}

export type ConfirmationIngestResult = {
  confirmation_id: string;
  match_status: "MATCHED" | "MISMATCHED" | "UNMATCHED";
  deal_id: string | null;
  differences: { field_name: string; keyed_value: string; confirmed_value: string }[];
  queue_item_id: string | null;
};

export function ingestConfirmation(body: {
  message_type: string;
  reference: string;
  counterparty_id?: string | null;
  instrument: string;
  principal_pence: number;
  rate_bp: number;
  value_date: string;
  maturity_date?: string | null;
  raw_payload?: string | null;
}): Promise<ConfirmationIngestResult> {
  return post("/confirmations", body) as Promise<ConfirmationIngestResult>;
}

// -- Credit-signal scanner (AI) ---------------------------------------------

export type NewsSummary = {
  id: string;
  source: string;
  headline: string;
  published_at: string;
  materiality: "MATERIAL" | "WATCH" | "IMMATERIAL";
  reasoning: string;
};

export type CreditSignal = {
  counterparty_id: string;
  counterparty_name: string;
  rating: string;
  severity: "MATERIAL" | "WATCH" | "QUIET";
  used_pence: number;
  limit_pence: number;
  utilisation_bp: number;
  summary: string;
  suggested_action: "PUT_ON_WATCH" | "REDUCE" | "ROLL_OFF" | "MONITOR" | "IGNORE";
  items: NewsSummary[];
};

export function scanCreditSignals(): Promise<{ signals: CreditSignal[] }> {
  return post("/credit-signals/scan", {}) as Promise<{ signals: CreditSignal[] }>;
}

// -- FX Hedging ------------------------------------------------------------

export type FxCurrencySummary = {
  currency: string;
  gross_minor: number;
  hedged_minor: number;
  unhedged_minor: number;
  hedge_ratio_bp: number;
  gross_gbp_pence: number;
  unhedged_gbp_pence: number;
  target_cover_bp: number;
  gap_to_target_minor: number;
};

export type FxBucketRow = {
  bucket: string;
  label: string;
  forecast_minor: number;
  hedged_minor: number;
  unhedged_minor: number;
  forecast_gbp_pence: number;
  unhedged_gbp_pence: number;
};

export type FxExposureRow = {
  id: string;
  expected_date: string;
  amount_minor: number;
  direction: string;
  source: string;
  source_reference: string | null;
  status: string;
  hedged_minor: number;
};

export type FxSummaryView = {
  as_of_date: string;
  base_currency: string;
  currencies: FxCurrencySummary[];
  sources: Record<string, string>;
};

export type FxExposureView = {
  currency: string;
  summary: FxCurrencySummary;
  buckets: FxBucketRow[];
  exposures: FxExposureRow[];
};

export type FxRateQuote = {
  pair: string;
  spot: number;
  forward: number;
  forward_points_bp: number;
  tenor_months: number;
  source: string;
  quality: string;
  as_of: string;
};

export type FxCounterparty = {
  id: string;
  name: string;
  rating: string;
  status: string;
  group_name: string | null;
  entity_limit_pence: number;
  entity_used_pence: number;
  entity_headroom_pence: number;
  group_limit_pence: number;
  group_used_pence: number;
  group_headroom_pence: number;
  near_cap: boolean;
};

export type FxHedgeInitiateResponse = {
  deal_id: string;
  hedge_link_ids: string[];
  currency: string;
  sell_amount_minor: number;
  tenor_months: number;
  forward_rate: number;
  expected_gbp_pence: number;
  counterparty_name: string;
  trade_date: string;
  maturity_date: string;
};

export function getFxSummary(): Promise<FxSummaryView> {
  return get("/fx/exposures");
}

export function getFxByCurrency(currency: string): Promise<FxExposureView> {
  return get(`/fx/exposures/${currency}`);
}

export function getFxForwardRate(
  pair: string,
  tenor: number,
): Promise<FxRateQuote> {
  return get(`/fx/rates/forward/${pair}?tenor=${tenor}`);
}

export function getFxCounterparties(): Promise<FxCounterparty[]> {
  return get("/fx/counterparties");
}

export function initiateHedge(body: {
  currency: string;
  sell_amount_minor: number;
  tenor_months: number;
  counterparty_id: string;
  exposure_ids: string[];
  reference?: string;
  comments?: string;
  override_reason?: string;
}): Promise<FxHedgeInitiateResponse> {
  return post("/fx/hedges", body);
}

export type FxRecommendation = {
  currency: string;
  amount_minor: number;
  tenor_months: number;
  counterparty_id: string;
  counterparty_name: string;
  reason: string;
};

export type FxBriefing = {
  briefing: string;
  recommendations: FxRecommendation[];
  watch: string[];
};

export function narrateFx(): Promise<FxBriefing> {
  return post("/fx/narrate", {});
}

export type FxPolicyTarget = {
  currency: string;
  target_cover_bp: number;
  horizon_days: number;
};

export type FxPolicy = {
  policy_id: string;
  as_of_date: string;
  targets: FxPolicyTarget[];
};

export function getFxPolicy(): Promise<FxPolicy> {
  return get("/fx/policy");
}

export function putFxPolicy(targets: FxPolicyTarget[]): Promise<FxPolicy> {
  return put("/fx/policy", { targets });
}

export function adviseHedge(
  body: {
    currency: string;
    sell_amount_minor: number;
    tenor_months: number;
    counterparty_id: string;
  },
  signal?: AbortSignal,
): Promise<{ observations: string[] }> {
  return post("/fx/hedges/advise", body, signal);
}

export type FxLiveHedge = {
  deal_id: string;
  counterparty_id: string;
  counterparty_name: string;
  currency: string;
  principal_pence: number;
  tenor_months: number;
  trade_date: string;
  maturity_date: string;
  status: string;
  covered_amount_minor: number;
  exposure_ids: string[];
};

export function listHedges(): Promise<FxLiveHedge[]> {
  return get("/fx/hedges");
}

export function checkHedge(
  body: {
    currency: string;
    sell_amount_minor: number;
    tenor_months: number;
    counterparty_id: string;
  },
  signal?: AbortSignal,
): Promise<CheckResult> {
  return post<CheckResult>("/fx/hedges/check", body, signal);
}
