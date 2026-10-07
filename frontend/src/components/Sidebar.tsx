import { NavLink, useLocation } from 'react-router-dom';
import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import type { IconType } from 'react-icons';
import { useTranslation } from 'react-i18next';
import {
  FiHome, FiUsers, FiServer, FiSettings, FiLogOut, FiChevronLeft, FiChevronRight,
  FiMenu, FiList, FiBarChart2,
} from 'react-icons/fi';
import { useAuth } from '../context/AuthContext';
import { useLive } from '../context/LiveContext';
import apiClient from '../services/api';
import { asList } from '../utils/apiData';
import Logo from './Logo';

const readCollapsed = () => {
  try { return localStorage.getItem('ovmanager-sidebar-collapsed') === 'true'; }
  catch { return false; }
};

type NavItem = {
  to: string;
  label: string;
  icon: IconType;
  end?: boolean;
  group: string;
};

const Sidebar = () => {
  const { userRole, logout } = useAuth();
  const { t } = useTranslation();
  const location = useLocation();
  const { subscribe, unsubscribe } = useLive();
  const [collapsed, setCollapsed] = useState(readCollapsed);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [stats, setStats] = useState({ totalUsers: 0, totalUsage: 0 });
  const hamburgerRef = useRef<HTMLButtonElement | null>(null);
  const drawerRef = useRef<HTMLElement | null>(null);

  const username = useMemo(() => {
    try { return localStorage.getItem('username') || ''; }
    catch { return ''; }
  }, []);

  useEffect(() => {
    try { localStorage.setItem('ovmanager-sidebar-collapsed', String(collapsed)); } catch { /* private mode */ }
    window.dispatchEvent(new Event('sidebar-pin-change'));
  }, [collapsed]);

  useEffect(() => {
    const onResize = () => { if (window.innerWidth >= 768) setMobileOpen(false); };
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

  useEffect(() => {
    if (!mobileOpen) return undefined;
    drawerRef.current?.querySelector<HTMLElement>('a, button')?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setMobileOpen(false);
    };
    document.addEventListener('keydown', onKey);
    const trigger = hamburgerRef.current;
    return () => {
      document.removeEventListener('keydown', onKey);
      trigger?.focus();
    };
  }, [mobileOpen]);

  const fetchStats = useCallback(async () => {
    try {
      const [usersRes] = await Promise.all([
        apiClient.get('/users/'),
      ]);
      const users = asList(usersRes.data, 'users');
      const totalUsage = users.reduce((sum: number, u: any) => sum + Number(u.used || 0), 0);
      setStats({ totalUsers: users.length, totalUsage });
    } catch { /* ignore */ }
  }, []);

  useEffect(() => {
    if (userRole !== 'owner') {
      setStats({ totalUsers: 0, totalUsage: 0 });
      return undefined;
    }
    fetchStats();
    const u1 = subscribe('users.changed', fetchStats);
    const u2 = subscribe('users.created', fetchStats);
    const u3 = subscribe('users.deleted', fetchStats);
    return () => { u1(); u2(); u3(); };
  }, [subscribe, unsubscribe, fetchStats, userRole]);

  const toggleCollapse = useCallback(() => setCollapsed(c => !c), []);

  const isActive = (item: NavItem) => {
    if (item.end) return location.pathname === item.to;
    return location.pathname.startsWith(item.to);
  };
  const isActiveClass = (item: NavItem) => isActive(item) ? 'sidebar-nav-link active' : 'sidebar-nav-link';

  const isOwner = userRole === 'owner';

  const navItems: NavItem[] = [
    { to: '/',          label: t('navHome',     'Home'),     icon: FiHome,     end: true, group: t('navGroupOverview', 'Overview') },
    { to: '/users',     label: t('navUsers',    'Users'),    icon: FiUsers,              group: t('navGroupManage',   'Manage')   },
    ...(isOwner ? [
      { to: '/nodes',   label: t('navNodes',    'Nodes'),    icon: FiServer,             group: t('navGroupManage',   'Manage')   },
      { to: '/admins',  label: t('navAdmins',   'Admins'),   icon: FiList,               group: t('navGroupManage',   'Manage')   },
    ] : []),
    { to: '/settings',  label: t('navSettings', 'Settings'), icon: FiSettings,           group: t('navGroupSystem',   'System')   },
    ...(isOwner ? [
      { to: '/audit',   label: t('navAudit',    'Logs'),     icon: FiBarChart2,          group: t('navGroupSystem',   'System')   },
    ] : []),
  ];

  const renderNavItem = (item: NavItem, index: number) => (
    <li key={item.to} className="sidebar-nav-item">
      {(index === 0 || navItems[index - 1].group !== item.group) && (
        <span className="sidebar-section-label" aria-hidden={collapsed}>{item.group}</span>
      )}
      <NavLink
        to={item.to}
        end={item.end}
        className={isActiveClass(item)}
        onClick={() => mobileOpen && setMobileOpen(false)}
        title={collapsed ? item.label : undefined}
        aria-label={item.label}
      >
        <item.icon className="sidebar-nav-icon" aria-hidden="true" />
        <span className="sidebar-nav-label" aria-hidden={collapsed}>{item.label}</span>
      </NavLink>
    </li>
  );

  const formatUsage = (bytes: number) => {
    if (bytes >= 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
    if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    return `${bytes} B`;
  };

  return (
    <>
      <button
        ref={hamburgerRef}
        className="sidebar-hamburger"
        onClick={() => setMobileOpen(true)}
        aria-label={t('openNavigation', 'Open navigation')}
        aria-expanded={mobileOpen}
        aria-controls="ops-sidebar"
      >
        <FiMenu aria-hidden="true" />
      </button>

      {mobileOpen && (
        <div className="sidebar-mobile-overlay" onClick={() => setMobileOpen(false)} aria-hidden="true" />
      )}

      {/* Sidebar — full height: the brand lives here, so the top-left corner
          is never an empty notch beside the topbar. */}
      <aside
        ref={drawerRef}
        id="ops-sidebar"
        className={`ops-sidebar ${collapsed ? 'ops-sidebar--collapsed' : ''} ${mobileOpen ? 'ops-sidebar--mobile ops-sidebar--open' : ''}`}
        aria-label={t('mainNavigation', 'Main navigation')}
      >
        {/* In rail mode this collapses to the logo mark, wordmark hidden. */}
        <div className="sidebar-brand" aria-hidden={collapsed}>
          <Logo size={30} />
          <span className="sidebar-brand-text">OV<span className="brand-accent">Manager</span></span>
        </div>

        <button
          className="sidebar-toggle"
          onClick={toggleCollapse}
          aria-label={collapsed ? t('expandSidebar', 'Expand sidebar') : t('collapseSidebar', 'Collapse sidebar')}
          aria-expanded={!collapsed}
          aria-controls="ops-sidebar"
          title={collapsed ? t('expandSidebar', 'Expand sidebar') : t('collapseSidebar', 'Collapse sidebar')}
        >
          {collapsed ? <FiChevronRight aria-hidden="true" /> : <FiChevronLeft aria-hidden="true" />}
        </button>

        <nav className="sidebar-nav" aria-label={t('sidebarSections', 'Sections')}>
          <ul className="sidebar-nav-list">
            {navItems.map(renderNavItem)}
          </ul>
        </nav>

        <div className="sidebar-footer">
          <div className="sidebar-profile">
            <div className="sidebar-profile-avatar" title={collapsed ? username : undefined}>
              <span className="avatar-md" aria-hidden="true">{username.slice(0, 1).toUpperCase() || '?'}</span>
              <span className={`sidebar-profile-pulse ${isOwner ? 'is-owner' : 'is-operator'}`} aria-hidden="true" />
            </div>
            <div className="sidebar-profile-info" aria-hidden={collapsed}>
              <div className="sidebar-profile-name-row">
                <strong className="sidebar-profile-name">{username}</strong>
                <span className="sidebar-profile-role-pill">
                  {isOwner ? t('owner', 'Owner') : t('adminShort', 'Admin')}
                </span>
              </div>
              <div className="sidebar-profile-stats">
                <span className="stat-chip" title={t('totalUsers', 'Total users')}>
                  <FiUsers className="stat-chip-icon" aria-hidden="true" />
                  <span className="stat-chip-value">{stats.totalUsers}</span>
                </span>
                <span className="stat-chip" title={t('totalUsage', 'Total usage')}>
                  <FiBarChart2 className="stat-chip-icon" aria-hidden="true" />
                  <span className="stat-chip-value">{formatUsage(stats.totalUsage)}</span>
                </span>
              </div>
            </div>
            <button
              type="button"
              className="sidebar-logout-btn"
              onClick={() => { if (window.confirm(t('logoutConfirm', 'Sign out of the panel?'))) logout(); }}
              aria-label={t('logout', 'Logout')}
              title={t('logout', 'Logout')}
            >
              <FiLogOut aria-hidden="true" />
            </button>
          </div>
        </div>
      </aside>
    </>
  );
};

export default Sidebar;
