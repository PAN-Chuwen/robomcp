import type { Metadata } from "next";
import { safeNext, SIGN_IN_ERRORS, type SignInError } from "@/lib/auth-helpers";

export const metadata: Metadata = { title: "Sign in" };

const first = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v);

export default async function SignIn({ searchParams }: PageProps<"/sign-in">) {
  const sp = await searchParams;
  const error = first(sp.error) as SignInError | undefined;
  const next = safeNext(first(sp.next));
  return (
    <main className="mx-auto max-w-md px-4 py-12">
      <form action="/auth/sign-in" method="post" className="pane flex flex-col gap-3 p-5">
        <h1 className="text-base font-semibold">Sign in with an API key</h1>
        <p className="text-[13px] text-muted">
          The key stays on the server: it is kept in an httpOnly cookie and only sent to the platform API.
          Create one with <code className="font-mono">robomcp-platform create-api-key</code>.
        </p>
        <input type="hidden" name="next" value={next} />
        <label className="flex flex-col gap-1 text-[13px] text-muted">
          API key
          <input
            name="key"
            type="password"
            required
            autoComplete="off"
            spellCheck={false}
            placeholder="rmcp_…"
            className="rounded-md border border-line bg-bg px-2.5 py-1.5 font-mono text-[13px] text-fg outline-none focus:border-accent"
          />
        </label>
        {error && error in SIGN_IN_ERRORS && (
          <p role="alert" className="text-[13px] text-bad">
            {SIGN_IN_ERRORS[error]}
          </p>
        )}
        <button className="btn self-start" type="submit">
          Sign in
        </button>
      </form>
    </main>
  );
}
