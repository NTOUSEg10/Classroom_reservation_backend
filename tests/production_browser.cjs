/* Run against a built SPA served by Caddy, so response CSP participates in the test. */
const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const path = require("node:path");

async function main() {
  const baseURL = process.env.PRODUCTION_BASE_URL || "http://127.0.0.1:8081";
  const executablePath =
    process.env.CHROME_EXECUTABLE ||
    (process.platform === "win32"
      ? "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"
      : undefined);
  const browser = await chromium.launch({
    headless: true,
    ...(executablePath ? { executablePath } : {}),
  });
  try {
    const page = await browser.newPage({
      viewport: { width: 1440, height: 1000 },
    });
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    const checks = [];
    for (const route of [
      "/",
      "/login",
      "/auth/callback",
      "/account",
      "/reservations",
      "/admin",
      "/rooms/11111111-1111-4111-8111-111111111111",
    ]) {
      const response = await page.goto(`${baseURL}${route}`);
      assert.equal(
        response.status(),
        200,
        `${route} must serve the built fallback`,
      );
      await page.locator("main h1").waitFor();
      assert(
        (await page.locator("main h1").innerText()).trim(),
        `${route} must hydrate`,
      );
      const guestHeading =
        route === "/reservations"
          ? "登入後查看借用紀錄"
          : route === "/admin"
            ? "請登入管理員帳號"
            : null;
      if (guestHeading) {
        await page
          .getByRole("heading", { name: guestHeading, exact: true })
          .waitFor();
        assert.equal(
          await page
            .locator("main .loading-row,main .record,.admin-tabs")
            .count(),
          0,
          "Guest routes must show a login prompt without loading forever or private controls",
        );
      }
      checks.push({
        route,
        hydrated: true,
        ...(guestHeading ? { guest_login_prompt: true } : {}),
      });
    }
    const response = await page.goto(baseURL);
    await page.getByRole("heading", { name: "找到適合的教室" }).waitFor();
    const meta = await page
      .locator('meta[http-equiv="content-security-policy" i]')
      .getAttribute("content");
    assert(meta, "The static fallback must carry SvelteKit CSP");
    const scriptPolicy = meta
      .split(";")
      .find((value) => value.trim().startsWith("script-src "));
    assert(
      scriptPolicy?.includes("'self'") && /'sha256-[^']+'/.test(scriptPolicy),
      "Bootstrap needs a build-specific hash",
    );
    assert(
      !scriptPolicy.includes("'unsafe-inline'") &&
        !scriptPolicy.includes("'unsafe-eval'"),
      "Scripts must remain restricted",
    );
    assert(
      response
        .headers()
        ["content-security-policy"].includes("frame-ancestors 'none'"),
      "Framing requires a response header",
    );
    assert.deepEqual(
      errors,
      [],
      "Normal production navigation must have no JavaScript errors",
    );
    const inlineRan = await page.evaluate(() => {
      window.__cspUntrustedProbe = false;
      const script = document.createElement("script");
      script.textContent = "window.__cspUntrustedProbe = true";
      document.head.appendChild(script);
      script.remove();
      return window.__cspUntrustedProbe;
    });
    assert.equal(inlineRan, false, "Untrusted inline scripts must be blocked");
    const directory = path.join(__dirname, "..", "reports");
    await fs.mkdir(directory, { recursive: true });
    await page.screenshot({
      path: path.join(directory, "upgrade-caddy-home-desktop.png"),
      fullPage: true,
    });
    const report = {
      generated_at: new Date().toISOString(),
      browser: browser.version(),
      checks,
      bootstrap_hash_allowed: true,
      untrusted_inline_blocked: true,
      page_errors: errors,
      passed: true,
      scope:
        "Built SPA + native Caddy CSP over loopback HTTP; no TLS certificate or remote Supabase acceptance",
    };
    await fs.writeFile(
      path.join(directory, "upgrade-caddy-browser.json"),
      JSON.stringify(report, null, 2),
    );
    console.log(
      JSON.stringify({
        passed: true,
        hydrated_routes: checks.length,
        untrusted_inline_blocked: true,
      }),
    );
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error.message);
  process.exitCode = 1;
});
