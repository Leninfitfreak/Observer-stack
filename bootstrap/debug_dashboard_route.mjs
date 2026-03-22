import { chromium } from '../frontend/node_modules/playwright/index.mjs';
import fs from 'node:fs';
import path from 'node:path';

const baseUrl = process.env.SIGNOZ_BASE_URL || 'http://127.0.0.1:8080';
const apiKey = process.env.SIGNOZ_API_KEY || '';
const routePath = process.env.DASHBOARD_ROUTE || '/dashboard';
const outputFile =
  process.env.DEBUG_OUTPUT_FILE ||
  path.resolve('observer-stack', 'bootstrap', 'dashboard-route-debug.json');
const screenshotFile = process.env.DEBUG_SCREENSHOT_FILE || '';

if (!apiKey) {
  throw new Error('SIGNOZ_API_KEY is required.');
}

const browser = await chromium.launch({ headless: true });

try {
  const context = await browser.newContext({
    viewport: { width: 1440, height: 960 },
    extraHTTPHeaders: {
      'SIGNOZ-API-KEY': apiKey,
    },
  });

  await context.addInitScript(() => {
    window.localStorage.setItem('IS_LOGGED_IN', 'true');
    window.localStorage.setItem('AUTH_TOKEN', 'placeholder');
    window.localStorage.setItem('REFRESH_AUTH_TOKEN', 'placeholder');
  });

  const page = await context.newPage();
  const events = {
    route: routePath,
    console: [],
    pageErrors: [],
    requestFailures: [],
    responses: [],
  };

  page.on('console', (msg) => {
    events.console.push({ type: msg.type(), text: msg.text() });
  });

  page.on('pageerror', (err) => {
    events.pageErrors.push(err.message);
  });

  page.on('requestfailed', (request) => {
    events.requestFailures.push({
      url: request.url(),
      method: request.method(),
      error: request.failure()?.errorText || 'unknown',
    });
  });

  page.on('response', async (response) => {
    const url = response.url();
    if (!url.includes('/api/')) {
      return;
    }
    events.responses.push({
      url,
      status: response.status(),
    });
  });

  let navigationStatus = 'loaded';
  try {
    await page.goto(`${baseUrl}${routePath}`, { waitUntil: 'domcontentloaded', timeout: 30000 });
  } catch (error) {
    navigationStatus = `goto-timeout:${error?.name || 'error'}`;
  }

  await page.waitForTimeout(8000);

  const bodyText = await page.locator('body').innerText().catch(() => '');
  let screenshotStatus = 'skipped';
  if (screenshotFile) {
    try {
      await page.screenshot({ path: screenshotFile, fullPage: false, timeout: 15000 });
      screenshotStatus = 'captured';
    } catch (error) {
      screenshotStatus = `failed:${error?.name || 'error'}`;
    }
  }
  const payload = {
    route: routePath,
    url: page.url(),
    title: await page.title(),
    navigationStatus,
    bodySample: bodyText.slice(0, 1000),
    bodyLength: bodyText.length,
    screenshotStatus,
    events,
  };

  fs.writeFileSync(outputFile, JSON.stringify(payload, null, 2), 'utf-8');
  console.log(JSON.stringify(payload, null, 2));

  await context.close();
} finally {
  await browser.close();
}
