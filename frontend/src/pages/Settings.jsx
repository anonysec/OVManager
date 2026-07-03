import { useEffect, useState } from 'react';
import { FiActivity, FiAlertTriangle, FiBell, FiLink, FiMoon, FiShield, FiSun } from 'react-icons/fi';
import apiClient from '../services/api';

const Settings = () => {
  const [settings, setSettings] = useState(null);
  const [security, setSecurity] = useState(null);
  const [activity, setActivity] = useState([]);
  const [notifications, setNotifications] = useState([]);
  const [theme, setTheme] = useState(() => localStorage.getItem('ovmanager-theme') || 'dark');

  const load = async () => {
    const [settingsRes, securityRes, activityRes, notificationsRes] = await Promise.all([
      apiClient.get('/server/settings'),
      apiClient.get('/security/summary?hours=8'),
      apiClient.get('/activity/?limit=25'),
      apiClient.get('/notifications/'),
    ]);
    setSettings(settingsRes.data?.data || null);
    setSecurity(securityRes.data?.data || null);
    setActivity(activityRes.data?.data || []);
    setNotifications(notificationsRes.data?.data || []);
  };

  useEffect(() => { load().catch(() => {}); }, []);

  const toggleTheme = () => {
    const next = theme === 'dark' ? 'light' : 'dark';
    setTheme(next);
    document.documentElement.dataset.theme = next;
    localStorage.setItem('ovmanager-theme', next);
  };

  const subExample = settings
    ? `${settings.subscription_url_prefix}${settings.subscription_path ? `${settings.subscription_path}/` : ''}{user_uuid}`
    : 'Loading...';

  return (
    <div id="settings-view" className="view settings-page">
      <div className="view-header">
        <h2>Settings</h2>
        <button className="btn" type="button" onClick={() => load().catch(() => {})}>Refresh</button>
      </div>

      <div className="settings-grid premium-settings-grid">
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
            {(security?.last_errors || []).slice(0, 5).map((e, i) => <p key={i}>{e.common_name}: {e.line}</p>)}
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
            <li>Connect real threat/intelligence feed if needed.</li>
            <li>Add persistent traffic history snapshots for 24h/7d charts.</li>
            <li>Add editable node geolocation fields for exact map placement.</li>
          </ul>
        </section>
      </div>
    </div>
  );
};

export default Settings;
