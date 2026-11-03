// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

import { useEffect, useMemo, useState, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useLive } from '../context/LiveContext';
import { useAuth } from '../context/AuthContext';

import apiClient from '../services/api';
import { setDisplayTimezone } from '../utils/displayTimezone';
import { FiSettings } from 'react-icons/fi';
import { PageHeader, Tabs } from '../components/ui';
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

/* Four tabs, ordered by how often a VPN admin reaches for them:
   1. Panel          — how the panel and subscriptions are reached, and what a
                       new user gets by default. The options you set once and
                       come back to when onboarding.
   2. Notifications  — Telegram bot and which alerts fire.
   3. Backup & system — backups, updates, maintenance, connection errors.
   4. Interface      — theme, language, your own activity (per-person, not panel). */
const SECTIONS = [
  { id: 'general',    tab: 'panel',         labelKey: 'settingsGeneral',    label: 'General',    descKey: 'settingsGeneralDesc',    desc: 'Panel URL path and subscription link prefix', Component: GeneralSection, shared: true },
  { id: 'defaults',   tab: 'panel',         labelKey: 'settingsDefaults',   label: 'Defaults',   descKey: 'settingsDefaultsDesc',   desc: 'New user defaults used by the Telegram bot', Component: DefaultsSection, shared: true },
  { id: 'display',    tab: 'panel',         labelKey: 'settingsDisplay',    label: 'Display',    descKey: 'settingsDisplayDesc',    desc: 'Timezone used for all date and time displays', Component: DisplaySection, shared: true },
  { id: 'telegram',   tab: 'notifications', labelKey: 'settingsTelegram',   label: 'Telegram',   descKey: 'settingsTelegramDesc',   desc: 'Daily usage summary, user events and test message', Component: TelegramSection, shared: true },
  { id: 'alerts',     tab: 'notifications', labelKey: 'settingsAlerts',     label: 'Alerts',     descKey: 'settingsAlertsDesc',     desc: 'Which alerts to show and how often to refresh', Component: AlertsSection },
  { id: 'backup',     tab: 'maintenance',   labelKey: 'settingsBackup',     label: 'Backup',     descKey: 'settingsBackupDesc',     desc: 'Create, download and restore the database', Component: BackupSection },
  { id: 'system',     tab: 'maintenance',   labelKey: 'settingsSystem',     label: 'System',     descKey: 'settingsSystemDesc',     desc: 'Server info and maintenance actions', Component: SystemSection },
  { id: 'security',   tab: 'maintenance',   labelKey: 'settingsSecurity',   label: 'Security',   descKey: 'settingsSecurityDesc',   desc: 'Authentication errors and session signals', Component: SecuritySection },
  { id: 'appearance', tab: 'interface',     labelKey: 'settingsAppearance', label: 'Appearance', descKey: 'settingsAppearanceDesc', desc: 'Theme and interface language', Component: AppearanceSection },
  { id: 'activity',   tab: 'interface',     labelKey: 'activityCard',       label: 'My activity', descKey: 'activityDesc',          desc: 'Your latest actions on this panel.', Component: MyActivitySection, bare: true },
];

const TABS = [
  { id: 'panel',         labelKey: 'settingsTabPanel',         label: 'Panel' },
  { id: 'notifications', labelKey: 'settingsTabNotifications', label: 'Notifications' },
  { id: 'maintenance',   labelKey: 'settingsTabMaintenance',   label: 'Backup & system' },
  { id: 'interface',     labelKey: 'settingsTabInterface',     label: 'Interface' },
] as const;

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

  // Operators without owner rights only have a couple of sections, so tabs
  // that would be empty for them are not shown at all.
  const visibleTabs = useMemo(
    () => TABS.filter((tab) => activeSections.some((s) => s.tab === tab.id)),
    [activeSections],
  );
  const [tabId, setTabId] = useState<string>(TABS[0].id);
  const currentTab = visibleTabs.find((tab) => tab.id === tabId) ?? visibleTabs[0];
  const sections = activeSections.filter((s) => s.tab === currentTab?.id);

  return (
    <div className="sp-page">
      <PageHeader
        title={t('navSettings', 'Settings')}
        icon={<FiSettings aria-hidden="true" />}
        subtitle={t('settingsSubtitle', 'All panel settings in one place.')}
      />

      <Tabs
        className="sp-tabs"
        ariaLabel={t('settingsNavigation', 'Settings sections')}
        value={currentTab?.id}
        onChange={setTabId}
        tabs={visibleTabs.map((tab) => ({ id: tab.id, label: t(tab.labelKey, tab.label) }))}
      />

      <div
        className="sp-content"
        role="tabpanel"
        aria-labelledby={currentTab ? `tab-${currentTab.id}` : undefined}
      >
        {sections.map((s) => (
          <section
            key={s.id}
            id={`sp-section-${s.id}`}
            className="sp-block"
            aria-labelledby={s.bare ? undefined : `sp-heading-${s.id}`}
            aria-label={s.bare ? t(s.labelKey, s.label) : undefined}
          >
            {s.bare ? (
              <s.Component />
            ) : (
              <>
                <SectionHeader
                  headingId={`sp-heading-${s.id}`}
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
  );
};

export default Settings;
