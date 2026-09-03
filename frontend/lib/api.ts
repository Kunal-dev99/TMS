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
  DealDetail,
  ExposureView,
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
