import { describe, it, expect } from 'vitest';
import i18n, { loadLanguage } from './i18n';

const KEY = 'username';

describe('lazy locale bundles', () => {
  it('changeLanguage ALONE leaves the bundle unloaded - the reported bug', async () => {
    await i18n.changeLanguage('fa');
    expect(i18n.hasResourceBundle('fa', 'translation')).toBe(false);
    // The fa bundle is absent, so the key still resolves to its English text:
    // the page mirrors to RTL while every label stays English.
    expect(i18n.t(KEY)).toBe('Username');
  });

  it('loadLanguage loads the bundle, so the string actually becomes Persian', async () => {
    await i18n.changeLanguage('en');
    await loadLanguage('fa');
    expect(i18n.hasResourceBundle('fa', 'translation')).toBe(true);
    expect(i18n.t(KEY)).toBe('نام کاربری');
  });
});
