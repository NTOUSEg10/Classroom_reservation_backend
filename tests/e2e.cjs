/* Browser verification uses real FastAPI + PostgreSQL; only the external Supabase HTTP boundary is a fixture. */
const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const path = require("node:path");
const { performance } = require("node:perf_hooks");
const { createHash, randomUUID } = require("node:crypto");

const baseURL = process.env.E2E_BASE_URL || "http://127.0.0.1:5173";
const apiURL = process.env.E2E_API_URL || "http://127.0.0.1:8004";
const reports = path.join(__dirname, "..", "reports");
const roomID = "11111111-1111-4111-8111-111111111111";
const sessionsFile =
  process.env.E2E_SESSIONS_FILE ||
  path.join(__dirname, "..", ".local", "ntou_e2e-sessions.json");
let sessions;
const fixtures = new WeakMap();
const applicationPurpose = `Playwright 完整借用流程 ${Date.now()}`;
const measurements = {
  generated_at: new Date().toISOString(),
  browser: {},
  checks: [],
  screenshots: [],
};

async function upstreamFixture(context) {
  const fixture = {
    index: 1,
    scenario: "success",
    challenge: "",
    authorizations: 0,
    exchanges: 0,
  };
  fixtures.set(context, fixture);
  await context.route(
    "https://fixture.supabase.co/auth/v1/**",
    async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      if (url.pathname === "/auth/v1/authorize") {
        assert.equal(url.searchParams.get("provider"), "google");
        assert.equal(url.searchParams.get("hd"), "email.ntou.edu.tw");
        assert.equal(url.searchParams.get("code_challenge_method"), "s256");
        fixture.challenge = url.searchParams.get("code_challenge");
        assert.match(fixture.challenge, /^[A-Za-z0-9_-]{43}$/);
        fixture.authorizations++;
        const callback = new URL(url.searchParams.get("redirect_to"));
        assert.equal(callback.origin, new URL(baseURL).origin);
        assert.equal(callback.pathname, "/auth/callback");
        if (fixture.scenario === "cancel") {
          callback.searchParams.set("error", "access_denied");
          callback.searchParams.set(
            "error_description",
            "Fixture user cancelled",
          );
        } else
          callback.searchParams.set("code", `fixture-code-${fixture.index}`);
        await route.fulfill({
          status: 302,
          headers: { location: callback.href },
        });
        return;
      }
      if (
        url.pathname === "/auth/v1/token" &&
        url.searchParams.get("grant_type") === "pkce"
      ) {
        const body = request.postDataJSON();
        assert.equal(body.auth_code, `fixture-code-${fixture.index}`);
        if (fixture.scenario === "missing-verifier") {
          assert(!body.code_verifier);
        } else {
          assert(body.code_verifier, "PKCE must carry the saved verifier");
          assert.equal(
            createHash("sha256").update(body.code_verifier).digest("base64url"),
            fixture.challenge,
          );
        }
        fixture.exchanges++;
        if (
          fixture.scenario === "invalid-code" ||
          fixture.scenario === "missing-verifier"
        ) {
          await route.fulfill({
            status: 400,
            json: {
              error: "invalid_grant",
              error_description: "Fixture PKCE exchange rejected",
            },
          });
        } else
          await route.fulfill({
            status: 200,
            json: sessions[String(fixture.index)],
          });
        return;
      }
      if (url.pathname === "/auth/v1/user") {
        const token = (request.headers().authorization || "").replace(
          /^Bearer /,
          "",
        );
        const session = Object.values(sessions).find(
          (value) => value.access_token === token,
        );
        await route.fulfill({
          status: session ? 200 : 401,
          json: session ? session.user : { message: "Fixture token rejected" },
        });
        return;
      }
      if (
        url.pathname === "/auth/v1/token" &&
        url.searchParams.get("grant_type") === "refresh_token"
      ) {
        const session = Object.values(sessions).find(
          (value) =>
            value.refresh_token === request.postDataJSON().refresh_token,
        );
        await route.fulfill({
          status: session ? 200 : 401,
          json: session || { message: "Fixture refresh rejected" },
        });
        return;
      }
      if (url.pathname === "/auth/v1/logout") {
        await route.fulfill({ status: 200, json: {} });
        return;
      }
      await route.fulfill({
        status: 400,
        json: { message: "Unexpected fixture Auth request" },
      });
    },
  );
  return fixture;
}

