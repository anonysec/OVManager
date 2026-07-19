import { Outlet, NavLink } from 'react-router-dom';
import { useEffect, useMemo, useState } from 'react';
import { useAuth } from '../context/AuthContext';
import { useTranslation } from 'react-i18next';
import { FiBell, FiGlobe, FiMoon, FiSun, FiSettings } from 'react-icons/fi';
import apiClient, { API_ERROR_EVENT } from '../services/api';
import Logo from '../components/Logo';

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
  const [notifications, setNotifications] = useState([]);
  const [notifOpen, setNotifOpen] = useState(false);
  const [toasts, setToasts] = useState([]);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem('ovmanager-theme', theme);
  }, [theme]);

  useEffect(() => {
    if (!notifOpen) return;
    const onDoc = (e) => {
      if (!e.target.closest('.notification-wrap')) setNotifOpen(false);
    };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, [notifOpen]);

  const skipToContent = (e) => {
    const main = document.querySelector('.ops-main');
    if (main) {
      main.setAttribute('tabindex', '-1');
      main.focus();
    }
  };

  // Real, useful notification center: derived from live operational data
  // (offline nodes, expiring/inactive/max-login users, auth anomalies).
  const loadNotifications = async () => {
    try {
      const [usersRes, nodesRes, secRes] = await Promise.all([
        apiClient.get('/users/'),
        apiClient.get('/nodes/'),
        apiClient.get('/security/summary?hours=8'),
      ]);
      const users = usersRes.data?.data || [];
      const nodes = nodesRes.data?.data || [];
      const security = secRes.data?.data || {};
      // Probe node reachability (short timeout, non-blocking)
      const ns = await Promise.all(nodes.map(async (n) => {
        if (!n.status) return [n.id, { status: 'inactive' }];
        try {
          const r = await apiClient.get(`/nodes/${n.id}/status/`, { timeout: 4000 });
          return [n.id, r.data?.data || {}];
        } catch { return [n.id, { status: 'unreachable', node_info: undefined, session_diagnostics: undefined }]; }
      }));
      const nodeStatus = Object.fromEntries(ns);

      const out = [];
      nodes.forEach((n) => {
        const st = nodeStatus[n.id] || {};
        if (n.status && (st.node_info === undefined || st.session_diagnostics === undefined)) {
          out.push({ id: `node-${n.id}`, level: 'danger', title: `Node ${n.name} unreachable`, detail: 'No API response from OVNode', action: null, action_path: null });
        }
      });
      const now = new Date();
      users.forEach((u) => {
        const exp = new Date(u.expiry_date);
        const d = Math.ceil((exp - now) / 86400000);
        if (Number(u.max_logins || 0) > 0 && Number(u.active_connections || 0) >= Number(u.max_logins)) {
          out.push({ id: `full-${u.uuid}`, level: 'warning', title: `User ${u.name} at max logins`, detail: `${u.active_connections}/${u.max_logins} sessions`, action: null, action_path: null });
        }
      });
      if (Number(security.auth_errors || 0) > 0) out.push({ id: 'auth', level: 'danger', title: `${security.auth_errors} auth errors (8h)`, detail: 'Failed authentications across nodes', action: null, action_path: null });
      if (Number(security.rejects || 0) > 0) out.push({ id: 'rej', level: 'warning', title: `${security.rejects} connection rejects (8h)`, detail: 'OVNode connection rejects', action: null, action_path: null });
      setNotifications(out);
    } catch {
      // keep existing; API interceptor surfaces real errors as toasts
    }
  };

  useEffect(() => {
    loadNotifications();
    const id = setInterval(() => { if (document.visibilityState === 'visible') loadNotifications(); }, 30000);
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

  const navItems = useMemo(() => (
    [
      { to: '/', label: t('dashboard', 'Dashboard'), end: true },
      { to: '/users', label: t('users', 'Users') },
      { to: '/nodes', label: t('nodes', 'Nodes') },
      ...(userRole === 'main_admin' ? [{ to: '/audit', label: t('audit', 'Audit') }] : []),
    ]
  ), [t, userRole]);

  const changeLanguage = () => {
    const next = i18n.language === 'en' ? 'fa' : 'en';
    i18n.changeLanguage(next);
    document.documentElement.dir = next === 'fa' ? 'rtl' : 'ltr';
  };

  const notifCount = notifications.length;
  const levelClass = (lvl) => (lvl === 'danger' ? 'danger' : lvl === 'info' ? 'info' : 'warning');

  return (
    <div className="ops-shell">
      <a href="#main-content" className="skip-link" onClick={skipToContent}>Skip to content</a>
      <header className="ops-topbar" role="banner">
        <div className="ops-brand">
          <Logo size={40} />
          <strong>OV<span className="brand-accent">Manager</span></strong>
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
            <button
              type="button"
              className={`ops-bell ${notifCount ? 'has-alerts' : ''}`}
              aria-label={notifCount ? t('youHaveNotif', { count: notifCount }) : t('noNotif')}
              aria-expanded={notifOpen}
              onClick={() => setNotifOpen((o) => !o)}
            >
              <FiBell />{notifCount > 0 && <span>{notifCount > 9 ? '9+' : notifCount}</span>}
            </button>
            <div className={`notification-popover ${notifOpen ? 'is-open' : ''}`} role="dialog" aria-label={t('notifTitle')}>
              <div className="notif-head">
                <strong>{t('notifTitle')}</strong>
                {notifCount > 0 && <button type="button" className="notif-refresh" onClick={loadNotifications} aria-label={t('notifRefresh')}>↻</button>}
              </div>
              {notifCount === 0 ? (
                <p className="notification-empty">{t('notifEmpty')}</p>
              ) : (
                notifications.map((n, i) => {
                  const href = n.id?.startsWith('node-') ? `/dash/nodes?node=${n.id.replace('node-','')}`
                    : n.id?.startsWith('exp-') || n.id?.startsWith('full-') || n.id?.startsWith('inact-') ? `/dash/users?user=${n.id.replace(/^(exp|full|inact)-/, '')}`
                    : '/dash/settings';
                  return (
                    <a key={n.id ?? i} href={href} className={`notification-item ${levelClass(n.level)}`} onClick={() => setNotifOpen(false)}>
                      <span className="dot" />
                      <div>
                        <div className="n-title">{n.title}</div>
                        {n.detail && <div className="n-time">{n.detail}</div>}
                      </div>
                    </a>
                  );
                })
              )}
            </div>
          </div>
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