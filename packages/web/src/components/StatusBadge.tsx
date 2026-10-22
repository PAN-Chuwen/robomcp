const TONE: Record<string, string> = {
  succeeded: "text-good border-good",
  completed: "text-good border-good",
  failed: "text-bad border-bad",
  error: "text-tool border-tool",
  running: "text-accent border-accent",
  queued: "text-muted",
};

export function StatusBadge({ status }: { status: string }) {
  return <span className={`badge ${TONE[status] ?? "text-muted"}`}>{status}</span>;
}
