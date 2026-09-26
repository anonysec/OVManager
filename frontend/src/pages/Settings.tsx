// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

/**
 * Settings — one page, every section in a single flow.
 *
 * Sections live in ./settings/ (one file each) and are rendered unchanged.
 * Owner gating is unchanged: normal admins only see the local-only sections
 * (Appearance, Alerts); everything server-backed stays owner-only.
 *
 * Deep links (`/settings#backup`) still work: the hash scrolls the section
 * into view.
 */
import { useEffect, useMemo, useState, useCallback } from 'react';
import { useLocation, Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useLive } from '../context/LiveContext';
import { useAuth } from '../context/AuthContext';
import apiClient from '../services/api';
import { setDisplayTimezone } from '../utils/displayTimezone';
import {
  FiServer, FiShield, FiArchive, FiSend, FiLink, FiUserPlus,
  FiClock, FiMonitor, FiBell, FiLock, FiSettings,
} from 'react-icons/fi';
import { Card, PageHeader } from '../components/ui';
import { SectionHeader } from './settings/shared';
import DefaultsSection from './settings/DefaultsSection';
import BotSection from './settings/BotSection';
import DisplaySection from './settings/DisplaySection';
import AppearanceSection from './settings/AppearanceSection';
import AlertsSection from './settings/AlertsSection';
import GeneralSection from './settings/GeneralSection';
import SystemSection from './settings/SystemSection';
import SecuritySection from './settings/SecuritySection';
import BackupSection from './settings/BackupSection';
import TlsSection from './settings/TlsSection';
import MyActivitySection from './settings/MyActivitySection';
import './Settings.css';
import './SettingsPage.css';

// Order is the render order.
const SECTIONS = [
  { id: 'general',    icon: FiLink,      labelKey: 'settingsGeneral',    label: 'General',    descKey: 'settingsGeneralDesc',    desc: 'Panel URL path and subscription link prefix', Component: GeneralSection, shared: true },
  { id: 'appearance', icon: FiMonitor,   labelKey: 'settingsAppearance', label: 'Appearance', descKey: 'settingsAppearanceDesc', desc: 'Theme and interface language', Component: AppearanceSection },
  { id: 'defaults',   icon: FiUserPlus,  labelKey: 'settingsDefaults',   label: 'Defaults',   descKey: 'settingsDefaultsDesc',   desc: 'New user defaults used by the Telegram bot', Component: DefaultsSection, shared: true },
  { id: 'alerts',     icon: FiBell,      labelKey: 'settingsAlerts',     label: 'Alerts',     descKey: 'settingsAlertsDesc',     desc: 'Which alerts to show and how often to refresh', Component: AlertsSection },
  { id: 'bot',        icon: FiSend,      labelKey: 'settingsBot',        label: 'Bot',        descKey: 'settingsBotDesc',        desc: 'Telegram bot token, enable state and owner ID', Component: BotSection, shared: true },
  { id: 'tls',        icon: FiLock,      labelKey: 'settingsTls',        label: 'TLS',        descKey: 'settingsTlsDesc',        desc: 'Certificate status for the panel itself', Component: TlsSection },
  { id: 'backup',     icon: FiArchive,   labelKey: 'settingsBackup',     label: 'Backup',     descKey: 'settingsBackupDesc',     desc: 'Create, download and restore the database', Component: BackupSection },
  { id: 'security',   icon: FiShield,    labelKey: 'settingsSecurity',   label: 'Security',   descKey: 'settingsSecurityDesc',   desc: 'Authentication errors and session signals', Component: SecuritySection },
  { id: 'display',    icon: FiClock,     labelKey: 'settingsDisplay',    label: 'Display',    descKey: 'settingsDisplayDesc',    desc: 'Timezone used for all date and time displays', Component: DisplaySection, shared: true },
  { id: 'system',     icon: FiServer,    labelKey: 'settingsSystem',     label: 'System',     descKey: 'settingsSystemDesc',     desc: 'Server info and maintenance actions', Component: SystemSection },
];

const KNOWN_IDS = new Set(SECTIONS.map((s) => s.id));

