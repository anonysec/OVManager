// Copyright (c) 2025 anonysec. All rights reserved.
// Proprietary and confidential. Unauthorized copying, distribution, or use is prohibited.

import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';

// Only English is bundled into the entry chunk. fa/ru/cn are ~95 kB of JSON
// combined and every user was downloading all four regardless of language.
// The other locales are code-split and fetched on demand, so a first paint
// costs one locale instead of four.
import enTranslation from './lang/en.json';

const LAZY_LOCALES = {
  fa: () => import('./lang/fa.json'),
  ru: () => import('./lang/ru.json'),
  cn: () => import('./lang/cn.json'),
};

/** Apply the document direction + lang for the current i18n language. */
const applyDocumentDir = (lng) => {
  const dir = lng.startsWith('fa') ? 'rtl' : 'ltr';
  document.documentElement.dir = dir;
  document.documentElement.lang = lng;
  // Mark the whole app as RTL/LTR so CSS can rely on html[dir].
  document.body.setAttribute('dir', dir);
};

const stored = localStorage.getItem('ovmanager-lang') || 'en';
// Start on a language we definitely have. If the stored preference is a lazy
// locale we boot in English and swap the instant its bundle lands — this keeps
// first paint immediate instead of blocking render on a JSON fetch.
const initial = stored in LAZY_LOCALES ? 'en' : stored;

i18n
  .use(initReactI18next)
  .init({
    resources: { en: { translation: enTranslation } },
    lng: initial,
    fallbackLng: 'en',
    interpolation: { escapeValue: false },
    // Nothing is missing at boot — every key falls back to en until the real
    // locale arrives, so React never renders raw i18n keys.
    partialBundledLanguages: true,
  });

const loading = new Map();

/**
 * Ensure a locale's resource bundle is present, then activate it.
 * Safe to call repeatedly: in-flight loads are de-duplicated and already
 * loaded locales resolve immediately.
 */
export async function loadLanguage(lng) {
  if (!lng || lng === i18n.language) return;

  if (LAZY_LOCALES[lng] && !i18n.hasResourceBundle(lng, 'translation')) {
    if (!loading.has(lng)) {
      loading.set(
        lng,
        LAZY_LOCALES[lng]()
          .then((mod) => {
            i18n.addResourceBundle(lng, 'translation', mod.default, true, true);
          })
          .catch((err) => {
            // Stay on the current language rather than switching to a blank
            // bundle; the user keeps a usable UI.
            console.error(`Failed to load locale "${lng}"`, err);
            throw err;
          })
          .finally(() => loading.delete(lng)),
      );
    }
    try {
      await loading.get(lng);
    } catch {
      return;
    }
  }

  await i18n.changeLanguage(lng);
  localStorage.setItem('ovmanager-lang', lng);
}

// Restore the user's real language right after boot. Deferred so it never
// competes with the first paint or the initial data requests.
if (stored !== initial) {
  const idle = window.requestIdleCallback || ((fn) => setTimeout(fn, 1));
  idle(() => loadLanguage(stored));
}

// Apply direction immediately at startup (login page included — it renders
// outside DashboardLayout, which previously was the only place that set dir).
applyDocumentDir(i18n.language);

// Keep dir in sync whenever the language changes anywhere in the app.
i18n.on('languageChanged', applyDocumentDir);

export default i18n;
