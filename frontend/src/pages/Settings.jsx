import { useState, useEffect, Suspense, lazy } from 'react';
import { FiInfo, FiActivity } from 'react-icons/fi';
import apiClient from '../services/api';
import { useLive } from '../context/LiveContext';
import './Settings.css';

const GeneralTab = lazy(() => import('./Settings/GeneralTab'));
const SystemTab = lazy(() => import('./Settings/SystemTab'));
const SecurityTab = lazy(() => import('./Settings/SecurityTab'));
const BackupTab = lazy(() => import('./Settings/BackupTab'));
const ActivityTab = lazy(() => import('./Settings/ActivityTab'));

const TABS = [
  { id: 'general', label: 'General' },
  { id: 'system', label: 'System' },
  { id: 'security', label: 'Security' },
  { id: 'backup', label: 'Backup' },
  { id: 'activity', label: 'Activity' },
];

const TabLoader = () => (
  <div style={{ padding: '40px', textAlign: 'center', color: 'var(--text-secondary)' }}>Loading...</div>
);

const Settings = () => {
  const [activeTab, setActiveTab] = useState('general');
  const [panelVersion, setPanelVersion] = useState('');

  const loadSettings = async () => {
    try {
      const res = await apiClient.get('/server/settings');
      const s = res.data?.data || {};
      setPanelVersion(s.panel_version || '');
    } catch { /* noop */ }
  };

  useEffect(() => { loadSettings(); }, []);

  const { refreshTick } = useLive();
  useEffect(() => { loadSettings(); }, [refreshTick]);

  return (
    <div className="view">
      <div className="page-header">
        <div>
          <h2>Settings</h2>
          <span className="header-badge"><FiInfo size={14} /> {panelVersion ? `v${panelVersion}` : 'OVManager'}</span>
        </div>
        <div className="page-actions">
          <span className="header-badge"><FiActivity size={14} /> Live</span>
        </div>
      </div>

      <div className="settings-tabs">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            className={`seg-tab${activeTab === tab.id ? ' active' : ''}`}
            onClick={() => setActiveTab(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <Suspense fallback={<TabLoader />}>
        {activeTab === 'general' && <GeneralTab />}
        {activeTab === 'system' && <SystemTab />}
        {activeTab === 'security' && <SecurityTab />}
        {activeTab === 'backup' && <BackupTab />}
        {activeTab === 'activity' && <ActivityTab />}
      </Suspense>
    </div>
  );
};

export default Settings;
