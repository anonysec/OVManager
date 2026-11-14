// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

/**
 * Screenshot capture for visual review. Not an assertion suite: it renders
 * the main surfaces in both themes and at phone width so changes can be
 * judged against a real browser instead of source alone.
 */
import { test, type Page } from '@playwright/test';
import fs from 'node:fs';

const USER = process.env.OVM_E2E_USER || 'admin';
const PASS = process.env.OVM_E2E_PASS || 'TestPass123!';
const OUT = process.env.OVM_SHOTS_DIR || '/tmp/opencode/shots';

const shot = async (page: Page, name: string) => {
  await page.waitForTimeout(600);
  await page.screenshot({ path: `${OUT}/${name}.png`, fullPage: true });
};

const login = async (page: Page, theme: 'light' | 'dark') => {
  await page.addInitScript((t) => {
    try { localStorage.setItem('ovmanager-theme', t); } catch { /* blocked */ }
  }, theme);
  await page.goto('login');
  await page.waitForLoadState('domcontentloaded');
  await page.locator('input[type="text"]').first().fill(USER);
  await page.locator('input[type="password"]').first().fill(PASS);
  await page.click('button[type="submit"]');
  await page.waitForLoadState('domcontentloaded');
  await page.waitForTimeout(900);
};

test.beforeAll(() => { fs.mkdirSync(OUT, { recursive: true }); });

test.describe('screenshots desktop', () => {
  test.use({ viewport: { width: 1440, height: 900 } });

  test('light', async ({ page }) => {
    await login(page, 'light');
    for (const [name, url] of [
      ['dashboard-light', './'],
      ['users-light', 'users'],
      ['nodes-light', 'nodes'],
      ['settings-light', 'settings'],
      ['logs-light', 'logs'],
    ] as const) {
      await page.goto(url);
      await page.waitForLoadState('domcontentloaded');
      await shot(page, name);
    }

    await page.goto('users');
    await page.waitForLoadState('domcontentloaded');
    await page.waitForTimeout(600);
    await page.locator('.dt-row').first().click();
    await page.waitForSelector('.modal-window[role="dialog"]');
    await shot(page, 'user-detail-light');
  });

  test('dark', async ({ page }) => {
    await login(page, 'dark');
    for (const [name, url] of [
      ['dashboard-dark', './'],
      ['users-dark', 'users'],
      ['nodes-dark', 'nodes'],
    ] as const) {
      await page.goto(url);
      await page.waitForLoadState('domcontentloaded');
      await shot(page, name);
    }

    await page.goto('nodes');
    await page.waitForLoadState('domcontentloaded');
    await page.waitForTimeout(600);
    await page.locator('.nm-name').first().click();
    await page.waitForSelector('.node-drawer');
    await shot(page, 'node-drawer-dark');
  });
});

test.describe('screenshots phone', () => {
  test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });

  test('light', async ({ page }) => {
    await login(page, 'light');
    for (const [name, url] of [
      ['dashboard-phone', './'],
      ['users-phone', 'users'],
      ['nodes-phone', 'nodes'],
    ] as const) {
      await page.goto(url);
      await page.waitForLoadState('domcontentloaded');
      await shot(page, name);
    }

    await page.goto('users');
    await page.waitForLoadState('domcontentloaded');
    await page.waitForTimeout(600);
    await page.locator('.dt-row').first().click();
    await page.waitForSelector('.modal-window[role="dialog"]');
    await shot(page, 'user-detail-phone');
  });
});
