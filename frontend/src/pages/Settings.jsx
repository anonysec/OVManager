import { useState, useEffect, Suspense, lazy } from 'react';
import {
  FiActivity, FiAlertTriangle, FiBell, FiDatabase, FiDownload, FiGlobe, FiHardDrive,
  FiLayers, FiLink, FiLogOut, FiRefreshCw, FiShield, FiServer, FiUpload, FiZap,
  FiMoon, FiSun, FiSettings, FiCpu, FiClock, FiSave, FiCopy, FiArchive, FiBarChart2,
  FiTool, FiInfo, FiCheckCircle, FiMessageSquare, FiLock
} from 'react-icons/fi';
import { useTranslation } from 'react-i18next';
import apiClient from '../services/api';
import { useTheme } from '../context/ThemeContext';
import { useLive } from '../context/LiveContext';
import { validateSubscription, buildSubUrl as buildSubUrlHelper } from '../utils/settingsHelpers';
import { copyText } from '../utils/clipboard';
import { fmtDateTime, formatUptime } from '../utils/time';
import { formatBytes } from '../utils/format';
import { FiMessageSquare as MessageIcon } from 'react-icons/fi';
import './Settings.css';

const TIMEZONES = [
  'UTC', 'Asia/Tehran', 'Asia/Dubai', 'Asia/Kolkata', 'Asia/Shanghai', 'Asia/Tokyo',
  'Europe/Istanbul', 'Europe/Berlin', 'Europe/London', 'America/New_York', 'America/Los_Angeles', 'Australia/Sydney',
];

const TABS = [
  { id: 'general', label: 'General', icon: FiSettings },
  { id: 'system', label: 'System', icon: FiServer },
  { id: 'security', label: 'Security', icon: FiShield },
  { id: 'backup', label: 'Backup', icon: FiDatabase },
  { id: 'activity', label: 'Activity', icon: FiActivity },
];

// Lazy load tab components
const GeneralTab = lazy(() => import('./Settings/GeneralTab'));
const SystemTab = lazy(() => import('./Settings/SystemTab'));
const SecurityTab = lazy(() => import('./Settings/SecurityTab'));
const BackupTab = lazy(() => import('./Settings/BackupTab'));
const ActivityTab = lazy(() => import('./Settings/ActivityTab'));