async function newPage(browser, width = 1440, options = {}) {
  const context = await browser.newContext({
    viewport: { width, height: 1000 },
    timezoneId: "Asia/Taipei",
    reducedMotion: options.reducedMotion || "reduce",
  });
  const fixture = await upstreamFixture(context);
  const page = await context.newPage();
  if (options.businessClock !== false)
    await page.clock.install({ time: new Date("2026-10-12T02:00:00Z") });
  const errors = [];
  const mapTimings = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("requestfinished", (request) => {
    if (new URL(request.url()).pathname === "/campus-map.svg")
      mapTimings.push(request.timing());
  });
  return { context, page, errors, mapTimings, fixture };
}

async function login(page, index) {
  const fixture = fixtures.get(page.context());
  fixture.index = index;
  await page.goto(`${baseURL}/login`);
  assert.equal(await page.locator('input[type="password"]').count(), 0);
  const button = page.getByRole("button", {
    name: "使用學校 Google 登入",
    exact: true,
  });
  await button.focus();
  assert(
    await button.evaluate((element) => element === document.activeElement),
  );
  await page.keyboard.press("Enter");
  await page.waitForURL("**/account");
  if (index === 103)
    await page
      .getByRole("heading", { name: "完成基本資料", exact: true })
      .waitFor();
  else
    await page
      .locator("main")
      .getByText(`測試使用者 ${index}`, { exact: true })
      .first()
      .waitFor();
  assert.equal(fixture.authorizations, 1);
  assert.equal(fixture.exchanges, 1);
  assert.equal(new URL(page.url()).search, "");
}

async function assertGuestPrivateRoutes(browser) {
  const target = await newPage(browser);
  try {
    for (const [route, heading] of [
      ["/reservations", "登入後查看借用紀錄"],
      ["/admin", "請登入管理員帳號"],
    ]) {
      await target.page.goto(`${baseURL}${route}`);
      await target.page
        .getByRole("heading", { name: heading, exact: true })
        .waitFor();
      assert.equal(await target.page.locator("main .loading-row").count(), 0);
      assert.equal(
        await target.page.locator("main .record,main .user-row").count(),
        0,
      );
      assert.equal(await target.page.locator(".admin-tabs").count(), 0);
      assert.equal(
        await target.page.locator('nav a[href="/admin"]').count(),
        0,
      );
      assert.equal(
        await target.page.locator('main a[href="/login"]').count(),
        1,
      );
      measurements.checks.push({
        name: "Guest private route resolves to a login prompt without private rows or actions",
        route,
        passed: true,
      });
    }
    assert.deepEqual(target.errors, []);
  } finally {
    await target.context.close();
  }
}

async function assertCallbackFailures(browser) {
  for (const scenario of ["cancel", "invalid-code", "missing-verifier"]) {
    const target = await newPage(browser);
    try {
      target.fixture.scenario = scenario;
      if (scenario === "missing-verifier") {
        await target.page.goto(`${baseURL}/login`);
        await target.page.evaluate(() => localStorage.clear());
        await target.page.goto(`${baseURL}/auth/callback?code=fixture-code-1`);
      } else {
        await target.page.goto(`${baseURL}/login`);
        await target.page
          .getByRole("button", { name: "使用學校 Google 登入", exact: true })
          .click();
      }
      await target.page.getByRole("alert").waitFor();
      assert.match(
        await target.page.getByRole("alert").innerText(),
        /重新登入|未完成|取消/,
      );
      assert.equal(new URL(target.page.url()).pathname, "/auth/callback");
      assert.equal(new URL(target.page.url()).search, "");
      assert.equal(
        await target.page
          .getByRole("link", { name: "重新登入", exact: true })
          .count(),
        1,
      );
      const retained = await target.page.evaluate(() =>
        Object.keys(localStorage).filter((key) => key.startsWith("sb-")),
      );
      assert.deepEqual(retained, []);
      assert.equal(
        await target.page.locator('nav a[href="/admin"]').count(),
        0,
      );
      assert.deepEqual(target.errors, []);
      measurements.checks.push({
        name: `Google callback ${scenario} is safe and clears credentials and URL`,
        passed: true,
      });
    } finally {
      await target.context.close();
    }
  }
  const incomplete = await newPage(browser);
  try {
    await incomplete.page.goto(`${baseURL}/auth/callback`);
    await incomplete.page.getByRole("alert").waitFor();
    assert.match(
      await incomplete.page.getByRole("alert").innerText(),
      /不完整/,
    );
    assert.equal(incomplete.fixture.exchanges, 0);
    assert.deepEqual(incomplete.errors, []);
    measurements.checks.push({
      name: "Callback without a code does not attempt a token exchange",
      passed: true,
    });
  } finally {
    await incomplete.context.close();
  }
}

