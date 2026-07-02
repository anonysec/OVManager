import { NavLink } from 'react-router-dom';
import { FiGrid, FiUsers, FiServer, FiSettings } from 'react-icons/fi';
import { useAuth } from '../context/AuthContext';

const MobileNav = () => {
  const { userRole } = useAuth();

  return (
    <nav className="mobile-nav">
      <NavLink to="/" end className="mobile-nav-link">
        <FiGrid size={22} />
        <span>Dashboard</span>
      </NavLink>
      <NavLink to="/users" className="mobile-nav-link">
        <FiUsers size={22} />
        <span>Users</span>
      </NavLink>
      {userRole !== 'admin' && (
        <NavLink to="/nodes" className="mobile-nav-link">
          <FiServer size={22} />
          <span>Nodes</span>
        </NavLink>
      )}
      {userRole === 'main_admin' && (
        <NavLink to="/admins" className="mobile-nav-link">
          <FiUsers size={22} />
          <span>Admins</span>
        </NavLink>
      )}
      <NavLink to="/settings" className="mobile-nav-link">
        <FiSettings size={22} />
        <span>Settings</span>
      </NavLink>
    </nav>
  );
};

export default MobileNav;
