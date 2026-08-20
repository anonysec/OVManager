// Copyright (c) 2025 anonysec. All rights reserved.
// Proprietary and confidential. Unauthorized copying, distribution, or use is prohibited.

import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';

import enTranslation from './lang/en.json';
import faTranslation from './lang/fa.json';
import ruTranslation from './lang/ru.json';
import cnTranslation from './lang/cn.json';

const resources = {
  en: { translation: enTranslation },
  fa: { translation: faTranslation },
  ru: { translation: ruTranslation },
  cn: { translation: cnTranslation },
};

/** Apply the document direction + lang for the current i18n language. */
const applyDocumentDir = (lng) => {
  const dir = lng.startsWith('fa') ? 'rtl' : 'ltr';
  document.documentElement.dir = dir;
  document.documentElement.lang = lng;
  // Mark the whole app as RTL/LTR so CSS can rely on html[dir].
  document.body.setAttribute('dir', dir);
};

const initial = localStorage.getItem('ovmanager-lang') || 'en';

i18n
  .use(initReactI18next)
  .init({
    resources,
    lng: initial,
    fallbackLng: 'en',
    interpolation: { escapeValue: false },
  });

// Apply direction immediately at startup (login page included — it renders
// outside DashboardLayout, which previously was the only place that set dir).
applyDocumentDir(i18n.language);

// Keep dir in sync whenever the language changes anywhere in the app.
i18n.on('languageChanged', applyDocumentDir);

export default i18n;
