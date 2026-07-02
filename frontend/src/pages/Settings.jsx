import { useEffect, useState } from 'react';
import { FiLink, FiMoon, FiSun, FiShield, FiServer } from 'react-icons/fi';
import apiClient from '../services/api';

const Settings = () => {
  const [settings, setSettings] = useState(null);
  const [theme, setTheme] = useState(() => localStorage.getItem('ovmanager-theme') || 'dark');

  useEffect(() => {
    apiClient.get('/server/settings')
      .then((res) => setSettings(res.data?.data || null))
      .catch(() => setSettings(null));
  }, []);

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
      </div>

      <div className="settings-grid">
        <section className="settings-panel settings-hero-panel">
          <div className="settings-icon"><FiShield /></div>
          <h3>OVManager</h3>
          <p>Control panel branding, subscription links and operational preferences.</p>
        </section>

        <section className="settings-panel">
          <div className="settings-row-title">
            <FiLink />
            <h3>Subscription Link</h3>
          </div>
          <p className="settings-muted">Generated format used by the copy button in Users.</p>
          <code className="settings-code">{subExample}</code>
        </section>

        <section className="settings-panel">
          <div className="settings-row-title">
            {theme === 'dark' ? <FiMoon /> : <FiSun />}
            <h3>Appearance</h3>
          </div>
          <p className="settings-muted">Switch between dark and light OVManager themes.</p>
          <button className="btn" type="button" onClick={toggleTheme}>
            {theme === 'dark' ? 'Use Light Mode' : 'Use Dark Mode'}
          </button>
        </section>

        <section className="settings-panel">
          <div className="settings-row-title">
            <FiServer />
            <h3>OVNode</h3>
          </div>
          <p className="settings-muted">Nodes are managed from the Nodes tab. Use per-node actions to download configs or check health.</p>
        </section>
      </div>
    </div>
  );
};

export default Settings;
