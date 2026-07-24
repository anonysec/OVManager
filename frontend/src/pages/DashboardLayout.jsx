import { Outlet, NavLink } from 'react-router-dom';
import { useEffect, useMemo, useState, useRef } from 'react';
import { useAuth } from '../context/AuthContext';
import { useTheme } from '../context/ThemeContext';
import { LiveProvider } from '../context/LiveContext';
import { useTranslation } from 'react-i18next';
import { FiBell, FiGlobe, FiMoon, FiSun, FiSettings, FiLogOut, FiUser } from 'react-icons/fi';
import apiClient from '../services/api';
import Logo from '../components/Logo';

const DashboardLayout = () => {
  const { logout, userRole } = useAuth();
  const { theme, setTheme } = useTheme();
  const { i18n, t } = useTranslation();
  const [notifications, setNotifications] = useState([]);
  const [notifOpen, setNotifOpen] = useState(false);
  const [langOpen, setLangOpen] = useState(false);
  const langRef = useRef(null);

  const tokenPayload = (() => {
    try {
      const token = localStorage.getItem('authToken');
      if (!token) return {};
      return JSON.parse(atob(token.split('.')[1] || ''));
    } catch { return {}; }
  })();
  const username = tokenPayload.sub || 'admin';

  // Keep document direction in sync with the active language and persist it,
  // so Farsi (RTL) survives navigation/refresh (not just the toggle click).
  useEffect(() => {
    const lang = i18n.language || 'en';
    const dir = lang.startsWith('fa') ? 'rtl' : 'ltr';
    document.documentElement.dir = dir;
    document.documentElement.lang = lang;
    localStorage.setItem('ovmanager-lang', lang);
  }, [i18n.language]);

  useEffect(() => {
    if (!notifOpen && !langOpen) return;
    const onDoc = (e) => {
      if (!e.target.closest('.notification-wrap')) setNotifOpen(false);
      if (!e.target.closest('.lang-picker-wrap')) setLangOpen(false);
    };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, [notifOpen, langOpen]);

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

  const navItems = useMemo(() => {
    const adminOnly = userRole === 'main_admin' ? [{ to: '/admins', label: t('admins', 'Admins') }] : [];
    return [
      { to: '/', label: t('dashboard', 'Dashboard'), end: true },
      { to: '/users', label: t('users', 'Users') },
      { to: '/nodes', label: t('nodes', 'Nodes') },
      ...adminOnly,
    ];
  }, [t, userRole]);

  const notifCount = notifications.length;
  const levelClass = (lvl) => (lvl === 'danger' ? 'danger' : lvl === 'info' ? 'info' : 'warning');

  return (
    <LiveProvider>
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
          <div className="lang-picker-wrap" ref={langRef}>
            <button type="button" className={`lang-picker-btn${langOpen ? ' active' : ''}`} onClick={() => setLangOpen(o => !o)} title={t('language', 'Language')}>
              <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" width="18" height="18">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M3 5h12M9 3v2m1.048 9.5A18.022 18.022 0 016.412 9m6.088 9h7M11 21l5-10 5 10M12.751 5C11.783 10.77 8.07 15.61 3 18.129" />
              </svg>
            </button>
            <div className={`lang-dropdown${langOpen ? ' open' : ''}`}>
              <button className={`lang-option${i18n.language === 'fa' ? ' active' : ''}`} onClick={() => { i18n.changeLanguage('fa'); document.documentElement.dir = 'rtl'; localStorage.setItem('ovmanager-lang', 'fa'); setLangOpen(false); }}>
                <span className="lang-flag-svg"><svg viewBox="0 0 24 24"><rect width="24" height="8" y="0" fill="#239f40"/><rect width="24" height="8" y="8" fill="#fff"/><rect width="24" height="8" y="16" fill="#da0000"/><g transform="translate(12,12)"><circle r="2.6" fill="#d62828"/><g fill="#f4d35e"><circle r="2"/><polygon points="0,-7 1,-4 -1,-4"/><polygon points="0,7 1,4 -1,4"/><polygon points="-7,0 -4,1 -4,-1"/><polygon points="7,0 4,1 4,-1"/></g></g></svg></span>
                <span>فارسی</span>
                {i18n.language === 'fa' && <span className="lang-check">✓</span>}
              </button>
              <button className={`lang-option${i18n.language === 'en' ? ' active' : ''}`} onClick={() => { i18n.changeLanguage('en'); document.documentElement.dir = 'ltr'; localStorage.setItem('ovmanager-lang', 'en'); setLangOpen(false); }}>
                <span className="lang-flag-svg"><svg viewBox="0 0 24 24"><rect width="24" height="24" fill="#fff"/><rect width="24" height="2.4" y="0" fill="#b22234"/><rect width="24" height="2.4" y="4.8" fill="#b22234"/><rect width="24" height="2.4" y="9.6" fill="#b22234"/><rect width="24" height="2.4" y="14.4" fill="#b22234"/><rect width="24" height="2.4" y="19.2" fill="#b22234"/><rect width="11" height="13" x="0" y="0" fill="#3c3b6e"/><g fill="#fff"><circle cx="2" cy="2.2" r="0.9"/><circle cx="5" cy="2.2" r="0.9"/><circle cx="8" cy="2.2" r="0.9"/><circle cx="2" cy="5.5" r="0.9"/><circle cx="5" cy="5.5" r="0.9"/><circle cx="8" cy="5.5" r="0.9"/><circle cx="3.5" cy="8.8" r="0.9"/><circle cx="6.5" cy="8.8" r="0.9"/></g></svg></span>
                <span>English</span>
                {i18n.language === 'en' && <span className="lang-check">✓</span>}
              </button>
              <button className={`lang-option${i18n.language === 'ru' ? ' active' : ''}`} onClick={() => { i18n.changeLanguage('ru'); document.documentElement.dir = 'ltr'; localStorage.setItem('ovmanager-lang', 'ru'); setLangOpen(false); }}>
                <span className="lang-flag-svg"><svg viewBox="0 0 24 24"><rect width="24" height="8" y="0" fill="#fff"/><rect width="24" height="8" y="8" fill="#0039a6"/><rect width="24" height="8" y="16" fill="#da291c"/></svg></span>
                <span>Русский</span>
                {i18n.language === 'ru' && <span className="lang-check">✓</span>}
              </button>
              <button className={`lang-option${i18n.language === 'cn' ? ' active' : ''}`} onClick={() => { i18n.changeLanguage('cn'); document.documentElement.dir = 'ltr'; localStorage.setItem('ovmanager-lang', 'cn'); setLangOpen(false); }}>
                <span className="lang-flag-svg"><svg viewBox="0 0 24 24"><rect width="24" height="24" fill="#de2910"/><polygon points="5,4 6.2,7.2 9.6,7.2 6.8,9.2 7.8,12.4 5,10.3 2.2,12.4 3.2,9.2 0.4,7.2 3.8,7.2" fill="#ffde00"/><g fill="#ffde00"><polygon points="17,5 17.7,6.6 19.4,6.6 18,7.7 18.6,9.3 17,8.2 15.4,9.3 16,7.7 14.6,6.6 16.3,6.6"/><polygon points="19.5,8.5 20.2,10.1 21.9,10.1 20.5,11.2 21.1,12.8 19.5,11.7 17.9,12.8 18.5,11.2 17.1,10.1 18.8,10.1"/></g></svg></span>
                <span>中文</span>
                {i18n.language === 'cn' && <span className="lang-check">✓</span>}
              </button>
            </div>
          </div>
          <button type="button" className="icon-btn" onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')} title={t('theme', 'Theme')} aria-label={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}>
            {theme === 'dark' ? <FiSun /> : <FiMoon />}
          </button>
          <NavLink to="/settings" className="ops-settings-link" title={t('settings', 'Settings')} aria-label="Settings"><FiSettings /></NavLink>
          <div className="notification-wrap">
            <button
              type="button"
              className={`ops-bell${notifCount ? ' has-alerts' : ''}`}
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
                  const urlpath = import.meta.env.VITE_URLPATH || '';
                    const prefix = urlpath ? `/${urlpath}` : '';
                    const href = n.id?.startsWith('node-') ? `${prefix}/nodes?node=${n.id.replace('node-','')}`
                      : n.id?.startsWith('exp-') || n.id?.startsWith('full-') || n.id?.startsWith('inact-') ? `${prefix}/users?user=${n.id.replace(/^(exp|full|inact)-/, '')}`
                      : `${prefix}/settings`;
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
          <div className="ops-user-corner">
            <div className="ops-profile" title={`${t('loggedInAs') || 'Logged in as'}: ${username}`}>
              <span className="avatar-xs">{username.slice(0, 1).toUpperCase()}</span>
              <span className="ops-username">{username}</span>
              <span className="ops-role-badge">{userRole === 'main_admin' ? 'Admin' : 'Op'}</span>
            </div>
            <button type="button" className="ops-logout-btn" onClick={logout} title={t('logout')} aria-label={t('logout')}><FiLogOut /></button>
          </div>
        </div>
      </header>
      <main id="main-content" className="ops-main" tabIndex="-1">
        <Outlet />
      </main>
    </div>
      </LiveProvider>
  );
};

export default DashboardLayout;