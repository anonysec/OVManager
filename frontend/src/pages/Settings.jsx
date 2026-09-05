// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

/**
 * Settings — single friendly page. Every section is always visible (no
 * Simple/Advanced split): defaults → bot → display → appearance → alerts →
 * general → system → security → backup → activity. The page was a "user
 * friendly" wish-list item (2026-09): fewer clicks to reach any control, the
 * most-touched settings sit at the top.
 *
 * Sections live in ./settings/ (one file each, split from the 1157-line
 * original with no logic changes). This file only owns the registry,
 * jump-nav and deep-link scrolling.
 *
 * The page also responds to deep links: arriving at `/settings#defaults`
 * scrolls the matching <section> into view. Previously the hash was ignored
 * and the page reset to the top.
 */
import { useEffect, useMemo, useState, useCallback } from 'react';
import { useLocation, Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useLive } from '../context/LiveContext';
import apiClient from '../services/api';
import {
  FiServer, FiShield, FiArchive, FiSend, FiActivity,
  FiLink, FiUserPlus, FiClock, FiMonitor, FiBell,
} from 'react-icons/fi';
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
import ActivitySection from './settings/ActivitySection';
import './Settings.css';

const SECTIONS = [
  { id: 'defaults',   icon: FiUserPlus,  labelKey: 'settingsDefaults',   label: 'Defaults',   descKey: 'settingsDefaultsDesc',   desc: 'New user defaults used by the Telegram bot', Component: DefaultsSection, simple: true },
  { id: 'bot',        icon: FiSend,      labelKey: 'settingsBot',        label: 'Bot',        descKey: 'settingsBotDesc',        desc: 'Telegram bot token, enable state and owner ID', Component: BotSection, simple: true },
  { id: 'display',    icon: FiClock,     labelKey: 'settingsDisplay',    label: 'Display',    descKey: 'settingsDisplayDesc',    desc: 'Timezone used for all date and time displays', Component: DisplaySection, simple: true },
  { id: 'appearance', icon: FiMonitor,   labelKey: 'settingsAppearance', label: 'Appearance', descKey: 'settingsAppearanceDesc', desc: 'Theme and interface language', Component: AppearanceSection, simple: true },
  { id: 'alerts',     icon: FiBell,      labelKey: 'settingsAlerts',     label: 'Alerts',     descKey: 'settingsAlertsDesc',     desc: 'Which alerts to show and how often to refresh', Component: AlertsSection, simple: true },
  { id: 'general',    icon: FiLink,      labelKey: 'settingsGeneral',    label: 'General',    descKey: 'settingsGeneralDesc',    desc: 'Panel URL path and subscription link prefix', Component: GeneralSection, simple: false },
  { id: 'system',     icon: FiServer,    labelKey: 'settingsSystem',     label: 'System',     descKey: 'settingsSystemDesc',     desc: 'Server info and maintenance actions', Component: SystemSection, simple: false },
  { id: 'security',   icon: FiShield,    labelKey: 'settingsSecurity',   label: 'Security',   descKey: 'settingsSecurityDesc',   desc: 'Authentication errors and session signals', Component: SecuritySection, simple: false },
  { id: 'backup',     icon: FiArchive,   labelKey: 'settingsBackup',     label: 'Backup',     descKey: 'settingsBackupDesc',     desc: 'Create, download and restore the database', Component: BackupSection, simple: false },
  { id: 'activity',   icon: FiActivity,  labelKey: 'settingsActivity',   label: 'Activity',   descKey: 'settingsActivityDesc',   desc: 'Recent administrator actions', Component: ActivitySection, simple: false },
];

const Settings = () => {
  const { t } = useTranslation();
  const location = useLocation();
  const { refreshTick } = useLive();

  // Single shared load of /server/settings for the sections that need it
  // (Defaults/Bot/Display/General). Previously each one fetched it on mount
  // and on every live tick — same data, N requests. Saves live on the wire;
  // each section keeps its own skeleton/error/retry visuals.
  const [shared, setShared] = useState({ data: null, loading: true, error: false });
  const reloadShared = useCallback(async () => {
    try {
      setShared((s) => ({ ...s, loading: true, error: false }));
      const res = await apiClient.get('/server/settings');
      setShared({ data: res.data?.data || {}, loading: false, error: false });
    } catch { setShared((s) => ({ ...s, loading: false, error: true })); }
  }, []);

  useEffect(() => { reloadShared(); }, [reloadShared, refreshTick]);

  // All sections always visible — no Simple/Advanced split
  const visible = useMemo(() => SECTIONS, []);
  const activeHash = location.hash.replace(/^#/, '');

  // Deep-link scroll: when URL has #section-id, scroll that section into
  // view and move focus there so keyboard users land in the right place.
  useEffect(() => {
    const hash = location.hash.replace(/^#/, '');
    if (!hash) return;
    const el = document.getElementById(`sp-section-${hash}`);
    if (!el) return;
    const reduceMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    // Allow the page to paint first, then scroll.
    const id = setTimeout(() => {
      el.scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth', block: 'start' });
      el.focus({ preventScroll: true });
    }, 0);
    return () => clearTimeout(id);
  }, [location.hash]);

  return (
    <div className="sp-page">
      <nav className="sp-jumpnav" aria-label={t('settingsNavigation', 'Settings sections')}>
        {visible.map(s => (
          <Link
            key={s.id}
            to={`#${s.id}`}
            replace
            className="sp-jumpnav-link"
            aria-current={activeHash === s.id ? 'true' : undefined}
          >
            <s.icon size={14} aria-hidden="true" />
            <span>{t(s.labelKey, s.label)}</span>
          </Link>
        ))}
      </nav>

      {/* All sections */}
      <div className="sp-sections">
        {visible.map((sec) => {
          const Component = sec.Component;
          // Sections that read server settings share the single load above.
          const sharedProp = ['defaults', 'bot', 'display', 'general'].includes(sec.id) ? { shared } : {};
          return (
            <section key={sec.id} className="sp-section" id={`sp-section-${sec.id}`} tabIndex={-1} aria-labelledby={`sp-heading-${sec.id}`}>
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
      </div>
    </div>
  );
};

export default Settings;
