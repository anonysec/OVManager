// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

import { useEffect, useMemo, useState, useCallback } from 'react';
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
  { id: 'general',    icon: FiLink,      labelKey: 'settingsGeneral',    label: 'General',    descKey: 'settingsGeneralDesc',    desc: 'Panel URL path and subscription link prefix', Component: GeneralSection, shared: true },
  { id: 'appearance', icon: FiMonitor,   labelKey: 'settingsAppearance', label: 'Appearance', descKey: 'settingsAppearanceDesc', desc: 'Theme and interface language', Component: AppearanceSection },
  { id: 'display',    icon: FiClock,     labelKey: 'settingsDisplay',    label: 'Display',    descKey: 'settingsDisplayDesc',    desc: 'Timezone used for all date and time displays', Component: DisplaySection, shared: true },
  { id: 'defaults',   icon: FiUserPlus,  labelKey: 'settingsDefaults',   label: 'Defaults',   descKey: 'settingsDefaultsDesc',   desc: 'New user defaults used by the Telegram bot', Component: DefaultsSection, shared: true },
  { id: 'alerts',     icon: FiBell,      labelKey: 'settingsAlerts',     label: 'Alerts',     descKey: 'settingsAlertsDesc',     desc: 'Which alerts to show and how often to refresh', Component: AlertsSection },
  { id: 'telegram',   icon: FiSend,      labelKey: 'settingsTelegram',   label: 'Telegram',   descKey: 'settingsTelegramDesc',   desc: 'Daily usage summary, user events and test message', Component: TelegramSection, shared: true },
  { id: 'security',   icon: FiShield,    labelKey: 'settingsSecurity',   label: 'Security',   descKey: 'settingsSecurityDesc',   desc: 'Authentication errors and session signals', Component: SecuritySection },
  { id: 'backup',     icon: FiArchive,   labelKey: 'settingsBackup',     label: 'Backup',     descKey: 'settingsBackupDesc',     desc: 'Create, download and restore the database', Component: BackupSection },
  { id: 'system',     icon: FiServer,    labelKey: 'settingsSystem',     label: 'System',     descKey: 'settingsSystemDesc',     desc: 'Server info and maintenance actions', Component: SystemSection },
  { id: 'activity',   icon: FiActivity,  labelKey: 'activityCard',       label: 'My activity', descKey: 'activityDesc',          desc: 'Your latest actions on this panel.', Component: MyActivitySection, bare: true },
];

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

  return (
    <div className="sp-page">
      <PageHeader
        title={t('navSettings', 'Settings')}
        icon={<FiSettings aria-hidden="true" />}
        subtitle={t('settingsSubtitle', 'All panel settings in one place.')}
      />

      <div className="bento-grid" role="region" aria-label={t('settingsNavigation', 'Settings sections')}>
          {activeSections.map((s) => (
            <section
              key={s.id}
              className={`bento-tile bento-tile--${s.id}${s.bare ? ' bento-tile--bare' : ''}`}
              id={`sp-section-${s.id}`}
              aria-labelledby={s.bare ? undefined : `sp-heading-${s.id}`}
              aria-label={t(s.labelKey, s.label)}
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
  );
};

export default Settings;
