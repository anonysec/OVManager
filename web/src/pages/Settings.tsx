// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

import { useEffect, useMemo, useRef, useState, useCallback } from 'react';
import type { MouseEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { useLive } from '../context/LiveContext';
import { useAuth } from '../context/AuthContext';

import apiClient from '../services/api';
import { setDisplayTimezone } from '../utils/displayTimezone';
import {
  FiServer, FiShield, FiArchive, FiSend, FiLink, FiUserPlus,
  FiClock, FiMonitor, FiBell, FiSettings, FiActivity,
} from 'react-icons/fi';
import { PageHeader } from '../components/ui';
import { SectionHeader } from './settings/shared';
import DefaultsSection from './settings/DefaultsSection';
import DisplaySection from './settings/DisplaySection';
import AppearanceSection from './settings/AppearanceSection';
import AlertsSection from './settings/AlertsSection';
import GeneralSection from './settings/GeneralSection';
import SystemSection from './settings/SystemSection';
import SecuritySection from './settings/SecuritySection';
import BackupSection from './settings/BackupSection';
import TelegramSection from './settings/TelegramSection';
import MyActivitySection from './settings/MyActivitySection';
import './Settings.css';
import './SettingsPage.css';

const SECTIONS = [
  { id: 'general',    group: 'general', icon: FiLink,      labelKey: 'settingsGeneral',    label: 'General',    descKey: 'settingsGeneralDesc',    desc: 'Panel URL path and subscription link prefix', Component: GeneralSection, shared: true },
  { id: 'appearance', group: 'general', icon: FiMonitor,   labelKey: 'settingsAppearance', label: 'Appearance', descKey: 'settingsAppearanceDesc', desc: 'Theme and interface language', Component: AppearanceSection },
  { id: 'display',    group: 'general', icon: FiClock,     labelKey: 'settingsDisplay',    label: 'Display',    descKey: 'settingsDisplayDesc',    desc: 'Timezone used for all date and time displays', Component: DisplaySection, shared: true },
  { id: 'defaults',   group: 'general', icon: FiUserPlus,  labelKey: 'settingsDefaults',   label: 'Defaults',   descKey: 'settingsDefaultsDesc',   desc: 'New user defaults used by the Telegram bot', Component: DefaultsSection, shared: true },
  { id: 'alerts',     group: 'operations', icon: FiBell,    labelKey: 'settingsAlerts',     label: 'Alerts',     descKey: 'settingsAlertsDesc',     desc: 'Which alerts to show and how often to refresh', Component: AlertsSection },
  { id: 'telegram',   group: 'operations', icon: FiSend,    labelKey: 'settingsTelegram',   label: 'Telegram',   descKey: 'settingsTelegramDesc',   desc: 'Daily usage summary, user events and test message', Component: TelegramSection, shared: true },
  { id: 'activity',   group: 'operations', icon: FiActivity, labelKey: 'activityCard',      label: 'My activity', descKey: 'activityDesc',          desc: 'Your latest actions on this panel.', Component: MyActivitySection, bare: true },
  { id: 'security',   group: 'system', icon: FiShield,     labelKey: 'settingsSecurity',   label: 'Security',   descKey: 'settingsSecurityDesc',   desc: 'Authentication errors and session signals', Component: SecuritySection },
  { id: 'backup',     group: 'system', icon: FiArchive,    labelKey: 'settingsBackup',     label: 'Backup',     descKey: 'settingsBackupDesc',     desc: 'Create, download and restore the database', Component: BackupSection },
  { id: 'system',     group: 'system', icon: FiServer,     labelKey: 'settingsSystem',     label: 'System',     descKey: 'settingsSystemDesc',     desc: 'Server info and maintenance actions', Component: SystemSection },
];

const GROUPS = [
  { id: 'general',    labelKey: 'settingsGroupGeneral',    label: 'General' },
  { id: 'operations', labelKey: 'settingsGroupOperations', label: 'Operations' },
  { id: 'system',     labelKey: 'settingsGroupSystem',     label: 'System' },
] as const;

const sectionDomId = (id: string) => `sp-section-${id}`;

/** Which section is currently under the reading line. Drives the nav highlight. */
const useActiveSection = (ids: string[]) => {
  const [active, setActive] = useState<string>(ids[0] ?? '');
  // After a nav click the page scrolls past every section in between; without
  // this the highlight would flicker through each of them on the way.
  const pausedUntil = useRef(0);
  const key = ids.join('|');

  useEffect(() => {
    setActive((cur) => (ids.includes(cur) ? cur : ids[0] ?? ''));
    // jsdom and very old browsers have no IntersectionObserver; the nav then
    // simply keeps its first/last-clicked item highlighted.
    if (typeof IntersectionObserver === 'undefined') return;
    const visible = new Set<string>();
    const observer = new IntersectionObserver(
      (entries) => {
        if (performance.now() < pausedUntil.current) return;
        for (const e of entries) {
          const id = e.target.id.replace(/^sp-section-/, '');
          if (e.isIntersecting) visible.add(id); else visible.delete(id);
        }
        const first = ids.find((id) => visible.has(id));
        if (first) setActive(first);
      },
      // A thin band near the top of the viewport: the section crossing it is
      // the one being read.
      { rootMargin: '-15% 0px -70% 0px' },
    );
    for (const id of ids) {
      const el = document.getElementById(sectionDomId(id));
      if (el) observer.observe(el);
    }
    return () => observer.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const select = useCallback((id: string) => {
    pausedUntil.current = performance.now() + 900;
    setActive(id);
  }, []);

  return [active, select] as const;
};

const Settings = () => {
  const { t } = useTranslation();
  const { refreshTick } = useLive();
  const { userRole } = useAuth();
  const isOwner = userRole === 'owner';
  const [shared, setShared] = useState<{ data: any; loading: boolean; error: boolean }>({ data: null, loading: true, error: false });
  const [editing, setEditing] = useState(false);
  const reloadShared = useCallback(async () => {
    try {
      setShared((s) => ({ ...s, loading: s.data == null, error: false }));
      const res = await apiClient.get('/settings');
      setShared((s) => ({ ...s, data: res.data?.data || {}, loading: false, error: false }));
      if (res.data?.data?.timezone) setDisplayTimezone(res.data.data.timezone);
    } catch {
      setShared((s) => ({ ...s, loading: false, error: true }));
    }
  }, []);
  const sharedWithReload = useMemo(() => ({ ...shared, reload: reloadShared }), [shared, reloadShared]);

  useEffect(() => {
    if (isOwner) {
      if (editing) { setShared((s) => ({ ...s, loading: false })); return; }
      reloadShared();
    } else setShared({ data: {}, loading: false, error: false });
  }, [reloadShared, refreshTick, isOwner, editing]);

  const activeSections = useMemo(
    () => (isOwner ? SECTIONS : SECTIONS.filter((s) => s.id === 'alerts' || s.id === 'appearance' || s.id === 'activity')),
    [isOwner],
  );

  const [activeId, setActiveId] = useActiveSection(activeSections.map((s) => s.id));

  const jumpTo = (e: MouseEvent<HTMLAnchorElement>, id: string) => {
    e.preventDefault();
    const el = document.getElementById(sectionDomId(id));
    if (!el) return;
    const reduceMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    el.scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth', block: 'start' });
    // Move focus with the scroll so keyboard and screen-reader users land in
    // the section they chose, not back on the nav link.
    el.focus({ preventScroll: true });
    setActiveId(id);
  };

  return (
    <div className="sp-page">
      <PageHeader
        title={t('navSettings', 'Settings')}
        icon={<FiSettings aria-hidden="true" />}
        subtitle={t('settingsSubtitle', 'All panel settings in one place.')}
      />

      <div className="sp-layout">
        <nav className="sp-nav" aria-label={t('settingsNavigation', 'Settings sections')}>
          {GROUPS.map((group) => {
            const items = activeSections.filter((s) => s.group === group.id);
            if (items.length === 0) return null;
            return (
              <div key={group.id} className="sp-nav-group">
                <p className="sp-nav-group-title">{t(group.labelKey, group.label)}</p>
                <ul className="sp-nav-list">
                  {items.map((s) => {
                    const Icon = s.icon;
                    return (
                      <li key={s.id}>
                        <a
                          href={`#${sectionDomId(s.id)}`}
                          className="sp-nav-link"
                          aria-current={activeId === s.id ? 'location' : undefined}
                          onClick={(e) => jumpTo(e, s.id)}
                        >
                          <Icon aria-hidden="true" />
                          <span>{t(s.labelKey, s.label)}</span>
                        </a>
                      </li>
                    );
                  })}
                </ul>
              </div>
            );
          })}
        </nav>

        <div className="sp-content">
          {GROUPS.flatMap((group) => activeSections.filter((s) => s.group === group.id)).map((s) => (
            <section
              key={s.id}
              id={sectionDomId(s.id)}
              className="sp-section sp-block"
              tabIndex={-1}
              aria-labelledby={s.bare ? undefined : `sp-heading-${s.id}`}
              aria-label={s.bare ? t(s.labelKey, s.label) : undefined}
            >
              {s.bare ? (
                <s.Component />
              ) : (
                <>
                  <SectionHeader
                    headingId={`sp-heading-${s.id}`}
                    icon={s.icon}
                    label={t(s.labelKey, s.label)}
                    description={t(s.descKey, s.desc)}
                  />
                  <s.Component {...(s.shared ? { shared: sharedWithReload, onEditingChange: setEditing } : {})} />
                </>
              )}
            </section>
          ))}
        </div>
      </div>
    </div>
  );
};

export default Settings;
