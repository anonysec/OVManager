import { NavLink } from 'react-router-dom';
import { FiGrid, FiUsers, FiServer, FiSettings, FiList } from 'react-icons/fi';
import { useAuth } from '../context/AuthContext';
import { useTranslation } from 'react-i18next';

const MobileNav = () => {
  const { userRole } = useAuth();
  const { t } = useTranslation();

  const items = [
    { to: '/', label: t('navDashboard', 'Dashboard'), icon: FiGrid, end: true },
    { to: '/users', label: t('navUsers', 'Users'), icon: FiUsers },
    { to: '/nodes', label: t('navNodes', 'Nodes'), icon: FiServer },
    ...(userRole === 'owner' ? [{ to: '/admins', label: t('navAdmins', 'Admins'), icon: FiList }] : []),
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
