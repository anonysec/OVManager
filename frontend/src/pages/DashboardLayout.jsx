import { Outlet, NavLink, useLocation, Link } from 'react-router-dom';
import { useEffect, useState, useRef, useCallback, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { FiBell, FiMoon, FiSun, FiSearch, FiCommand, FiChevronDown, FiMonitor, FiSettings } from 'react-icons/fi';
import apiClient from '../services/api';
import { useAuth } from '../context/AuthContext';
import { useTheme } from '../context/ThemeContext';
import { LiveProvider } from '../context/LiveContext';
import { ToastProvider } from '../context/ToastContext';
import Sidebar from '../components/Sidebar';
import Logo from '../components/Logo';
import OnboardingChecklist from '../components/OnboardingChecklist';
import CommandPalette from '../components/CommandPalette';
import MobileNav from '../components/MobileNav';
import { readPrefs, alertPrefKey } from '../utils/notifPrefs';

const DashboardLayout = () => {
  const { userRole } = useAuth();
  const { theme, cycleTheme } = useTheme();
  const { i18n, t } = useTranslation();
  const [notifications, setNotifications] = useState([]);
  const [notifOpen, setNotifOpen] = useState(false);
  const [langOpen, setLangOpen] = useState(false);
  const langRef = useRef(null);
  const [profileOpen, setProfileOpen] = useState(false);
  const location = useLocation();

  const getPageTitle = (pathname) => {
    const map = {
      '/': t('navDashboard', 'Dashboard'),
      '/users': t('navUsers', 'Users'),
      '/nodes': t('navNodes', 'Nodes'),
      '/admins': t('navAdmins', 'Admins'),
      '/settings': t('navSettings', 'Settings'),
      '/audit': t('navAudit', 'Audit Log'),
      '/maintenance': t('navMaintenance', 'Maintenance'),
    };
    if (map[pathname]) return map[pathname];
    if (pathname.startsWith('/users')) return t('navUsers', 'Users');
    if (pathname.startsWith('/nodes')) return t('navNodes', 'Nodes');
    if (pathname.startsWith('/settings')) return t('navSettings', 'Settings');
    return t('navDashboard', 'Dashboard');
  };

  const tokenPayload = useMemo(() => {
    try {
      const token = localStorage.getItem('authToken');
      if (!token) return {};
      return JSON.parse(atob(token.split('.')[1] || ''));
    } catch { return {}; }
  }, []);
  const username = tokenPayload.sub || '';

  useEffect(() => {
    const lang = i18n.language || 'en';
    const dir = lang.startsWith('fa') ? 'rtl' : 'ltr';
    document.documentElement.dir = dir;
    document.documentElement.lang = lang;
    localStorage.setItem('ovmanager-lang', lang);
  }, [i18n.language]);

  useEffect(() => {
    if (!notifOpen && !langOpen && !profileOpen) return;
    const onDoc = (e) => {
      if (!e.target.closest('.notification-wrap')) setNotifOpen(false);
      if (!e.target.closest('.lang-picker-wrap')) setLangOpen(false);
      if (!e.target.closest('.profile-wrap')) setProfileOpen(false);
    };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, [notifOpen, langOpen, profileOpen]);

  const skipToContent = () => {
    const main = document.querySelector('.ops-main-content');
    if (main) {
      main.setAttribute('tabindex', '-1');
      main.focus();
    }
  };

  const openCommandPalette = () => {
    window.dispatchEvent(new CustomEvent('ovmanager:open-palette'));
  };

  // Notification bell: lightweight poll — avoids duplicating the heavy per-node
  // status calls that ServerStats already makes on the same 30-second cycle.
  // We only use the fast /nodes/ list (DB-side status flag) + /security/summary.
  // Per-node reachability checks belong in ServerStats, not in the topbar.
  const loadNotifications = useCallback(async () => {
    try {
      const [usersRes, nodesRes, secRes] = await Promise.all([
        apiClient.get('/users/'),
        apiClient.get('/nodes/'),
        apiClient.get('/security/summary?hours=8'),
      ]);
      const usersRaw = usersRes.data?.data;
      const users = Array.isArray(usersRaw) ? usersRaw : (usersRaw?.users || []);
      const nodesRaw = nodesRes.data?.data;
      const nodes = Array.isArray(nodesRaw) ? nodesRaw : (nodesRaw?.nodes || []);
      const security = secRes.data?.data || {};
      const out = [];
      // Surface nodes that are marked inactive in the DB
      nodes.forEach((n) => {
        if (!n.status) {
          out.push({ id: `node-${n.id}`, level: 'warning', title: `Node ${n.name} is disabled`, detail: 'Marked offline in panel database', action: null, action_path: null });
        }
      });
      users.forEach((u) => {
        if (Number(u.max_logins || 0) > 0 && Number(u.active_connections || 0) >= Number(u.max_logins)) {
          out.push({ id: `full-${u.uuid}`, level: 'warning', title: `User ${u.name} at max logins`, detail: `${u.active_connections}/${u.max_logins} sessions`, action: null, action_path: null });
        }
      });
      if (Number(security.auth_errors || 0) > 0) out.push({ id: 'auth', level: 'danger', title: `${security.auth_errors} auth errors (8h)`, detail: 'Failed authentications across nodes', action: null, action_path: null });
      if (Number(security.rejects || 0) > 0) out.push({ id: 'rej', level: 'warning', title: `${security.rejects} connection rejects (8h)`, detail: 'OVNode connection rejects', action: null, action_path: null });
      // Respect the "Alerts & Dashboard" preferences from Settings.
      const prefs = readPrefs();
      setNotifications(out.filter((n) => {
        const pref = alertPrefKey(n.id);
        return !pref || prefs[pref] !== false;
      }));
    } catch {
      // keep existing; API interceptor surfaces real errors as toasts
    }
  }, []);

  // Poll cadence comes from Settings → Alerts & Dashboard, and restarts
  // immediately when the preference changes.
  useEffect(() => {
    let id = null;
    const start = () => {
      if (id) clearInterval(id);
      const sec = readPrefs().refreshSec;
      id = setInterval(() => { if (document.visibilityState === 'visible') loadNotifications(); }, sec * 1000);
    };
    start();
    window.addEventListener('ovmanager-prefs-changed', start);
    return () => { if (id) clearInterval(id); window.removeEventListener('ovmanager-prefs-changed', start); };
  }, [loadNotifications]);

  const notifCount = notifications.length;
  const levelClass = (lvl) => (lvl === 'danger' ? 'danger' : lvl === 'info' ? 'info' : 'warning');
  const ThemeIcon = theme === 'light' ? FiSun : theme === 'dark' ? FiMoon : FiMonitor;
  const themeLabel = theme === 'light'
    ? t('lightMode', 'Light mode')
    : theme === 'dark'
      ? t('darkMode', 'Dark mode')
      : t('systemMode', 'System default');

  // Sync sidebar state across this layout and the Sidebar component so the
  // main-content margin matches the rendered sidebar width (220px / 72px collapsed)
  // and reacts to collapse toggles + viewport resizes without prop-drilling.
  const getIsMobile = useCallback(() => (typeof window !== 'undefined' && window.innerWidth < 768), []);
  const computeCollapsed = useCallback(() => (localStorage.getItem('ovmanager-sidebar-collapsed') === 'true' && !getIsMobile()), [getIsMobile]);
  const [collapsed, setCollapsed] = useState(computeCollapsed);
  const [isMobile, setIsMobile] = useState(getIsMobile);

  useEffect(() => {
    const applyCollapsed = () => setCollapsed(computeCollapsed());
    const onResize = () => {
      const mobile = getIsMobile();
      setIsMobile(mobile);
      applyCollapsed();
    };
    window.addEventListener('resize', onResize);
    window.addEventListener('storage', applyCollapsed);
    // Sidebar emits this custom event on toggle
    window.addEventListener('sidebar-pin-change', applyCollapsed);
    return () => {
      window.removeEventListener('resize', onResize);
      window.removeEventListener('storage', applyCollapsed);
      window.removeEventListener('sidebar-pin-change', applyCollapsed);
    };
  }, [computeCollapsed, getIsMobile]);

  const mainContentClass = [
    'ops-main-content',
    collapsed ? 'ops-main-content--collapsed' : '',
    isMobile ? 'ops-main-content--mobile' : '',
  ].filter(Boolean).join(' ');

  const urlPath = window.__OV_URLPATH__ || '';
  void urlPath; /* used for future URLPATH-based adjustments */

  return (
    <LiveProvider>
      <ToastProvider>
        <div className="ops-layout">
          <a href="#main-content" className="skip-link" onClick={skipToContent}>Skip to content</a>

          <Sidebar />

          <div className={`ops-main-container${collapsed ? ' ops-main-container--collapsed' : ''}${isMobile ? ' ops-main-container--mobile' : ''}`}>
            <header className="ops-topbar-minimal" role="banner">
              <div className="topbar-brand" aria-label="OVManager">
                <Logo size={30} />
                <span>OV<span className="brand-accent">Manager</span></span>
              </div>
              <nav className="ops-breadcrumb" aria-label="Breadcrumb">
                <ol>
                  {location.pathname !== '/' && (
                    <>
                      <li><Link to="/" className="ops-breadcrumb-link">{t('navDashboard', 'Dashboard')}</Link></li>
                      <li className="ops-breadcrumb-separator">/</li>
                    </>
                  )}
                  <li className="ops-current-page">{getPageTitle(location.pathname)}</li>
                </ol>
              </nav>
              <div className="ops-userbar">
                <button
                  type="button"
                  className="topbar-search-trigger"
                  onClick={openCommandPalette}
                  aria-label={t('palPlaceholder', 'Search pages, users, nodes…')}
                >
                  <FiSearch aria-hidden="true" />
                  <span>{t('palSearch', 'Search')}</span>
                  <kbd><FiCommand aria-hidden="true" />K</kbd>
                </button>
                <div className="lang-picker-wrap" ref={langRef}>
                  <button type="button" className={`icon-btn${langOpen ? ' active' : ''}`} onClick={() => setLangOpen(o => !o)} title={t('language', 'Language')} aria-label="Change language">
                    <LangIcon size={18} />
                  </button>
                  <div className={`lang-dropdown${langOpen ? ' open' : ''}`}>
                    <button className={`lang-option${i18n.language === 'fa' ? ' active' : ''}`} onClick={() => { i18n.changeLanguage('fa'); document.documentElement.dir = 'rtl'; localStorage.setItem('ovmanager-lang', 'fa'); setLangOpen(false); }}>
                      <FaFlagIcon />
                      <span>فارسی</span>
                      {i18n.language === 'fa' && <span className="lang-check">✓</span>}
                    </button>
                    <button className={`lang-option${i18n.language === 'en' ? ' active' : ''}`} onClick={() => { i18n.changeLanguage('en'); document.documentElement.dir = 'ltr'; localStorage.setItem('ovmanager-lang', 'en'); setLangOpen(false); }}>
                      <EnFlagIcon />
                      <span>English</span>
                      {i18n.language === 'en' && <span className="lang-check">✓</span>}
                    </button>
                    <button className={`lang-option${i18n.language === 'ru' ? ' active' : ''}`} onClick={() => { i18n.changeLanguage('ru'); document.documentElement.dir = 'ltr'; localStorage.setItem('ovmanager-lang', 'ru'); setLangOpen(false); }}>
                      <RuFlagIcon />
                      <span>Русский</span>
                      {i18n.language === 'ru' && <span className="lang-check">✓</span>}
                    </button>
                    <button className={`lang-option${i18n.language === 'cn' ? ' active' : ''}`} onClick={() => { i18n.changeLanguage('cn'); document.documentElement.dir = 'ltr'; localStorage.setItem('ovmanager-lang', 'cn'); setLangOpen(false); }}>
                      <ChinaFlagIcon />
                      <span>中文</span>
                      {i18n.language === 'cn' && <span className="lang-check">✓</span>}
                    </button>
                  </div>
                </div>
                <button type="button" className="icon-btn" onClick={cycleTheme} title={`${t('theme', 'Theme')}: ${themeLabel}`} aria-label={`${t('theme', 'Theme')}: ${themeLabel}`}>
                  <ThemeIcon aria-hidden="true" />
                </button>
                <div className="notification-wrap">
                  <button type="button" className={`icon-btn${notifCount ? ' has-alerts' : ''}`} aria-label={notifCount ? t('youHaveNotif', { count: notifCount }) : t('noNotif')} aria-expanded={notifOpen} onClick={() => setNotifOpen((o) => !o)}>
                    <FiBell />{notifCount > 0 && <span className="icon-btn-badge">{notifCount > 9 ? '9+' : notifCount}</span>}
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
                          <Link key={n.id ?? i} to={href.replace(window.location.origin, '')} className={`notification-item ${levelClass(n.level)}`} onClick={() => setNotifOpen(false)}>
                            <span className="dot" />
                            <div>
                              <div className="n-title">{n.title}</div>
                              {n.detail && <div className="n-time">{n.detail}</div>}
                            </div>
                          </Link>
                        );
                      })
                    )}
                  </div>
                </div>
                <div className="profile-wrap">
                  <button type="button" className={`profile-trigger${profileOpen ? ' active' : ''}`} onClick={() => setProfileOpen(o => !o)} aria-expanded={profileOpen} aria-haspopup="true" title={t('loggedInAs', 'Logged in as')}>
                    <span className="avatar-xs">{username.slice(0, 1).toUpperCase()}</span>
                    <span className="profile-trigger-copy">
                      <strong>{username}</strong>
                      <small>{userRole === 'owner' ? t('administrator', 'Administrator') : t('operator', 'Operator')}</small>
                    </span>
                    <FiChevronDown className={`profile-trigger-chevron${profileOpen ? ' is-open' : ''}`} aria-hidden="true" />
                  </button>
                  <div className={`profile-dropdown${profileOpen ? ' open' : ''}`} role="menu">
                    <div className="profile-dropdown-header">
                      <span className="avatar-sm">{username.slice(0, 1).toUpperCase()}</span>
                      <div>
                        <div className="profile-dropdown-name">{username}</div>
                        <div className="profile-dropdown-role">{userRole === 'owner' ? t('administrator', 'Administrator') : t('operator', 'Operator')}</div>
                      </div>
                    </div>
                    <div className="profile-dropdown-divider" />
                    {/* Settings is the only menu action — theme lives in the top bar
                        (one click, no open state) and logout lives at the bottom of
                        the sidebar, so duplicating either here adds noise. */}
                    <Link to="/settings" className="profile-dropdown-item" role="menuitem" onClick={() => setProfileOpen(false)}>
                      <FiSettings aria-hidden="true" />
                      <span>{t('navSettings', 'Settings')}</span>
                    </Link>
                  </div>
                </div>
              </div>
            </header>

            <main id="main-content" className={mainContentClass} tabIndex="-1">
              <OnboardingChecklist />
              <Outlet />
            </main>
          </div>

          <MobileNav />
          <CommandPalette userRole={userRole} />
          {/* Bottom safe-area spacer — keeps content above mobile keyboard / browser chrome */}
          <div className="bottom-safe-bar" aria-hidden="true" />
        </div>
      </ToastProvider>
    </LiveProvider>
  );
};

