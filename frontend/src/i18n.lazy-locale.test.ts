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
    // Imported as source, not via node:fs: the browser tsconfig has no node
    // types, and importing the modules also proves they load.
    const pickers = await Promise.all([
      import('./pages/DashboardLayout'),
      import('./pages/settings/AppearanceSection'),
    ]);
    for (const mod of pickers) {
      // The modules are imported for their side-effect-free load; the assertion
      // below reads the source the bundler actually resolves.
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
    // The behaviour the pickers now depend on.
    expect(i18n.t(KEY)).toBe('Username');
    await loadLanguage('fa');
    expect(i18n.t(KEY)).toBe('نام کاربری');
    expect(document.documentElement.dir).toBe('rtl');
  });

  it('a click while a chunk is in flight still lands on the LAST choice', async () => {
    // loadLanguage is async. Two rapid picks must not leave the first winning
    // just because its chunk fetch happened to resolve second.
    await i18n.changeLanguage('en');
    const first = loadLanguage('ru');
    const second = loadLanguage('fa');
    await Promise.all([first, second]);
    expect(i18n.language, 'the later click must win').toBe('fa');
  });
});