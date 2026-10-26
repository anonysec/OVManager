import './Sidebar.css';
import { NavLink, useLocation } from 'react-router-dom';
import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import type { IconType } from 'react-icons';
import { useTranslation } from 'react-i18next';
import {
  FiHome, FiUsers, FiServer, FiSettings, FiLogOut, FiChevronsLeft, FiChevronsRight,
  FiMenu, FiBarChart2, FiFileText,
} from 'react-icons/fi';
import { useAuth } from '../context/AuthContext';
import { useLive } from '../context/LiveContext';
import apiClient from '../services/api';
import { asList } from '../utils/apiData';
import { createQueuedRefresh } from '../utils/queuedRefresh';
import Logo from './Logo';
import ConfirmModal from './ConfirmModal';

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

  const [logoutOpen, setLogoutOpen] = useState(false);

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

  const fetchStatsWork = useCallback(async () => {
    try {
      const usersRes = await apiClient.get('/users/');
      const users = asList(usersRes.data, 'users');
      const totalUsage = users.reduce((sum: number, u: any) => sum + Number(u.used || 0), 0);
      setStats({ totalUsers: users.length, totalUsage });
    } catch { /* ignore */ }
  }, []);
  const fetchStats = useMemo(() => createQueuedRefresh(fetchStatsWork), [fetchStatsWork]);
  const refreshStatsForUserEvent = useCallback((data?: any) => {
    const op = data?.op;
    if (op && !['create', 'delete', 'restore', 'reset-usage'].includes(op)) return;
    fetchStats();
  }, [fetchStats]);

  useEffect(() => {
    if (userRole !== 'owner') {
      setStats({ totalUsers: 0, totalUsage: 0 });
      return undefined;
    }
    fetchStats();
    const u1 = subscribe('users.changed', refreshStatsForUserEvent);
    const u2 = subscribe('users.created', fetchStats);
    const u3 = subscribe('users.deleted', fetchStats);
    const u4 = subscribe('tick', fetchStats);
    return () => { u1(); u2(); u3(); u4(); };
  }, [subscribe, unsubscribe, fetchStats, refreshStatsForUserEvent, userRole]);

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
    ] : []),
    { to: '/settings',  label: t('navSettings', 'Settings'), icon: FiSettings,           group: t('navGroupSystem',   'System')   },
    { to: '/logs',      label: t('navLogs',     'Logs'),        icon: FiFileText,       group: t('navGroupSystem',   'System')   },
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

        <nav className="sidebar-nav" aria-label={t('sidebarSections', 'Sections')}>
          <ul className="sidebar-nav-list">
            {navItems.map(renderNavItem)}
          </ul>
        </nav>

        <div className="sidebar-footer">
          <button
            type="button"
            className="sidebar-collapse-bar"
            onClick={toggleCollapse}
            aria-label={collapsed ? t('expandSidebar', 'Expand sidebar') : t('collapseSidebar', 'Collapse sidebar')}
            aria-expanded={!collapsed}
            aria-controls="ops-sidebar"
            title={collapsed ? t('expandSidebar', 'Expand sidebar') : t('collapseSidebar', 'Collapse sidebar')}
          >
            {collapsed ? <FiChevronsRight aria-hidden="true" /> : <FiChevronsLeft aria-hidden="true" />}
            <span className="sidebar-collapse-label" aria-hidden={collapsed}>
              {t('collapseSidebar', 'Collapse sidebar')}
            </span>
          </button>

          <div className="sidebar-profile">
            <div className="sidebar-profile-avatar" title={collapsed ? username : undefined}>
              <span className="avatar-md" aria-hidden="true">{username.slice(0, 1).toUpperCase() || '?'}</span>
              <span className={`sidebar-profile-pulse ${isOwner ? 'is-owner' : 'is-operator'}`} aria-hidden="true" />
              {isOwner && <span className="sidebar-owner-badge" aria-label={t('soleOwner', 'Sole owner / administrator')}>👑</span>}
            </div>
            <div className="sidebar-profile-info" aria-hidden={collapsed}>
              <div className="sidebar-profile-name-row">
                <strong className="sidebar-profile-name">{username}</strong>
                <span className={`sidebar-profile-role-pill${isOwner ? ' is-owner' : ''}`}>
                  {isOwner ? t('soleOwnerShort', 'Sole Owner') : t('adminShort', 'Admin')}
                </span>
              </div>
              <div className="sidebar-profile-stats">
                <span className="stat-chip" title={t('totalUsers', 'Total users')}>
                  <FiUsers className="stat-chip-icon" aria-hidden="true" />
                  <span className="stat-chip-value">{stats.totalUsers}</span>
                  <span className="sr-only">{`${stats.totalUsers} ${t('totalUsers', 'total users')}`}</span>
                </span>
                <span className="stat-chip" title={t('totalUsage', 'Total usage')}>
                  <FiBarChart2 className="stat-chip-icon" aria-hidden="true" />
                  <span className="stat-chip-value">{formatUsage(stats.totalUsage)}</span>
                  <span className="sr-only">{`${formatUsage(stats.totalUsage)} ${t('totalUsage', 'total usage')}`}</span>
                </span>
              </div>
            </div>
            <button
              type="button"
              className="sidebar-logout-btn"
              onClick={() => setLogoutOpen(true)}
              aria-label={t('logout', 'Logout')}
              title={t('logout', 'Logout')}
            >
              <FiLogOut aria-hidden="true" />
            </button>
          </div>
        </div>
      </aside>
      <ConfirmModal
        open={logoutOpen}
        onClose={() => setLogoutOpen(false)}
        onConfirm={logout}
        title={t('logoutConfirm', 'Sign out?')}
        message={t('logoutConfirmDetail', 'You will be returned to the login page.')}
        confirmLabel={t('logout', 'Logout')}
        danger={false}
      />
    </>
  );
};

export default Sidebar;
