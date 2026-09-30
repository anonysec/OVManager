// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

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

const applyDocumentDir = (lng) => {
  const dir = lng.startsWith('fa') ? 'rtl' : 'ltr';
  document.documentElement.dir = dir;
  document.documentElement.lang = lng;
  // Mark the whole app as RTL/LTR so CSS can rely on html[dir].
  document.body.setAttribute('dir', dir);
};

// localStorage is missing in some contexts (tests without a DOM origin,
// privacy modes that throw on access) — the app must still boot in English.
const readStoredLang = () => {
  try {
    if (typeof localStorage !== 'undefined') return localStorage.getItem('ovmanager-lang');
  } catch { /* blocked storage: fall back to English */ }
  return null;
};
const writeStoredLang = (lng) => {
  try {
    if (typeof localStorage !== 'undefined') localStorage.setItem('ovmanager-lang', lng);
  } catch { /* preference only: a failed write must not break the switch */ }
};

const stored = readStoredLang() || 'en';
// Start on a language that is definitely bundled. A stored lazy locale boots
// in English and swaps the instant its bundle lands, so first paint is never
// blocked on a JSON fetch.
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

/** Safe to call repeatedly: in-flight loads are de-duplicated. */
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
            // Stay on the current language: switching to a missing bundle
            // would leave every key blank.
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
  writeStoredLang(lng);
}

// Deferred so restoring the stored language never competes with the first
// paint or the initial data requests.
if (stored !== initial) {
  const idle = window.requestIdleCallback || ((fn) => setTimeout(fn, 1));
  idle(() => loadLanguage(stored));
}

// Applied at startup, not from DashboardLayout: the login page renders outside
// it and used to come up with the wrong direction.
applyDocumentDir(i18n.language);

i18n.on('languageChanged', applyDocumentDir);

export default i18n;
