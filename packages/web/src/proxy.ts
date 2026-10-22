import { type NextRequest, NextResponse } from "next/server";
import { SESSION_COOKIE } from "@/lib/auth-helpers";

// Optimistic check only: no cookie → sign-in. Whether the key is valid is decided by the API on every call.
export function proxy(request: NextRequest) {
  if (request.cookies.has(SESSION_COOKIE)) return NextResponse.next();
  const url = new URL("/sign-in", request.url);
  const next = request.nextUrl.pathname + request.nextUrl.search;
  if (next !== "/") url.searchParams.set("next", next);
  return NextResponse.redirect(url);
}

export const config = {
  matcher: ["/((?!sign-in|auth/|_next/|favicon.ico|icon.svg).*)"],
};
