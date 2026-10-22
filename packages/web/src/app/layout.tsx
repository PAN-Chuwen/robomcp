import type { Metadata, Viewport } from "next";
import Link from "next/link";
import { getMe } from "@/lib/api/server";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "RoboMCP", template: "%s · RoboMCP" },
  description: "Evaluation and replay for embodied-agent harnesses",
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: dark)", color: "#0f1413" },
    { media: "(prefers-color-scheme: light)", color: "#f5f7f6" },
  ],
};

export default async function RootLayout({ children }: LayoutProps<"/">) {
  const me = await getMe();
  return (
    <html lang="en">
      <body className="min-h-dvh">
        <header className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-line px-4 py-2.5 sm:px-5">
          <Link href="/" className="font-semibold tracking-wide no-underline">
            RoboMCP
          </Link>
          {me && (
            <div className="ml-auto flex items-center gap-3">
              <span className="meta" title={me.email}>
                {me.org_slug} · {me.api_key_prefix}…
              </span>
              <form action="/auth/sign-out" method="post">
                <button className="btn" type="submit">
                  Sign out
                </button>
              </form>
            </div>
          )}
        </header>
        {children}
      </body>
    </html>
  );
}
