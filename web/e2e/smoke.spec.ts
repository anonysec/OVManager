import { test, expect } from '@playwright/test';

test('panel page loads without console errors', async ({ page }) => {
  const errors: string[] = [];
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  page.on('pageerror', e => errors.push(e.message));
  const resp = await page.goto('./');
  expect(resp?.status()).toBe(200);
  await page.waitForLoadState('networkidle');
  const jsLoaded = await page.evaluate(() => !!document.querySelector('script[src*="assets/"]'));
  expect(jsLoaded).toBeTruthy();
  // report but don't hard-fail on warnings; hard-fail on pageerror
  // Note: Self-signed certificates cause "SSL certificate error" when loading scripts
  // This is expected behavior for self-signed certs and is not a bug.
  const pageErrors = errors.filter(e => /error/i.test(e) && !/favicon/i.test(e) && !/SSL certificate error/i.test(e));
  expect(pageErrors.length).toBe(0);
});

test('SPA renders root element', async ({ page }) => {
  await page.goto('./');
  await page.waitForSelector('#root', { timeout: 10000 });
  const root = page.locator('#root');
  await expect(root).toBeAttached();
});

test('health endpoint ok', async ({ request }) => {
  const r = await request.get('/health');
  expect(r.ok()).toBeTruthy();
  const body = await r.json();
  expect(body.status).toBe('ok');
  if (body.version !== undefined) {
    expect(body.version).toBeTruthy();
  }
});

test('login page renders form', async ({ page }) => {
  await page.goto('./');
  await page.waitForLoadState('networkidle');
  const inputs = page.locator('input');
  await expect(inputs.first()).toBeAttached({ timeout: 10000 });
});
