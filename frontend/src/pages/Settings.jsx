import { useEffect, useState } from 'react';
import { FiActivity, FiAlertTriangle, FiBell, FiLink, FiMoon, FiRefreshCw, FiShield, FiSun, FiTool } from 'react-icons/fi';
import apiClient from '../services/api';

const Settings = () => {
  const [settings, setSettings] = useState(null);
  const [security, setSecurity] = useState(null);
  const [activity, setActivity] = useState([]);
  const [notifications, setNotifications] = useState([]);
  const [loginHealth, setLoginHealth] = useState(null);
  const [busy, setBusy] = useState(false);
  const [theme, setTheme] = useState(() => localStorage.getItem('ovmanager-theme') || 'dark');

  const load = async () => {
    const [settingsRes, securityRes, activityRes, notificationsRes, loginHealthRes] = await Promise.all([
      apiClient.get('/server/settings'),
      apiClient.get('/security/summary?hours=8'),
      apiClient.get('/activity/?limit=25'),
      apiClient.get('/notifications/'),
      apiClient.get('/maintenance/login-health?hours=8'),
    ]);
    setSettings(settingsRes.data?.data || null);
    setSecurity(securityRes.data?.data || null);
    setActivity(activityRes.data?.data || []);
    setNotifications(notificationsRes.data?.data || []);
    setLoginHealth(loginHealthRes.data?.data || null);
  };

  useEffect(() => { load().catch(() => {}); }, []);

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

  return (
    <div id="settings-view" className="view settings-page">
      <div className="view-header">
        <h2>Settings</h2>
        <button className="btn" type="button" onClick={() => load().catch(() => {})}><FiRefreshCw /> Refresh</button>
      </div>

      <div className="settings-grid premium-settings-grid">
        <section className="settings-panel wide-panel">
          <div className="settings-row-title"><FiTool /><h3>Max-login Health</h3></div>
          <p className="settings-muted">Automatic maintenance runs in the background: limits sync every 30 minutes; stale session cleanup every 15 minutes. Max-login 1 users use takeover mode, so a new device disconnects the old one instead of failing auth.</p>
          <div className="settings-kpis">
            <div><span>Users</span><strong>{totals.users ?? '-'}</strong></div>
            <div><span>Online</span><strong>{totals.online ?? '-'}</strong></div>
            <div><span>Full</span><strong>{totals.full ?? '-'}</strong></div>
            <div><span>Stale</span><strong>{totals.stale ?? '-'}</strong></div>
            <div><span>Takeover</span><strong>{totals.takeover_mode ?? '-'}</strong></div>
          </div>
          <div className="settings-actions">
            <button className="btn" disabled={busy} onClick={() => runAction('/maintenance/sync-limits')}>Sync limits now</button>
            <button className="btn btn-secondary" disabled={busy} onClick={() => runAction('/maintenance/clean-stale')}>Clean stale now</button>
          </div>
          <div className="table-container list-table-container health-table-wrap">
            <table className="list-table">
              <thead><tr><th>User</th><th>Active/Max</th><th>Mode</th><th>Status</th><th>Stale</th><th>Auth events</th></tr></thead>
              <tbody>
                {healthRows.map((row) => (
                  <tr key={row.name}>
                    <td>{row.name}</td>
                    <td><strong className="login-count">{row.active_connections}/{row.max_logins === 0 ? '∞' : row.max_logins}</strong></td>
                    <td>{row.mode}</td>
                    <td><span className={row.status === 'online' || row.status === 'idle' ? 'pill online' : 'pill'}>{row.status}</span></td>
                    <td>{row.stale_markers}</td>
                    <td>{row.auth_events}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section className="settings-panel">
          <div className="settings-row-title"><FiBell /><h3>Notification Center</h3></div>
          <p className="settings-muted">Live operational issues from nodes and users.</p>
          <div className="settings-list">
            {notifications.length ? notifications.map((n, i) => <p key={i} className={`notice ${n.level}`}>{n.title}</p>) : <p className="notice good">No active notifications</p>}
          </div>
        </section>

        <section className="settings-panel">
          <div className="settings-row-title"><FiShield /><h3>Security Summary</h3></div>
          <div className="settings-kpis">
            <div><span>Auth errors</span><strong>{security?.auth_errors ?? '-'}</strong></div>
            <div><span>Rejects</span><strong>{security?.rejects ?? '-'}</strong></div>
            <div><span>Stale markers</span><strong>{security?.stale_markers ?? '-'}</strong></div>
          </div>
          <div className="settings-list small">
            {(security?.last_errors || []).slice(0, 5).map((e, i) => <p key={i}>{e.time_tehran || ''} — {e.common_name}: {e.reason} ({e.active || '?'}/{e.limit || '?'})</p>)}
          </div>
        </section>

        <section className="settings-panel">
          <div className="settings-row-title"><FiActivity /><h3>Activity Log</h3></div>
          <p className="settings-muted">Recent admin actions recorded by OVManager.</p>
          <div className="settings-list small">
            {activity.length ? activity.map((a) => <p key={a.id}>{new Date(a.ts * 1000).toLocaleString()} — {a.actor || 'system'} — {a.action} {a.target || ''}</p>) : <p>No activity recorded yet.</p>}
          </div>
        </section>

        <section className="settings-panel">
          <div className="settings-row-title"><FiLink /><h3>Subscription Link</h3></div>
          <p className="settings-muted">Generated format used by the copy button in Users.</p>
          <code className="settings-code">{subExample}</code>
        </section>

        <section className="settings-panel">
          <div className="settings-row-title">{theme === 'dark' ? <FiMoon /> : <FiSun />}<h3>Appearance</h3></div>
          <p className="settings-muted">Switch between dark and light OVManager themes.</p>
          <button className="btn" type="button" onClick={toggleTheme}>{theme === 'dark' ? 'Use Light Mode' : 'Use Dark Mode'}</button>
        </section>

        <section className="settings-panel">
          <div className="settings-row-title"><FiAlertTriangle /><h3>Recommended Next</h3></div>
          <ul className="settings-bullets">
            <li>Add editable node geolocation fields for exact map placement.</li>
            <li>Add read/unread persistent notification state.</li>
            <li>Add dedicated Security and Activity pages when the log volume grows.</li>
          </ul>
        </section>
      </div>
    </div>
  );
};

export default Settings;
