import { type NextRequest, NextResponse } from "next/server";
import { isSameOrigin, SESSION_COOKIE } from "@/lib/auth-helpers";

export async function POST(request: NextRequest) {
  if (!isSameOrigin(request.headers.get("origin"), request.headers.get("host"))) {
    return new NextResponse("cross-site request rejected", { status: 403 });
  }
  const res = NextResponse.redirect(new URL("/sign-in", request.url), 303);
  res.cookies.delete(SESSION_COOKIE);
  return res;
}
