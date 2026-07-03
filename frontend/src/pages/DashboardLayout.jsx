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
          <button type="button" onClick={changeLanguage} title={t('language', 'Language')}><FiGlobe /></button>
          <button type="button" onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')} title={t('theme', 'Theme')}>
            {theme === 'dark' ? <FiSun /> : <FiMoon />}
          </button>
          <NavLink to="/settings" className="ops-settings-link" title={t('settings', 'Settings')}><FiSettings /></NavLink>
          <div className="notification-wrap">
            <button type="button" className={`ops-bell ${alerts.length ? 'has-alerts' : ''}`} title={alerts.length ? alerts.join('\n') : 'No alerts'}>
              <FiBell />{alerts.length > 0 && <span>{alerts.length}</span>}
            </button>
            {alerts.length > 0 && <div className="notification-popover">{alerts.map((a) => <p key={a}>{a}</p>)}</div>}
          </div>
          <div className="ops-profile" title={`${username} (${account.type || userRole || 'admin'})`}><span>{initials}</span><b>{username}</b></div>
          <button type="button" onClick={logout} title={t('logout', 'Logout')}><FiLogOut /></button>
        </div>
      </header>
      <main className="ops-main">
        <Outlet />
      </main>
      <div className="toast-stack">
        {toasts.map((toast) => <div className="toast" key={toast.id}><strong>{toast.status || 'Error'}</strong><span>{toast.message}</span></div>)}
      </div>
    </div>
  );
};

export default DashboardLayout;
