// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useTheme } from '../../context/ThemeContext';
import { getUiPref, setUiPref } from '../../utils/uiPrefs';
import { FiSun, FiMoon, FiMonitor, FiGlobe, FiDownload } from 'react-icons/fi';
import apiClient from '../../services/api';
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

  // ── Install app (PWA) ──────────────────────────────────────────────────
  // Chrome/Edge fire beforeinstallprompt when the app is installable; we
  // store the event and replay it from the button. Safari/iOS never fires it,
  // so the card simply stays hidden there.
  const [installEvent, setInstallEvent] = useState(null);
  const [installHint, setInstallHint] = useState(true);
  const [installed, setInstalled] = useState(
    () =>
      window.matchMedia?.('(display-mode: standalone)').matches === true ||
      window.navigator.standalone === true,
  );

  useEffect(() => {
    const onBeforeInstall = (e) => {
      e.preventDefault();
      setInstallEvent(e);
    };
    const onInstalled = () => {
      setInstalled(true);
      setInstallEvent(null);
    };
    window.addEventListener('beforeinstallprompt', onBeforeInstall);
    window.addEventListener('appinstalled', onInstalled);
    return () => {
      window.removeEventListener('beforeinstallprompt', onBeforeInstall);
      window.removeEventListener('appinstalled', onInstalled);
    };
  }, []);

  // Phones refuse to install over an untrusted certificate, so ask the panel
  // what it is serving and hide the hint when install cannot succeed.
  useEffect(() => {
    let cancelled = false;
    apiClient
      .get('/health/tls')
      .then((res) => {
        if (!cancelled) setInstallHint(res.data?.install_hint !== false);
      })
      .catch(() => {
        /* keep the hint; the browser prompt is still the authoritative check */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const install = async () => {
    if (!installEvent) return;
    installEvent.prompt();
    await installEvent.userChoice.catch(() => null);
    setInstallEvent(null);
  };

  const showInstallCard = installed || installEvent !== null || installHint === false;

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

      {showInstallCard && (
        <Card title={t('pwaInstallTitle', 'Install app')} icon={FiDownload}>
          {installed ? (
            <p className="sp-hint" style={{ margin: 0 }}>
              {t('pwaInstalled', 'Installed')}
            </p>
          ) : installHint === false ? (
            <p className="sp-hint" style={{ margin: 0 }}>
              {t('pwaCertRequired', "Install needs a trusted certificate — switch to Let's Encrypt, then reload.")}{' '}
              <Link to="/settings#tls">{t('pwaOpenTls', 'Open TLS settings')}</Link>
            </p>
          ) : (
            <>
              <button type="button" className="btn btn-primary btn-sm" onClick={install}>
                <FiDownload size={13} aria-hidden="true" />
                <span>{t('pwaInstallButton', 'Install app')}</span>
              </button>
              <p className="sp-hint">{t('pwaInstallDesc', 'Install OVManager on this device for a full-screen window.')}</p>
            </>
          )}
        </Card>
      )}
    </div>
  );
};

export default AppearanceSection;
