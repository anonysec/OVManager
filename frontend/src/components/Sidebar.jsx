import { NavLink, useLocation } from 'react-router-dom';
import { useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { FiHome, FiUsers, FiServer, FiSettings, FiLogOut, FiChevronLeft, FiChevronRight, FiMenu, FiList } from 'react-icons/fi';
import { useAuth } from '../context/AuthContext';

const Sidebar = () => {
  const { userRole, logout } = useAuth();
  const { t } = useTranslation();
  const location = useLocation();
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem('ovmanager-sidebar-collapsed') === 'true');
  const [mobileOpen, setMobileOpen] = useState(false);

  useEffect(() => {
    localStorage.setItem('ovmanager-sidebar-collapsed', String(collapsed));
    window.dispatchEvent(new Event('sidebar-pin-change'));
  }, [collapsed]);

  useEffect(() => {
    const onResize = () => { if (window.innerWidth >= 768) setMobileOpen(false); };
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

  const toggleCollapse = useCallback(() => setCollapsed(c => !c), []);

  const isActive = (item) => {
    if (item.end) return location.pathname === item.to;
    return location.pathname.startsWith(item.to);
  };
  const isActiveClass = (item) => isActive(item) ? 'sidebar-nav-link active' : 'sidebar-nav-link';

  // Build flat nav list — Settings is a plain link like all other pages.
  // The Settings page itself has its own left-panel tab navigation; a sidebar
  // submenu would duplicate that and create two competing navigation systems.
  const navItems = [
    { to: '/',          label: t('navDashboard', 'Dashboard'), icon: FiHome,     end: true, group: t('navGroupOverview', 'Overview') },
    { to: '/users',     label: t('navUsers',     'Users'),     icon: FiUsers,              group: t('navGroupManage',   'Manage')   },
    { to: '/nodes',     label: t('navNodes',     'Nodes'),     icon: FiServer,             group: t('navGroupManage',   'Manage')   },
  ];

  if (userRole === 'owner') {
    navItems.push(
      { to: '/admins',      label: t('navAdmins',      'Admins'),      icon: FiList,     group: t('navGroupManage', 'Manage')          },
      { to: '/audit',       label: t('navAudit',       'Audit Log'),   icon: FiList,     group: t('navGroupAdmin',  'Administration')  },
      { to: '/maintenance', label: t('navMaintenance', 'Maintenance'), icon: FiSettings, group: t('navGroupAdmin',  'Administration')  },
    );
  }

  // Settings is always last, always a plain link
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

  return (
    <>
      {/* Mobile hamburger trigger */}
      <button
        className="sidebar-hamburger"
        onClick={() => setMobileOpen(true)}
        aria-label="Open navigation"
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
        aria-label="Main navigation"
      >
        {/* Collapse toggle */}
        <button
          className="sidebar-toggle"
          onClick={toggleCollapse}
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          {collapsed ? <FiChevronRight /> : <FiChevronLeft />}
        </button>

        {/* Navigation — flat list, no submenus */}
        <nav className="sidebar-nav">
          <ul className="sidebar-nav-list">
            {navItems.map(renderNavItem)}
          </ul>
        </nav>

        {/* Footer: version + logout */}
        <div className="sidebar-footer">
          <button
            className={`sidebar-logout ${collapsed ? 'sidebar-logout--icon' : ''}`}
            onClick={logout}
            title={collapsed ? t('logout') : undefined}
          >
            <FiLogOut className="sidebar-nav-icon" />
            {!collapsed && <span className="sidebar-nav-label">{t('logout')}</span>}
          </button>
        </div>
      </aside>
    </>
  );
};

export default Sidebar;
