import { chromium } from '../frontend/node_modules/playwright/index.mjs';
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

const baseUrl = process.env.SIGNOZ_BASE_URL || 'http://127.0.0.1:8080';
const apiKey = process.env.SIGNOZ_API_KEY || '';
const outputDir = process.env.SCREENSHOT_DIR || path.resolve('screenshots', 'observer-stack');
const summaryFile =
  process.env.E2E_SUMMARY_FILE ||
  path.resolve('observer-stack', 'bootstrap', 'dashboard-e2e-summary.json');
const jwtSecret = process.env.SIGNOZ_JWT_SECRET || 'secret';

if (!apiKey) {
  throw new Error('SIGNOZ_API_KEY is required.');
}

fs.mkdirSync(outputDir, { recursive: true });

const dashboards = [
  { title: 'LeninKart Platform Overview', slug: 'platform-overview' },
  { title: 'LeninKart Product Service Overview', slug: 'product-service-overview' },
  { title: 'LeninKart Order Service Overview', slug: 'order-service-overview' },
  { title: 'LeninKart Kafka Overview', slug: 'kafka' },
  { title: 'LeninKart Frontend Overview', slug: 'frontend-overview' },
];

function isIgnorableFailure(url) {
  return (
    url.startsWith('https://fonts.gstatic.com/') ||
    url.startsWith('https://api.github.com/') ||
    url.startsWith('https://cms.signoz.cloud/') ||
    url.startsWith('https://widget.usepylon.com/') ||
    url.startsWith('http://fast.appcues.com/')
  );
}

