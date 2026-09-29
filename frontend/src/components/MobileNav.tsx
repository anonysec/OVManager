import { NavLink } from 'react-router-dom';
import { FiGrid, FiUsers, FiServer, FiSettings, FiActivity } from 'react-icons/fi';
import { useAuth } from '../context/AuthContext';
import { useTranslation } from 'react-i18next';

const MobileNav = () => {
  const { userRole } = useAuth();
  const { t } = useTranslation();

  // Primary destinations only — Admins/Audit live in the drawer's Advanced
  // group, and Nodes/Health are owner-only. Owner sees 5 tabs, admin 3.
  const items = [
    { to: '/', label: t('navHome', 'Home'), icon: FiGrid, end: true },
    { to: '/users', label: t('navUsers', 'Users'), icon: FiUsers },
    ...(userRole === 'owner' ? [
      { to: '/nodes', label: t('navNodes', 'Nodes'), icon: FiServer },
      { to: '/health', label: t('navHealth', 'Health'), icon: FiActivity },
    ] : []),
    { to: '/settings', label: t('navSettings', 'Settings'), icon: FiSettings },
  ];

  return (
    <nav className={`mobile-nav mobile-nav--${items.length}`} aria-label={t('mobileNavigation', 'Mobile navigation')}>
      {items.map((item) => (
        <NavLink key={item.to} to={item.to} end={item.end} className="mobile-nav-link">
          <item.icon aria-hidden="true" />
          <span>{item.label}</span>
        </NavLink>
      ))}
    </nav>
  );
};

export default MobileNav;
