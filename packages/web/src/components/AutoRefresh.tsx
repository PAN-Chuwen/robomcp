"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

/** Re-render the server page every `seconds` while `active` (e.g. an experiment is queued or running). */
export function AutoRefresh({ active, seconds = 3 }: { active: boolean; seconds?: number }) {
  const router = useRouter();
  useEffect(() => {
    if (!active) return;
    const id = setInterval(() => {
      if (document.visibilityState === "visible") router.refresh();
    }, seconds * 1000);
    return () => clearInterval(id);
  }, [active, seconds, router]);
  if (!active) return null;
  return (
    <span className="badge border-accent text-accent" title={`refreshing every ${seconds}s`}>
      live
    </span>
  );
}
