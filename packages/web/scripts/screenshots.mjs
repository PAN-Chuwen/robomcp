// Sign in through the real form, walk project → experiment → comparison → episode, and save full-page
// screenshots at desktop and phone width (dark and light).
//
//   ROBOMCP_KEY_FILE=path/to/key WEB_URL=http://localhost:3000 OUT_DIR=/tmp/shots npm run screenshots
//
// Uses an installed Chrome (CHROME_PATH, default: macOS Google Chrome) through playwright-core, so no
// browser download is needed. The key is read from ROBOMCP_API_KEY or ROBOMCP_KEY_FILE and never printed.
import { mkdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { chromium } from "playwright-core";

const base = process.env.WEB_URL ?? "http://localhost:3000";
const out = process.env.OUT_DIR ?? "screenshots";
const chrome = process.env.CHROME_PATH ?? "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const key = process.env.ROBOMCP_API_KEY ?? (process.env.ROBOMCP_KEY_FILE && readFileSync(process.env.ROBOMCP_KEY_FILE, "utf8").trim());
if (!key) throw new Error("set ROBOMCP_API_KEY or ROBOMCP_KEY_FILE");
mkdirSync(out, { recursive: true });

const VIEWPORTS = { desktop: { width: 1440, height: 900 }, phone: { width: 400, height: 860 } };

const browser = await chromium.launch({ executablePath: chrome, headless: true });
try {
  // Discover the pages once, on a desktop dark context.
  const ctx = await browser.newContext({ viewport: VIEWPORTS.desktop, colorScheme: "dark" });
  const page = await ctx.newPage();
  await page.goto(`${base}/`);
  if (!page.url().includes("/sign-in")) throw new Error("expected a redirect to /sign-in when signed out");
  await page.fill('input[name="key"]', key);
  await Promise.all([page.waitForURL((u) => !u.pathname.startsWith("/sign-in")), page.click('button[type="submit"]')]);
  const cookie = (await ctx.cookies()).find((c) => c.name === "robomcp_key");
  if (!cookie?.httpOnly || cookie.sameSite !== "Lax") throw new Error("session cookie must be httpOnly + SameSite=Lax");

  const urls = { projects: `${base}/` };
  await page.click('a[href^="/projects/"]');
  await page.waitForURL(/\/projects\//);
  urls.project = page.url();
  const boxes = page.locator('input[type="checkbox"][aria-label^="Compare"]');
  if ((await boxes.count()) >= 2) {
    await boxes.nth(0).check();
    await Promise.all([page.waitForURL(/\/compare\?/), boxes.nth(1).check()]);
    urls.compare = page.url();
    await page.goto(urls.project);
  }
  // Prefer an experiment with a failed episode: its replay is the interesting one.
  const experiments = await page.locator('a[href^="/experiments/"]').evaluateAll((as) => as.map((a) => a.href));
  for (const href of experiments) {
    await page.goto(href);
    const failed = page.locator('tr:has(.badge:text-is("failed")) a[href^="/episodes/"]');
    if (!urls.experiment || (await failed.count())) {
      urls.experiment = href;
      const anyEpisode = page.locator('a[href^="/episodes/"]');
      urls.episode = await ((await failed.count()) ? failed.first() : anyEpisode.first()).evaluate((a) => a.href);
    }
    if (await failed.count()) break;
  }
  const storage = await ctx.storageState();
  await ctx.close();

  for (const [vp, viewport] of Object.entries(VIEWPORTS)) {
    for (const scheme of ["dark", "light"]) {
      if (scheme === "light" && vp === "phone") continue;
      const c = await browser.newContext({ viewport, colorScheme: scheme, storageState: storage });
      const p = await c.newPage();
      for (const [name, url] of Object.entries(urls)) {
        await p.goto(url);
        await p.waitForLoadState("networkidle");
        if (name === "episode") {
          for (let i = 0; i < 5; i++) await p.keyboard.press("ArrowRight"); // scrub with the keyboard to step 5
        }
        const file = join(out, `${name}-${vp}-${scheme}.png`);
        await p.screenshot({ path: file, fullPage: true });
        console.log(file);
      }
      await c.close();
    }
  }
} finally {
  await browser.close();
}
