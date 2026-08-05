import { NavLink, useLocation } from 'react-router-dom';
import { useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { FiHome, FiUsers, FiServer, FiSettings, FiLogOut, FiChevronLeft, FiChevronRight, FiChevronDown } from 'react-icons/fi';
import { useAuth } from '../context/AuthContext';
import Logo from './Logo';

const Sidebar = () => {
  const { userRole, logout } = useAuth();
  const { t } = useTranslation();
  const location = useLocation();
  const [pinned, setPinned] = useState(() => localStorage.getItem('ovmanager-sidebar-pinned') !== 'false');
  const [expanded, setExpanded] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [isMobile, setIsMobile] = useState(window.innerWidth < 768);
  const [settingsOpen, setSettingsOpen] = useState(false);

  useEffect(() => {
    const onResize = () => setIsMobile(window.innerWidth < 768);
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

  const togglePin = useCallback(() => {
    const next = !pinned;
    setPinned(next);
    localStorage.setItem('ovmanager-sidebar-pinned', String(next));
    try { window.dispatchEvent(new CustomEvent('sidebar-pin-change', { detail: { pinned: next } })); } catch {}
  }, [pinned]);

  const rail = pinned && !isMobile;
  const showLabels = !rail || expanded;

  const navItems = [
    { to: '/', label: t('dashboard'), icon: FiHome, end: true },
    { to: '/users', label: t('users'), icon: FiUsers },
    { to: '/nodes', label: t('nodes'), icon: FiServer },
  ];
  if (userRole === 'main_admin') {
    navItems.push({ to: '/admins', label: t('admins'), icon: FiSettings });
  }
  const settingsItem = { to: '/settings', label: t('settings'), icon: FiSettings };

  const isActive = (item) => {
    if (item.end) return location.pathname === item.to;
    return location.pathname.startsWith(item.to);
  };

  const renderNavItem = (item) => (
    <li key={item.to} className="sidebar-nav-item">
      <NavLink
        to={item.to}
        end={item.end}
        className={`sidebar-nav-link ${isActive(item) ? 'active' : ''}`}
        onMouseEnter={() => !pinned && setExpanded(true)}
        onMouseLeave={() => !pinned && setExpanded(false)}
        onClick={() => isMobile && setMobileOpen(false)}
        title={rail && !expanded ? item.label : undefined}
      >
        <item.icon className="sidebar-nav-icon" />
        {showLabels && <span className="sidebar-nav-label">{item.label}</span>}
        {showLabels && !rail && (
          <svg className="sidebar-nav-chevron" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M9 18l6-6-6-6" />
          </svg>
        )}
      </NavLink>
    </li>
  );

  return (
    <>
      {/* Mobile hamburger */}
      <button
        className="sidebar-mobile-trigger"
        onClick={() => setMobileOpen(true)}
        aria-label="Open navigation"
      >
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M3 12h18M3 6h18M3 18h18" />
        </svg>
      </button>

      {/* Mobile overlay */}
      {isMobile && mobileOpen && (
        <div className="sidebar-mobile-overlay" onClick={() => setMobileOpen(false)} />
      )}

      {/* Sidebar */}
      <aside
        className={`ops-sidebar ${rail ? 'ops-sidebar--rail' : ''} ${isMobile ? 'ops-sidebar--mobile' : ''} ${isMobile && mobileOpen ? 'ops-sidebar--open' : ''}`}
        onMouseEnter={() => rail && setExpanded(true)}
        onMouseLeave={() => rail && setExpanded(false)}
      >
        {/* Pin toggle */}
        {!isMobile && (
          <button
            className="sidebar-pin-btn"
            onClick={togglePin}
            aria-label={pinned ? 'Unpin sidebar' : 'Pin sidebar'}
          >
            {pinned ? <FiChevronLeft /> : <FiChevronRight />}
          </button>
        )}

        {/* Logo — always visible in both rail and expanded mode */}
        <div className="sidebar-brand">
          <Logo size={28} />
          <strong className="sidebar-brand-text">OV<span className="brand-accent">Manager</span></strong>
        </div>

        {/* Navigation */}
        <nav className="sidebar-nav" aria-label="Main navigation">
          <ul className="sidebar-nav-list">
            {navItems.map(renderNavItem)}

            {/* Settings with submenu */}
            <li className="sidebar-nav-item">
              <NavLink
                to={settingsItem.to}
                className={`sidebar-nav-link ${isActive(settingsItem) ? 'active' : ''}`}
                onClick={(e) => {
                  if (showLabels) {
                    e.preventDefault();
                    setSettingsOpen(o => !o);
                  }
                  if (isMobile) setMobileOpen(false);
                }}
                title={rail && !expanded ? settingsItem.label : undefined}
                onMouseEnter={() => !pinned && setExpanded(true)}
                onMouseLeave={() => !pinned && setExpanded(false)}
              >
                <settingsItem.icon className="sidebar-nav-icon" />
                {showLabels && <span className="sidebar-nav-label">{settingsItem.label}</span>}
                {showLabels && !rail && (
                  <FiChevronDown
                    className={`sidebar-nav-chevron ${settingsOpen ? 'rotated' : ''}`}
                  />
                )}
              </NavLink>
              {settingsOpen && showLabels && !rail && (
                <ul className="sidebar-submenu">
                  <li><NavLink to="/settings#general" className="sidebar-submenu-link" onClick={() => isMobile && setMobileOpen(false)}>General</NavLink></li>
                  <li><NavLink to="/settings#appearance" className="sidebar-submenu-link" onClick={() => isMobile && setMobileOpen(false)}>Appearance</NavLink></li>
                  <li><NavLink to="/settings#security" className="sidebar-submenu-link" onClick={() => isMobile && setMobileOpen(false)}>Security</NavLink></li>
                  <li><NavLink to="/settings#notifications" className="sidebar-submenu-link" onClick={() => isMobile && setMobileOpen(false)}>Notifications</NavLink></li>
                  <li><NavLink to="/settings#backup" className="sidebar-submenu-link" onClick={() => isMobile && setMobileOpen(false)}>Backup</NavLink></li>
                  <li><NavLink to="/settings#system" className="sidebar-submenu-link" onClick={() => isMobile && setMobileOpen(false)}>System</NavLink></li>
                </ul>
              )}
            </li>
          </ul>
        </nav>

        {/* Version badge (like 3x-ui) */}
        <div className="sidebar-version">
          <span className="sidebar-version-badge">v1.5.0</span>
        </div>

        {/* Logout */}
        <button className="sidebar-logout" onClick={logout}>
          <FiLogOut className="sidebar-nav-icon" />
          {showLabels && <span className="sidebar-nav-label">Logout</span>}
        </button>
      </aside>
    </>
  );
};

export default Sidebar;
