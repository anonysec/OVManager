// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';

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
  document.body.setAttribute('dir', dir);
};

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
const initial = stored in LAZY_LOCALES ? 'en' : stored;

i18n
  .use(initReactI18next)
  .init({
    resources: { en: { translation: enTranslation } },
    lng: initial,
    fallbackLng: 'en',
    interpolation: { escapeValue: false },
    partialBundledLanguages: true,
  });

const loading = new Map();

/** Safe to call repeatedly: in-flight loads are de-duplicated. */
let wanted = 0;

export async function loadLanguage(lng) {
  if (!lng || lng === i18n.language) return;
  const token = ++wanted;

  if (LAZY_LOCALES[lng] && !i18n.hasResourceBundle(lng, 'translation')) {
    if (!loading.has(lng)) {
      loading.set(
        lng,
        LAZY_LOCALES[lng]()
          .then((mod) => {
            i18n.addResourceBundle(lng, 'translation', mod.default, true, true);
          })
          .catch((err) => {
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

  if (token !== wanted) return; // a newer pick superseded this one
  await i18n.changeLanguage(lng);
  if (token !== wanted) return;
  writeStoredLang(lng);
}

if (stored !== initial) {
  const idle = window.requestIdleCallback || ((fn) => setTimeout(fn, 1));
  idle(() => loadLanguage(stored));
}

applyDocumentDir(i18n.language);

i18n.on('languageChanged', applyDocumentDir);

export default i18n;