const LangIcon = ({ size = 16 }) => (
  <svg xmlns="http://www.w3.org/2000/svg" width={size} height={size} fill="none" viewBox="0 0 24 24" stroke="currentColor">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 21a9 9 0 100-18 9 9 0 000 18z" />
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M2 12h20" />
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 2a15.3 15.3 0 014 10 15.3 15.3 0 01-4 10 15.3 15.3 0 01-4-10 15.3 15.3 0 014-10z" />
  </svg>
);

const FaFlagIcon = () => (
  <svg viewBox="0 0 24 24" width="18" height="18">
    <rect width="24" height="8" y="0" fill="#239f40" />
    <rect width="24" height="8" y="8" fill="#fff" />
    <rect width="24" height="8" y="16" fill="#da0000" />
    <g transform="translate(12,12)">
      <circle r="2.6" fill="#d62828" />
      <g fill="#f4d35e">
        <circle r="2" /><polygon points="0,-7 1,-4 -1,-4" />
        <circle r="2" /><polygon points="0,7 1,4 -1,4" />
        <circle r="2" /><polygon points="-7,0 -4,1 -4,-1" />
        <circle r="2" /><polygon points="7,0 4,1 4,-1" />
      </g>
    </g>
  </svg>
);

const EnFlagIcon = () => (
  <svg viewBox="0 0 24 24" width="18" height="18">
    <rect width="24" height="24" fill="#fff" />
    <rect width="24" height="2.4" y="0" fill="#b22234" />
    <rect width="24" height="2.4" y="4.8" fill="#b22234" />
    <rect width="24" height="2.4" y="9.6" fill="#b22234" />
    <rect width="24" height="2.4" y="19.2" fill="#b22234" />
    <rect width="11" height="13" x="0" y="0" fill="#3c3b6e" />
    <g fill="#fff">
      <circle cx="2" cy="2.2" r="0.9" /><circle cx="5" cy="2.2" r="0.9" /><circle cx="8" cy="2.2" r="0.9" />
      <circle cx="2" cy="5.5" r="0.9" /><circle cx="5" cy="5.5" r="0.9" /><circle cx="8" cy="5.5" r="0.9" />
      <circle cx="2" cy="8.8" r="0.9" /><circle cx="5" cy="8.8" r="0.9" /><circle cx="6.5" cy="8.8" r="0.9" /><circle cx="9.5" cy="8.8" r="0.9" />
      <circle cx="3.5" cy="12.1" r="0.9" /><circle cx="6.5" cy="12.1" r="0.9" /><circle cx="9.5" cy="12.1" r="0.9" />
      <circle cx="2" cy="15.4" r="0.9" /><circle cx="5" cy="15.4" r="0.9" /><circle cx="8" cy="15.4" r="0.9" />
      <circle cx="8.5" cy="21.3" r="0.9" fill="#da0000" /><rect width="24" height="2.4" y="21.6" fill="#da0000" />
    </g>
  </svg>
);

const RuFlagIcon = () => (
  <svg viewBox="0 0 24 24" width="18" height="18">
    <rect width="24" height="8" y="0" fill="#fff" />
    <rect width="24" height="8" y="8" fill="#0039a6" />
    <rect width="24" height="8" y="16" fill="#da291c" />
  </svg>
);

const ChinaFlagIcon = () => (
  <svg viewBox="0 0 24 24" width="18" height="18">
    <rect width="24" height="24" fill="#de2910" />
    <polygon points="5,4 6.2,7.2 9.6,7.2 6.8,9.2 7.8,12.4 5,10.3 2.2,12.4 3.2,9.2 0.4,7.2 3.8,7.2" fill="#ffde00" />
    <g transform="translate(12,12)">
      <circle r="2.6" fill="#d62828" />
      <g fill="#f4d35e">
        <circle r="2" /><polygon points="0,-7 1,-4 -1,-4" />
        <circle r="2" /><polygon points="0,7 1,4 -1,4" />
        <polygon points="-7,0 -4,1 -4,-1" /><polygon points="7,0 4,1 4,-1" />
      </g>
    </g>
  </svg>
);

export default DashboardLayout;
