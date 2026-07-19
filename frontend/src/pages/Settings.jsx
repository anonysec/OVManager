import { useEffect, useState } from 'react';
import { FiActivity, FiAlertTriangle, FiBell, FiLink, FiMoon, FiRefreshCw, FiShield, FiSun, FiTool, FiCpu, FiUsers, FiZap } from 'react-icons/fi';
import { useTranslation } from 'react-i18next';
import apiClient from '../services/api';

const TIMEZONES = [
  'UTC',
  'Asia/Tehran',
  'Asia/Dubai',
  'Asia/Kolkata',
  'Asia/Shanghai',
  'Asia/Tokyo',
  'Europe/Istanbul',
  'Europe/Berlin',
  'Europe/London',
  'America/New_York',
  'America/Los_Angeles',
  'Australia/Sydney',
];

const Settings = () => {
  const { t } = useTranslation();
  const [settings, setSettings] = useState(null);
  const [security, setSecurity] = useState(null);
  const [activity, setActivity] = useState([]);
  const [notifications, setNotifications] = useState([]);
  const [loginHealth, setLoginHealth] = useState(null);
  const [busy, setBusy] = useState(false);
  const [theme, setTheme] = useState(() => localStorage.getItem('ovmanager-theme') || 'dark');
  const [timezone, setTimezoneState] = useState(() => localStorage.getItem('ovTimezone') || 'UTC');
  const [tzSaving, setTzSaving] = useState(false);
  const [subPrefix, setSubPrefix] = useState('');
  const [subPath, setSubPath] = useState('');
  const [subSaving, setSubSaving] = useState(false);
  const [subSaved, setSubSaved] = useState(false);

  const load = async () => {
    const [settingsRes, securityRes, activityRes, notificationsRes, loginHealthRes] = await Promise.all([
      apiClient.get('/server/settings'),
      apiClient.get('/security/summary?hours=8'),
      apiClient.get('/activity/?limit=25'),
      apiClient.get('/notifications/'),
      apiClient.get('/maintenance/login-health?hours=8'),
    ]);
    setSettings(settingsRes.data?.data || null);
    const tz = settingsRes.data?.data?.timezone || 'UTC';
    setTimezoneState(tz);
    localStorage.setItem('ovTimezone', tz);
    setSecurity(securityRes.data?.data || null);
    setActivity(activityRes.data?.data || []);
    setNotifications(notificationsRes.data?.data || []);
    setLoginHealth(loginHealthRes.data?.data || null);
    const s = settingsRes.data?.data || {};
    setSubPrefix(s.subscription_url_prefix || '');
    setSubPath(s.subscription_path || '');
  };

  useEffect(() => { load().catch(() => {}); }, []);

  const saveTimezone = async (tz) => {
    setTimezoneState(tz);
    localStorage.setItem('ovTimezone', tz);
    setTzSaving(true);
    try {
      await apiClient.put('/server/settings/timezone', { timezone: tz });
    } catch { /* keep local copy */ } finally { setTzSaving(false); }
  };

  const saveSubscription = async () => {
    setSubSaving(true);
    setSubSaved(false);
    try {
      await apiClient.put('/server/settings/subscription', {
        subscription_url_prefix: subPrefix,
        subscription_path: subPath,
      });
      setSubSaved(true);
      setTimeout(() => setSubSaved(false), 2500);
    } catch { /* ignore */ } finally { setSubSaving(false); }
  };

  const runAction = async (path) => {
    setBusy(true);
    try {
      await apiClient.post(path);
      await load();
    } finally { setBusy(false); }
  };

  const toggleTheme = () => {
    const next = theme === 'dark' ? 'light' : 'dark';
    setTheme(next);
    document.documentElement.dataset.theme = next;
    localStorage.setItem('ovmanager-theme', next);
  };

  const healthRows = loginHealth?.users || [];
  const totals = loginHealth?.totals || {};
  const notifCount = Array.isArray(notifications) ? notifications.length : 0;

  return (
    <div id="settings-view" className="view settings-overhaul">
      <div className="view-header">
        <h2>{t('settingsTitle')}</h2>
        <button className="btn" type="button" onClick={() => load().catch(() => {})}><FiRefreshCw /> {t('refresh')}</button>
      </div>

      <div className="settings-grid">
        <section className="set-card span-2">
          <header className="set-card-head">
            <span className="set-ico"><FiTool /></span>
            <div><h3>{t('maintenance')}</h3><p>{t('maintenanceDesc')}</p></div>
          </header>
          <div className="set-kpis">
            <div><span>{t('kpiUsers')}</span><strong>{totals.users ?? '-'}</strong></div>
            <div><span>{t('kpiOnline')}</span><strong>{totals.online ?? '-'}</strong></div>
            <div><span>{t('kpiFull')}</span><strong>{totals.full ?? '-'}</strong></div>
            <div><span>{t('kpiStale')}</span><strong>{totals.stale ?? '-'}</strong></div>
            <div><span>{t('kpiTakeover')}</span><strong>{totals.takeover_mode ?? '-'}</strong></div>
          </div>
          <div className="set-actions">
            <button className="btn" disabled={busy} onClick={() => runAction('/maintenance/sync-limits')}><FiZap /> {t('syncLimits')}</button>
            <button className="btn btn-secondary" disabled={busy} onClick={() => runAction('/maintenance/clean-stale')}><FiRefreshCw /> {t('cleanStale')}</button>
          </div>
        </section>

        <section className="set-card">
          <header className="set-card-head">
            <span className="set-ico"><FiBell /></span>
            <div><h3>{t('notificationsCard')}</h3><p>{notifCount} {notifCount === 1 ? t('notifIssue') : t('notifIssues')}.</p></div>
          </header>
          <div className="set-list">
            {notifCount ? notifications.map((n, i) => (
              <p key={n.id ?? i} className={`notice ${n.level || 'warning'}`}>{n.title}</p>
            )) : <p className="notice good">{t('noActiveNotif')}</p>}
          </div>
        </section>

        <section className="set-card">
          <header className="set-card-head">
            <span className="set-ico"><FiShield /></span>
            <div><h3>{t('securityCard')}</h3><p>{t('securityDesc')}</p></div>
          </header>
          <div className="set-kpis compact">
            <div><span>{t('authErrors')}</span><strong>{security?.auth_errors ?? '-'}</strong></div>
            <div><span>{t('rejects')}</span><strong>{security?.rejects ?? '-'}</strong></div>
            <div><span>{t('staleMarkers')}</span><strong>{security?.stale_markers ?? '-'}</strong></div>
          </div>
        </section>

        <section className="set-card span-2">
          <header className="set-card-head">
            <span className="set-ico"><FiActivity /></span>
            <div><h3>{t('activityLogCard')}</h3><p>{t('activityDesc')}</p></div>
          </header>
          <div className="set-list small scroll">
            {activity.length ? activity.map((a) => <p key={a.id}>{new Date(a.ts * 1000).toLocaleString()} — {a.actor || 'system'} — {a.action} {a.target || ''}</p>) : <p className="set-empty">{t('noActivity')}</p>}
          </div>
        </section>

        <section className="set-card span-2">
          <header className="set-card-head">
            <span className="set-ico"><FiLink /></span>
            <div><h3>{t('subscriptionLinkCard')}</h3><p>{t('subscriptionLinkDesc')}</p></div>
          </header>
          <div className="set-fields">
            <label className="set-field">
              <span>{t('urlPrefix')}</span>
              <input type="text" value={subPrefix} onChange={(e) => setSubPrefix(e.target.value)} placeholder="https://vpn.example.com/sub/" />
            </label>
            <label className="set-field">
              <span>{t('path')}</span>
              <input type="text" value={subPath} onChange={(e) => setSubPath(e.target.value)} placeholder="sub" />
            </label>
          </div>
          <div className="set-foot">
            <button className="btn btn-sm" disabled={subSaving} onClick={saveSubscription}>
              <FiRefreshCw /> {subSaving ? t('saving') : t('saveLink')}
            </button>
            {subSaved && <small className="set-saved">{t('saved')}</small>}
          </div>
          <code className="set-code">{`${subPrefix}${subPath ? subPath.replace(/^\/+|\/+$/g, '') + '/' : ''}{user_uuid}`}</code>
        </section>

        <section className="set-card">
          <header className="set-card-head">
            <span className="set-ico"><FiTool /></span>
            <div><h3>{t('timezoneCard')}</h3><p>{t('timezoneDesc')}</p></div>
          </header>
          <label className="set-field">
            <span>{t('displayTimezone')}</span>
            <select value={timezone} onChange={(e) => saveTimezone(e.target.value)} disabled={tzSaving}>
              {TIMEZONES.map((tz) => <option key={tz} value={tz}>{tz}</option>)}
            </select>
          </label>
          {tzSaving && <small className="set-saved">{t('saving')}</small>}
        </section>

        <section className="set-card">
          <header className="set-card-head">
            <span className="set-ico">{theme === 'dark' ? <FiMoon /> : <FiSun />}</span>
            <div><h3>{t('appearanceCard')}</h3><p>{t('appearanceDesc')}</p></div>
          </header>
          <button className="btn" type="button" onClick={toggleTheme}>{theme === 'dark' ? t('useLightMode') : t('useDarkMode')}</button>
        </section>

        <section className="set-card">
          <header className="set-card-head">
            <span className="set-ico"><FiCpu /></span>
            <div><h3>{t('systemCard')}</h3><p>{t('systemDesc')}</p></div>
          </header>
          <div className="set-kpis compact">
            <div><span>{t('version')}</span><strong>{(settings && (settings.version || settings.panel_version)) || '1.4.0'}</strong></div>
            <div><span>{t('nodeMode')}</span><strong>{settings?.node_protocol || t('nodeProtocol')}</strong></div>
          </div>
        </section>
      </div>
    </div>
  );
};

export default Settings;