async function assertMotion(browser, reducedMotion) {
  const target = await newPage(browser, 1440, {
    reducedMotion,
    businessClock: false,
  });
  try {
    await target.page.addInitScript(() => {
      window.__motionProbe = { changes: 0, detachedChanges: 0 };
      new MutationObserver((records) => {
        for (const record of records) {
          const node = record.target;
          if (
            !(node instanceof HTMLElement) ||
            !node.matches(".page-heading h1,.room-row,.map-pin,.status")
          )
            continue;
          if (node.style.transform || node.style.opacity)
            window.__motionProbe.changes++;
          if (!node.isConnected && (node.style.transform || node.style.opacity))
            window.__motionProbe.detachedChanges++;
        }
      }).observe(document, {
        subtree: true,
        attributes: true,
        attributeFilter: ["style"],
      });
    });
    await target.page.goto(baseURL);
    await target.page.locator(".room-row").first().waitFor();
    await target.page.waitForTimeout(350);
    const initial = await target.page.evaluate(
      () => window.__motionProbe.changes,
    );
    if (reducedMotion === "reduce")
      assert.equal(initial, 0, "Reduced motion must not animate styles");
    else
      assert(
        initial > 0,
        "Normal preference must produce actual GSAP transforms/opacity",
      );
    for (let index = 0; index < 3; index++) {
      await target.page.locator('.sidebar-account[href="/account"]').click();
      await target.page.locator("main h1").waitFor();
      await target.page.locator('nav a[href="/"]').click();
      await target.page.locator(".room-row").first().waitFor();
    }
    await target.page.waitForTimeout(400);
    assert.equal(
      await target.page
        .locator("main h1")
        .evaluate((node) => node.style.transform || node.style.opacity),
      "",
    );
    assert.equal(
      await target.page.evaluate(() => window.__motionProbe.detachedChanges),
      0,
    );
    assert.deepEqual(target.errors, []);
    measurements.checks.push({
      name: `GSAP ${reducedMotion} respects preference and quick navigation cleans styles`,
      passed: true,
      observed_style_changes: initial,
      navigation_round_trips: 3,
    });
  } finally {
    await target.context.close();
  }
}

async function assertFirstOnboarding(browser) {
  const target = await newPage(browser);
  try {
    await login(target.page, 103);
    const email = target.page.getByRole("textbox", {
      name: /^已驗證的學校 Google 信箱/,
    });
    assert.equal(await email.inputValue(), "fixture103@email.ntou.edu.tw");
    assert.equal(await email.getAttribute("readonly"), "");
    await target.page
      .getByRole("textbox", { name: "姓名", exact: true })
      .fill("首次 OAuth 借用人");
    await target.page
      .getByRole("textbox", { name: /^校園證號/ })
      .fill("TEST000103");
    await target.page
      .getByRole("textbox", { name: "聯絡電話", exact: true })
      .fill("0912345678");
    await target.page
      .getByRole("textbox", { name: "系所 / 單位", exact: true })
      .fill("資訊工程學系");
    const saved = target.page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === "/api/auth/register" &&
        response.request().method() === "POST",
    );
    await target.page
      .getByRole("button", { name: "完成資料並啟用借用", exact: true })
      .click();
    const response = await saved;
    assert.equal(response.status(), 201, await response.text());
    assert.deepEqual(Object.keys(response.request().postDataJSON()).sort(), [
      "department",
      "institutional_id",
      "name",
      "phone",
    ]);
    const profile = await response.json();
    assert.equal(profile.id, sessions["103"].user.id);
    assert.equal(profile.role, "borrower");
    assert.equal(profile.verified, true);
    await target.page
      .getByText("基本資料已完成，您現在可以提出借用申請。", { exact: true })
      .waitFor();
    await target.page.reload();
    await target.page
      .locator("main")
      .getByText("首次 OAuth 借用人", { exact: true })
      .waitFor();
    assert.equal(
      await target.page
        .getByRole("heading", { name: "完成基本資料", exact: true })
        .count(),
      0,
    );
    assert.deepEqual(target.errors, []);
    measurements.checks.push({
      name: "Google auth-only identity completes onboarding through real API and survives reload",
      passed: true,
    });
    await screenshot(target.page, "onboarding-completed");
  } finally {
    await target.context.close();
  }
}

