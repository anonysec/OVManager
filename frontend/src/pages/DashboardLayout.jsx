import { Outlet, NavLink } from 'react-router-dom';
import { useEffect, useMemo, useState } from 'react';
import { useAuth } from '../context/AuthContext';
import { useTranslation } from 'react-i18next';
import { FiBell, FiLogOut, FiGlobe, FiMoon, FiSun, FiSettings } from 'react-icons/fi';
import apiClient, { API_ERROR_EVENT } from '../services/api';
import logoSrc from '../assets/ovmanager-character.webp';

const readTokenPayload = () => {
  try {
    const token = localStorage.getItem('authToken');
    if (!token) return {};
    return JSON.parse(atob(token.split('.')[1] || ''));
  } catch {
    return {};
  }
};

const DashboardLayout = () => {
  const { logout, userRole } = useAuth();
  const { i18n, t } = useTranslation();
  const [theme, setTheme] = useState(() => localStorage.getItem('ovmanager-theme') || 'dark');
  const [account, setAccount] = useState(() => readTokenPayload());
  const [alerts, setAlerts] = useState([]);
  const [toasts, setToasts] = useState([]);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem('ovmanager-theme', theme);
  }, [theme]);

  useEffect(() => {
    setAccount(readTokenPayload());
  }, []);

  // Skip to content handler
  const skipToContent = (e) => {
    const main = document.querySelector('.ops-main');
    if (main) {
      main.setAttribute('tabindex', '-1');
      main.focus();
    }
  };

  useEffect(() => {
    const loadAlerts = async () => {
      try {
        const [nodesRes, usersRes] = await Promise.all([apiClient.get('/nodes/'), apiClient.get('/users/')]);
        const nodes = nodesRes.data?.data || [];
        const users = usersRes.data?.data || [];
        const next = [];
        const offline = nodes.filter((n) => !n.status);
        if (offline.length) next.push(`${offline.length} node(s) offline`);
        const full = users.filter((u) => Number(u.max_logins || 0) > 0 && Number(u.active_connections || 0) >= Number(u.max_logins || 0));
        if (full.length) next.push(`${full.length} user(s) at max logins`);
        const expired = users.filter((u) => u.is_active === false);
        if (expired.length) next.push(`${expired.length} inactive user(s)`);
        setAlerts(next);
      } catch {
        // api interceptor shows error toast
      }
    };
    loadAlerts();
    const id = setInterval(loadAlerts, 60000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    const onApiError = (event) => {
      const id = `${Date.now()}-${Math.random()}`;
      setToasts((items) => [...items.slice(-2), { id, ...event.detail }]);
      setTimeout(() => setToasts((items) => items.filter((item) => item.id !== id)), 5200);
    };
    window.addEventListener(API_ERROR_EVENT, onApiError);
    return () => window.removeEventListener(API_ERROR_EVENT, onApiError);
  }, []);

  const navItems = useMemo(() => ([
    { to: '/', label: t('dashboard', 'Dashboard'), end: true },
    { to: '/users', label: t('users', 'Users') },
    { to: '/nodes', label: t('nodes', 'Nodes') },
    ...(userRole === 'main_admin' ? [{ to: '/admins', label: t('admins', 'Admins') }] : []),
  ]), [t, userRole]);

  const changeLanguage = () => {
    const next = i18n.language === 'en' ? 'fa' : 'en';
    i18n.changeLanguage(next);
    document.documentElement.dir = next === 'fa' ? 'rtl' : 'ltr';
  };

  const username = account.sub || 'Admin';
  const initials = username.slice(0, 2).toUpperCase();

  return (
    <div className="ops-shell">
      <a href="#main-content" className="skip-link" onClick={skipToContent}>Skip to content</a>
      <header className="ops-topbar" role="banner">
        <div className="ops-brand">
          <span className="ops-logo-mark" aria-hidden="true" />
          <strong><span>OV</span>Manager</strong>
          <img src={logoSrc} alt="OVManager character logo" />
        </div>

        <nav className="ops-nav" aria-label="Main navigation">
          {navItems.map((item) => (
            <NavLink key={`${item.label}-${item.to}`} to={item.to} end={item.end} className="ops-nav-link">
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div className="ops-userbar">
          <button type="button" onClick={changeLanguage} title={t('language', 'Language')} aria-label="Change language"><FiGlobe /></button>
          <button type="button" onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')} title={t('theme', 'Theme')} aria-label={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}>
            {theme === 'dark' ? <FiSun /> : <FiMoon />}
          </button>
          <NavLink to="/settings" className="ops-settings-link" title={t('settings', 'Settings')} aria-label="Settings"><FiSettings /></NavLink>
          <div className="notification-wrap">
            <button type="button" className={`ops-bell ${alerts.length ? 'has-alerts' : ''}`} aria-label={alerts.length ? `You have ${alerts.length} alerts` : 'No alerts'}>
              <FiBell />{alerts.length > 0 && <span className="sr-only">{alerts.length} alerts</span>}
            </button>
            {alerts.length > 0 && <div className="notification-popover" role="status" aria-live="polite">{alerts.map((a) => <p key={a}>{a}</p>)}</div>}
          </div>
          <div className="ops-profile" title={`${username} (${account.type || userRole || 'admin'})`} aria-label={`User profile: ${username}, role: ${account.type || userRole || 'admin'}`}><span>{initials}</span><b>{username}</b></div>
          <button type="button" onClick={logout} title={t('logout', 'Logout')} aria-label="Logout"><FiLogOut /></button>
        </div>
      </header>
      <main id="main-content" className="ops-main" tabIndex="-1">
        <Outlet />
      </main>
      <div className="toast-stack" aria-live="polite" aria-atomic="true">
        {toasts.map((toast) => <div className="toast" key={toast.id} role="alert"><strong>{toast.status || 'Error'}</strong><span>{toast.message}</span></div>)}
      </div>
    </div>
  );
};

export default DashboardLayout;
