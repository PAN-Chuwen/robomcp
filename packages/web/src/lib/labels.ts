// Human labels for ids the API returns (agent / suite versions), and small result lookups.

export interface AgentVersionLike {
  id: string;
  name: string;
  version: number;
}
export interface SuiteVersionLike {
  id: string;
  suite_name: string;
  version: number;
}

export function versionLabels(agents: AgentVersionLike[], suites: SuiteVersionLike[]) {
  const agent = new Map(agents.map((a) => [a.id, `${a.name} v${a.version}`]));
  const suite = new Map(suites.map((s) => [s.id, `${s.suite_name} v${s.version}`]));
  return {
    agent: (id: string) => agent.get(id) ?? id.slice(0, 8),
    suite: (id: string) => suite.get(id) ?? id.slice(0, 8),
  };
}

/** pass^k for one k, or null when the experiment has no group with k scored trials. */
export function passAt(passK: { k: number; value: number }[], k: number): number | null {
  return passK.find((p) => p.k === k)?.value ?? null;
}
