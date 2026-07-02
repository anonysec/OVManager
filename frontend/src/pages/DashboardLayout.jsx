import { Outlet, NavLink } from 'react-router-dom';
import { useEffect, useState } from 'react';
import { useAuth } from '../context/AuthContext';
import { useTranslation } from 'react-i18next';
import { FiBell, FiLogOut, FiGlobe, FiMoon, FiSun, FiSettings } from 'react-icons/fi';
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
    { to: '/', label: i18n.language === 'fa' ? 'داشبورد' : 'Dashboard', end: true },
    { to: '/users', label: i18n.language === 'fa' ? 'کاربران' : 'Users' },
    { to: '/nodes', label: i18n.language === 'fa' ? 'نودها' : 'Nodes' },
    ...(userRole === 'main_admin' ? [{ to: '/admins', label: i18n.language === 'fa' ? 'ادمین‌ها' : 'Admins' }] : []),
    { to: '/settings', label: i18n.language === 'fa' ? 'تنظیمات' : 'Settings' },
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
