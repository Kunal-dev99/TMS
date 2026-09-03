/**
 * The signed in session.
 *
 * One module holds the token, and the request layer reads it from here. No
 * component ever sees it, and nothing else in the client knows how the
 * caller is identified, so replacing this with Entra ID single sign on is a
 * change to two files rather than to every call site.
 *
 * The token lives in memory and in sessionStorage rather than
 * localStorage: closing the tab ends the session, which is the right default
 * for a treasury screen somebody might leave open on a shared machine.
 */

const KEY = "treasury.token";

export interface SignedInUser {
  id: string;
  display_name: string;
  email: string;
  roles: string[];
}

let token: string | null = null;
let user: SignedInUser | null = null;

export function currentToken(): string | null {
  if (token) return token;
  try {
    token = sessionStorage.getItem(KEY);
  } catch {
    // A browser with site data blocked. The session then lasts as long as
    // the page does, which still works.
    token = null;
  }
  return token;
}

export function currentUser(): SignedInUser | null {
  return user;
}

export function startSession(nextToken: string, nextUser: SignedInUser): void {
  token = nextToken;
  user = nextUser;
  try {
    sessionStorage.setItem(KEY, nextToken);
  } catch {
    // Nothing to do. The token is still held in memory.
  }
}

export function endSession(): void {
  token = null;
  user = null;
  try {
    sessionStorage.removeItem(KEY);
  } catch {
    // Nothing to do.
  }
}

/**
 * Whether this person may sign an amount.
 *
 * Read only to decide what to offer, never to decide what is allowed. The
 * server refuses on its own account, and it is the only thing that does.
 * Showing somebody a button that will be refused is a worse interface than
 * hiding it, and hiding it is not a control.
 */
export function mayPossiblySign(roles: string[], requiredRole: string | null): boolean {
  if (!requiredRole) return false;
  const order = ["ANALYST", "HEAD_OF_TREASURY", "CFO"];
  const needed = order.indexOf(requiredRole);
  return roles.some((held) => order.indexOf(held) >= needed && needed >= 0);
}
