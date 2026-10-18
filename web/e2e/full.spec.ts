import { test, expect } from '@playwright/test';

const CREDS = { username: 'admin', password: 'TestPass123!' };

async function login(page: any) {
  await page.goto('/login');
  await page.waitForLoadState('networkidle');
  await page.fill('input[name="username"], input[type="text"]', CREDS.username).catch(() => {});
  // fallback: first text input
  const userIn = page.locator('input').first();
  if (!(await userIn.inputValue())) await userIn.fill(CREDS.username);
  const passIn = page.locator('input[type="password"]').first();
  await passIn.fill(CREDS.password);
  await page.click('button[type="submit"], button:has-text("Login"), button:has-text("Sign in")');
  await page.waitForLoadState('networkidle');
}

test.describe('full project E2E', () => {
  test('login succeeds and lands on dashboard', async ({ page }) => {
    await login(page);
    // should leave /login
    await page.waitForTimeout(1500);
    const url = page.url();
    expect(url).not.toContain('/login');
  });

  test('dashboard renders without console errors', async ({ page }) => {
    await login(page);
    const errors: string[] = [];
    page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
    page.on('pageerror', e => errors.push(e.message));
    await page.waitForLoadState('networkidle');
    const real = errors.filter(e => !/favicon/i.test(e));
    expect(real.length).toBe(0);
  });

  test('users page loads', async ({ page }) => {
    await login(page);
    await page.goto('/users');
    await page.waitForLoadState('networkidle');
    await expect(page.locator('body')).toBeVisible();
  });

  test('nodes page loads', async ({ page }) => {
    await login(page);
    await page.goto('/nodes');
    await page.waitForLoadState('networkidle');
    await expect(page.locator('body')).toBeVisible();
  });

  test('logs page loads', async ({ page }) => {
    await login(page);
    await page.goto('/logs');
    await page.waitForLoadState('networkidle');
    await expect(page.locator('body')).toBeVisible();
  });

  test('settings page loads', async ({ page }) => {
    await login(page);
    await page.goto('/settings');
    await page.waitForLoadState('networkidle');
    await expect(page.locator('body')).toBeVisible();
  });

  test('security headers present', async ({ request }) => {
    const r = await request.get('/health');
    expect(r.headers()['x-frame-options']).toBe('DENY');
    expect(r.headers()['x-content-type-options']).toBe('nosniff');
    expect(r.headers()['content-security-policy']).toContain("default-src 'self'");
  });

  test('health endpoint returns version', async ({ request }) => {
    const r = await request.get('/health');
    const body = await r.json();
    expect(body.status).toBe('ok');
    expect(body.version).toBeTruthy();
  });

  test('assets load (no 404)', async ({ request }) => {
    const idx = await request.get('/');
    const html = await idx.text();
    const m = html.match(/assets\/[A-Za-z0-9._-]+\.js/);
    expect(m).not.toBeNull();
    const r = await request.get('/' + m![0]);
    expect(r.ok()).toBeTruthy();
  });
});
