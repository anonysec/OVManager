import { test, expect } from '@playwright/test';

test.describe('Login', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/dashboard');
  });

  test('renders login form', async ({ page }) => {
    await expect(page.locator('#login-container')).toBeVisible();
    await expect(page.locator('#username')).toBeVisible();
    await expect(page.locator('#password')).toBeVisible();
    await expect(page.locator('button[type="submit"]')).toBeVisible();
  });

  test('shows error on invalid credentials', async ({ page }) => {
    await page.fill('#username', 'wrong');
    await page.fill('#password', 'wrong');
    await page.click('button[type="submit"]');
    await expect(page.locator('.error-message')).toBeVisible();
  });
});