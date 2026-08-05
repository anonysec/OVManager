import { NavLink, useLocation } from 'react-router-dom';
import { useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { FiHome, FiUsers, FiServer, FiSettings, FiLogOut, FiChevronLeft, FiChevronRight, FiChevronDown, FiMenu, FiActivity, FiList, FiSearch, FiRefreshCw, FiGlobe, FiLock } from 'react-icons/fi';
import { useAuth } from '../context/AuthContext';
import Logo from './Logo';

const Sidebar = () => {
  const { userRole, logout, user } = useAuth();
  const { t } = useTranslation();
  const location = useLocation();
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem('ovmanager-sidebar-collapsed') === 'true');
  const [mobileOpen, setMobileOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);

  useEffect(() => {
    localStorage.setItem('ovmanager-sidebar-collapsed', String(collapsed));
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

  const navItems = [
    { to: '/', label: t('dashboard'), icon: FiHome, end: true },
    { to: '/users', label: t('users'), icon: FiUsers },
    { to: '/nodes', label: t('nodes'), icon: FiServer, badge: 'online' },
  ];

  if (userRole === 'main_admin') {
    navItems.push(
      { to: '/admins', label: t('admins'), icon: FiList },
    );
  }

  // VPN-specific sections (x-ui / PasarGuard pattern)
  navItems.push(
    { to: '/traffic', label: t('navTrafficLogs'), icon: FiActivity },
    { to: '/subscriptions', label: t('navSubscriptions'), icon: FiGlobe },
    { to: '/security', label: t('navSecurity'), icon: FiLock },
  );

  const settingsItem = { to: '/settings', label: t('settings'), icon: FiSettings };

  const renderNavItem = (item) => (
    <li key={item.to} className="sidebar-nav-item">
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
        className={`ops-sidebar ${collapsed ? 'ops-sidebar--collapsed' : ''}`}
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
                onClick={(e) => {
                  if (!collapsed) {
                    e.preventDefault();
                    setSettingsOpen(o => !o);
                  }
                  mobileOpen && setMobileOpen(false);
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
                  <li><NavLink to="/settings#appearance" className="sidebar-submenu-link">Appearance</NavLink></li>
                  <li><NavLink to="/settings#security" className="sidebar-submenu-link">Security</NavLink></li>
                  <li><NavLink to="/settings#notifications" className="sidebar-submenu-link">Notifications</NavLink></li>
                  <li><NavLink to="/settings#backup" className="sidebar-submenu-link">Backup</NavLink></li>
                  <li><NavLink to="/settings#system" className="sidebar-submenu-link">System</NavLink></li>
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
