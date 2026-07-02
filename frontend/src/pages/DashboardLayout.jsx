import { Outlet, NavLink } from 'react-router-dom';
import { useEffect, useState } from 'react';
import { useAuth } from '../context/AuthContext';
import { useTranslation } from 'react-i18next';
import { FiBell, FiLogOut, FiGlobe, FiMoon, FiSun, FiSettings } from 'react-icons/fi';
import logoSrc from '../assets/ovmanager-character.webp';

const DashboardLayout = () => {
  const { logout } = useAuth();
  const { i18n } = useTranslation();
  const [theme, setTheme] = useState(() => localStorage.getItem('ovmanager-theme') || 'dark');

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem('ovmanager-theme', theme);
  }, [theme]);

  const navItems = [
    { to: '/', label: 'Dashboard', end: true },
    { to: '/users', label: 'Users' },
    { to: '/nodes', label: 'Servers' },
    { to: '/nodes', label: 'Network' },
    { to: '/settings', label: 'Security' },
    { to: '/users', label: 'Activity' },
    { to: '/settings', label: 'Settings' },
  ];

  const changeLanguage = () => {
    const next = i18n.language === 'en' ? 'fa' : 'en';
    i18n.changeLanguage(next);
    document.documentElement.dir = next === 'fa' ? 'rtl' : 'ltr';
  };

  return (
    <div className="ops-shell">
      <header className="ops-topbar">
        <div className="ops-brand">
          <span className="ops-logo-mark" />
          <strong><span>OV</span>Manager</strong>
          <img src={logoSrc} alt="OVManager character" />
        </div>

        <nav className="ops-nav">
          {navItems.map((item) => (
            <NavLink key={`${item.label}-${item.to}`} to={item.to} end={item.end} className="ops-nav-link">
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div className="ops-userbar">
          <button type="button" onClick={changeLanguage} title="Language"><FiGlobe /></button>
          <button type="button" onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')} title="Theme">
            {theme === 'dark' ? <FiSun /> : <FiMoon />}
          </button>
          <button type="button" title="Settings"><FiSettings /></button>
          <button type="button" className="ops-bell" title="Alerts"><FiBell /></button>
          <div className="ops-profile"><span>AR</span><b>Alex R.</b></div>
          <button type="button" onClick={logout} title="Logout"><FiLogOut /></button>
        </div>
      </header>
      <main className="ops-main">
        <Outlet />
      </main>
    </div>
  );
};

export default DashboardLayout;
