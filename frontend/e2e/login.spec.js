import { test, expect } from '@playwright/test';

const BASE = 'http://127.0.0.1:2095/dash';

test.describe('OVManager E2E', () => {
  test('login form renders', async ({ page }) => {
    await page.context().clearCookies();
    await page.goto(`${BASE}/login`);
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(3000);
    await expect(page.locator('#username')).toBeVisible({ timeout: 10000 });
    await expect(page.locator('#password')).toBeVisible();
    await expect(page.locator('button[type="submit"]')).toBeVisible();
  });

  test('invalid credentials shows error', async ({ page }) => {
    await page.context().clearCookies();
    await page.evaluate(() => localStorage.clear()).catch(() => {});
    await page.goto(`${BASE}/login`);
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(3000);
    await page.fill('#username', 'wronguser');
    await page.fill('#password', 'wrongpass');
    await page.click('button[type="submit"]');
    await page.waitForTimeout(1000);
    const hasError = await page.locator('.error-message, .error-state, [class*="error"]').count();
    expect(hasError).toBeGreaterThan(0);
  });

  test('displays existing users', async ({ page }) => {
    await page.context().clearCookies();
    await page.evaluate(() => localStorage.clear()).catch(() => {});
    await page.goto(`${BASE}/login`);
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000);
    await page.fill('#username', 'admin');
    await page.fill('#password', 'admin');
    await page.click('button[type="submit"]');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000);
    await page.evaluate(() => { localStorage.setItem('ovmanager-onboard-dismissed', '1'); });
    await page.goto(`${BASE}/users`);
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000);
    // Check table has at least 3 users
    const rowCount = await page.locator('tbody tr').count();
    expect(rowCount).toBeGreaterThanOrEqual(3);
  });

  test('creates a new user successfully', async ({ page }) => {
    await page.context().clearCookies();
    await page.evaluate(() => localStorage.clear()).catch(() => {});
    await page.goto(`${BASE}/login`);
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000);
    await page.fill('#username', 'admin');
    await page.fill('#password', 'admin');
    await page.click('button[type="submit"]');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000);
    await page.evaluate(() => { localStorage.setItem('ovmanager-onboard-dismissed', '1'); });
    await page.goto(`${BASE}/users`);
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000);
    
    const beforeCount = await page.locator('tbody tr').count();
    const newUser = `pw${Math.floor(1000 + Math.random() * 9000)}`;
    
    await page.click('text=Add New User');
    await page.waitForTimeout(500);
    await page.fill('#new-user-name', newUser);
    await page.click('.date-chip:has-text("1m")');
    await page.fill('#new-user-max-logins', '1');
    
    await page.click('button:has-text("Create User")');
    await page.waitForTimeout(8000);
    
    const afterCount = await page.locator('tbody tr').count();
    expect(afterCount).toBeGreaterThan(beforeCount);
  });

  test('loads dashboard page', async ({ page }) => {
    await page.context().clearCookies();
    await page.evaluate(() => localStorage.clear()).catch(() => {});
    await page.goto(`${BASE}/login`);
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000);
    await page.fill('#username', 'admin');
    await page.fill('#password', 'admin');
    await page.click('button[type="submit"]');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000);
    await page.evaluate(() => { localStorage.setItem('ovmanager-onboard-dismissed', '1'); });
    await page.goto(`${BASE}/dashboard`);
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000);
    const hasContent = await page.locator('h1, h2, .dashboard-title, .resource-card').count();
    expect(hasContent).toBeGreaterThan(0);
  });

  test('loads nodes page', async ({ page }) => {
    await page.context().clearCookies();
    await page.evaluate(() => localStorage.clear()).catch(() => {});
    await page.goto(`${BASE}/login`);
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000);
    await page.fill('#username', 'admin');
    await page.fill('#password', 'admin');
    await page.click('button[type="submit"]');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000);
    await page.evaluate(() => { localStorage.setItem('ovmanager-onboard-dismissed', '1'); });
    await page.goto(`${BASE}/nodes`);
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000);
    const hasNode = await page.locator('tr').filter({ hasText: 'de-main' }).count();
    expect(hasNode).toBeGreaterThan(0);
  });

  test('settings tabs load without error', async ({ page }) => {
    await page.context().clearCookies();
    await page.evaluate(() => localStorage.clear()).catch(() => {});
    await page.goto(`${BASE}/login`);
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000);
    await page.fill('#username', 'admin');
    await page.fill('#password', 'admin');
    await page.click('button[type="submit"]');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000);
    await page.evaluate(() => { localStorage.setItem('ovmanager-onboard-dismissed', '1'); });
    await page.goto(`${BASE}/settings`);
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000);
    const tabs = ['General', 'Bot', 'System', 'Security', 'Activity'];
    for (const tab of tabs) {
      await page.locator('.settings-nav-item').filter({ hasText: tab }).first().click();
      await page.waitForTimeout(1000);
      const errorCount = await page.locator('.error-state').count();
      expect(errorCount).toBe(0);
    }
  });
});