async function assertResponsive(page, route, width) {
  await page.setViewportSize({ width, height: 1000 });
  await page.goto(`${baseURL}${route}`);
  await page.locator("main h1").waitFor();
  await page.locator(".loading-row").waitFor({ state: "detached" });
  const sizes = await page.evaluate(() => ({
    scroll: document.documentElement.scrollWidth,
    viewport: document.documentElement.clientWidth,
  }));
  assert(
    sizes.scroll <= sizes.viewport + 1,
    `${route} overflows at ${width}px: ${JSON.stringify(sizes)}`,
  );
  measurements.checks.push({
    name: "RWD no document overflow",
    route,
    width,
    passed: true,
  });
}

async function assertWeeklySchedule(page, width) {
  await assertResponsive(page, "/", width);
  const toggle = page.getByRole("button", { name: "週課表", exact: true });
  await toggle.focus();
  await page.keyboard.press("Enter");
  await page.locator('.week-grid[aria-busy="false"]').waitFor();
  assert.equal(await page.locator(".day-column").count(), 7);
  assert.equal(
    await page.locator(".day-column:visible").count(),
    width < 600 ? 1 : 7,
  );
  if (width < 600) {
    const day = page.locator(".day-switch button").first();
    await day.focus();
    await page.keyboard.press("Enter");
    assert.equal(
      await page
        .locator(".day-column.mobile-current .day-heading span")
        .textContent(),
      await day.textContent(),
    );
  }
  const dimensions = await page.evaluate(() => ({
    scroll: document.documentElement.scrollWidth,
    viewport: document.documentElement.clientWidth,
  }));
  assert(
    dimensions.scroll <= dimensions.viewport + 1,
    `Weekly schedule overflows at ${width}px`,
  );
  measurements.checks.push({
    name: "Weekly schedule keyboard toggle and mobile day selection",
    width,
    passed: true,
  });
}

async function screenshot(page, name) {
  const filename = `upgrade-e2e-${name}.png`;
  await page.screenshot({ path: path.join(reports, filename), fullPage: true });
  measurements.screenshots.push(filename);
}

async function assertQuerySnapshot(browser) {
  const target = await newPage(browser);
  let release;
  const held = new Promise((resolve) => (release = resolve));
  let received;
  const dispatched = new Promise((resolve) => (received = resolve));
  try {
    await target.page.goto(baseURL);
    await target.page.locator(".room-row").first().waitFor();
    const queryDate = await target.page.getByLabel("借用日期").inputValue();
    await target.page.route("**/api/rooms/availability?**", async (route) => {
      const response = await route.fetch();
      received();
      await held;
      await route.fulfill({ response });
    });
    await target.page.getByLabel("開始時間").fill("09:00");
    await target.page.getByLabel("結束時間").fill("11:00");
    await target.page
      .getByRole("button", { name: "查詢教室", exact: true })
      .click();
    await dispatched;
    await target.page.getByLabel("開始時間").fill("13:00");
    await target.page.getByLabel("結束時間").fill("15:00");
    release();
    await target.page.locator(".loading-row").waitFor({ state: "detached" });
    assert.match(
      await target.page.locator(".results-heading").innerText(),
      /09:00–11:00/,
    );
    const href = await target.page
      .getByRole("link", { name: "查看教室", exact: true })
      .first()
      .getAttribute("href");
    const submitted = new URL(href, baseURL).searchParams;
    assert.equal(submitted.get("date"), queryDate);
    assert.equal(submitted.get("start"), "09:00");
    assert.equal(submitted.get("end"), "11:00");
    await target.page.unroute("**/api/rooms/availability?**");
    await target.page
      .getByRole("button", { name: "查詢教室", exact: true })
      .click();
    await target.page.locator(".loading-row").waitFor({ state: "detached" });
    assert.match(
      await target.page.locator(".results-heading").innerText(),
      /13:00–15:00/,
    );
    assert.deepEqual(target.errors, []);
    measurements.checks.push({
      name: "Delayed availability preserves submitted time and room-link snapshot until the next query",
      passed: true,
    });
  } finally {
    release();
    await target.context.close();
  }
}

