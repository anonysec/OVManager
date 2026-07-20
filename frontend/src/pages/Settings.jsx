import { useEffect, useState } from 'react';
import { FiActivity, FiAlertTriangle, FiBell, FiLink, FiMoon, FiRefreshCw, FiShield, FiSun, FiTool, FiCpu, FiUsers, FiZap, FiCheck, FiCopy } from 'react-icons/fi';
import { useTranslation } from 'react-i18next';
import apiClient from '../services/api';
import { useTheme } from '../context/ThemeContext';
import { validateSubscription, buildSubUrl as buildSubUrlHelper } from '../utils/settingsHelpers';
import { copyText } from '../utils/clipboard';

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
  const { theme, setTheme } = useTheme();
  const [settings, setSettings] = useState(null);
  const [security, setSecurity] = useState(null);
  const [activity, setActivity] = useState([]);
  const [notifications, setNotifications] = useState([]);
  const [loginHealth, setLoginHealth] = useState(null);
  const [busy, setBusy] = useState(false);
  const [timezone, setTimezoneState] = useState(() => localStorage.getItem('ovTimezone') || 'UTC');
  const [tzSaving, setTzSaving] = useState(false);
  const [subPrefix, setSubPrefix] = useState('');
  const [subPath, setSubPath] = useState('');
  const [subSaving, setSubSaving] = useState(false);
  const [subSaved, setSubSaved] = useState(false);
  const [subError, setSubError] = useState('');
  const [copied, setCopied] = useState(false);
  const [notifFilter, setNotifFilter] = useState('all');
  const [dismissed, setDismissed] = useState(() => {
    try { return JSON.parse(localStorage.getItem('ovmanager-dismissed') || '[]'); } catch { return []; }
  });

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

  const validateSub = () => validateSubscription(subPrefix, subPath, t);

  const buildSubUrl = () => buildSubUrlHelper(subPrefix, subPath);

  const saveSubscription = async () => {
    const err = validateSub();
    setSubError(err);
    if (err) return;
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

  const copyLink = async () => {
    try {
      const ok = await copyText(buildSubUrl());
      setCopied(ok);
      setTimeout(() => setCopied(false), 1800);
    } catch { /* ignore */ }
  };

  const runAction = async (path) => {
    setBusy(true);
    try {
      await apiClient.post(path);
      await load();
    } finally { setBusy(false); }
  };

  const setThemeMode = (next) => setTheme(next);

  const healthRows = loginHealth?.users || [];
  const totals = loginHealth?.totals || {};
  const notifCount = Array.isArray(notifications) ? notifications.length : 0;
  const dismissNotif = (id) => {
    const next = [...new Set([...dismissed, id])];
    setDismissed(next);
    localStorage.setItem('ovmanager-dismissed', JSON.stringify(next));
  };
  const visibleNotifications = (Array.isArray(notifications) ? notifications : [])
    .filter((n) => !dismissed.includes((n.target || '') + n.title))
    .filter((n) => notifFilter === 'all' || (n.level || 'warning') === notifFilter);

  return (
    <div id="settings-view" className="view settings-overhaul">
      <div className="view-header">
        <div>
          <h2>{t('settingsTitle')}</h2>
          <p className="view-sub">{t('settingsSub')}</p>
        </div>
        <button className="btn" type="button" onClick={() => load().catch(() => {})}><FiRefreshCw /> {t('refresh')}</button>
      </div>

      <div className="settings-grid">
        <section className="set-card set-card-accent">
          <header className="set-card-head">
            <span className="set-ico">{theme === 'dark' ? <FiMoon /> : <FiSun />}</span>
            <div><h3>{t('appearanceCard')}</h3><p>{t('appearanceDesc')}</p></div>
          </header>
          <label className="set-field">
            <span>{t('theme')}</span>
            <div className="segmented" role="group" aria-label={t('theme')}>
              <button type="button" className={theme === 'dark' ? 'seg active' : 'seg'} onClick={() => setThemeMode('dark')} aria-pressed={theme === 'dark'}>
                <FiMoon /> {t('darkMode')}
              </button>
              <button type="button" className={theme === 'light' ? 'seg active' : 'seg'} onClick={() => setThemeMode('light')} aria-pressed={theme === 'light'}>
                <FiSun /> {t('lightMode')}
              </button>
            </div>
          </label>
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
            <span className="set-ico"><FiCpu /></span>
            <div><h3>{t('systemCard')}</h3><p>{t('systemDesc')}</p></div>
          </header>
          <div className="set-kpis compact">
            <div><span>{t('version')}</span><strong>{settings?.panel_version || settings?.version || '1.5.0'}</strong></div>
            <div><span>{t('nodeMode')}</span><strong>{settings?.node_protocol || t('nodeProtocol')}</strong></div>
          </div>
        </section>

        <section className="set-card span-3">
          <header className="set-card-head">
            <span className="set-ico"><FiLink /></span>
            <div><h3>{t('subscriptionLinkCard')}</h3><p>{t('subscriptionLinkDesc')}</p></div>
          </header>
          <div className="set-fields">
            <label className="set-field">
              <span>{t('urlPrefix')}</span>
              <input type="text" value={subPrefix} onChange={(e) => { setSubPrefix(e.target.value); if (subError) setSubError(''); }} placeholder="https://vpn.example.com/sub/" />
            </label>
            <label className="set-field">
              <span>{t('path')}</span>
              <input type="text" value={subPath} onChange={(e) => { setSubPath(e.target.value); if (subError) setSubError(''); }} placeholder="sub" />
            </label>
          </div>
          {subError && <p className="set-err notice warning">{subError}</p>}
          <code className="set-code">
            <span>{buildSubUrl()}</span>
            <button type="button" className="code-copy" onClick={copyLink} aria-label={t('copyLink')}>
              {copied ? <FiCheck /> : <FiCopy />}
            </button>
          </code>
          <p className="set-note">{t('subIsOpenvpn')}</p>
          <div className="set-foot">
            <button className="btn btn-sm" disabled={subSaving} onClick={saveSubscription}>
              <FiRefreshCw /> {subSaving ? t('saving') : t('saveLink')}
            </button>
            {subSaved && <small className="set-saved">{t('saved')}</small>}
          </div>
        </section>

        <section className="set-card span-3">
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
          <div className="set-notif-filters">
            {['all', 'danger', 'warning'].map((f) => (
              <button key={f} type="button" className={notifFilter === f ? 'seg active' : 'seg'} onClick={() => setNotifFilter(f)}>{t(`notifFilter${f}`)}</button>
            ))}
          </div>
          <div className="set-list">
            {visibleNotifications.length ? visibleNotifications.map((n, i) => (
              <div key={(n.target || '') + n.title} className={`notice ${n.level || 'warning'} set-notice-row`}>
                <span className="set-notice-text">{n.title}</span>
                <button type="button" className="set-notice-dismiss" aria-label={t('dismiss')} onClick={() => dismissNotif((n.target || '') + n.title)}>×</button>
              </div>
            )) : <p className="notice good">{t('noActiveNotif')}</p>}
          </div>
        </section>

        <section className="set-card span-2">
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

        <section className="set-card span-3">
          <header className="set-card-head">
            <span className="set-ico"><FiActivity /></span>
            <div><h3>{t('activityLogCard')}</h3><p>{t('activityDesc')}</p></div>
          </header>
          <div className="set-list small scroll">
            {activity.length ? activity.map((a) => <p key={a.id}>{new Date(a.ts * 1000).toLocaleString()} — {a.actor || 'system'} — {a.action} {a.target || ''}</p>) : <p className="set-empty">{t('noActivity')}</p>}
          </div>
        </section>
      </div>
    </div>
  );
};

export default Settings;
