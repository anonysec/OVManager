import { useState, useEffect, Suspense, lazy, useCallback, useMemo } from 'react';
import { FiActivity, FiArchive, FiChevronRight, FiInfo, FiServer, FiSend, FiShield, FiSliders } from 'react-icons/fi';
import { useTranslation } from 'react-i18next';
import apiClient from '../services/api';
import { useLive } from '../context/LiveContext';
import PanelSkeleton from '../components/ui/PanelSkeleton';
import './Settings.css';

const GeneralTab = lazy(() => import('./Settings/GeneralTab'));
const SystemTab = lazy(() => import('./Settings/SystemTab'));
const SecurityTab = lazy(() => import('./Settings/SecurityTab'));
const BackupTab = lazy(() => import('./Settings/BackupTab'));
const ActivityTab = lazy(() => import('./Settings/ActivityTab'));
const BotTab = lazy(() => import('./Settings/BotTab'));

const getTabs = (t) => [
  { id: 'general', label: t('settingsGeneral', 'General'), description: t('settingsGeneralDesc', 'Panel URL and access defaults'), icon: FiSliders, group: t('settingsGroupCore', 'Core') },
  { id: 'system', label: t('settingsSystem', 'System'), description: t('settingsSystemDesc', 'Runtime health and maintenance'), icon: FiServer, group: t('settingsGroupCore', 'Core') },
  { id: 'security', label: t('settingsSecurity', 'Security'), description: t('settingsSecurityDesc', 'Authentication and session signals'), icon: FiShield, group: t('settingsGroupOperations', 'Operations') },
  { id: 'backup', label: t('settingsBackup', 'Backup'), description: t('settingsBackupDesc', 'Protect and restore panel data'), icon: FiArchive, group: t('settingsGroupOperations', 'Operations') },
  { id: 'bot', label: t('settingsBot', 'Bot'), description: t('settingsBotDesc', 'Telegram notifications and control'), icon: FiSend, group: t('settingsGroupIntegrations', 'Integrations') },
  { id: 'activity', label: t('settingsActivity', 'Activity'), description: t('settingsActivityDesc', 'Recent administrator actions'), icon: FiActivity, group: t('settingsGroupOperations', 'Operations') },
];

const getTabFromHash = (tabs) => {
  if (typeof window === 'undefined') return tabs[0].id;
  const hash = window.location.hash.slice(1);
  return tabs.some((tab) => tab.id === hash) ? hash : tabs[0].id;
};

const TabLoader = () => (
  <div className="settings-tab-loader">
    <PanelSkeleton lines={6} label="Loading settings" />
  </div>
);

const Settings = () => {
  const { t } = useTranslation();
  const { refreshTick } = useLive();
  const tabs = useMemo(() => getTabs(t), [t]);
  const [activeTab, setActiveTab] = useState(() => getTabFromHash(getTabs(t)));
  const [panelVersion, setPanelVersion] = useState('');

  const active = tabs.find((tab) => tab.id === activeTab) || tabs[0];
  const ActiveIcon = active.icon;

  const loadSettings = useCallback(async () => {
    try {
      const res = await apiClient.get('/server/settings');
      const s = res.data?.data || {};
      setPanelVersion(s.panel_version || '');
    } catch { /* individual settings tabs surface their own errors */ }
  }, []);

  useEffect(() => { loadSettings(); }, [loadSettings, refreshTick]);

  useEffect(() => {
    const onHashChange = () => setActiveTab(getTabFromHash(tabs));
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, [tabs]);

  const handleTabClick = useCallback((tabId) => {
    setActiveTab(tabId);
    if (typeof window !== 'undefined') window.location.hash = tabId;
  }, []);

  return (
    <div className="settings-page">
      <header className="settings-hero">
        <div className="settings-hero-copy">
          <span className="settings-eyebrow"><FiSliders aria-hidden="true" /> {t('settingsEyebrow', 'Control plane')}</span>
          <h1>{t('settingsTitle', 'Settings & Operations')}</h1>
          <p>{t('settingsSub', 'Manage theme, subscription links, maintenance, and system info.')}</p>
        </div>
        <div className="settings-hero-meta">
          <span className="settings-meta-chip"><span className="live-indicator" /> {t('liveSync', 'Live sync')}</span>
          <span className="settings-meta-chip"><FiInfo aria-hidden="true" /> {panelVersion ? `v${panelVersion}` : 'OVManager'}</span>
        </div>
      </header>

      <div className="settings-layout">
        <aside className="settings-nav" aria-label={t('settingsNavigation', 'Settings navigation')}>
          <div className="settings-nav-intro">
            <strong>{t('settingsNavigationTitle', 'Workspace settings')}</strong>
            <span>{t('settingsNavigationDesc', 'Choose a section to configure.')}</span>
          </div>
          <nav>
            {tabs.map((tab, index) => {
              const Icon = tab.icon;
              const showGroup = index === 0 || tabs[index - 1].group !== tab.group;
              return (
                <div key={tab.id}>
                  {showGroup && <div className="settings-nav-group">{tab.group}</div>}
                  <button
                    type="button"
                    className={`settings-nav-item${activeTab === tab.id ? ' active' : ''}`}
                    onClick={() => handleTabClick(tab.id)}
                    aria-current={activeTab === tab.id ? 'page' : undefined}
                  >
                    <span className="settings-nav-icon"><Icon aria-hidden="true" /></span>
                    <span className="settings-nav-item-copy"><strong>{tab.label}</strong><small>{tab.description}</small></span>
                    <FiChevronRight className="settings-nav-arrow" aria-hidden="true" />
                  </button>
                </div>
              );
            })}
          </nav>
        </aside>

        <section className="settings-content" aria-labelledby="settings-section-title">
          <div className="settings-content-header">
            <div className="settings-content-title">
              <span className="settings-content-icon"><ActiveIcon aria-hidden="true" /></span>
              <div>
                <h2 id="settings-section-title">{active.label}</h2>
                <p>{active.description}</p>
              </div>
            </div>
            <span className="settings-content-status"><span className="status-dot online" /> {t('settingsReady', 'Ready')}</span>
          </div>
          <Suspense fallback={<TabLoader />}>
            {activeTab === 'general' && <GeneralTab />}
            {activeTab === 'system' && <SystemTab />}
            {activeTab === 'security' && <SecurityTab />}
            {activeTab === 'backup' && <BackupTab />}
            {activeTab === 'bot' && <BotTab />}
            {activeTab === 'activity' && <ActivityTab />}
          </Suspense>
        </section>
      </div>
    </div>
  );
};

export default Settings;