async function assertHistoryIdentityBoundary(browser) {
  const target = await newPage(browser);
  const purposeA = `跨分頁 A 私密用途 ${randomUUID()}`;
  const purposeB = `跨分頁 B 私密用途 ${randomUUID()}`;
  let release;
  const held = new Promise((resolve) => (release = resolve));
  let received;
  const dispatched = new Promise((resolve) => (received = resolve));
  try {
    for (const [index, purpose] of [
      [1, purposeA],
      [2, purposeB],
    ]) {
      const response = await target.context.request.post(
        `${apiURL}/api/reservations`,
        {
          headers: {
            Authorization: `Bearer ${sessions[String(index)].access_token}`,
          },
          data: {
            room_id: roomID,
            starts_at: "2026-10-14T10:00:00+08:00",
            ends_at: "2026-10-14T11:00:00+08:00",
            purpose,
            attendees: 2,
            mode: "scheduled",
            request_id: randomUUID(),
          },
        },
      );
      assert.equal(response.status(), 201, await response.text());
    }
    await login(target.page, 1);
    await target.page.goto(`${baseURL}/reservations`);
    await target.page.getByText(purposeA, { exact: true }).waitFor();
    await target.page.route("**/api/reservations?**", async (route) => {
      if (
        route.request().headers().authorization !==
        `Bearer ${sessions["1"].access_token}`
      )
        return route.continue();
      const response = await route.fetch();
      received();
      await held;
      await route.fulfill({ response });
    });
    await target.page
      .getByRole("button", { name: "重新整理", exact: true })
      .click();
    await dispatched;
    const second = await target.context.newPage();
    await second.clock.install({ time: new Date("2026-10-12T02:00:00Z") });
    target.fixture.authorizations = 0;
    target.fixture.exchanges = 0;
    await login(second, 2);
    await target.page.waitForFunction(() =>
      document
        .querySelector(".account-name")
        ?.textContent?.includes("測試使用者 2"),
    );
    await target.page.getByText(purposeB, { exact: true }).waitFor();
    assert.equal(
      await target.page.getByText(purposeA, { exact: true }).count(),
      0,
    );
    const lateResponse = target.page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === "/api/reservations" &&
        response.request().headers().authorization ===
          `Bearer ${sessions["1"].access_token}`,
    );
    release();
    await lateResponse;
    // Drain the old fetch continuation before checking the visible identity boundary.
    await target.page.evaluate(
      () =>
        new Promise((resolve) =>
          requestAnimationFrame(() => requestAnimationFrame(resolve)),
        ),
    );
    assert.equal(
      await target.page.getByText(purposeA, { exact: true }).count(),
      0,
    );
    assert.equal(
      await target.page.getByText(purposeB, { exact: true }).count(),
      1,
    );
    assert.deepEqual(target.errors, []);
    measurements.checks.push({
      name: "Cross-tab Google account change reloads borrower history and rejects the previous owner's late response",
      passed: true,
    });
  } finally {
    release();
    await target.context.close();
  }
}

async function turnPage(page, button, pathname) {
  const pending = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === pathname &&
      response.request().method() === "GET",
  );
  await button.click();
  const response = await pending;
  assert.equal(response.status(), 200, await response.text());
  await page.locator(".loading-row").waitFor({ state: "detached" });
  return response.json();
}

