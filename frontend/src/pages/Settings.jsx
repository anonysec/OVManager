import { useState, useEffect } from 'react';
import {
  FiActivity, FiAlertTriangle, FiBell, FiDatabase, FiDownload, FiGlobe, FiHardDrive,
  FiLayers, FiLink, FiLogOut, FiRefreshCw, FiShield, FiServer, FiUpload, FiZap,
  FiMoon, FiSun, FiSettings, FiCpu, FiClock, FiSave, FiCopy, FiArchive, FiBarChart2,
  FiTool, FiInfo, FiCheckCircle
} from 'react-icons/fi';
import { useTranslation } from 'react-i18next';
import apiClient from '../services/api';
import { useTheme } from '../context/ThemeContext';
import { useLive } from '../context/LiveContext';
import { validateSubscription, buildSubUrl as buildSubUrlHelper } from '../utils/settingsHelpers';
import { copyText } from '../utils/clipboard';
import { fmtDateTime, formatUptime } from '../utils/time';
import { formatBytes } from '../utils/format';
import { FiMessageSquare } from 'react-icons/fi';
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

  useEffect(() => { loadSettings(); load(); }, [load]);

  // Live auto-refresh — polls stats every 8s, does NOT touch form fields
  const { refreshTick } = useLive();
  useEffect(() => { load().catch(() => {}); }, [refreshTick, load]);

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
      window.alert(res.data?.msg || msg || 'Done');
      await load();
    } finally { setBusy(false); }
  };

  const createBackup = async () => {
    setBusy(true);
    try {
      const res = await apiClient.get('/maintenance/backup');
      window.alert(res.data?.msg || 'Backup created');
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
      window.alert(e.response?.data?.detail || 'Download failed');
    }
  };

  const handleRestore = async () => {
    if (!restoreFile) { window.alert('Select a backup file first'); return; }
    setRestoreMsg('');
    setBusy(true);
    try {
      const form = new FormData();
      form.append('file', restoreFile);
      const res = await apiClient.post('/maintenance/backup/restore', form, { headers: { 'Content-Type': 'multipart/form-data' } });
      window.alert(res.data?.msg || 'Restore complete');
      await load();
    } catch (e) {
      setRestoreMsg(e.response?.data?.msg || 'Restore failed');
    } finally { setBusy(false); }
  };

  const sec = security || {};
  const traffic = (metrics?.traffic || []).at(-1) || {};

  const renderTab = (tab) => (
    <button key={tab.id} className={`seg-tab${activeTab === tab.id ? ' active' : ''}`} onClick={() => setActiveTab(tab.id)}>
      <tab.icon size={16} /> {tab.label}
    </button>
  );

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

      {/* Server Stats Row */}
      <div className="user-stats-row" style={{ gridTemplateColumns: 'repeat(4, 1fr)' }}>
        <div className="user-stat" style={{ '--us-accent': '#90caf9' }}>
          <span className="us-ico"><FiCpu /></span>
          <span className="us-body"><span className="us-label">CPU</span><span className="us-value">{serverInfo?.cpu ?? '-'}%</span></span>
        </div>
        <div className="user-stat" style={{ '--us-accent': '#43a047' }}>
          <span className="us-ico"><FiHardDrive /></span>
          <span className="us-body"><span className="us-label">Memory</span><span className="us-value">{serverInfo?.memory_percent ?? '-'}%</span></span>
        </div>
        <div className="user-stat" style={{ '--us-accent': '#e53935' }}>
          <span className="us-ico"><FiDatabase /></span>
          <span className="us-body"><span className="us-label">Disk</span><span className="us-value">{serverInfo?.disk_percent ?? '-'}%</span></span>
        </div>
        <div className="user-stat" style={{ '--us-accent': '#ff9800' }}>
          <span className="us-ico"><FiClock /></span>
          <span className="us-body"><span className="us-label">{t('uptime')}</span><span className="us-value">{formatUptime(serverInfo?.uptime)}</span></span>
        </div>
      </div>

      {/* Tabs */}
      <div className="settings-tabs">{TABS.map(renderTab)}</div>

      {/* ──── GENERAL TAB ──── */}
      {activeTab === 'general' && (
        <div className="settings-section">
          <div className="setting-card">
            <div className="setting-card-header"><FiLink /> Subscription Link</div>
            <div className="setting-card-body">
              <div className="input-group">
                <label>URL prefix</label>
                <input value={subPrefix} onChange={(e) => setSubPrefix(e.target.value)} placeholder="https://domain.tld" />
              </div>
              <div className="input-group">
                <label>Path</label>
                <input value={subPath} onChange={(e) => setSubPath(e.target.value)} placeholder="sub" />
              </div>
              {subError && <p className="error-message">{subError}</p>}
              <div className="card-actions">
                <button className="btn btn-sm" onClick={saveSubscription}><FiSave size={14} /> {subSaved ? 'Saved' : 'Save'}</button>
                <button className="btn btn-sm btn-secondary" onClick={copyLink}><FiCopy size={14} /> Copy link</button>
              </div>
              {buildSubUrlHelper(subPrefix, subPath) && (
                <div className="sub-url-display">{buildSubUrlHelper(subPrefix, subPath)}</div>
              )}
            </div>
          </div>

          <div className="setting-card">
            <div className="setting-card-header">{theme === 'dark' ? <FiMoon /> : <FiSun />} Appearance</div>
            <div className="setting-card-body">
              <div className="theme-pills" style={{ marginBottom: 16 }}>
                <button className={`theme-pill ${theme === 'dark' ? 'active' : ''}`} onClick={() => setTheme('dark')}><FiMoon size={16} /> Dark</button>
                <button className={`theme-pill ${theme === 'light' ? 'active' : ''}`} onClick={() => setTheme('light')}><FiSun size={16} /> Light</button>
              </div>
              <div className="input-group">
                <label>Timezone</label>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                  <select value={timezone} onChange={(e) => saveTimezone(e.target.value)} style={{ flex: 1 }}>
                    {TIMEZONES.map((z) => <option key={z} value={z}>{z}</option>)}
                  </select>
                  {tzSaving && <span style={{ fontSize: 12, color: 'var(--muted)' }}>Saving...</span>}
                </div>
              </div>
            </div>
          </div>

          <div className="setting-card">
            <div className="setting-card-header"><FiMessageSquare /> Telegram Bot</div>
            <div className="setting-card-body">
              <div className="input-group">
                <label>Bot Token</label>
                <input type="password" value={botToken} onChange={(e) => setBotToken(e.target.value)} placeholder="123456:ABC-DEF..." />
              </div>
              <div className="input-group">
                <label>Owner Telegram ID</label>
                <input type="number" value={ownerTg} onChange={(e) => setOwnerTg(e.target.value)} placeholder="Your Telegram user ID" />
              </div>
              <div className="input-group">
                <label>Enabled</label>
                <div className="theme-pills" style={{ marginBottom: 0 }}>
                  <button className={`theme-pill ${botEnabled ? 'active' : ''}`} onClick={() => setBotEnabled(true)}>Yes</button>
                  <button className={`theme-pill ${!botEnabled ? 'active' : ''}`} onClick={() => setBotEnabled(false)}>No</button>
                </div>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12 }}>
                <div className="input-group">
                  <label>Default Days</label>
                  <input type="number" value={defaultDays} onChange={(e) => setDefaultDays(Number(e.target.value))} min="0" />
                </div>
                <div className="input-group">
                  <label>Traffic GB</label>
                  <input type="number" value={defaultTraffic} onChange={(e) => setDefaultTraffic(Number(e.target.value))} min="0" />
                </div>
                <div className="input-group">
                  <label>Max Users</label>
                  <input type="number" value={defaultUsers} onChange={(e) => setDefaultUsers(Number(e.target.value))} min="0" />
                </div>
              </div>
              <div className="card-actions">
                <button className="btn btn-sm" onClick={saveBotConfig}><FiSave size={14} /> {botSaved ? 'Saved' : 'Save'}</button>
              </div>
              <p style={{ fontSize: 12, color: 'var(--muted)', marginTop: 8 }}>Admin Telegram IDs are set in the Admin Management page.</p>
            </div>
          </div>
        </div>
      )}

      {/* ──── SYSTEM TAB ──── */}
      {activeTab === 'system' && (
        <div className="settings-section">
          <div className="setting-card">
            <div className="setting-card-header"><FiBarChart2 /> Metrics</div>
            <div className="setting-card-body">
              <div className="metric-mini-grid">
                <div className="metric-mini"><div className="metric-label">Active Connections</div><div className="metric-value">{traffic.active_connections || 0}</div></div>
                <div className="metric-mini"><div className="metric-label">Traffic</div><div className="metric-value">{formatBytes(traffic.total_used || 0)}</div></div>
                <div className="metric-mini"><div className="metric-label">Login Health</div><div className="metric-value">{loginHealth?.totals?.online || 0}/{loginHealth?.totals?.users || 0}</div></div>
              </div>
              <div className="card-actions">
                <button className="btn btn-sm btn-secondary" onClick={() => runAction('/metrics/collect', 'Metrics collected')}><FiBarChart2 size={14} /> Collect now</button>
              </div>
            </div>
          </div>

          <div className="setting-card">
            <div className="setting-card-header"><FiTool /> Maintenance</div>
            <div className="setting-card-body">
              <div className="card-actions">
                <button className="btn btn-sm" onClick={() => runAction('/maintenance/sync-limits', 'Limits synced')}><FiZap size={14} /> Sync limits</button>
                <button className="btn btn-sm btn-secondary" onClick={() => runAction('/maintenance/clean-stale', 'Stale cleaned')}><FiRefreshCw size={14} /> Clean stale</button>
                <button className="btn btn-sm btn-secondary" onClick={() => runAction('/maintenance/clean-global-registry', 'Registry cleaned')}><FiLayers size={14} /> Clean registry</button>
              </div>
            </div>
          </div>

          <div className="setting-card">
            <div className="setting-card-header"><FiBell /> Notifications</div>
            <div className="setting-card-body">
              {notifications.length === 0 ? (
                <div className="empty-state-card"><h3><FiCheckCircle size={24} style={{ display: 'block', margin: '0 auto 8px', color: 'var(--green)' }} /></h3><p>No active notifications</p></div>
              ) : (
                notifications.slice(0, 8).map((n) => (
                  <div key={n.id || n.title} className="feed-item">
                    <span className={`feed-badge ${n.level === 'danger' ? 'danger' : 'warn'}`}>{n.level}</span>
                    <div className="feed-content">
                      <div className="feed-title">{n.title}</div>
                      {n.detail && <div className="feed-detail">{n.detail}</div>}
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      )}

      {/* ──── SECURITY TAB ──── */}
      {activeTab === 'security' && (
        <div className="settings-section">
          <div className="setting-card">
            <div className="setting-card-header"><FiShield /> Security Summary</div>
            <div className="setting-card-body">
              <div className="card-actions" style={{ marginBottom: 12 }}>
                <label style={{ fontSize: 12, color: 'var(--muted)', fontWeight: 600, alignSelf: 'center' }}>Hours:</label>
                {[4, 8, 12, 24, 48].map(h => (
                  <button key={h} className={`btn btn-sm ${secHours === h ? '' : 'btn-secondary'}`} onClick={() => { setSecHours(h); load(); }}>{h}h</button>
                ))}
              </div>
              <div className="metric-mini-grid" style={{ gridTemplateColumns: 'repeat(3, 1fr)' }}>
                <div className="metric-mini"><div className="metric-label">Auth Errors</div><div className={`metric-value ${sec.auth_errors > 0 ? 'danger' : ''}`}>{sec.auth_errors || 0}</div></div>
                <div className="metric-mini"><div className="metric-label">Rejects</div><div className={`metric-value ${sec.rejects > 0 ? 'danger' : ''}`}>{sec.rejects || 0}</div></div>
                <div className="metric-mini"><div className="metric-label">Stale</div><div className={`metric-value ${sec.stale_markers > 0 ? 'danger' : ''}`}>{sec.stale_markers || 0}</div></div>
              </div>
              <p style={{ fontSize: 12, color: 'var(--muted)', marginTop: 8 }}>Last {secHours} hours</p>
            </div>
          </div>

          <div className="setting-card">
            <div className="setting-card-header"><FiGlobe /> Login Health</div>
            <div className="setting-card-body">
              {loginHealth?.users?.length ? (
                <>
                  <div className="metric-mini-grid" style={{ gridTemplateColumns: 'repeat(3, 1fr)' }}>
                    <div className="metric-mini"><div className="metric-label">Users</div><div className="metric-value">{loginHealth.totals?.users || 0}</div></div>
                    <div className="metric-mini"><div className="metric-label">Online</div><div className="metric-value success">{loginHealth.totals?.online || 0}</div></div>
                    <div className="metric-mini"><div className="metric-label">Full</div><div className="metric-value">{loginHealth.totals?.full || 0}</div></div>
                  </div>
                  <p style={{ fontSize: 12, color: 'var(--muted)', marginTop: 8 }}>Last 8 hours</p>
                </>
              ) : (
                <div className="empty-state-card"><p>No login data yet</p></div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ──── BACKUP TAB ──── */}
      {activeTab === 'backup' && (
        <div className="settings-section">
          <div className="setting-card">
            <div className="setting-card-header"><FiArchive /> Backup & Restore</div>
            <div className="setting-card-body">
              <div className="card-actions" style={{ marginBottom: 16 }}>
                <button className="btn btn-sm" onClick={createBackup} disabled={busy}><FiUpload size={14} /> Create backup</button>
                <button className="btn btn-sm btn-secondary" onClick={downloadBackup}><FiDownload size={14} /> Download latest</button>
              </div>
              <div className="input-group file-input-wrap">
                <label>Restore from file</label>
                <input type="file" accept=".db" onChange={(e) => setRestoreFile(e.target.files?.[0] || null)} />
              </div>
              <div className="card-actions">
                <button className="btn btn-sm btn-secondary" onClick={handleRestore} disabled={busy || !restoreFile}><FiRefreshCw size={14} /> Restore</button>
              </div>
              {restoreMsg && <p className="error-message">{restoreMsg}</p>}
              {backups.length > 0 && (
                <div className="backup-tag"><FiDatabase size={12} /> {backups.length} backup(s) available</div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ──── ACTIVITY TAB ──── */}
      {activeTab === 'activity' && (
        <div className="settings-section">
          <div className="setting-card">
            <div className="setting-card-header"><FiActivity /> Recent Activity</div>
            <div className="setting-card-body">
              {activity.length === 0 ? (
                <div className="empty-state-card"><h3>No activity yet</h3><p>System actions will appear here</p></div>
              ) : (
                activity.slice(0, 30).map((e) => {
                  const ts = e.ts ? new Date(e.ts * 1000).toISOString() : null;
                  const isDel = e.action === 'delete_user' || e.action === 'delete_node';
                  return (
                    <div key={e.id} className="feed-item">
                      <span className={`feed-badge ${isDel ? 'danger' : 'muted'}`}>
                        {e.action?.replace(/_/g, ' ')}
                      </span>
                      <div className="feed-content">
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                          <span className="feed-actor">{e.actor || 'system'}</span>
                          {e.target && <><span style={{ color: 'var(--muted)', fontSize: 12 }}>→</span><span style={{ color: 'var(--text-primary)', fontWeight: 500, fontSize: 13 }}>{e.target}</span></>}
                          {ts && <span className="feed-detail" style={{ marginLeft: 'auto' }}>{fmtDateTime(ts)}</span>}
                        </div>
                        {e.detail && <div className="feed-detail">{e.detail}</div>}
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default Settings;