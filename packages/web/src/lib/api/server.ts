// Server-side API access (BFF): the browser never calls the platform API and never sees the key.
import "server-only";

import { cookies } from "next/headers";
import { notFound, redirect } from "next/navigation";
import createClient from "openapi-fetch";
import { cache } from "react";
import { SESSION_COOKIE } from "@/lib/auth-helpers";
import type { components, paths } from "./schema";

export type Schemas = components["schemas"];
export const API_URL = (process.env.ROBOMCP_API_URL ?? "http://localhost:8000").replace(/\/+$/, "");

export function apiClient(key: string) {
  return createClient<paths>({ baseUrl: API_URL, headers: { Authorization: `Bearer ${key}` }, cache: "no-store" });
}

export type ApiClient = ReturnType<typeof apiClient>;

export async function getApiKey(): Promise<string | null> {
  return (await cookies()).get(SESSION_COOKIE)?.value ?? null;
}

/** A client for the signed-in key; sends the visitor to sign-in when there is none. */
export async function api(): Promise<ApiClient> {
  const key = await getApiKey();
  if (!key) redirect("/sign-in");
  return apiClient(key);
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
  ) {
    super(`API ${status}: ${detail}`);
  }
}

function detailOf(error: unknown): string {
  if (error && typeof error === "object" && "detail" in error) {
    const d = (error as { detail: unknown }).detail;
    return typeof d === "string" ? d : JSON.stringify(d);
  }
  return typeof error === "string" ? error : JSON.stringify(error);
}

/** The response body, or: 401 → sign-in, 404 → the not-found page, anything else → ApiError. */
export function unwrap<T>(res: { data?: T; error?: unknown; response: Response }): T {
  const { status } = res.response;
  if (status === 401) redirect("/sign-in?error=expired");
  if (status === 404) notFound();
  if (res.data === undefined || res.error !== undefined) throw new ApiError(status, detailOf(res.error));
  return res.data;
}

/** The signed-in principal, once per request; null when signed out or the key stopped working. */
export const getMe = cache(async (): Promise<Schemas["MeOut"] | null> => {
  const key = await getApiKey();
  if (!key) return null;
  try {
    const { data } = await apiClient(key).GET("/v1/me");
    return data ?? null;
  } catch {
    return null;
  }
});

/** An episode artifact as text, or null when the episode has none (yet). */
export async function getArtifact(client: ApiClient, episodeId: string, kind: "trace" | "episode_log") {
  const res = await client.GET("/v1/episodes/{episode_id}/artifacts/{kind}", {
    params: { path: { episode_id: episodeId, kind } },
    parseAs: "text",
  });
  if (res.response.status === 404) return null;
  if (res.response.status === 401) redirect("/sign-in?error=expired");
  if (!res.response.ok || typeof res.data !== "string") throw new ApiError(res.response.status, "artifact fetch failed");
  return res.data;
}
