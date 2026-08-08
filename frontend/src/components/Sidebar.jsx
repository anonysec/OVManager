import { NavLink, useLocation } from 'react-router-dom';
import { useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { FiHome, FiUsers, FiServer, FiSettings, FiLogOut, FiChevronLeft, FiChevronRight, FiChevronDown, FiMenu, FiList } from 'react-icons/fi';
import { useAuth } from '../context/AuthContext';
import Logo from './Logo';

const Sidebar = () => {
  const { userRole, logout } = useAuth();
  const { t } = useTranslation();
  const location = useLocation();
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem('ovmanager-sidebar-collapsed') === 'true');
  const [mobileOpen, setMobileOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);

  useEffect(() => {
    localStorage.setItem('ovmanager-sidebar-collapsed', String(collapsed));
    window.dispatchEvent(new Event('sidebar-pin-change'));
  }, [collapsed]);

  useEffect(() => {
    const onResize = () => {
      if (window.innerWidth >= 768) setMobileOpen(false);
    };
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

  const toggleCollapse = useCallback(() => setCollapsed(c => !c), []);

  const isActive = (item) => {
    if (item.end) return location.pathname === item.to;
    return location.pathname.startsWith(item.to);
  };

  const isActiveClass = (item) => isActive(item) ? 'sidebar-nav-link active' : 'sidebar-nav-link';

  // Keep navigation limited to routes that are actually available. Dead links
  // are especially confusing in an operations panel because they look like
  // a failed health check rather than an unfinished section.
  const navItems = [
    { to: '/', label: t('navDashboard', 'Dashboard'), icon: FiHome, end: true, group: t('navGroupOverview', 'Overview') },
    { to: '/users', label: t('navUsers', 'Users'), icon: FiUsers, group: t('navGroupManage', 'Manage') },
    { to: '/nodes', label: t('navNodes', 'Nodes'), icon: FiServer, group: t('navGroupManage', 'Manage') },
  ];

  if (userRole === 'main_admin') {
    navItems.push(
      { to: '/admins', label: t('navAdmins', 'Admins'), icon: FiList, group: t('navGroupManage', 'Manage') },
      { to: '/audit', label: t('navAudit', 'Audit Log'), icon: FiList, group: t('navGroupAdmin', 'Administration') },
      { to: '/maintenance', label: t('navMaintenance', 'Maintenance'), icon: FiSettings, group: t('navGroupAdmin', 'Administration') },
    );
  }

  const settingsItem = { to: '/settings', label: t('navSettings', 'Settings'), icon: FiSettings, group: t('navGroupSystem', 'System') };

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
        {item.badge && !collapsed && <span className="sidebar-nav-badge">{item.badge}</span>}
      </NavLink>
    </li>
  );

  return (
    <>
      {/* Mobile hamburger trigger — separate from sidebar */}
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
        {/* Brand — always shows icon, shows text when not collapsed */}
        <div className="sidebar-brand">
          <Logo size={28} />
          {!collapsed && <strong className="sidebar-brand-text">O<span className="brand-accent">VManager</span></strong>}
        </div>

        {/* Collapse toggle at top (icon-only, like pro panels) */}
        <button
          className="sidebar-toggle"
          onClick={toggleCollapse}
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          {collapsed ? <FiChevronRight /> : <FiChevronLeft />}
        </button>

        {/* Navigation */}
        <nav className="sidebar-nav">
          <ul className="sidebar-nav-list">
            {navItems.map(renderNavItem)}
            {/* Settings with submenu */}
            <li className="sidebar-nav-item">
              <NavLink
                to={settingsItem.to}
                className={`${isActiveClass(settingsItem)} ${settingsOpen ? 'open' : ''}`}
                onClick={() => {
                  if (!collapsed) setSettingsOpen((open) => !open);
                  if (mobileOpen) setMobileOpen(false);
                }}
                title={collapsed ? settingsItem.label : undefined}
              >
                <settingsItem.icon className="sidebar-nav-icon" />
                {!collapsed && (
                  <>
                    <span className="sidebar-nav-label">{settingsItem.label}</span>
                    <FiChevronDown className={`sidebar-nav-chevron ${settingsOpen ? 'rotated' : ''}`} />
                  </>
                )}
              </NavLink>
              {!collapsed && settingsOpen && (
                <ul className="sidebar-submenu">
                  <li><NavLink to="/settings#general" className="sidebar-submenu-link">General</NavLink></li>
                  <li><NavLink to="/settings#system" className="sidebar-submenu-link">System</NavLink></li>
                  <li><NavLink to="/settings#security" className="sidebar-submenu-link">Security</NavLink></li>
                  <li><NavLink to="/settings#backup" className="sidebar-submenu-link">Backup</NavLink></li>
                  <li><NavLink to="/settings#bot" className="sidebar-submenu-link">Bot</NavLink></li>
                  <li><NavLink to="/settings#activity" className="sidebar-submenu-link">Activity</NavLink></li>
                </ul>
              )}
            </li>
          </ul>
        </nav>

        {/* Bottom: Version + Logout */}
        <div className="sidebar-footer">
          {!collapsed && (
            <div className="sidebar-version">
              <span className="sidebar-version-badge">v1.5.0</span>
            </div>
          )}
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
