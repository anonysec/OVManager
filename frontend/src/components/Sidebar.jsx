import { NavLink, useLocation } from 'react-router-dom';
import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import {
  FiHome, FiUsers, FiServer, FiSettings, FiLogOut, FiChevronLeft, FiChevronRight,
  FiMenu, FiList, FiBarChart2, FiDatabase,
} from 'react-icons/fi';
import { useAuth } from '../context/AuthContext';
import { useLive } from '../context/LiveContext';
import apiClient from '../services/api';
import { asList } from '../utils/apiData';

const readCollapsed = () => {
  try { return localStorage.getItem('ovmanager-sidebar-collapsed') === 'true'; }
  catch { return false; }
};

const readCorner = () => {
  try { return localStorage.getItem('ovmanager-sidebar-corner') || 'inline-start'; }
  catch { return 'inline-start'; }
};

const Sidebar = () => {
  const { userRole, logout } = useAuth();
  const { t } = useTranslation();
  const location = useLocation();
  const { subscribe, unsubscribe } = useLive();
  const [collapsed, setCollapsed] = useState(readCollapsed);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [corner, setCorner] = useState(readCorner);
  const [stats, setStats] = useState({ totalUsers: 0, totalUsage: 0 });
  const hamburgerRef = useRef(null);
  const drawerRef = useRef(null);

  // Username for the profile block. The session token is opaque (random
  // bytes), so it has no "sub" claim to decode — AuthContext stores the name
  // from the login response instead.
  const username = useMemo(() => {
    try { return localStorage.getItem('username') || ''; }
    catch { return ''; }
  }, []);

  useEffect(() => {
    try { localStorage.setItem('ovmanager-sidebar-collapsed', String(collapsed)); } catch { /* private mode */ }
    window.dispatchEvent(new Event('sidebar-pin-change'));
  }, [collapsed]);

  // Sidebar position can change live from Settings (no reload) or another tab.
  useEffect(() => {
    const applyCorner = (e) => {
      if (e?.detail?.corner) setCorner(e.detail.corner);
      else setCorner(readCorner());
    };
    window.addEventListener('sidebar-corner-change', applyCorner);
    window.addEventListener('storage', applyCorner);
    return () => {
      window.removeEventListener('sidebar-corner-change', applyCorner);
      window.removeEventListener('storage', applyCorner);
    };
  }, []);

  useEffect(() => {
    const onResize = () => { if (window.innerWidth >= 768) setMobileOpen(false); };
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

  // Mobile drawer: Escape closes, focus moves in on open and returns to the
  // hamburger on close.
  useEffect(() => {
    if (!mobileOpen) return undefined;
    drawerRef.current?.querySelector('a, button')?.focus();
    const onKey = (e) => {
      if (e.key === 'Escape') setMobileOpen(false);
    };
    document.addEventListener('keydown', onKey);
    const trigger = hamburgerRef.current;
    return () => {
      document.removeEventListener('keydown', onKey);
      trigger?.focus();
    };
  }, [mobileOpen]);

  // Fetch admin/user stats for the profile block
  const fetchStats = useCallback(async () => {
    try {
      const [usersRes] = await Promise.all([
        apiClient.get('/users/'),
      ]);
      const users = asList(usersRes.data, 'users');
      const totalUsage = users.reduce((sum, u) => sum + Number(u.used || 0), 0);
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

  const isActive = (item) => {
    if (item.end) return location.pathname === item.to;
    return location.pathname.startsWith(item.to);
  };
  const isActiveClass = (item) => isActive(item) ? 'sidebar-nav-link active' : 'sidebar-nav-link';

  // Build flat nav list — Settings is a plain link like all other pages.
  const navItems = [
    { to: '/',          label: t('navDashboard', 'Dashboard'), icon: FiHome,     end: true, group: t('navGroupOverview', 'Overview') },
    { to: '/users',     label: t('navUsers',     'Users'),     icon: FiUsers,              group: t('navGroupManage',   'Manage')   },
    { to: '/nodes',     label: t('navNodes',     'Nodes'),     icon: FiServer,             group: t('navGroupManage',   'Manage')   },
  ];

  if (userRole === 'owner') {
    navItems.push(
      { to: '/admins', label: t('navAdmins', 'Admins'), icon: FiList, group: t('navGroupManage', 'Manage') },
      { to: '/audit', label: t('navAudit', 'Audit Log'), icon: FiBarChart2, group: t('navGroupSystem', 'System') },
      { to: '/maintenance', label: t('navMaintenance', 'Maintenance'), icon: FiDatabase, group: t('navGroupSystem', 'System') },
    );
  }

  navItems.push(
    { to: '/settings', label: t('navSettings', 'Settings'), icon: FiSettings, group: t('navGroupSystem', 'System') }
  );

  // Labels stay mounted in both modes — the collapsed rail fades/collapses
  // them via CSS instead of unmounting, so the width tween looks smooth and
  // focus is never destroyed mid-toggle.
  const renderNavItem = (item, index) => (
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

  const isOwner = userRole === 'owner';

  const formatUsage = (bytes) => {
    if (bytes >= 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
    if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    return `${bytes} B`;
  };

  return (
    <>
      {/* Mobile hamburger trigger */}
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

      {/* Mobile overlay */}
      {mobileOpen && (
        <div className="sidebar-mobile-overlay" onClick={() => setMobileOpen(false)} aria-hidden="true" />
      )}

      {/* Sidebar */}
      <aside
        ref={drawerRef}
        id="ops-sidebar"
        className={`ops-sidebar ${collapsed ? 'ops-sidebar--collapsed' : ''} ${mobileOpen ? 'ops-sidebar--mobile ops-sidebar--open' : ''}`}
        data-corner={corner}
        aria-label={t('mainNavigation', 'Main navigation')}
      >
        {/* Collapse toggle */}
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

        {/* Navigation — flat list, no submenus */}
        <nav className="sidebar-nav" aria-label={t('sidebarSections', 'Sections')}>
          <ul className="sidebar-nav-list">
            {navItems.map(renderNavItem)}
          </ul>
        </nav>

        {/* Footer: profile with inline logout (icon-only in rail) */}
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
              onClick={logout}
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
