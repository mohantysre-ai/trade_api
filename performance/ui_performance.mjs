import { chromium } from '@playwright/test';
import fs from 'node:fs/promises';

const baseUrl = process.env.FRONTEND_URL ?? 'http://127.0.0.1:3000';
const iterations = Number(process.env.UI_ITERATIONS ?? 5);
const maxPageLoadMs = Number(process.env.UI_MAX_PAGE_LOAD_MS ?? 2500);
const maxTabResponseMs = Number(process.env.UI_MAX_TAB_RESPONSE_MS ?? 500);
const labels = ['SNAPSHOT', 'HEATMAP', 'SWING', 'INTRADAY', 'INDEX OPTIONS', 'EOD'];
const output = process.env.UI_REPORT_PATH ?? new URL('./reports/ui-report.json', import.meta.url);
const percentile = (values, point) => {
  const ordered = [...values].sort((a, b) => a - b);
  if (!ordered.length) return 0;
  const index = Math.min(ordered.length - 1, Math.ceil((ordered.length - 1) * point));
  return ordered[index];
};

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const failures = [];
page.on('response', (response) => {
  if (response.status() >= 500) failures.push(`${response.status()} ${response.url()}`);
});
const started = performance.now();
await page.goto(baseUrl, { waitUntil: 'domcontentloaded', timeout: 60000 });
await page.getByRole('tablist', { name: 'Desk views' }).waitFor({ state: 'visible' });
const pageLoadMs = performance.now() - started;
const navigation = await page.evaluate(() => {
  const entry = performance.getEntriesByType('navigation')[0];
  const paints = Object.fromEntries(performance.getEntriesByType('paint').map((item) => [item.name, item.startTime]));
  return entry ? { domContentLoadedMs: entry.domContentLoadedEventEnd, loadMs: entry.loadEventEnd, ...paints } : {};
});
const screens = {};
for (const label of labels) {
  const timings = [];
  for (let iteration = 0; iteration < iterations; iteration += 1) {
    const tab = page.getByRole('tab', { name: label, exact: true });
    const begin = performance.now();
    await tab.click();
    await page.waitForFunction((name) => document.querySelector('[role="tab"][aria-selected="true"]')?.textContent?.trim() === name, label);
    await page.waitForTimeout(100);
    timings.push(performance.now() - begin);
  }
  screens[label] = { p50Ms: percentile(timings, 0.50), p95Ms: percentile(timings, 0.95), maxMs: Math.max(...timings), passed: percentile(timings, 0.95) <= maxTabResponseMs };
}
const report = { baseUrl, iterations, pageLoadMs, navigation, screens, serverFailures: [...new Set(failures)], thresholds: { maxPageLoadMs, maxTabResponseMs } };
report.passed = pageLoadMs <= maxPageLoadMs && Object.values(screens).every((item) => item.passed) && report.serverFailures.length === 0;
await fs.mkdir(new URL('./reports/', import.meta.url), { recursive: true });
await fs.writeFile(output, JSON.stringify(report, null, 2));
console.log(JSON.stringify(report, null, 2));
await browser.close();
process.exitCode = report.passed ? 0 : 1;
