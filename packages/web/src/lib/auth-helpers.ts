// Pure helpers for the sign-in flow (no Next.js imports, so they can be unit tested).

/** Name of the httpOnly cookie that holds the API key. */
export const SESSION_COOKIE = "robomcp_key";
export const SESSION_MAX_AGE_S = 60 * 60 * 24 * 30;

/** A post-sign-in destination: only same-site absolute paths, never `//host` or a full URL. */
export function safeNext(next: string | null | undefined): string {
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.startsWith("/\\")) return "/";
  if (next.startsWith("/sign-in") || next.startsWith("/auth/")) return "/";
  return next;
}

/**
 * Reject cross-site form posts (login CSRF): a browser sends Origin on every POST; when present it must name
 * this host. Requests without Origin (curl, old browsers) are allowed, since the cookie is SameSite=Lax.
 */
export function isSameOrigin(origin: string | null, host: string | null): boolean {
  if (!origin) return true;
  if (!host) return false;
  try {
    return new URL(origin).host === host;
  } catch {
    return false;
  }
}

export type SignInError = "missing" | "invalid" | "unreachable" | "expired" | "forbidden";

export const SIGN_IN_ERRORS: Record<SignInError, string> = {
  missing: "Enter an API key.",
  invalid: "The API rejected this key.",
  unreachable: "Could not reach the API.",
  expired: "Your key is no longer valid. Sign in again.",
  forbidden: "Cross-site sign-in request rejected.",
};