async function run() {
  await fs.mkdir(reports, { recursive: true });
  const data = JSON.parse(await fs.readFile(sessionsFile, "utf8"));
  assert.equal(data.test_only, true);
  sessions = data.sessions;
  const browser = await chromium.launch({
    headless: true,
    ...(process.env.BROWSER_CHANNEL
      ? { channel: process.env.BROWSER_CHANNEL }
      : process.platform === "win32"
        ? { channel: "chrome" }
        : {}),
  });
  measurements.browser = {
    version: browser.version(),
    timezone: "Asia/Taipei",
    auth: "test-only upstream fixture",
    backend: "real TCP FastAPI + PostgreSQL",
  };
  const borrower = await newPage(browser);
  const admin = await newPage(browser);
  try {
    await assertGuestPrivateRoutes(browser);
    await assertCallbackFailures(browser);
    await assertMotion(browser, "reduce");
    await assertMotion(browser, "no-preference");
    await assertQuerySnapshot(browser);
    await assertHistoryIdentityBoundary(browser);
    for (const width of [375, 768, 1440])
      await assertWeeklySchedule(borrower.page, width);
    await assertResponsive(borrower.page, "/", 1440);
    await screenshot(borrower.page, "home-desktop");
    await borrower.page.setViewportSize({ width: 375, height: 1000 });
    await screenshot(borrower.page, "home-mobile");
    await login(borrower.page, 1);
    assert.equal(
      await borrower.page.locator('nav a[href="/admin"]').count(),
      0,
    );
    await borrower.page.goto(`${baseURL}/admin`);
    await borrower.page
      .getByRole("heading", { name: "您沒有管理台存取權限", exact: true })
      .waitFor();
    assert.equal(
      await borrower.page
        .getByRole("button", { name: "待審申請", exact: true })
        .count(),
      0,
    );
    measurements.checks.push({
      name: "Borrower admin navigation hidden and direct admin page denied",
      passed: true,
    });
    const markerStarted = performance.now();
    await borrower.page.goto(`${baseURL}/rooms/${roomID}`);
    await borrower.page.locator(".map-pin").waitFor();
    const markerDuration = performance.now() - markerStarted;
    const timing = borrower.mapTimings.at(-1);
    const mapResource = timing
      ? {
          duration_ms: timing.responseEnd,
          source: "Playwright browser protocol request timing",
        }
      : null;
    assert(
      mapResource && mapResource.duration_ms < 2000,
      `Map resource SLA failed: ${JSON.stringify(mapResource)}`,
    );
    assert(
      markerDuration < 2000,
      `Map marker navigation SLA failed: ${markerDuration}ms`,
    );
    measurements.checks.push({
      name: "Local map resource and marker loaded",
      passed: true,
      ...mapResource,
      marker_duration_ms: Number(markerDuration.toFixed(3)),
      marker_source:
        "Node performance monotonic clock from navigation start to visible marker",
      sla_ms: 2000,
    });
    await screenshot(borrower.page, "room-mobile");
    await borrower.page
      .getByRole("button", { name: "即時借用", exact: true })
      .click();
    await borrower.page.getByLabel("借用人數").fill("12");
    await borrower.page.getByLabel("借用用途").fill(applicationPurpose);
    const createResponse = borrower.page.waitForResponse(
      (response) =>
        response.url().endsWith("/api/reservations") &&
        response.request().method() === "POST",
    );
    await borrower.page.getByRole("button", { name: "送出借用申請" }).click();
    const reservationResponse = await createResponse;
    assert.equal(
      reservationResponse.status(),
      201,
      await reservationResponse.text(),
    );
    const reservation = await reservationResponse.json();
    await borrower.page
      .getByRole("heading", { name: "借用申請已送出" })
      .waitFor();
    await borrower.page.getByRole("link", { name: "查看我的借用" }).click();
    await borrower.page
      .getByText(applicationPurpose, { exact: true })
      .waitFor();
    measurements.checks.push({
      name: "Google PKCE keyboard login, immediate application, and own history",
      passed: true,
    });

    await login(admin.page, 101);
    assert.equal(await admin.page.locator('nav a[href="/admin"]').count(), 1);
    await admin.page.goto(`${baseURL}/admin`);
    const changeStatus = async (label) => {
      const record = admin.page
        .locator(".record-list .record")
        .filter({ hasText: applicationPurpose });
      await record.getByRole("button", { name: label, exact: true }).click();
      const changed = admin.page.waitForResponse(
        (response) =>
          response.url().endsWith(`/reservations/${reservation.id}/status`) &&
          response.request().method() === "PATCH",
      );
      await record
        .getByRole("button", { name: `確認${label}`, exact: true })
        .click();
      const response = await changed;
      assert.equal(response.status(), 200, await response.text());
    };
    await changeStatus("核准");
    await admin.page
      .getByRole("button", { name: "借用紀錄", exact: true })
      .click();
    await changeStatus("交付鑰匙");
    await changeStatus("記錄歸還");
    await borrower.page.reload();
    await borrower.page
      .locator(".record-list .record")
      .filter({ hasText: applicationPurpose })
      .locator(".status.completed")
      .waitFor();
    await borrower.page.goto(`${baseURL}/notifications`);
    await borrower.page
      .getByText(/已歸還鑰匙/)
      .first()
      .waitFor();
    measurements.checks.push({
      name: "Admin approval, key handover, key return, and borrower notifications",
      passed: true,
    });

    await admin.page
      .getByRole("button", { name: "使用者", exact: true })
      .click();
    await admin.page.locator(".loading-row").waitFor({ state: "detached" });
    const userRow = admin.page
      .locator(".user-row")
      .filter({ hasText: "fixture1@email.ntou.edu.tw" });
    let visitedUsers = await admin.page.locator(".user-row").count();
    const seenUsers = new Set(
      await admin.page.locator(".user-row").allTextContents(),
    );
    while ((await userRow.count()) === 0) {
      const next = admin.page.getByRole("button", {
        name: "下一頁",
        exact: true,
      });
      assert(
        !(await next.isDisabled()),
        "Oldest borrower must be reachable through user pagination",
      );
      const result = await turnPage(admin.page, next, "/api/admin/users");
      assert.equal(
        await admin.page.locator(".user-row").count(),
        result.items.length,
      );
      visitedUsers += result.items.length;
      for (const text of await admin.page
        .locator(".user-row")
        .allTextContents())
        seenUsers.add(text);
    }
    assert.equal(visitedUsers, 102);
    assert.equal(seenUsers.size, 102);
    measurements.checks.push({
      name: "102 admin users including a borrower beyond the original 100 row limit are reachable",
      passed: true,
      users: 102,
    });
    const suspensionResponse = admin.page.waitForResponse(
      (response) =>
        response.url().endsWith(`/api/admin/users/${reservation.user_id}`) &&
        response.request().method() === "PATCH",
    );
    await userRow
      .getByRole("button", { name: "停權帳號", exact: true })
      .click();
    assert.equal((await suspensionResponse).status(), 200);
    await borrower.page.goto(`${baseURL}/rooms/${roomID}`);
    await borrower.page
      .getByText(/帳號停權|帳號已停權/)
      .first()
      .waitFor();
    assert.equal(
      await borrower.page.getByRole("button", { name: "送出借用申請" }).count(),
      0,
    );
    measurements.checks.push({
      name: "Suspension blocks the already authenticated borrower",
      passed: true,
    });
    for (const width of [375, 768, 1440])
      await assertResponsive(admin.page, "/admin", width);
    await screenshot(admin.page, "admin-desktop");

    await admin.page
      .getByRole("button", { name: "違規管理", exact: true })
      .click();
    await admin.page.locator(".loading-row").waitFor({ state: "detached" });
    const select = admin.page.getByRole("combobox", { name: /^違規借用人/ });
    const selected = await select
      .locator("option")
      .nth(1)
      .getAttribute("value");
    assert(selected);
    await select.selectOption(selected);
    await turnPage(
      admin.page,
      admin.page.getByRole("button", { name: "下一頁使用者", exact: true }),
      "/api/admin/users",
    );
    assert.equal(await select.inputValue(), selected);
    assert(
      (await select.locator("option:checked").textContent()).includes("已選擇"),
    );
    await turnPage(
      admin.page,
      admin.page.getByRole("button", { name: "上一頁使用者", exact: true }),
      "/api/admin/users",
    );
    assert.equal(await select.inputValue(), selected);
    for (let index = 0; index < 5; index++) {
      await turnPage(
        admin.page,
        admin.page.getByRole("button", { name: "下一頁使用者", exact: true }),
        "/api/admin/users",
      );
    }
    assert.equal(await select.inputValue(), selected);
    const oldestOption = select
      .locator("option")
      .filter({ hasText: "TEST000001" });
    assert.equal(await oldestOption.count(), 1);
    await select.selectOption(reservation.user_id);
    assert.equal(await select.inputValue(), reservation.user_id);
    assert(
      await admin.page
        .getByRole("button", { name: "下一頁使用者", exact: true })
        .isDisabled(),
    );
    measurements.checks.push({
      name: "Violation borrower selection survives next/back pages and includes borrower beyond 100 rows",
      passed: true,
      borrowers: 101,
    });

    let visitedViolations = await admin.page
      .locator('[aria-label="違規紀錄"] .record')
      .count();
    const oldestReason = "Playwright 最舊未結案違規";
    for (let index = 0; index < 5; index++) {
      const result = await turnPage(
        admin.page,
        admin.page.getByRole("button", { name: "下一頁違規紀錄", exact: true }),
        "/api/admin/violations",
      );
      assert.equal(result.total, 101);
      visitedViolations += result.items.length;
    }
    assert.equal(visitedViolations, 101);
    const oldestRecord = admin.page
      .locator('[aria-label="違規紀錄"] .record')
      .filter({ hasText: oldestReason });
    assert.equal(await oldestRecord.count(), 1);
    assert((await oldestRecord.textContent()).includes("測試使用者 1"));
    assert(
      await admin.page
        .getByRole("button", { name: "下一頁違規紀錄", exact: true })
        .isDisabled(),
    );
    await turnPage(
      admin.page,
      admin.page.getByRole("button", { name: "上一頁違規紀錄", exact: true }),
      "/api/admin/violations",
    );
    assert.equal(
      await admin.page.locator('[aria-label="違規紀錄"] .record').count(),
      20,
    );
    await turnPage(
      admin.page,
      admin.page.getByRole("button", { name: "下一頁違規紀錄", exact: true }),
      "/api/admin/violations",
    );
    assert.equal(await oldestRecord.count(), 1);
    measurements.checks.push({
      name: "101 violation records page stably and retain the oldest unresolved record and borrower name",
      passed: true,
      violations: 101,
    });
    await admin.page.setViewportSize({ width: 1440, height: 1000 });
    await screenshot(admin.page, "violations-desktop");
    await admin.page.setViewportSize({ width: 375, height: 1000 });
    const violationSize = await admin.page.evaluate(() => ({
      scroll: document.documentElement.scrollWidth,
      viewport: document.documentElement.clientWidth,
    }));
    assert(
      violationSize.scroll <= violationSize.viewport + 1,
      "Violation pagination overflows on mobile",
    );
    await screenshot(admin.page, "violations-mobile");
    const resolution = admin.page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname.startsWith("/api/admin/violations/") &&
        response.request().method() === "PATCH",
    );
    await oldestRecord
      .getByRole("button", { name: "違規結案", exact: true })
      .click();
    const resolved = await resolution;
    assert.equal(resolved.status(), 200, await resolved.text());
    assert.equal((await resolved.json()).resolved, true);
    await admin.page.locator(".loading-row").waitFor({ state: "detached" });
    await oldestRecord.getByText("已結案", { exact: true }).waitFor();
    measurements.checks.push({
      name: "Oldest unresolved violation beyond 100 rows resolves from the mobile paginated view",
      passed: true,
    });

    const fallback = await newPage(browser, 375);
    try {
      await fallback.context.route("**/campus-map.svg", (route) =>
        route.abort("failed"),
      );
      await fallback.page.goto(`${baseURL}/rooms/${roomID}`);
      await fallback.page
        .getByText("文字版位置描述", { exact: true })
        .waitFor();
      await fallback.page
        .getByText(/工學院二樓，主樓梯右側走廊第一間/)
        .waitFor();
      measurements.checks.push({
        name: "Map server failure retains location text",
        passed: true,
      });
      await screenshot(fallback.page, "map-fallback-mobile");
      assert.deepEqual(fallback.errors, []);
    } finally {
      await fallback.context.close();
    }
    await assertFirstOnboarding(browser);
    assert.deepEqual(borrower.errors, []);
    assert.deepEqual(admin.errors, []);
    measurements.passed = true;
  } catch (error) {
    measurements.passed = false;
    measurements.error = String(error.stack || error);
    await screenshot(borrower.page, "failure-borrower").catch(() => {});
    await screenshot(admin.page, "failure-admin").catch(() => {});
    throw error;
  } finally {
    await fs.writeFile(
      path.join(reports, "upgrade-e2e-browser.json"),
      JSON.stringify(measurements, null, 2),
    );
    await borrower.context.close();
    await admin.context.close();
    await browser.close();
    console.log(JSON.stringify(measurements, null, 2));
  }
}
run().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
