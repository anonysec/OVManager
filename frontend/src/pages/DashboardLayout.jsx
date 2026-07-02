import { Outlet } from 'react-router-dom';
import Sidebar from '../components/Sidebar';
import MobileNav from '../components/MobileNav'; 
import { useAuth } from '../context/AuthContext';
import { useTranslation } from 'react-i18next';
import { useEffect, useState } from 'react';
import { FiLogOut, FiRefreshCw, FiGlobe, FiMoon, FiSun } from 'react-icons/fi';
import logoSrc from '../assets/ovmanager-character.webp'; 

const DashboardLayout = () => {
  const { logout } = useAuth();
  const { t, i18n } = useTranslation();
  const [theme, setTheme] = useState(() => localStorage.getItem('ovmanager-theme') || 'dark');

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem('ovmanager-theme', theme);
  }, [theme]);

  const toggleTheme = () => setTheme((current) => (current === 'dark' ? 'light' : 'dark'));

  const handleRefresh = () => {
    window.location.reload();
  };

  const changeLanguage = () => {
    const newLang = i18n.language === 'en' ? 'fa' : 'en';
    i18n.changeLanguage(newLang);
    document.documentElement.dir = newLang === 'fa' ? 'rtl' : 'ltr';
  };

  return (
    <div id="main-container">
      <Sidebar />
      <div className="content-wrapper">
        <header className="main-header">
          {/* Logo container, visible only on mobile */}
          <div className="header-logo-container">
            <img src={logoSrc} alt="Panel Logo" className="header-logo" />
          </div>
          <div className="header-actions">
            <button onClick={changeLanguage} className="action-btn" title="Language">
              <FiGlobe size={18} />
            </button>
            <button onClick={toggleTheme} className="action-btn" title={theme === 'dark' ? 'Light mode' : 'Dark mode'}>
              {theme === 'dark' ? <FiSun size={18} /> : <FiMoon size={18} />}
            </button>
            <button onClick={handleRefresh} className="action-btn" title="Refresh">
              <FiRefreshCw size={18} />
            </button>
            <button onClick={logout} className="btn btn-danger" style={{width: 'auto', display: 'flex', alignItems: 'center', gap: '8px', padding: '8px 16px'}}>
              <FiLogOut />
              <span className="logout-text">{t('logout')}</span>
            </button>
          </div>
        </header>
        <main>
          <Outlet />
        </main>
      </div>
      <MobileNav />
    </div>
  );
};

export default DashboardLayout;