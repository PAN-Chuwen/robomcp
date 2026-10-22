import { type NextRequest, NextResponse } from "next/server";
import { apiClient } from "@/lib/api/server";
import { isSameOrigin, safeNext, SESSION_COOKIE, SESSION_MAX_AGE_S, type SignInError } from "@/lib/auth-helpers";

/** Validate the posted API key with GET /v1/me and keep it in an httpOnly cookie. */
export async function POST(request: NextRequest) {
  const form = await request.formData();
  const next = safeNext(form.get("next")?.toString());
  const back = (error: SignInError) => {
    const url = new URL("/sign-in", request.url);
    url.searchParams.set("error", error);
    if (next !== "/") url.searchParams.set("next", next);
    return NextResponse.redirect(url, 303);
  };

  if (!isSameOrigin(request.headers.get("origin"), request.headers.get("host"))) return back("forbidden");
  const key = form.get("key")?.toString().trim();
  if (!key) return back("missing");

  let status: number;
  try {
    status = (await apiClient(key).GET("/v1/me")).response.status;
  } catch {
    return back("unreachable");
  }
  if (status === 401) return back("invalid");
  if (status !== 200) return back("unreachable");

  const res = NextResponse.redirect(new URL(next, request.url), 303);
  res.cookies.set(SESSION_COOKIE, key, {
    httpOnly: true,
    sameSite: "lax",
    secure: request.nextUrl.protocol === "https:",
    path: "/",
    maxAge: SESSION_MAX_AGE_S,
  });
  return res;
}
