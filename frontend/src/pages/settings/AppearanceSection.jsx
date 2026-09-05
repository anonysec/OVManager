// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useTheme } from '../../context/ThemeContext';
import { getUiPref, setUiPref, getUiStyle, setUiStyle } from '../../utils/uiPrefs';
import { FiSun, FiMoon, FiMonitor, FiGlobe, FiLayout, FiGrid, FiMinus } from 'react-icons/fi';
import { Card } from './shared';

/* ═══════════════════════════════════════════════════════
   APPEARANCE — theme + language (front-end only)
═══════════════════════════════════════════════════════ */
const AppearanceSection = () => {
  const { t, i18n } = useTranslation();
  const { theme, setTheme } = useTheme();
  const [lang, setLang] = useState(i18n.language || 'en');

  const THEMES = [
    { id: 'light', label: t('lightTheme', 'Light'), icon: FiSun },
    { id: 'dark', label: t('darkTheme', 'Dark'), icon: FiMoon },
    { id: 'system', label: t('systemTheme', 'System'), icon: FiMonitor },
  ];

  const LANGS = [
    { id: 'fa', label: 'فارسی' },
    { id: 'en', label: 'English' },
    { id: 'ru', label: 'Русский' },
    { id: 'cn', label: '中文' },
  ];

  const changeLanguage = (id) => {
    i18n.changeLanguage(id);
    localStorage.setItem('ovmanager-lang', id);
    setLang(id);
    // No document.documentElement.dir write here: DashboardLayout owns that in
    // an effect keyed on i18n.language, and it sets html[lang] and body[dir]
    // too, which this duplicate did not. Mutating the DOM from a function
    // created during render is what the rule objects to.
  };

  const ACCENTS = [
    { hex: '#ff6a1a', name: 'Orange' },
    { hex: '#2fd276', name: 'Emerald' },
    { hex: '#6366f1', name: 'Indigo' },
    { hex: '#ec4899', name: 'Rose' },
    { hex: '#19d3e9', name: 'Cyan' },
    { hex: '#eab308', name: 'Amber' },
  ];
  const [accent, setAccent] = useState(() => getUiPref('accent', ''));
  const chooseAccent = (hex) => {
    setAccent(hex);
    setUiPref('accent', hex);
    document.documentElement.style.setProperty('--accent-color', hex);
  };

  const [uiStyle, setUiStyleState] = useState(() => getUiStyle());
  const chooseUiStyle = (style) => {
    setUiStyle(style);
    setUiStyleState(style);
  };

  const [corner, setCorner] = useState(() => {
    try { return localStorage.getItem('ovmanager-sidebar-corner') || 'inline-start'; }
    catch { return 'inline-start'; }
  });
  const chooseCorner = (id) => {
    try { localStorage.setItem('ovmanager-sidebar-corner', id); } catch { /* private mode */ }
    setCorner(id);
    // Applied live by the sidebar — no reload, no lost form state.
    window.dispatchEvent(new CustomEvent('sidebar-corner-change', { detail: { corner: id } }));
  };

  return (
    <div className="sp-cards">
      <Card title={t('accentCard', 'Accent color')} icon={FiSun}>
        <div className="accent-picker" role="group" aria-label={t('accentCard', 'Accent color')}>
          <button
            type="button"
            className={`accent-swatch${accent === '' ? ' active' : ''}`}
            style={{ background: 'var(--accent-color)' }}
            onClick={() => chooseAccent('')}
            title={t('accentDefault', 'Default')}
            aria-label={t('accentDefault', 'Default')}
            aria-pressed={accent === ''}
          />
          {ACCENTS.map((a) => (
            <button
              key={a.hex}
              type="button"
              className={`accent-swatch${accent === a.hex ? ' active' : ''}`}
              style={{ background: a.hex }}
              onClick={() => chooseAccent(a.hex)}
              title={a.name}
              aria-label={a.name}
              aria-pressed={accent === a.hex}
            />
          ))}
        </div>
        <p className="sp-hint">{t('accentDesc', 'Changes the brand color across the panel. Saved per browser.')}</p>
      </Card>

      <Card title={t('themeCard', 'Theme')} icon={FiMonitor}>
        <div className="sp-theme-pills" role="group" aria-label={t('themeCard', 'Theme')}>
          {THEMES.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`sp-theme-pill${theme === item.id ? ' active' : ''}`}
              onClick={() => setTheme(item.id)}
              aria-pressed={theme === item.id}
            >
              <item.icon size={15} aria-hidden="true" />
              <span>{item.label}</span>
            </button>
          ))}
        </div>
        <p className="sp-hint">{t('themeDesc', 'System follows your operating system preference.')}</p>
      </Card>

      <Card title={t('styleCard', 'Panel style')} icon={FiLayout}>
        <div className="sp-theme-pills sp-pills-2" role="group" aria-label={t('styleCard', 'Panel style')}>
          <button
            type="button"
            className={`sp-theme-pill${uiStyle === 'normal' ? ' active' : ''}`}
            onClick={() => chooseUiStyle('normal')}
            aria-pressed={uiStyle === 'normal'}
          >
            <FiGrid size={15} aria-hidden="true" />
            <span>{t('styleNormal', 'Normal')}</span>
          </button>
          <button
            type="button"
            className={`sp-theme-pill${uiStyle === 'minimal' ? ' active' : ''}`}
            onClick={() => chooseUiStyle('minimal')}
            aria-pressed={uiStyle === 'minimal'}
          >
            <FiMinus size={15} aria-hidden="true" />
            <span>{t('styleMinimal', 'Minimal')}</span>
          </button>
        </div>
        <p className="sp-hint">{t('styleDesc', 'Normal uses rich cards and soft shadows; Minimal is flat with hairline borders. Saved per browser.')}</p>
      </Card>

      <Card title={t('sidebarCornerCard', 'Sidebar position')} icon={FiLayout}>
        <div className="sp-theme-pills sp-pills-5" role="group" aria-label={t('sidebarCornerCard', 'Sidebar position')}>
          {[
            { id: 'inline-start', label: t('sidebarEdge', 'Edge') },
            { id: 'top-left',     label: t('sidebarTopLeft',     'Top L') },
            { id: 'top-right',    label: t('sidebarTopRight',    'Top R') },
            { id: 'bottom-left',  label: t('sidebarBottomLeft',  'Bot L') },
            { id: 'bottom-right', label: t('sidebarBottomRight', 'Bot R') },
          ].map((c) => (
            <button
              key={c.id}
              type="button"
              className={`sp-theme-pill${corner === c.id ? ' active' : ''}`}
              onClick={() => chooseCorner(c.id)}
              aria-pressed={corner === c.id}
            >
              <span>{c.label}</span>
            </button>
          ))}
        </div>
        <p className="sp-hint">{t('sidebarCornerDesc', 'Where the sidebar anchors. "Edge" is the default full-height rail; the four corners dock to the top or bottom. Saved per browser.')}</p>
      </Card>

      <Card title={t('languageCard', 'Language')} icon={FiGlobe}>
        <div className="sp-lang-row" role="group" aria-label={t('languageCard', 'Language')}>
          {LANGS.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`sp-lang-btn${lang === item.id ? ' active' : ''}`}
              onClick={() => changeLanguage(item.id)}
              aria-pressed={lang === item.id}
            >
              {item.label}
            </button>
          ))}
        </div>
        <p className="sp-hint">{t('languageDesc', 'Interface language. Persian switches the panel to RTL.')}</p>
      </Card>
    </div>
  );
};

export default AppearanceSection;
