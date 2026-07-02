import { NavLink } from 'react-router-dom';
import { FiGrid, FiUsers, FiServer, FiShield, FiSettings } from 'react-icons/fi';
import { useTranslation } from 'react-i18next';
import { useAuth } from '../context/AuthContext';
import logoSrc from '../assets/ovmanager-character.webp';

const Sidebar = () => {
  const { t } = useTranslation();
  const { userRole } = useAuth();

  return (
    <aside className="sidebar">
      <div className="sidebar-header brand-header">
        <img
          src={logoSrc}
          alt="Panel Logo"
          className="sidebar-logo brand-logo"
        />
        <div className="brand-copy">
          <strong>OVManager</strong>
          <span><FiShield size={12} /> VPN Control</span>
        </div>
      </div>
      <nav>
        <ul>
          <li>
            <NavLink to="/" end className="nav-link">
              <div className="icon-wrapper">
                <FiGrid size={22} />
              </div>
              <span>Dashboard</span>
            </NavLink>
          </li>
          <li>
            <NavLink to="/users" className="nav-link">
              <div className="icon-wrapper">
                <FiUsers size={22} />
              </div>
              <span>Users</span>
            </NavLink>
          </li>
          {userRole !== 'admin' && (
            <li>
              <NavLink to="/nodes" className="nav-link">
                <div className="icon-wrapper">
                  <FiServer size={22} />
                </div>
                <span>Nodes</span>
              </NavLink>
            </li>
          )}
          {userRole === 'main_admin' && (
            <li>
              <NavLink to="/admins" className="nav-link">
                <div className="icon-wrapper">
                  <FiUsers size={22} />
                </div>
                <span>Admins</span>
              </NavLink>
            </li>
          )}
          <li>
            <NavLink to="/settings" className="nav-link">
              <div className="icon-wrapper">
                <FiSettings size={22} />
              </div>
              <span>Settings</span>
            </NavLink>
          </li>
        </ul>
      </nav>
    </aside>
  );
};

export default Sidebar;