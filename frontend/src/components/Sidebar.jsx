import { NavLink, useLocation } from 'react-router-dom';
import { useState, useEffect, useCallback, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import {
  FiHome, FiUsers, FiServer, FiSettings, FiLogOut, FiChevronLeft, FiChevronRight,
  FiMenu, FiList, FiBarChart2,
} from 'react-icons/fi';
import { useAuth } from '../context/AuthContext';
import { useLive } from '../context/LiveContext';
import apiClient from '../services/api';
import { asList } from '../utils/apiData';

const Sidebar = () => {
  const { userRole, logout } = useAuth();
  const { t } = useTranslation();
  const location = useLocation();
  const { subscribe, unsubscribe } = useLive();
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem('ovmanager-sidebar-collapsed') === 'true');
  const [mobileOpen, setMobileOpen] = useState(false);
  const [stats, setStats] = useState({ totalUsers: 0, totalUsage: 0 });

  // Username for the profile block. The session token is opaque (random
  // bytes), so it has no "sub" claim to decode — AuthContext stores the name
  // from the login response instead.
  const username = useMemo(() => localStorage.getItem('username') || '', []);

  useEffect(() => {
    localStorage.setItem('ovmanager-sidebar-collapsed', String(collapsed));
    window.dispatchEvent(new Event('sidebar-pin-change'));
  }, [collapsed]);

  useEffect(() => {
    const onResize = () => { if (window.innerWidth >= 768) setMobileOpen(false); };
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

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
    );
  }

  navItems.push(
    { to: '/settings', label: t('navSettings', 'Settings'), icon: FiSettings, group: t('navGroupSystem', 'System') }
  );

  const renderNavItem = (item, index) => (
    <li key={item.to} className="sidebar-nav-item">
      {!collapsed && (index === 0 || navItems[index - 1].group !== item.group) && (
        <span className="sidebar-section-label">{item.group}</span>
      )}
      <NavLink
        to={item.to}
        end={item.end}
        className={isActiveClass(item)}
        onClick={() => mobileOpen && setMobileOpen(false)}
        title={collapsed ? item.label : undefined}
      >
        <item.icon className="sidebar-nav-icon" />
        {!collapsed && <span className="sidebar-nav-label">{item.label}</span>}
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
        className="sidebar-hamburger"
        onClick={() => setMobileOpen(true)}
        aria-label={t('openNavigation', 'Open navigation')}
      >
        <FiMenu />
      </button>

      {/* Mobile overlay */}
      {mobileOpen && (
        <div className="sidebar-mobile-overlay" onClick={() => setMobileOpen(false)} />
      )}

      {/* Sidebar */}
      <aside
        className={`ops-sidebar ${collapsed ? 'ops-sidebar--collapsed' : ''} ${mobileOpen ? 'ops-sidebar--mobile ops-sidebar--open' : ''}`}
        data-corner={(() => { try { return localStorage.getItem('ovmanager-sidebar-corner') || 'inline-start'; } catch { return 'inline-start'; } })()}
        aria-label={t('mainNavigation', 'Main navigation')}
      >
        {/* Collapse toggle */}
        <button
          className="sidebar-toggle"
          onClick={toggleCollapse}
          aria-label={collapsed ? t('expandSidebar', 'Expand sidebar') : t('collapseSidebar', 'Collapse sidebar')}
          title={collapsed ? t('expandSidebar', 'Expand sidebar') : t('collapseSidebar', 'Collapse sidebar')}
        >
          {collapsed ? <FiChevronRight /> : <FiChevronLeft />}
        </button>

        {/* Navigation — flat list, no submenus */}
        <nav className="sidebar-nav">
          <ul className="sidebar-nav-list">
            {navItems.map(renderNavItem)}
          </ul>
        </nav>

        {/* Footer: profile with inline logout */}
        <div className="sidebar-footer">
          <div className="sidebar-profile">
            <div className="sidebar-profile-avatar">
              <span className="avatar-md">{username.slice(0, 1).toUpperCase() || '?'}</span>
              <span className={`sidebar-profile-pulse ${isOwner ? 'is-owner' : 'is-operator'}`} aria-hidden="true" />
            </div>
            {!collapsed && (
              <div className="sidebar-profile-info">
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
            )}
            {!collapsed && (
              <button
                type="button"
                className="sidebar-logout-btn"
                onClick={logout}
                aria-label={t('logout', 'Logout')}
                title={t('logout', 'Logout')}
              >
                <FiLogOut aria-hidden="true" />
              </button>
            )}
          </div>
        </div>
      </aside>
    </>
  );
};

export default Sidebar;