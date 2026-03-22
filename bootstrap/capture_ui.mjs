import { chromium } from '../frontend/node_modules/playwright/index.mjs';
import fs from 'node:fs';
import path from 'node:path';

const baseUrl = process.env.SIGNOZ_BASE_URL || 'http://127.0.0.1:8080';
const apiKey = process.env.SIGNOZ_API_KEY || '';
const outputDir = process.env.SCREENSHOT_DIR || path.resolve('screenshots', 'observer-stack');

if (!apiKey) {
  throw new Error('SIGNOZ_API_KEY is required to capture authenticated UI screenshots.');
}

fs.mkdirSync(outputDir, { recursive: true });

const routes = [
  { name: 'home', path: '/home', waitFor: /home|onboarding|dashboard|service/i },
  { name: 'dashboard-list', path: '/dashboard', waitFor: /dashboard/i },
  { name: 'dashboard-kafka-optimized', path: '/dashboard/019d120b-c24b-716e-9890-14c5f3d54031?relativeTime=5m', waitFor: /kafka|dashboard|configure/i },
  { name: 'dashboard-otel-optimized', path: '/dashboard/019d120b-c226-7b3a-95de-ef4723546a4a?relativeTime=5m', waitFor: /otel|dashboard|configure/i },
  { name: 'alerts-list', path: '/alerts', waitFor: /alerts/i },
  { name: 'channels-list', path: '/settings/channels', waitFor: /channel/i },
];

const browser = await chromium.launch({ headless: true });

try {
  const loginContext = await browser.newContext({ viewport: { width: 1440, height: 960 } });
  const loginPage = await loginContext.newPage();
  await loginPage.goto(`${baseUrl}/login`, { waitUntil: 'domcontentloaded' });
  await loginPage.screenshot({ path: path.join(outputDir, 'login-page.png'), fullPage: true });
  await loginContext.close();

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

  const results = [];

  for (const route of routes) {
    const page = await context.newPage();
    let navigationStatus = 'loaded';
    try {
      await page.goto(`${baseUrl}${route.path}`, { waitUntil: 'domcontentloaded', timeout: 30000 });
    } catch (error) {
      navigationStatus = `goto-timeout:${error?.name || 'error'}`;
    }
    await page.waitForLoadState('networkidle', { timeout: 10000 }).catch(() => {});
    await page.waitForTimeout(4000);
    const bodyText = await page.locator('body').innerText().catch(() => '');
    results.push({
      name: route.name,
      url: page.url(),
      matched: route.waitFor.test(bodyText),
      navigationStatus,
    });
    const useFullPage = !route.name.startsWith('dashboard-');
    try {
      await page.screenshot({
        path: path.join(outputDir, `${route.name}.png`),
        fullPage: useFullPage,
        timeout: 15000,
      });
    } catch (error) {
      results[results.length - 1].screenshotStatus = `failed:${error?.name || 'error'}`;
    }
    await page.close();
  }

  fs.writeFileSync(
    path.join(outputDir, 'ui-capture-summary.json'),
    JSON.stringify(results, null, 2),
    'utf-8',
  );

  await context.close();
} finally {
  await browser.close();
}
