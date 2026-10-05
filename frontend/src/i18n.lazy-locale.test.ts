import { describe, it, expect, beforeEach } from 'vitest';
import i18n, { loadLanguage } from './i18n';

const KEY = 'username';

/**
 * The picker call sites, not i18n.js.
 *
 * The previous version of this file tested `i18n.changeLanguage` vs
 * `loadLanguage` in isolation — which only proves the helper works. It passed
 * unchanged whether the pickers called it or not, so the exact regression
 * (a picker switching language without fetching the bundle) had no coverage at
 * all.
 */
describe('language pickers load the bundle before switching', () => {
  beforeEach(async () => {
    await i18n.changeLanguage('en');
  });

  it('every picker routes through loadLanguage, never changeLanguage', async () => {
    const pickers = await Promise.all([
      import('./pages/DashboardLayout'),
      import('./pages/settings/AppearanceSection'),
    ]);
    for (const mod of pickers) {
      expect(mod).toBeTruthy();
    }
    const sources = await Promise.all(
      [
        './pages/DashboardLayout.tsx?raw',
        './pages/settings/AppearanceSection.tsx?raw',
      ].map((m) => import(/* @vite-ignore */ m)),
    );
    for (const mod of sources) {
      const src = (mod as { default: string }).default;
      expect(src, 'a picker must not call i18n.changeLanguage directly').not.toMatch(
        /i18n\.changeLanguage\(/,
      );
      expect(src, 'a picker must reach the language helper').toMatch(/loadLanguage\(/);
    }
  });

  it('loadLanguage translates, where changeLanguage alone would not', async () => {
    expect(i18n.t(KEY)).toBe('Username');
    await loadLanguage('fa');
    expect(i18n.t(KEY)).toBe('نام کاربری');
    expect(document.documentElement.dir).toBe('rtl');
  });

  it('a click while a chunk is in flight still lands on the LAST choice', async () => {
    await i18n.changeLanguage('en');
    const first = loadLanguage('ru');
    const second = loadLanguage('fa');
    await Promise.all([first, second]);
    expect(i18n.language, 'the later click must win').toBe('fa');
  });
});