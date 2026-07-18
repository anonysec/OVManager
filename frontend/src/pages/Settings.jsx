import { useEffect, useState } from 'react';
import { FiActivity, FiAlertTriangle, FiBell, FiLink, FiMoon, FiRefreshCw, FiShield, FiSun, FiTool, FiCpu, FiUsers, FiZap } from 'react-icons/fi';
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
    } catch {
      // keep local copy even if backend fails
    } finally {
      setTzSaving(false);
    }
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
    } catch {
      // ignore
    } finally {
      setSubSaving(false);
    }
  };

  const runAction = async (path) => {
    setBusy(true);
    try {
      await apiClient.post(path);
      await load();
    } finally {
      setBusy(false);
    }
  };

  const toggleTheme = () => {
    const next = theme === 'dark' ? 'light' : 'dark';
    setTheme(next);
    document.documentElement.dataset.theme = next;
    localStorage.setItem('ovmanager-theme', next);
  };

  const subExample = settings
    ? `${settings.subscription_url_prefix}${settings.subscription_path ? `${settings.subscription_path}/` : ''}{user_uuid}`
    : 'Loading...';

  const healthRows = loginHealth?.users || [];
  const totals = loginHealth?.totals || {};
  const notifCount = Array.isArray(notifications) ? notifications.length : 0;

  return (
    <div id="settings-view" className="view settings-overhaul">
      <div className="view-header">
        <h2>Settings &amp; Operations</h2>
        <button className="btn" type="button" onClick={() => load().catch(() => {})}><FiRefreshCw /> Refresh</button>
      </div>

      <div className="settings-grid">
        <section className="set-card span-2">
          <header className="set-card-head">
            <span className="set-ico"><FiTool /></span>
            <div><h3>Maintenance</h3><p>Background jobs run automatically. Trigger them on demand below.</p></div>
          </header>
          <div className="set-kpis">
            <div><span>Users</span><strong>{totals.users ?? '-'}</strong></div>
            <div><span>Online</span><strong>{totals.online ?? '-'}</strong></div>
            <div><span>Full</span><strong>{totals.full ?? '-'}</strong></div>
            <div><span>Stale</span><strong>{totals.stale ?? '-'}</strong></div>
            <div><span>Takeover</span><strong>{totals.takeover_mode ?? '-'}</strong></div>
          </div>
          <div className="set-actions">
            <button className="btn" disabled={busy} onClick={() => runAction('/maintenance/sync-limits')}><FiZap /> Sync limits now</button>
            <button className="btn btn-secondary" disabled={busy} onClick={() => runAction('/maintenance/clean-stale')}><FiRefreshCw /> Clean stale now</button>
          </div>
          <div className="set-table-wrap">
            <table className="set-table">
              <thead><tr><th>User</th><th>Active/Max</th><th>Mode</th><th>Status</th><th>Stale</th><th>Auth events</th></tr></thead>
              <tbody>
                {healthRows.length ? healthRows.map((row) => (
                  <tr key={row.name}>
                    <td>{row.name}</td>
                    <td><strong className="login-count">{row.active_connections}/{row.max_logins === 0 ? '∞' : row.max_logins}</strong></td>
                    <td>{row.mode}</td>
                    <td><span className={row.status === 'online' || row.status === 'idle' ? 'pill online' : 'pill'}>{row.status}</span></td>
                    <td>{row.stale_markers}</td>
                    <td>{row.auth_events}</td>
                  </tr>
                )) : <tr><td colSpan={6} className="set-empty">No user login data yet.</td></tr>}
              </tbody>
            </table>
          </div>
        </section>

        <section className="set-card">
          <header className="set-card-head">
            <span className="set-ico"><FiBell /></span>
            <div><h3>Notifications</h3><p>{notifCount} active operational {notifCount === 1 ? 'issue' : 'issues'}.</p></div>
          </header>
          <div className="set-list">
            {notifCount ? notifications.map((n, i) => (
              <p key={n.id ?? i} className={`notice ${n.level || 'warning'}`}>{n.title}</p>
            )) : <p className="notice good">No active notifications</p>}
          </div>
        </section>

        <section className="set-card">
          <header className="set-card-head">
            <span className="set-ico"><FiShield /></span>
            <div><h3>Security</h3><p>Last 8 hours from nodes.</p></div>
          </header>
          <div className="set-kpis compact">
            <div><span>Auth errors</span><strong>{security?.auth_errors ?? '-'}</strong></div>
            <div><span>Rejects</span><strong>{security?.rejects ?? '-'}</strong></div>
            <div><span>Stale markers</span><strong>{security?.stale_markers ?? '-'}</strong></div>
          </div>
          <div className="set-list small">
            {(security?.last_errors || []).slice(0, 5).map((e, i) => <p key={i} className="set-err">{e.time_tehran || ''} — {e.common_name}: {e.reason} ({e.active || '?'}/{e.limit || '?'})</p>)}
          </div>
        </section>

        <section className="set-card">
          <header className="set-card-head">
            <span className="set-ico"><FiActivity /></span>
            <div><h3>Activity Log</h3><p>Recent admin actions.</p></div>
          </header>
          <div className="set-list small scroll">
            {activity.length ? activity.map((a) => <p key={a.id}>{new Date(a.ts * 1000).toLocaleString()} — {a.actor || 'system'} — {a.action} {a.target || ''}</p>) : <p className="set-empty">No activity recorded yet.</p>}
          </div>
        </section>

        <section className="set-card span-2">
          <header className="set-card-head">
            <span className="set-ico"><FiLink /></span>
            <div><h3>Subscription Link</h3><p>Base URL and path used by user VPN subscription links.</p></div>
          </header>
          <div className="set-fields">
            <label className="set-field">
              <span>URL prefix</span>
              <input type="text" value={subPrefix} onChange={(e) => setSubPrefix(e.target.value)} placeholder="https://vpn.example.com/sub/" />
            </label>
            <label className="set-field">
              <span>Path</span>
              <input type="text" value={subPath} onChange={(e) => setSubPath(e.target.value)} placeholder="sub" />
            </label>
          </div>
          <div className="set-foot">
            <button className="btn btn-sm" disabled={subSaving} onClick={saveSubscription}>
              <FiRefreshCw /> {subSaving ? 'Saving…' : 'Save link settings'}
            </button>
            {subSaved && <small className="set-saved">Saved.</small>}
          </div>
          <code className="set-code">{`${subPrefix}${subPath ? subPath.replace(/^\/+|\/+$/g, '') + '/' : ''}{user_uuid}`}</code>
        </section>

        <section className="set-card">
          <header className="set-card-head">
            <span className="set-ico"><FiTool /></span>
            <div><h3>Timezone</h3><p>Used for all dates.</p></div>
          </header>
          <label className="set-field">
            <span>Display timezone</span>
            <select value={timezone} onChange={(e) => saveTimezone(e.target.value)} disabled={tzSaving}>
              {TIMEZONES.map((tz) => <option key={tz} value={tz}>{tz}</option>)}
            </select>
          </label>
          {tzSaving && <small className="set-saved">Saving…</small>}
        </section>

        <section className="set-card">
          <header className="set-card-head">
            <span className="set-ico">{theme === 'dark' ? <FiMoon /> : <FiSun />}</span>
            <div><h3>Appearance</h3><p>Switch theme.</p></div>
          </header>
          <button className="btn" type="button" onClick={toggleTheme}>{theme === 'dark' ? 'Use Light Mode' : 'Use Dark Mode'}</button>
        </section>

        <section className="set-card">
          <header className="set-card-head">
            <span className="set-ico"><FiCpu /></span>
            <div><h3>System</h3><p>Runtime info.</p></div>
          </header>
          <div className="set-kpis compact">
            <div><span>Version</span><strong>{(settings && (settings.version || settings.panel_version)) || '1.3.3'}</strong></div>
            <div><span>Node mode</span><strong>{settings?.node_protocol || 'gRPC'}</strong></div>
          </div>
        </section>
      </div>
    </div>
  );
};

export default Settings;