const Settings = () => {
  const { t } = useTranslation();
  const { theme, setTheme } = useTheme();
  const [activeTab, setActiveTab] = useState('general');
  const [serverInfo, setServerInfo] = useState(null);
  const [security, setSecurity] = useState(null);
  const [notifications, setNotifications] = useState([]);
  const [activity, setActivity] = useState([]);
  const [metrics, setMetrics] = useState(null);
  const [loginHealth, setLoginHealth] = useState(null);
  const [backups, setBackups] = useState([]);
  const [busy, setBusy] = useState(false);
  const [panelVersion, setPanelVersion] = useState('');
  const [timezone, setTimezoneState] = useState(() => localStorage.getItem('ovTimezone') || 'UTC');
  const [tzSaving, setTzSaving] = useState(false);
  const [secHours, setSecHours] = useState(8);
  const [subPrefix, setSubPrefix] = useState('');
  const [subPath, setSubPath] = useState('');
  const [subSaved, setSubSaved] = useState(false);
  const [subError, setSubError] = useState('');
  const [restoreFile, setRestoreFile] = useState(null);
  const [restoreMsg, setRestoreMsg] = useState('');
  const [botToken, setBotToken] = useState('');
  const [botEnabled, setBotEnabled] = useState(false);
  const [ownerTg, setOwnerTg] = useState('');
  const [defaultDays, setDefaultDays] = useState(30);
  const [defaultTraffic, setDefaultTraffic] = useState(100);
  const [defaultUsers, setDefaultUsers] = useState(1);
  const [botSaved, setBotSaved] = useState(false);

  // Toast listener setup
  useEffect(() => {
    const handleToast = (e) => {
      const { message, type = 'success' } = e.detail;
      addToastToSystem(message, type);
    };
    window.addEventListener('addToast', handleToast);
    return () => window.removeEventListener('addToast', handleToast);
  }, []);

  const load = async () => {
    const [serverRes, secRes, activityRes, notifRes, healthRes, metricsRes, backupRes] = await Promise.all([
      apiClient.get('/server/info'),
      apiClient.get(`/security/summary?hours=${secHours}`),
      apiClient.get('/activity/?limit=25'),
      apiClient.get('/notifications/'),
      apiClient.get('/maintenance/login-health?hours=8'),
      apiClient.get('/metrics/history?hours=24'),
      apiClient.get('/maintenance/backup/list'),
    ]);
    setServerInfo(serverRes.data?.data || null);
    setSecurity(secRes.data?.data || null);
    setActivity(activityRes.data?.data || []);
    setNotifications(notifRes.data?.data || []);
    setLoginHealth(healthRes.data?.data || null);
    setMetrics(metricsRes.data?.data || null);
    setBackups(backupRes.data?.data || []);
  };

  const loadSettings = async () => {
    const res = await apiClient.get('/server/settings');
    const s = res.data?.data || {};
    setTimezoneState(s.timezone || 'UTC');
    localStorage.setItem('ovTimezone', s.timezone || 'UTC');
    setPanelVersion(s.panel_version || '');
    setSubPrefix(s.subscription_url_prefix || '');
    setSubPath(s.subscription_path || '');
    setBotToken(s.bot_token || '');
    setBotEnabled(!!s.bot_enabled);
    setOwnerTg(s.owner_telegram_id != null ? String(s.owner_telegram_id) : '');
    setDefaultDays(s.default_days || 30);
    setDefaultTraffic(s.default_traffic_gb || 100);
    setDefaultUsers(s.default_max_users || 1);
  };

  useEffect(() => { loadSettings(); load(); }, []);

  // Live auto-refresh
  const { refreshTick } = useLive();
  useEffect(() => { load().catch(() => {}); }, [refreshTick]);

  const saveTimezone = async (tz) => {
    setTimezoneState(tz);
    localStorage.setItem('ovTimezone', tz);
    setTzSaving(true);
    try { await apiClient.put('/server/settings/timezone', { timezone: tz }); } catch { /* noop */ } finally { setTzSaving(false); }
  };

  const saveSubscription = async () => {
    const err = validateSubscription(subPrefix, subPath, t);
    setSubError(err);
    if (err) return;
    setSubSaved(false);
    try {
      await apiClient.put('/server/settings/subscription', { subscription_url_prefix: subPrefix, subscription_path: subPath });
      setSubSaved(true);
      setTimeout(() => setSubSaved(false), 2500);
    } catch { /* noop */ }
  };

  const copyLink = async () => {
    try { await copyText(buildSubUrlHelper(subPrefix, subPath)); } catch { /* noop */ }
  };

  const saveBotConfig = async () => {
    setBotSaved(false);
    try {
      await apiClient.put('/server/settings/bot', {
        bot_token: botToken || null,
        bot_enabled: botEnabled,
        owner_telegram_id: ownerTg ? parseInt(ownerTg, 10) : null,
        default_days: defaultDays,
        default_traffic_gb: defaultTraffic,
        default_max_users: defaultUsers,
      });
      setBotSaved(true);
      setTimeout(() => setBotSaved(false), 2500);
    } catch (e) {
      console.error('saveBotConfig error:', e?.response?.data || e);
    }
  };

  const runAction = async (path, msg) => {
    setBusy(true);
    try {
      const res = await apiClient.post(path);
      addToastToSystem(res.data?.msg || msg || 'Done', 'success');
      await load();
    } finally { setBusy(false); }
  };

  const createBackup = async () => {
    setBusy(true);
    try {
      const res = await apiClient.get('/maintenance/backup');
      addToastToSystem(res.data?.msg || 'Backup created', 'success');
      await load();
    } finally { setBusy(false); }
  };

  const downloadBackup = async () => {
    try {
      const res = await apiClient.get('/maintenance/backup/download', { responseType: 'blob' });
      const blob = new Blob([res.data], { type: 'application/octet-stream' });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = 'ov-panel-backup.db';
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    } catch (e) {
      addToastToSystem(e.response?.data?.detail || 'Download failed', 'error');
    }
  };

  const handleRestore = async () => {
    if (!restoreFile) { addToastToSystem('Select a backup file first', 'error'); return; }
    setRestoreMsg('');
    setBusy(true);
    try {
      const form = new FormData();
      form.append('file', restoreFile);
      const res = await apiClient.post('/maintenance/backup/restore', form, { headers: { 'Content-Type': 'multipart/form-data' } });
      addToastToSystem(res.data?.msg || 'Restore complete', 'success');
      await load();
    } catch (e) {
      setRestoreMsg(e.response?.data?.msg || 'Restore failed');
    } finally { setBusy(false); }
  };

  // Toast system integration via custom event
  const addToastToSystem = (message, type = 'success') => {
    try {
      const event = new CustomEvent('addToast', { detail: { message, type } });
      window.dispatchEvent(event);
    } catch {
      console.log(`[${type.toUpperCase()}] ${message}`);
    }
  };

  const sec = security || {};
  const traffic = (metrics?.traffic || []).at(-1) || {};

  // Tab rendering with injected props
  const renderTab = (tab) => {
    const commonProps = {
      key: tab.id,
      t, setActiveTab, setTimezoneState, setTzSaving, setSecHours, setSubPrefix, setSubPath,
      setSubSaved, setSubError, setRestoreFile, setRestoreMsg, setBotToken,
      setBotEnabled, setOwnerTg, setDefaultDays, setDefaultTraffic, setDefaultUsers,
      saveSubscription, copyLink, saveBotConfig, runAction, createBackup,
      downloadBackup, handleRestore, saveTimezone, traffic, metrics,
      backupFile: restoreFile, setBackupFile: setRestoreFile
    };

    switch (tab.id) {
      case 'general': return <GeneralTab {...commonProps} />;
      case 'system': return <SystemTab {...commonProps} />;
      case 'security': return <SecurityTab {...commonProps} secHours={secHours} setSecHours={setSecHours} sec={sec} />;
      case 'backup': return <BackupTab {...commonProps} />;
      case 'activity': return <ActivityTab {...commonProps} />;
      default: return null;
    }
  };

  return (
    <div className="view">
      {/* Page Header */}
      <div className="page-header">
        <div>
          <h2>Settings</h2>
          <span className="header-badge"><FiInfo size={14} /> {panelVersion ? `v${panelVersion}` : 'OVManager'}</span>
        </div>
        <div className="page-actions">
          <span className="header-badge"><FiActivity size={14} /> Live</span>
        </div>
      </div>

      {/* Tabs */}
      <div className="settings-tabs">{TABS.map((tab) => renderTab(tab))}</div>

      {/* ──── CONTENT WRAPPER (for Suspense) ──── */}
      <Suspense fallback={<div className="settings-section"><div style={{ padding: '40px', textAlign: 'center', color: 'var(--muted)' }}>Loading...</div></div>}>
        {/* Content injected per-tab */}
        {activeTab && renderTab(TABS.find((t) => t.id === activeTab))}
      </Suspense>
    </div>
  );
};

export default Settings;