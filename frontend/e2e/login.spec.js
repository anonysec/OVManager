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
    
    // Click the Add New User button via JavaScript to avoid pointer-events interception
    await page.evaluate(() => {
      const btn = Array.from(document.querySelectorAll('button')).find(b => b.textContent?.includes('Add New User'));
      if (btn) btn.click();
    });
    // Wait for modal to appear
    await page.waitForSelector('#new-user-name', { timeout: 10000 });
    await page.fill('#new-user-name', newUser);
    await page.evaluate(() => {
      const chip = Array.from(document.querySelectorAll('button')).find(b => b.textContent?.trim() === '1m');
      if (chip) chip.click();
    });
    await page.fill('#new-user-max-logins', '1');
    
    await page.evaluate(() => {
      const btn = Array.from(document.querySelectorAll('button')).find(b => b.textContent?.includes('Create User'));
      if (btn) btn.click();
    });
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

  test('settings page loads sections', async ({ page }) => {
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
    // Settings is now a single scroll page with sections (no sub-tabs)
    const hasGeneral = await page.locator('h2').filter({ hasText: 'General' }).count();
    expect(hasGeneral).toBeGreaterThan(0);
  });
});