// TLS E2E: the TLS card is gone from panel Settings (cert management lives in
// the `ovm tls` CLI now), and an authenticated session renders the app
// against the live panel.
import { test, expect } from '@playwright/test';

const CREDS = { username: 'admin', password: 'TestPass123!' };

async function login(page: any) {
  await page.goto('/login');
  await page.waitForLoadState('networkidle');
  await page.fill('input[name="username"], input[type="text"]', CREDS.username).catch(() => {});
  const userIn = page.locator('input').first();
  if (!(await userIn.inputValue())) await userIn.fill(CREDS.username);
  const passIn = page.locator('input[type="password"]').first();
  await passIn.fill(CREDS.password);
  await page.click('button[type="submit"], button:has-text("Login"), button:has-text("Sign in")');
  await page.waitForLoadState('networkidle');
}

test('login succeeds and lands on dashboard', async ({ page }) => {
  await login(page);
  await page.waitForTimeout(1500);
  expect(page.url()).not.toContain('/login');
});

test('settings has no TLS card and no TLS deep-link section', async ({ page }) => {
  await login(page);
  await page.goto('/settings');
  await page.waitForLoadState('networkidle');
  // No tab labeled TLS / HTTPS certificate in the settings tab bar.
  const tabs = page.locator('[role="tablist"] [role="tab"]');
  await expect(tabs.filter({ hasText: /tls|https/i })).toHaveCount(0);
  // A stale /settings#tls deep-link must not produce a TLS section.
  await page.goto('/settings#tls');
  await page.waitForLoadState('networkidle');
  await expect(page.locator('#tls, [id^="tls-"]')).toHaveCount(0);
});
