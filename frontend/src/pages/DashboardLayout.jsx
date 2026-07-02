import { Outlet, NavLink } from 'react-router-dom';
import { useEffect, useState } from 'react';
import { useAuth } from '../context/AuthContext';
import { useTranslation } from 'react-i18next';
import { FiGrid, FiUsers, FiServer, FiSettings, FiLogOut, FiRefreshCw, FiGlobe, FiMoon, FiSun, FiShield } from 'react-icons/fi';
import logoSrc from '../assets/ovmanager-character.webp';

const DashboardLayout = () => {
  const { logout, userRole } = useAuth();
  const { i18n } = useTranslation();
  const [theme, setTheme] = useState(() => localStorage.getItem('ovmanager-theme') || 'dark');

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem('ovmanager-theme', theme);
  }, [theme]);

  const navItems = [
    { to: '/', label: 'Dashboard', icon: <FiGrid />, end: true },
    { to: '/users', label: 'Users', icon: <FiUsers /> },
    ...(userRole !== 'admin' ? [{ to: '/nodes', label: 'Nodes', icon: <FiServer /> }] : []),
    ...(userRole === 'main_admin' ? [{ to: '/admins', label: 'Admins', icon: <FiShield /> }] : []),
    { to: '/settings', label: 'Settings', icon: <FiSettings /> },
  ];

  const changeLanguage = () => {
    const next = i18n.language === 'en' ? 'fa' : 'en';
    i18n.changeLanguage(next);
    document.documentElement.dir = next === 'fa' ? 'rtl' : 'ltr';
  };

  return (
    <div className="ov-shell">
      <header className="ov-topbar">
        <div className="ov-brand">
          <img src={logoSrc} alt="OVManager" />
          <div>
            <strong>OVManager</strong>
            <span>OpenVPN Operations</span>
          </div>
        </div>

        <nav className="ov-tabs" aria-label="Primary navigation">
          {navItems.map((item) => (
            <NavLink key={item.to} to={item.to} end={item.end} className="ov-tab">
              {item.icon}
              <span>{item.label}</span>
            </NavLink>
          ))}
        </nav>

        <div className="ov-actions">
          <button type="button" className="ov-icon-btn" onClick={changeLanguage} title="Language"><FiGlobe /></button>
          <button type="button" className="ov-icon-btn" onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')} title="Theme">
            {theme === 'dark' ? <FiSun /> : <FiMoon />}
          </button>
          <button type="button" className="ov-icon-btn" onClick={() => window.location.reload()} title="Refresh"><FiRefreshCw /></button>
          <button type="button" className="ov-logout" onClick={logout}><FiLogOut /> Logout</button>
        </div>
      </header>

      <section className="ov-hero-strip">
        <div>
          <span className="ov-eyebrow">Live control center</span>
          <h1>Manage users, nodes and traffic without noise.</h1>
        </div>
        <div className="ov-hero-metrics">
          <span>OVManager</span>
          <strong>v2 UI</strong>
        </div>
      </section>

      <main className="ov-main">
        <Outlet />
      </main>
    </div>
  );
};

export default DashboardLayout;
