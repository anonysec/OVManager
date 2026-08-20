import { NavLink, Link, useLocation } from 'react-router-dom';
import { useState, useEffect, useCallback, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import {
  FiHome, FiUsers, FiServer, FiSettings, FiLogOut, FiChevronLeft, FiChevronRight,
  FiChevronUp, FiMenu, FiList,
} from 'react-icons/fi';
import { useAuth } from '../context/AuthContext';

const Sidebar = () => {
  const { userRole, logout } = useAuth();
  const { t } = useTranslation();
  const location = useLocation();
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem('ovmanager-sidebar-collapsed') === 'true');
  const [profileOpen, setProfileOpen] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  // Decode the JWT subject for the profile block (moved from the topbar).
  const username = useMemo(() => {
    try {
      const token = localStorage.getItem('authToken');
      if (!token) return '';
      return JSON.parse(atob(token.split('.')[1] || '')).sub || '';
    } catch { return ''; }
  }, []);

  useEffect(() => {
    localStorage.setItem('ovmanager-sidebar-collapsed', String(collapsed));
    window.dispatchEvent(new Event('sidebar-pin-change'));
  }, [collapsed]);

  useEffect(() => {
    const onResize = () => { if (window.innerWidth >= 768) setMobileOpen(false); };
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

  // Close the profile popover on outside click.
  useEffect(() => {
    if (!profileOpen) return;
    const onDoc = (e) => {
      if (!e.target.closest('.sidebar-profile')) setProfileOpen(false);
    };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, [profileOpen]);

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
  const roleLabel = isOwner ? t('administrator', 'Administrator') : t('operator', 'Operator');

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

        {/* Footer: profile + logout (logout only when expanded) */}
        <div className="sidebar-footer">
          <div className="sidebar-profile">
            <button
              type="button"
              className={`sidebar-profile-trigger${profileOpen ? ' active' : ''}`}
              onClick={() => setProfileOpen(o => !o)}
              aria-haspopup="true"
              aria-expanded={profileOpen}
              title={collapsed ? username : undefined}
            >
              <span className="avatar-xs">{username.slice(0, 1).toUpperCase() || '?'}</span>
              {!collapsed && (
                <span className="sidebar-profile-copy">
                  <strong>{username}</strong>
                  <small>{roleLabel}</small>
                </span>
              )}
              {!collapsed && <FiChevronUp className={`sidebar-profile-chevron${profileOpen ? ' is-open' : ''}`} aria-hidden="true" />}
            </button>
            <div className={`sidebar-profile-dropdown${profileOpen ? ' open' : ''}`} role="menu">
              <Link to="/settings" role="menuitem" onClick={() => setProfileOpen(false)}>
                <FiSettings aria-hidden="true" />
                <span>{t('navSettings', 'Settings')}</span>
              </Link>
              <button type="button" role="menuitem" className="danger" onClick={() => { setProfileOpen(false); logout(); }}>
                <FiLogOut aria-hidden="true" />
                <span>{t('logout', 'Logout')}</span>
              </button>
            </div>
          </div>

          {!collapsed && (
            <button
              className="sidebar-logout"
              onClick={logout}
              title={t('logout', 'Logout')}
            >
              <FiLogOut className="sidebar-nav-icon" />
              <span className="sidebar-nav-label">{t('logout', 'Logout')}</span>
            </button>
          )}
        </div>
      </aside>
    </>
  );
};

export default Sidebar;
