// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';

import enTranslation from './lang/en.json';

const LAZY_LOCALES: Record<string, () => Promise<{ default: Record<string, unknown> }>> = {
  fa: () => import('./lang/fa.json'),
  ru: () => import('./lang/ru.json'),
  cn: () => import('./lang/cn.json'),
};

export const SUPPORTED_LANGS = ['fa', 'en', 'ru', 'cn'];

export const LANG_LABELS: Record<string, string> = { fa: 'فارسی', en: 'English', ru: 'Русский', cn: '中文' };

// ponytail: Persian-only RTL; add ar/he when second RTL locale lands
export const isRTL = (lng: string) => String(lng).startsWith('fa');

const applyDocumentDir = (lng: string) => {
  const dir = isRTL(lng) ? 'rtl' : 'ltr';
  document.documentElement.dir = dir;
  document.documentElement.lang = lng;
  document.body.setAttribute('dir', dir);
};

const readStoredLang = (): string | null => {
  try {
    if (typeof localStorage !== 'undefined') return localStorage.getItem('ovmanager-lang');
  } catch { /* blocked storage: fall back to English */ }
  return null;
};
const writeStoredLang = (lng: string) => {
  try {
    if (typeof localStorage !== 'undefined') localStorage.setItem('ovmanager-lang', lng);
  } catch { /* preference only: a failed write must not break the switch */ }
};

const stored = readStoredLang() || 'en';
const initial = SUPPORTED_LANGS.includes(stored) && !(stored in LAZY_LOCALES) ? stored : 'en';

i18n
  .use(initReactI18next)
  .init({
    resources: { en: { translation: enTranslation } },
    lng: initial,
    fallbackLng: 'en',
    interpolation: { escapeValue: false },
    partialBundledLanguages: true,
  });

const loading = new Map<string, Promise<void>>();

/** Safe to call repeatedly: in-flight loads are de-duplicated. */
let wanted = 0;

export async function loadLanguage(lng: string): Promise<void> {
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

if (stored in LAZY_LOCALES) {
  const idle = window.requestIdleCallback || ((fn: () => void) => setTimeout(fn, 1));
  idle(() => { void loadLanguage(stored); });
}

applyDocumentDir(i18n.language);

i18n.on('languageChanged', applyDocumentDir);

export default i18n;
