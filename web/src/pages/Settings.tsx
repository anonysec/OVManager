// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

import { useEffect, useMemo, useState, useCallback } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useLive } from '../context/LiveContext';
import { useAuth } from '../context/AuthContext';
import apiClient from '../services/api';
import { setDisplayTimezone } from '../utils/displayTimezone';
import {
  FiServer, FiShield, FiArchive, FiSend, FiLink, FiUserPlus,
  FiClock, FiMonitor, FiBell, FiLock, FiSettings, FiActivity,
} from 'react-icons/fi';
import { Card, PageHeader, Tabs } from '../components/ui';
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
  { id: 'activity',   icon: FiActivity,  labelKey: 'activityCard',       label: 'My activity', descKey: 'activityDesc',          desc: 'Your latest actions on this panel.', Component: MyActivitySection, bare: true },
];

const KNOWN_IDS = new Set(SECTIONS.map((s) => s.id));

const Settings = () => {
  const { t } = useTranslation();
  const location = useLocation();
  const navigate = useNavigate();
  const { refreshTick } = useLive();
  const { userRole } = useAuth();
  const isOwner = userRole === 'owner';

  const [shared, setShared] = useState<{ data: any; loading: boolean; error: boolean }>({ data: null, loading: true, error: false });
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
  const sharedWithReload = useMemo(() => ({ ...shared, reload: reloadShared }), [shared, reloadShared]);

  useEffect(() => {
    if (isOwner) reloadShared();
    else setShared({ data: {}, loading: false, error: false });
  }, [reloadShared, refreshTick, isOwner]);

  const activeSections = useMemo(
    () => (isOwner ? SECTIONS : SECTIONS.filter((s) => s.id === 'alerts' || s.id === 'appearance' || s.id === 'activity')),
    [isOwner],
  );

  // One section mounted at a time: the active tab is the URL hash, so links
  // like /settings#tls still deep-link. Sections hold only unsaved-edit state,
  // and every one of them saves explicitly — same contract as the reference
  // panels, where switching tabs drops unsaved input.
  const hashId = location.hash.replace(/^#/, '');
  const activeId = KNOWN_IDS.has(hashId) ? hashId : activeSections[0].id;
  const active = activeSections.find((s) => s.id === activeId) || activeSections[0];

  const openTab = (id: string) => navigate({ hash: `#${id}` }, { replace: true });

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
          <div className="sp-tabbar">
            <Tabs
              ariaLabel={t('settingsNavigation', 'Settings sections')}
              value={active.id}
              onChange={openTab}
              tabs={activeSections.map((s) => ({
                id: s.id,
                icon: <s.icon size={14} aria-hidden="true" />,
                label: t(s.labelKey, s.label),
              }))}
            />
          </div>

          <div className="sp-sections">
            <section
              key={active.id}
              className="sp-section"
              id={`sp-section-${active.id}`}
              tabIndex={-1}
              aria-labelledby={active.bare ? undefined : `sp-heading-${active.id}`}
            >
              {active.bare ? (
                <active.Component />
              ) : (
                <>
                  <SectionHeader
                    headingId={`sp-heading-${active.id}`}
                    icon={active.icon}
                    label={t(active.labelKey, active.label)}
                    description={t(active.descKey, active.desc)}
                  />
                  <active.Component {...(active.shared ? { shared: sharedWithReload } : {})} />
                </>
              )}
            </section>
          </div>
        </>
      )}
    </div>
  );
};

export default Settings;