const Settings = () => {
  const { t } = useTranslation();
  const location = useLocation();
  const { refreshTick } = useLive();
  // Admins only get the local-only sections (appearance, alerts) — every
  // server-backed section PUTs to owner-only endpoints.
  const { userRole } = useAuth();
  const isOwner = userRole === 'owner';

  // Single shared load of /server/settings for the sections that need it
  // (General/Defaults/Bot/Display). Saves live requests; each section keeps
  // its own skeleton/error/retry visuals.
  const [shared, setShared] = useState({ data: null, loading: true, error: false });
  const reloadShared = useCallback(async () => {
    try {
      setShared((s) => ({ ...s, loading: true, error: false }));
      const res = await apiClient.get('/server/settings');
      setShared((s) => ({ ...s, data: res.data?.data || {}, loading: false, error: false }));
      if (res.data?.data?.timezone) setDisplayTimezone(res.data.data.timezone);
    } catch {
      setShared((s) => ({ ...s, loading: false, error: true }));
    }
  }, []);
  // Stable object identity so sections only re-sync when the data changes.
  const sharedWithReload = useMemo(() => ({ ...shared, reload: reloadShared }), [shared, reloadShared]);

  useEffect(() => {
    if (isOwner) reloadShared();
    else setShared({ data: {}, loading: false, error: false });
  }, [reloadShared, refreshTick, isOwner]);

  // Owners see all sections; admins only the local-only ones (no server data).
  const activeSections = useMemo(
    () => (isOwner ? SECTIONS : SECTIONS.filter((s) => s.id === 'alerts' || s.id === 'appearance')),
    [isOwner],
  );

  // Deep links (`#backup`) scroll the section into view.
  useEffect(() => {
    const hash = location.hash.replace(/^#/, '');
    if (!hash || !KNOWN_IDS.has(hash)) return;
    const el = document.getElementById(`sp-section-${hash}`);
    if (!el) return;
    const reduceMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    const id = setTimeout(() => {
      el.scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth', block: 'start' });
      el.focus({ preventScroll: true });
    }, 0);
    return () => clearTimeout(id);
  }, [location.hash]);

  return (
    <div className="sp-page">
      <PageHeader
        title={t('navSettings', 'Settings')}
        icon={<FiSettings aria-hidden="true" />}
        subtitle={t('settingsSubtitle', 'All panel settings in one place.')}
      />

      {activeSections.length === 0 ? (
        <Card className="sp-owner-note" tone="warning">
          <div className="sp-owner-note-inner">
            <FiLock aria-hidden="true" />
            <div>
              <strong>{t('settingsOwnerOnly', 'Owner only')}</strong>
              <p>{t('settingsOwnerOnlyBody', 'These settings can only be changed by the panel owner.')}</p>
            </div>
          </div>
        </Card>
      ) : (
        <>
          <nav className="sp-jumpnav" aria-label={t('settingsNavigation', 'Settings sections')}>
            {activeSections.map((s) => (
              <Link key={s.id} to={`#${s.id}`} replace className="sp-jumpnav-link">
                <s.icon size={14} aria-hidden="true" />
                <span>{t(s.labelKey, s.label)}</span>
              </Link>
            ))}
          </nav>

          <div className="sp-sections">
            {activeSections.map((sec) => {
              const Component = sec.Component;
              const sharedProp = sec.shared ? { shared: sharedWithReload } : {};
              return (
                <section
                  key={sec.id}
                  className="sp-section"
                  id={`sp-section-${sec.id}`}
                  tabIndex={-1}
                  aria-labelledby={`sp-heading-${sec.id}`}
                >
                  <SectionHeader
                    headingId={`sp-heading-${sec.id}`}
                    icon={sec.icon}
                    label={t(sec.labelKey, sec.label)}
                    description={t(sec.descKey, sec.desc)}
                  />
                  <Component {...sharedProp} />
                </section>
              );
            })}
            <section className="sp-section" id="sp-section-activity">
              <MyActivitySection />
            </section>
          </div>
        </>
      )}
    </div>
  );
};

export default Settings;