function base64UrlEncode(input) {
  return Buffer.from(input)
    .toString('base64')
    .replace(/=/g, '')
    .replace(/\+/g, '-')
    .replace(/\//g, '_');
}

function signJwt(payload) {
  const header = { alg: 'HS256', typ: 'JWT' };
  const encodedHeader = base64UrlEncode(JSON.stringify(header));
  const encodedPayload = base64UrlEncode(JSON.stringify(payload));
  const signature = crypto
    .createHmac('sha256', jwtSecret)
    .update(`${encodedHeader}.${encodedPayload}`)
    .digest('base64')
    .replace(/=/g, '')
    .replace(/\+/g, '-')
    .replace(/\//g, '_');
  return `${encodedHeader}.${encodedPayload}.${signature}`;
}

async function fetchCurrentUser() {
  const response = await fetch(`${baseUrl}/api/v1/user/me`, {
    headers: { 'SIGNOZ-API-KEY': apiKey },
  });
  if (!response.ok) {
    throw new Error(`failed to fetch current user: ${response.status}`);
  }
  const payload = await response.json();
  return payload.data;
}

const browser = await chromium.launch({ headless: true });

try {
  const currentUser = await fetchCurrentUser();
  const now = Math.floor(Date.now() / 1000);
  const accessToken = signJwt({
    id: currentUser.id,
    email: currentUser.email,
    role: currentUser.role,
    orgId: currentUser.orgId,
    iat: now,
    exp: now + 3600,
  });
  const refreshToken = signJwt({
    id: currentUser.id,
    email: currentUser.email,
    role: currentUser.role,
    orgId: currentUser.orgId,
    iat: now,
    exp: now + 86400,
  });

  const context = await browser.newContext({ viewport: { width: 1440, height: 960 } });
  await context.addInitScript(
    ({ accessToken: at, refreshToken: rt }) => {
      window.localStorage.setItem('IS_LOGGED_IN', 'true');
      window.localStorage.setItem('AUTH_TOKEN', at);
      window.localStorage.setItem('REFRESH_AUTH_TOKEN', rt);
    },
    { accessToken, refreshToken },
  );

  const globalConsole = [];
  const globalPageErrors = [];
  const globalRequestFailures = [];

  const summary = {
    timestamp_utc: new Date().toISOString(),
    base_url: baseUrl,
    dashboards: [],
    list_page: {},
    global_console_errors: [],
    global_page_errors: [],
    global_request_failures: [],
  };

  const page = await context.newPage();
  page.on('console', (msg) => {
    globalConsole.push({ type: msg.type(), text: msg.text() });
  });
  page.on('pageerror', (err) => {
    globalPageErrors.push(err.message);
  });
  page.on('requestfailed', (request) => {
    globalRequestFailures.push({
      url: request.url(),
      method: request.method(),
      error: request.failure()?.errorText || 'unknown',
    });
  });

  const listStart = Date.now();
  await page.goto(`${baseUrl}/dashboard`, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
  await page.getByRole('heading', { name: 'Dashboards' }).waitFor({ timeout: 15000 });
  await page.screenshot({ path: path.join(outputDir, 'dashboard-list-e2e.png'), fullPage: true });
  summary.list_page = {
    url: page.url(),
    title: await page.title(),
    elapsed_ms: Date.now() - listStart,
    body_length: (await page.locator('body').innerText()).length,
  };

  for (const dashboard of dashboards) {
    const result = {
      title: dashboard.title,
      slug: dashboard.slug,
      optional: !!dashboard.optional,
      status: 'pending',
      found_in_list: false,
      click_navigation_passed: false,
      direct_route_passed: false,
      responsive: false,
      rendered: false,
      screenshot: '',
      url: '',
      title_text: '',
      elapsed_ms: 0,
      console_errors: [],
      page_errors: [],
      request_failures: [],
      api_responses: [],
    };

    const dashboardPage = await context.newPage();
    const consoleStart = globalConsole.length;
    const pageErrorStart = globalPageErrors.length;
    const failureStart = globalRequestFailures.length;
    dashboardPage.on('console', (msg) => {
      globalConsole.push({ type: msg.type(), text: msg.text() });
    });
    dashboardPage.on('pageerror', (err) => {
      globalPageErrors.push(err.message);
    });
    dashboardPage.on('requestfailed', (request) => {
      globalRequestFailures.push({
        url: request.url(),
        method: request.method(),
        error: request.failure()?.errorText || 'unknown',
      });
    });

    const responseListener = async (response) => {
      const url = response.url();
      if (url.startsWith(`${baseUrl}/api/`)) {
        result.api_responses.push({ url, status: response.status() });
      }
    };
    dashboardPage.on('response', responseListener);

    try {
      await dashboardPage.goto(`${baseUrl}/dashboard`, { waitUntil: 'domcontentloaded', timeout: 30000 });
      await dashboardPage.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
      await dashboardPage.getByRole('heading', { name: 'Dashboards' }).waitFor({ timeout: 15000 });
      await dashboardPage.waitForTimeout(1500);
      const card = dashboardPage.getByText(dashboard.title, { exact: true }).first();
      result.found_in_list = (await card.count()) > 0;

      if (!result.found_in_list) {
        result.status = dashboard.optional ? 'skipped-not-found' : 'failed-not-found';
      } else {
        const started = Date.now();
        await card.click({ timeout: 15000 });
        await dashboardPage.waitForURL(/\/dashboard\/.+/, { timeout: 15000 });
        result.click_navigation_passed = true;
        result.url = dashboardPage.url();

        const contentChecks = [
          dashboardPage.getByText(dashboard.title, { exact: true }).first().waitFor({ timeout: 20000 }),
          dashboardPage.getByText(/configure/i).first().waitFor({ timeout: 20000 }),
        ];
        await Promise.allSettled(contentChecks);
        await dashboardPage.waitForLoadState('networkidle', { timeout: 10000 }).catch(() => {});
        await dashboardPage.waitForTimeout(3000);

        const bodyText = await dashboardPage.locator('body').innerText({ timeout: 10000 });
        result.rendered =
          bodyText.includes(dashboard.title) &&
          /Configure|New Panel|Time Range/i.test(bodyText);

        const evalStart = Date.now();
        const bodyLength = await dashboardPage.evaluate(() => document.body.innerText.length);
        result.responsive = typeof bodyLength === 'number' && bodyLength > 0 && Date.now() - evalStart < 5000;

        const directUrl = result.url;
        await dashboardPage.goto(directUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
        await dashboardPage.waitForLoadState('networkidle', { timeout: 10000 }).catch(() => {});
        await dashboardPage.waitForTimeout(2000);
        const directBody = await dashboardPage.locator('body').innerText({ timeout: 10000 });
        result.direct_route_passed = directBody.includes(dashboard.title);

        result.elapsed_ms = Date.now() - started;
        result.title_text = await dashboardPage.title();
        result.screenshot = path.join(outputDir, `dashboard-${dashboard.slug}-e2e.png`);
        await dashboardPage.screenshot({ path: result.screenshot, fullPage: false, timeout: 20000 });

        if (result.rendered && result.responsive && result.click_navigation_passed && result.direct_route_passed) {
          result.status = 'passed';
        } else {
          result.status = 'failed-render';
        }
      }
    } catch (error) {
      result.status = `failed:${error?.name || 'error'}`;
      result.error = error?.message || String(error);
      try {
        result.url = dashboardPage.url();
      } catch {}
    } finally {
      dashboardPage.off('response', responseListener);
      result.console_errors = globalConsole
        .slice(consoleStart)
        .filter((entry) => !/warning/i.test(entry.type));
      result.page_errors = globalPageErrors.slice(pageErrorStart);
      result.request_failures = globalRequestFailures
        .slice(failureStart)
        .filter((entry) => !isIgnorableFailure(entry.url));
      summary.dashboards.push(result);
      fs.writeFileSync(summaryFile, JSON.stringify(summary, null, 2), 'utf-8');
      await dashboardPage.close().catch(() => {});
    }
  }

  summary.global_console_errors = globalConsole;
  summary.global_page_errors = globalPageErrors;
  summary.global_request_failures = globalRequestFailures;

  fs.writeFileSync(summaryFile, JSON.stringify(summary, null, 2), 'utf-8');
  console.log(JSON.stringify(summary, null, 2));

  await context.close();
} finally {
  await browser.close();
}
